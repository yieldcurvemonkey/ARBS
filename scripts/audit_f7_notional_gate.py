"""AUDIT PROBE 3 -- run F7's REGISTERED notional-weighted sensitivity arm.

H-F7 registered COUNT as the primary shock definition and a NOTIONAL-WEIGHTED arm as a
sensitivity ("reads capped values at their floor").  scripts/s3_f7_gate.py only ever ran
the count arm.  This probe runs the notional arm with EVERY other convention identical,
imported from the gate module itself so they cannot drift:

  same Z_WIN/FLOW_WIN=60, SHOCK_Q=0.90, Z_ENTRY=1.0 + 2-consecutive-close persistence,
  lag-1 fill, h in {1,5,21}, CM-2 round trip, same sample (par-grid days with an SDR file),
  same episode constructor, same .round(3)-then-median headline order.

Step 0 is a HARNESS VALIDATION: the count arm must reproduce the committed headline
(-0.123 / -0.216 / -0.215) before the notional numbers are allowed to mean anything.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/audit_f7_notional_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import s3_f7_gate as g  # noqa: E402  -- the gate itself, conventions and all

OUT = g.OUT
HORIZONS = g.HORIZONS


# ------------------------------------------------------------------ sample
def load_sample():
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
    dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    file_dates = pd.to_datetime(dg_all["file_date"])
    common = par.index.intersection(pd.DatetimeIndex(file_dates))
    return par, pkg, uni, common


# ------------------------------------------------------------------- arm
def run_arm(par, pkg, uni, common, mode: str):
    """mode = 'count' (the gate's primary) or 'notional' (the registered sensitivity)."""
    rows, panels, diag = [], {}, []
    for sig in uni:
        x = g.structure_series(par, sig).reindex(common).dropna()
        sub = pkg[pkg["signature"] == sig]
        if mode == "count":
            flow = sub.groupby("file_date").size()
        elif mode == "notional":
            flow = sub.groupby("file_date")["notional_sum"].sum()
        else:
            raise ValueError(mode)
        flow = flow.reindex(x.index, fill_value=0).astype(float)

        z = g.zscore(x, g.Z_WIN)
        shock = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
        persistent = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= g.Z_ENTRY)
        rt = g.round_trips(sig)
        panels[sig] = dict(x=x, z=z, persistent=persistent, shock=shock, flow=flow, rt=rt)
        diag.append({"signature": sig, "days": int(len(x)),
                     "shock_days": int(shock.sum()),
                     "entry_days": int(persistent.sum()),
                     "entry_and_shock": int((persistent & shock).sum())})

        for h in HORIZONS:
            base = dict(signature=sig, n_legs=len(sig.split("-")), h=h, **rt)
            for book, mask in (("all", persistent),
                               ("shock", persistent & shock),
                               ("noshock", persistent & ~shock)):
                rows.append({**base, "book": book,
                             **g.stats(g.episodes(x, z, mask, h), rt["rt_cm2"])})

    res = pd.DataFrame(rows)
    piv = res[res["book"].isin(["all", "shock", "noshock"])].pivot_table(
        index=["signature", "h"], columns="book",
        values=["n", "gross_med", "net_mean_1x", "abs_move_med"])
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    # SAME rounding order as the gate: round the per-signature increment to 3dp,
    # THEN take the median across signatures.
    piv["incr_gross_vs_all"] = (piv["gross_med_shock"] - piv["gross_med_all"]).round(3)
    piv["incr_gross_vs_noshock"] = (piv["gross_med_shock"] - piv["gross_med_noshock"]).round(3)
    piv = piv.reset_index()
    return res, piv, panels, pd.DataFrame(diag)


def headline(piv, label):
    out = {}
    for h in HORIZONS:
        s = piv[piv["h"] == h]
        out[h] = {
            "median_incr_vs_all": float(s["incr_gross_vs_all"].median()),
            "median_incr_vs_noshock": float(s["incr_gross_vs_noshock"].median()),
            "median_shock_net_1x": float(s["net_mean_1x_shock"].median()),
            "n_positive_incr": int((s["incr_gross_vs_noshock"] > 0).sum()),
            "n_sigs": int(len(s)),
        }
        print(f"  [{label}] h={h:>2}bd  median incr vs noshock "
              f"{out[h]['median_incr_vs_noshock']:+.3f}bp  vs all "
              f"{out[h]['median_incr_vs_all']:+.3f}bp  | positive "
              f"{out[h]['n_positive_incr']}/{out[h]['n_sigs']}  | median shock net@1x "
              f"{out[h]['median_shock_net_1x']:+.3f}bp")
    return out


