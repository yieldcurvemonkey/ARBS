"""Blocking checks on the 1-week point: overlap-corrected SE + the pre-event mirror."""
import sys, json
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import pandas as pd
import numpy as np

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)

BASE = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
RANK = 3
INTRA_W = [5, 15, 30, 60, 120, 240, 300]
PRE_W = [5, 15, 30, 60, 120]          # negative offsets that exist in the panel
WCOLS = [f"w{w}" for w in INTRA_W] + ["w1440", "w7200"]
WMIN = INTRA_W + [1440, 7200]


def cluster_t(x, g):
    x = np.asarray(x, float); ok = np.isfinite(x); x = x[ok]; g = np.asarray(g)[ok]
    n = len(x)
    if n < 3: return np.nan, np.nan, np.nan, n, 0
    m = x.mean(); e = x - m
    sg = pd.DataFrame({"e": e, "g": g}).groupby("g")["e"].sum().values
    G = len(sg)
    if G < 2: return m, np.nan, np.nan, n, G
    V = (G / (G - 1.0)) * (sg ** 2).sum() / (n ** 2)
    se = np.sqrt(V)
    return m, se, m / se, n, G


def load():
    ev = pd.read_parquet(BASE + r"\_event_study\event_paths.parquet")
    pl = pd.read_parquet(BASE + r"\_event_study\placebo_paths.parquet")
    dl = pd.read_parquet(BASE + r"\_driver_analysis\panel_daily.parquet").reset_index()
    dl["date"] = pd.to_datetime(dl["date"]).dt.date
    dl = dl.sort_values("date").reset_index(drop=True)
    d = dl["d_rate_bp"]
    dl["cum_1d"] = d                                    # close(t-1) -> close(t)
    dl["cum_1w"] = d.rolling(5).sum().shift(-4)         # close(t-1) -> close(t+4)
    dl["pre_1d"] = d.shift(1)                           # close(t-2) -> close(t-1)
    dl["pre_1w"] = d.rolling(5).sum().shift(1)          # close(t-6) -> close(t-1)
    dl["bpos"] = np.arange(len(dl))
    return ev, pl, dl


def build(paths, dl, rank=RANK):
    p = paths[paths.contract_rank == rank]
    piv = p.pivot_table(index="event_id", columns="offset_min", values="rate_bp")
    out = p.drop_duplicates("event_id").set_index("event_id")[
        ["date", "stance_sign", "bucket", "is_overlapping", "speaker", "speech_ts"]].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for w in INTRA_W:
        out[f"w{w}"] = (piv[w] - piv[0]) * out["stance_sign"]
    for w in PRE_W:
        out[f"pre{w}"] = (piv[0] - piv[-w]) * out["stance_sign"]
    dd = dl.set_index("date")
    for nm, col in [("w1440", "cum_1d"), ("w7200", "cum_1w"), ("pre1440", "pre_1d"), ("pre7200", "pre_1w")]:
        out[nm] = out["date"].map(dd[col]) * out["stance_sign"]
    out["bpos"] = out["date"].map(dd["bpos"])
    out["year"] = pd.to_datetime(out["date"]).dt.year
    return out


def block_bootstrap(df, col, dl, B=10, n_boot=5000, seed=20260825):
    """Moving-block bootstrap over the business-day spine. Blocks of B business days
    absorb serial correlation from overlapping multi-day windows."""
    rng = np.random.default_rng(seed)
    s = df.dropna(subset=[col, "bpos"])
    if len(s) < 10:
        return np.nan, np.nan, np.nan
    N = len(dl)
    lo, hi = int(s.bpos.min()), int(s.bpos.max())
    span = hi - lo + 1
    k = int(np.ceil(span / B))
    starts_pool = np.arange(lo, hi - B + 2)
    if len(starts_pool) < 2:
        return np.nan, np.nan, np.nan
    # bucket events by business-day position for fast lookup
    by_pos = {}
    for pos, v in zip(s.bpos.values.astype(int), s[col].values):
        by_pos.setdefault(pos, []).append(v)
    means = np.empty(n_boot)
    for b in range(n_boot):
        st = rng.choice(starts_pool, size=k, replace=True)
        vals = []
        for a in st:
            for p in range(a, a + B):
                if p in by_pos:
                    vals.extend(by_pos[p])
        means[b] = np.mean(vals) if vals else np.nan
    means = means[np.isfinite(means)]
    m = s[col].mean()
    se = means.std(ddof=1)
    # two-sided p from the bootstrap distribution recentred on 0
    p = float((np.abs(means - means.mean()) >= abs(m)).mean())
    return se, m / se if se > 0 else np.nan, p


def nw_day_t(df, col, lag):
    """Day-collapse then Newey-West on the collapsed series (Driscoll-Kraay style)."""
    s = df.dropna(subset=[col])
    day = s.groupby("date")[col].mean().sort_index()
    x = day.values
    n = len(x)
    if n < 10: return np.nan, np.nan
    m = x.mean(); e = x - m
    g0 = (e ** 2).sum()
    S = g0
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1.0)
        S += 2.0 * w * (e[l:] * e[:-l]).sum()
    S = max(S, 1e-12)
    se = np.sqrt(S) / n
    return se, m / se


