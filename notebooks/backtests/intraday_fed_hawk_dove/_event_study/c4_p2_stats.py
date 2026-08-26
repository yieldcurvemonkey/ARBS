"""Core window-decay statistics. No figure yet - just the numbers."""
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


def cluster_t(x, g):
    """t-stat of the mean of x, SE clustered on g. Returns (mean, se, t, n, G)."""
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x = x[ok]
    g = np.asarray(g)[ok]
    n = len(x)
    if n < 3:
        return np.nan, np.nan, np.nan, n, 0
    m = x.mean()
    e = x - m
    df = pd.DataFrame({"e": e, "g": g})
    sg = df.groupby("g")["e"].sum().values
    G = len(sg)
    if G < 2:
        return m, np.nan, np.nan, n, G
    meat = (sg ** 2).sum()
    corr = (G / (G - 1.0)) * ((n - 1.0) / (n - 1.0))  # K=1
    V = corr * meat / (n ** 2)
    se = np.sqrt(V)
    return m, se, m / se if se > 0 else np.nan, n, G


def load():
    ev = pd.read_parquet(BASE + r"\_event_study\event_paths.parquet")
    pl = pd.read_parquet(BASE + r"\_event_study\placebo_paths.parquet")
    dl = pd.read_parquet(BASE + r"\_driver_analysis\panel_daily.parquet").reset_index()
    dl["date"] = pd.to_datetime(dl["date"]).dt.date
    dl = dl.sort_values("date").reset_index(drop=True)
    # forward cumulative sums of d_rate_bp: cum_k = sum of d_rate_bp over days t..t+k
    d = dl["d_rate_bp"].values
    dl["cum_1d"] = d                                     # close(t-1) -> close(t)
    dl["cum_1w"] = pd.Series(d).rolling(5).sum().shift(-4).values  # close(t-1) -> close(t+4)
    return ev, pl, dl


def build_responses(paths, dl, rank=RANK):
    """One row per event: signed response at each window width."""
    p = paths[paths.contract_rank == rank]
    piv = p.pivot_table(index="event_id", columns="offset_min", values="rate_bp")
    meta = p.drop_duplicates("event_id").set_index("event_id")[
        ["date", "stance_sign", "bucket", "is_overlapping", "speaker", "speech_ts",
         "is_cpi_day", "is_nfp_day", "is_fomc_day"]]
    out = meta.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for w in INTRA_W:
        out[f"w{w}"] = (piv[w] - piv[0]) * out["stance_sign"]
    dd = dl.set_index("date")
    out["w1440"] = out["date"].map(dd["cum_1d"]) * out["stance_sign"]
    out["w7200"] = out["date"].map(dd["cum_1w"]) * out["stance_sign"]
    # unsigned (rate-space) intraday moves too, for the correlation check
    for w in [240]:
        out[f"raw{w}"] = piv[w] - piv[0]
    out["raw_base240"] = piv[240] - piv[-60]
    out["raw_daily"] = out["date"].map(dd["cum_1d"])
    return out


WCOLS = [f"w{w}" for w in INTRA_W] + ["w1440", "w7200"]
WMIN = INTRA_W + [1440, 7200]


def table(df, label, common=True):
    if common:
        m = df[WCOLS].notna().all(axis=1)
        df = df[m]
    rows = []
    for c, w in zip(WCOLS, WMIN):
        mean, se, t, n, G = cluster_t(df[c].values, df["date"].values)
        sd = np.nanstd(df[c].values, ddof=1)
        rows.append(dict(window_min=w, mean_bp=mean, se_bp=se, t=t, n=n, n_days=G, std_bp=sd,
                         snr=mean / sd if sd > 0 else np.nan))
    r = pd.DataFrame(rows)
    print(f"\n--- {label}  (common sample={common}) ---")
    print(r.to_string(index=False, float_format=lambda v: f"{v:10.4f}"))
    return r


def main():
    ev, pl, dl = load()
    E = build_responses(ev, dl)
    P = build_responses(pl, dl)

    Es = E[E.stance_sign != 0]
    Ps = P[P.stance_sign != 0]
    print("signed events rank3:", len(Es), " placebo:", len(Ps))

    res = {}
    res["event_common"] = table(Es, "EVENTS signed, all", common=True)
    res["event_maxn"] = table(Es, "EVENTS signed, all", common=False)
    res["placebo_common"] = table(Ps, "PLACEBO signed, all", common=True)
    res["event_nonoverlap"] = table(Es[~Es.is_overlapping], "EVENTS signed, NON-OVERLAPPING", common=True)
    res["event_bucket"] = table(Es[Es.bucket.abs() >= 1], "EVENTS signed, |bucket|>=1", common=True)

    # hawk / dove split on the common sample
    m = Es[WCOLS].notna().all(axis=1)
    Ec = Es[m]
    print("\nhawk n=%d dove n=%d (common)" % ((Ec.stance_sign > 0).sum(), (Ec.stance_sign < 0).sum()))
    for nm, sub in [("hawk", Ec[Ec.stance_sign > 0]), ("dove", Ec[Ec.stance_sign < 0])]:
        vals = []
        for c, w in zip(WCOLS, WMIN):
            mean, se, t, n, G = cluster_t(sub[c].values, sub["date"].values)
            vals.append(f"{w}:{mean:+.3f}(t{t:+.2f})")
        print(nm, " ".join(vals))

    # ---- correlation check: +240 event window vs same-day close-to-close ----
    print("\n=== CORRELATION: +240 event window vs same-day close-to-close ===")
    for label, col in [("0->+240 (window)", "raw240"), ("-60->+240 (from baseline)", "raw_base240")]:
        s = Es.dropna(subset=[col, "raw_daily"]).copy()
        s["a_intra"] = s[col].abs()
        s["a_daily"] = s["raw_daily"].abs()
        day = s.groupby("date").agg(a_intra=("a_intra", "mean"), a_daily=("a_daily", "first"),
                                    s_intra=(col, "mean"), s_daily=("raw_daily", "first"))
        pr = np.corrcoef(day.a_intra, day.a_daily)[0, 1]
        sp = day[["a_intra", "a_daily"]].corr(method="spearman").iloc[0, 1]
        prs = np.corrcoef(day.s_intra, day.s_daily)[0, 1]
        print(f"{label}: n_days={len(day)}  ABS pearson={pr:.4f} (R2={pr**2:.4f}) spearman={sp:.4f} | SIGNED pearson={prs:.4f} (R2={prs**2:.4f})")
        # event-level too
        pre = np.corrcoef(s.a_intra, s.a_daily)[0, 1]
        print(f"   event-level n={len(s)} ABS pearson={pre:.4f} (R2={pre**2:.4f})")

    # all events (not just signed), since the daily study did not condition on stance
    print("\n-- all events (unsigned sample, matching the daily study's unconditional book) --")
    s = E.dropna(subset=["raw240", "raw_daily"]).copy()
    day = s.assign(ai=s.raw240.abs(), ad=s.raw_daily.abs()).groupby("date").agg(
        ai=("ai", "mean"), ad=("ad", "first"))
    pr = np.corrcoef(day.ai, day.ad)[0, 1]
    sp = day.corr(method="spearman").iloc[0, 1]
    print(f"n_days={len(day)} ABS pearson={pr:.4f} (R2={pr**2:.4f}) spearman={sp:.4f}")

    out = {}
    for k, v in res.items():
        out[k] = v.to_dict(orient="records")
    with open(BASE + r"\_event_study\c4_stats.json", "w") as f:
        json.dump(out, f, indent=1, default=float)
    print("\nwrote c4_stats.json")


if __name__ == "__main__":
    main()