def placebo(panels, piv, draws=200, seed=20260809):
    rng = np.random.default_rng(seed)
    res = {}
    for h in HORIZONS:
        real = float(piv[piv["h"] == h]["incr_gross_vs_noshock"].median())
        d = []
        for _ in range(draws):
            incs = []
            for sig, P in panels.items():
                k = int(rng.integers(20, len(P["x"]) - 20))
                sh = pd.Series(np.roll(P["shock"].to_numpy(), k), index=P["x"].index)
                a = g.episodes(P["x"], P["z"], P["persistent"] & sh, h)
                b = g.episodes(P["x"], P["z"], P["persistent"] & ~sh, h)
                if len(a) and len(b):
                    incs.append(float(a["gross_bp"].median() - b["gross_bp"].median()))
            if incs:
                d.append(float(np.median(incs)))
        d = np.array(d)
        res[h] = {"real": real, "null_mean": float(d.mean()),
                  "null_sd": float(d.std(ddof=1)), "p_value": float((d >= real).mean()),
                  "draws": int(len(d))}
        print(f"  h={h:>2}bd  real {real:+.3f}  null mean {d.mean():+.3f} "
              f"sd {d.std(ddof=1):.3f}   p(null>=real) = {res[h]['p_value']:.3f}")
    return res