def main():
    ev, pl, dl = load()
    E = build(ev, dl); P = build(pl, dl)
    Es = E[E.stance_sign != 0]
    Ps = P[P.stance_sign != 0]
    Ec = Es[Es[WCOLS].notna().all(axis=1)]
    Pc = Ps[Ps[WCOLS].notna().all(axis=1)]
    print("common-sample events n=%d  days=%d | placebo n=%d" % (len(Ec), Ec.date.nunique(), len(Pc)))

    out = {}

    # ---------- 1. PRE-EVENT MIRROR ----------
    print("\n" + "=" * 78)
    print("1. PRE-EVENT MIRROR  (signed move over the window ENDING at the speech)")
    print("=" * 78)
    print(f"{'window':>8} {'POST mean':>10} {'POST t':>8} {'PRE mean':>10} {'PRE t':>8}   read")
    mirror = []
    for w in PRE_W + [1440, 7200]:
        pc, ps, pt, pn, pg = cluster_t(Ec[f"w{w}"].values, Ec["date"].values)
        qc, qs, qt, qn, qg = cluster_t(Ec[f"pre{w}"].values, Ec["date"].values)
        rd = "PRE >= POST -> momentum/drift" if abs(qc) >= abs(pc) else "post larger"
        print(f"{w:>8} {pc:>10.4f} {pt:>8.2f} {qc:>10.4f} {qt:>8.2f}   {rd}")
        mirror.append(dict(window_min=w, post_mean=pc, post_t=pt, pre_mean=qc, pre_t=qt, n=pn))
    out["pre_event_mirror"] = mirror

    # same on placebo, 1 week
    for nm, D in [("placebo", Pc)]:
        a = cluster_t(D["w7200"].values, D["date"].values)
        b = cluster_t(D["pre7200"].values, D["date"].values)
        print(f"  [{nm}] 1w POST mean {a[0]:+.4f} (t {a[2]:+.2f})   PRE mean {b[0]:+.4f} (t {b[2]:+.2f})")

    # ---------- 2. OVERLAP CORRECTION ----------
    print("\n" + "=" * 78)
    print("2. OVERLAP-CORRECTED INFERENCE on the multi-day windows")
    print("=" * 78)
    corr = []
    for w, lag in [(240, 0), (300, 0), (1440, 1), (7200, 5)]:
        m, se_cl, t_cl, n, G = cluster_t(Ec[f"w{w}"].values, Ec["date"].values)
        se_nw, t_nw = nw_day_t(Ec, f"w{w}", max(lag, 1))
        B = 10 if w < 7200 else 15
        se_bb, t_bb, p_bb = block_bootstrap(Ec, f"w{w}", dl, B=B)
        print(f"window {w:>5}min  mean {m:+.4f}bp | day-cluster t {t_cl:+.2f} | NW(lag{max(lag,1)}) t {t_nw:+.2f} "
              f"| block-boot(B={B}d) t {t_bb:+.2f} p={p_bb:.3f}")
        corr.append(dict(window_min=w, mean_bp=m, t_cluster=t_cl, t_nw=t_nw, t_block=t_bb, p_block=p_bb, block_days=B))
    out["overlap_corrected"] = corr

    # ---------- 3. IS THE 1-WEEK NUMBER CONCENTRATED? ----------
    print("\n" + "=" * 78)
    print("3. 1-WEEK signed response by year (common sample)")
    print("=" * 78)
    yr = []
    for y, s in Ec.groupby("year"):
        m, se, t, n, G = cluster_t(s["w7200"].values, s["date"].values)
        pm, pse, pt, pn, pg = cluster_t(s["pre7200"].values, s["date"].values)
        print(f"  {y}: n={n:4d} days={G:3d}  POST mean {m:+7.3f} (t {t:+5.2f})   PRE mean {pm:+7.3f} (t {pt:+5.2f})")
        yr.append(dict(year=int(y), n=n, post_mean=m, post_t=t, pre_mean=pm, pre_t=pt))
    out["one_week_by_year"] = yr

    # sign-of-arm decomposition in RAW rate space (drift diagnostic)
    print("\n  RAW (unsigned) 1-week rate change by stance arm -- drift diagnostic:")
    for nm, sub in [("hawk", Ec[Ec.stance_sign > 0]), ("dove", Ec[Ec.stance_sign < 0])]:
        raw = sub["w7200"] * sub["stance_sign"]     # undo the sign -> raw bp
        rawpre = sub["pre7200"] * sub["stance_sign"]
        print(f"    {nm}: n={len(sub):4d}  raw 1w POST {raw.mean():+7.3f}bp   raw 1w PRE {rawpre.mean():+7.3f}bp")

    with open(BASE + r"\_event_study\c4_checks.json", "w") as f:
        json.dump(out, f, indent=1, default=float)
    print("\nwrote c4_checks.json")


if __name__ == "__main__":
    main()