def main() -> None:
    par, pkg, uni, common = load_sample()
    print(f"universe {uni}\nsample {len(common)} file-days "
          f"{common.min().date()}..{common.max().date()}")

    # ---- capped/negative notional facts, stated before any number ----------
    tot = pkg["notional_sum"].sum()
    capped = pkg[pkg["capped_any"]]
    neg = pkg[pkg["notional_sum"] < 0]
    print(f"\npackages {len(pkg):,}; capped_any {len(capped):,} ({len(capped)/len(pkg):.2%}) "
          f"carrying {capped['notional_sum'].sum()/tot:.2%} of summed notional "
          f"(read at the CFTC FLOOR, which is the registered rule)")
    print(f"negative notional_sum packages: {len(neg)} "
          f"(total {neg['notional_sum'].sum():,.0f} = {neg['notional_sum'].sum()/tot:.4%} of the sum) "
          f"-- LEFT IN, dropping it would be tuning")
    if len(neg):
        print(neg[["file_date", "exec_ts", "signature", "notional_sum", "capped_any"]]
              .to_string(index=False))

    # ---- STEP 0: harness validation against the committed headline ---------
    print("\n=== STEP 0  harness validation: COUNT arm must reproduce the committed gate ===")
    res_c, piv_c, pan_c, dg_c = run_arm(par, pkg, uni, common, "count")
    h_c = headline(piv_c, "count")
    committed = json.loads((OUT / "f7_gate_verdict.json").read_text())["headline"]
    ok = True
    for h in HORIZONS:
        for k in ("median_incr_vs_all", "median_incr_vs_noshock",
                  "median_shock_net_1x", "n_positive_incr"):
            a, b = h_c[h][k], committed[str(h)][k]
            same = abs(float(a) - float(b)) < 1e-9
            ok &= same
            if not same:
                print(f"  MISMATCH h={h} {k}: mine {a} vs committed {b}")
    print(f"  harness reproduces the committed count-based headline EXACTLY: {ok}")
    if not ok:
        raise SystemExit("HARNESS INVALID -- refusing to report notional numbers.")

    # ---- STEP 1: the registered NOTIONAL arm -------------------------------
    print("\n=== STEP 1  NOTIONAL-WEIGHTED arm (registered sensitivity) ===")
    res_n, piv_n, pan_n, dg_n = run_arm(par, pkg, uni, common, "notional")
    h_n = headline(piv_n, "notional")

    # ---- STEP 2: how much does the shock-day SET move? ---------------------
    print("\n=== STEP 2  shock-day set: notional vs count (Jaccard) ===")
    jac_rows = []
    for sig in uni:
        sc = set(pan_c[sig]["shock"][pan_c[sig]["shock"]].index)
        sn = set(pan_n[sig]["shock"][pan_n[sig]["shock"]].index)
        inter, union = len(sc & sn), len(sc | sn)
        ec = set(pan_c[sig]["persistent"][pan_c[sig]["persistent"]].index) & sc
        en = set(pan_n[sig]["persistent"][pan_n[sig]["persistent"]].index) & sn
        jac_rows.append({
            "signature": sig, "n_shock_count": len(sc), "n_shock_notional": len(sn),
            "both": inter, "union": union, "jaccard": round(inter / union, 3) if union else np.nan,
            "entry_and_shock_count": len(ec), "entry_and_shock_notional": len(en),
            "entry_shock_jaccard": round(len(ec & en) / len(ec | en), 3) if (ec | en) else np.nan,
        })
    jac = pd.DataFrame(jac_rows)
    print(jac.to_string(index=False))
    print(f"  median Jaccard(shock days) = {jac['jaccard'].median():.3f}; "
          f"median Jaccard(entry&shock days) = {jac['entry_shock_jaccard'].median():.3f}")

    # ---- STEP 3: per-signature increment tables ----------------------------
    cols = ["signature", "h", "n_shock", "n_noshock", "gross_med_shock",
            "gross_med_noshock", "incr_gross_vs_noshock", "incr_gross_vs_all",
            "net_mean_1x_shock"]
    print("\n=== per-signature, NOTIONAL arm ===")
    print(piv_n[cols].to_string(index=False))
    print("\n=== per-signature, COUNT arm (for side-by-side) ===")
    print(piv_c[cols].to_string(index=False))

    merged = piv_n[["signature", "h", "n_shock", "incr_gross_vs_noshock"]].merge(
        piv_c[["signature", "h", "n_shock", "incr_gross_vs_noshock"]],
        on=["signature", "h"], suffixes=("_notional", "_count"))
    merged["delta"] = (merged["incr_gross_vs_noshock_notional"]
                       - merged["incr_gross_vs_noshock_count"]).round(3)
    print("\n=== notional minus count, per signature/horizon ===")
    print(merged.to_string(index=False))

    # ---- STEP 4: the only cell that can change the verdict ------------------
    # Step (i) POND has no shock in it at all, so no shock redefinition can revive the
    # five flies -- they died on |move| vs round trip. The registered gate needs >= 2
    # signatures positive at the SAME h, and only the pond-clearing SPREADS at h=21
    # can supply them.
    print("\n=== STEP 4  the pond-clearing cell: 5 spreads at h=21 ===")
    spreads = [s for s in uni if len(s.split("-")) == 2]
    for label, piv in (("notional", piv_n), ("count", piv_c)):
        s = piv[(piv["h"] == 21) & (piv["signature"].isin(spreads))]
        print(f"  [{label}] spreads h=21: median incr "
              f"{s['incr_gross_vs_noshock'].median():+.3f}bp, positive "
              f"{int((s['incr_gross_vs_noshock'] > 0).sum())}/{len(s)}, "
              f"median shock net@1x {s['net_mean_1x_shock'].median():+.3f}bp, "
              f"min n_shock {int(s['n_shock'].min())}")
        print(s[cols].to_string(index=False))

    # pond is shock-free by construction -- prove it moves not at all
    pond_n = piv_n[["signature", "h", "abs_move_med_all", "n_all"]]
    pond_c = piv_c[["signature", "h", "abs_move_med_all", "n_all"]]
    same_pond = pond_n.equals(pond_c)
    print(f"\n  POND identical under both shock definitions (it contains no shock): {same_pond}")
    pond_tab = pond_n.copy()
    pond_tab["rt_cm2"] = pond_tab["signature"].map(lambda s: g.round_trips(s)["rt_cm2"])
    pond_tab["pond_over_boat"] = (pond_tab["abs_move_med_all"] / pond_tab["rt_cm2"]).round(2)
    print(pond_tab.to_string(index=False))

    # ---- STEP 5: placebo on the NOTIONAL shock -----------------------------
    print("\n=== STEP 5  wrong-day placebo on the NOTIONAL shock (200 draws) ===")
    pb = placebo(pan_n, piv_n)

    (pathlib.Path(_HERE) / "audit_f7_notional_result.json").write_text(json.dumps({
        "harness_reproduces_committed_count_headline": bool(ok),
        "headline_count": {str(k): v for k, v in h_c.items()},
        "headline_notional": {str(k): v for k, v in h_n.items()},
        "jaccard": jac.to_dict("records"),
        "placebo_notional": {str(k): v for k, v in pb.items()},
        "per_signature_notional": piv_n[cols].to_dict("records"),
        "per_signature_count": piv_c[cols].to_dict("records"),
    }, indent=2, default=str), encoding="utf-8")
    print("\nwrote scripts/audit_f7_notional_result.json")


if __name__ == "__main__":
    main()
