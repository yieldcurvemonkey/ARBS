"""R0b — rebuild X with the Citi minute-curve sign in place of the trailing-median sign.

THE ONE CHANGE (r0b_prereg.md):

    customer_sign = sign(fixed_rate - Citi minute-curve par rate at the print's
                         snapped EXECUTION minute)          [+1 above mid, -1 below]

instead of

    customer_sign = sign(fixed_rate - trailing same-key median)

Everything else about X is R0's: the same per-print frame `build_x_tape.py` itself wrote,
the same bucket map, the same dv01, the same two clocks, the same
(bucket, minute, clock, is_block, venue_class) grain, the same emit window.

The proof that nothing else moved is a KNOWN-ANSWER GATE, run before anything else: this
script first re-derives R0's OWN X from the same per-print frame using the median sign,
and requires it to reproduce `data/x_signed_dv01.parquet` cell for cell. If the rebuild
of R0's X is exact, then the R0b file differs from R0's in exactly one column, for
exactly one reason.

Reads nothing over the network. The reference pull is a separate, resumable step
(`scratch_r0b_pull_ref.py`). Writes to D: only; C: was at 3.7 GB.

Choices frozen in r0b_deviations.md R0b-1 .. R0b-4 and R0b-9 before this file was written.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

from build_x_tape import customer_sign_from_mid                      # noqa: E402

LEGS = r"D:\r0_cache_moved\cache\tape_legs_signed.parquet"
REFDIRS = [r"D:\r0_cache_moved\cache_d1_ref", r"D:\r0b_cache\ref"]
OUTDIR = r"D:\r0b_cache"
X_R0B = os.path.join(OUTDIR, "x_signed_dv01_curve.parquet")
JOINED = os.path.join(OUTDIR, "legs_curve_signed.parquet")
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")

EMIT_START = pd.Timestamp("2026-05-01", tz="UTC")
EMIT_END = pd.Timestamp("2026-08-08", tz="UTC")      # exclusive
TOL = pd.Timedelta("2min")                            # R10, unchanged
BUCKETS = ["SFR_FF", "TU", "FV", "TY_UXY", "US"]

_L: list[str] = []


def log(m: str = "") -> None:
    print(m, flush=True)
    _L.append(m)


def bin_x(legs: pd.DataFrame, signcol: str) -> pd.DataFrame:
    """R0's binning, verbatim (build_x_tape.stage_build). Only `signcol` varies."""
    frames = []
    for clock, tscol in (("exec", "execution_timestamp"), ("diss", "dissem_ts_utc")):
        sub = legs[["bucket", "is_block", "venue_class", "dv01", signcol, tscol]].copy()
        sub["minute_utc"] = sub[tscol].dt.floor("min")
        sub = sub[(sub["minute_utc"] >= EMIT_START) & (sub["minute_utc"] < EMIT_END)]
        sub["signed"] = sub[signcol].astype(float) * sub["dv01"]
        g = sub.groupby(["bucket", "minute_utc", "is_block", "venue_class"], sort=False).agg(
            signed_dv01=("signed", "sum"),
            gross_dv01=("dv01", "sum"),
            n_prints=("dv01", "size"),
        ).reset_index()
        g["clock"] = clock
        frames.append(g)
    out = pd.concat(frames, ignore_index=True)
    out = out[["bucket", "minute_utc", "clock", "signed_dv01", "gross_dv01",
               "n_prints", "is_block", "venue_class"]]
    return out.sort_values(["clock", "bucket", "minute_utc", "is_block",
                            "venue_class"]).reset_index(drop=True)


def main() -> int:
    t0 = time.time()
    os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    log("=" * 100)
    log("R0b — X rebuilt with the Citi minute-curve sign.  ONE change; everything else gated.")
    log("=" * 100)

    legs = pd.read_parquet(LEGS)
    legs["tenor_lc"] = legs["tenor_label"].astype(str).str.lower()
    legs["_row"] = np.arange(len(legs))
    log(f"per-print frame handed over by the X workstream: {len(legs):,} legs")

    # =====================================================================
    # GATE 0 (known answer) — re-derive R0's OWN X from this frame and require
    # it to reproduce data/x_signed_dv01.parquet exactly. If this passes, the
    # binning below is R0's binning and the only thing R0b changes is the sign.
    # =====================================================================
    x_r0_disk = pd.read_parquet(os.path.join(DATA, "x_signed_dv01.parquet"))
    x_r0_mine = bin_x(legs, "customer_sign")
    same_shape = x_r0_mine.shape == x_r0_disk.shape
    key = ["clock", "bucket", "minute_utc", "is_block", "venue_class"]
    m = x_r0_disk.merge(x_r0_mine, on=key, how="outer", suffixes=("_disk", "_mine"),
                        indicator=True)
    unmatched = int((m["_merge"] != "both").sum())
    dmax_signed = float(np.abs(m["signed_dv01_disk"] - m["signed_dv01_mine"]).max())
    dmax_gross = float(np.abs(m["gross_dv01_disk"] - m["gross_dv01_mine"]).max())
    dmax_np = int(np.abs(m["n_prints_disk"] - m["n_prints_mine"]).max())
    gate0 = same_shape and unmatched == 0 and dmax_signed < 1e-6 and \
        dmax_gross < 1e-6 and dmax_np == 0
    log("")
    log("GATE 0 — rebuild R0's OWN X from this frame and compare to data/x_signed_dv01.parquet:")
    log(f"  shape {x_r0_mine.shape} vs {x_r0_disk.shape} [{same_shape}]   "
        f"unmatched cells {unmatched}")
    log(f"  max |d signed_dv01| = {dmax_signed:.3e}   max |d gross_dv01| = {dmax_gross:.3e}   "
        f"max |d n_prints| = {dmax_np}")
    log(f"  R0's X is reproduced exactly from the per-print frame [{gate0}]")
    if not gate0:
        log("  GATE 0 FAILED — the rebuild is not R0's binning. Refusing to build R0b's X.")
        return 2

    # =====================================================================
    # The reference series (R0b-4), verified after the move to D:
    # =====================================================================
    from scripts.citivelo_intraday_ts_warm import SPOT_TENORS
    warm_labels = {t.lower() for t in SPOT_TENORS}
    spot_sel = (legs["fwd_key"] == "spot") & (~legs["is_mac"]) & \
               (legs["execution_timestamp"] >= EMIT_START) & \
               (legs["execution_timestamp"] < EMIT_END)
    wanted = sorted({t for t in legs.loc[spot_sel, "tenor_lc"].unique() if t in warm_labels})

    frames, have, missing = [], [], []
    for tn in wanted:
        p = None
        for d in REFDIRS:
            c = os.path.join(d, f"ref_{tn}.parquet")
            if os.path.exists(c):
                p = c
                break
        if p is None:
            missing.append(tn)
            continue
        f = pd.read_parquet(p)
        assert f["ref_rate"].notna().all(), f"{tn}: NaN in the reference"
        assert not f.duplicated(["tenor_lc", "ref_min"]).any(), f"{tn}: duplicate minutes"
        frames.append(f)
        have.append((tn, len(f), f["ref_min"].min(), f["ref_min"].max()))
    log("")
    log(f"reference tenor set (R0b-4): wanted {len(wanted)}, available {len(have)}")
    for tn, n, a, b in have:
        log(f"    {tn:5s} {n:7,} minutes  {a} .. {b}")
    if missing:
        log(f"  NOT AVAILABLE, excluded and disclosed (R0b-4): {', '.join(missing)}")
    ref = pd.concat(frames, ignore_index=True).drop_duplicates(["tenor_lc", "ref_min"])
    ref = ref.sort_values("ref_min")

    # =====================================================================
    # Eligibility (R0b-3) and the join (R10, unchanged)
    # =====================================================================
    legs["exec_min"] = legs["execution_timestamp"].dt.floor("min")
    et_hour = legs["execution_timestamp"].dt.tz_convert("America/New_York").dt.hour
    elig_pre = (legs["fwd_key"] == "spot") & (~legs["is_mac"]) & \
               legs["tenor_lc"].isin([t for t, *_ in have])
    elig = elig_pre & et_hour.between(1, 22)
    log("")
    log(f"eligible before the Citi-session rule : {int(elig_pre.sum()):,} legs")
    log(f"R0b-3 Citi session 01:00-22:59 ET     : {int(elig.sum()):,} = "
        f"{elig.sum()/max(int(elig_pre.sum()),1):.1%} retained "
        f"({int(elig_pre.sum()) - int(elig.sum()):,} excluded, not filled)")

    d = legs[elig].sort_values("exec_min")
    parts = []
    for tn, g in d.groupby("tenor_lc"):
        r = ref[ref["tenor_lc"] == tn]
        if r.empty:
            continue
        parts.append(pd.merge_asof(
            g.sort_values("exec_min"),
            r[["ref_min", "ref_rate"]].sort_values("ref_min"),
            left_on="exec_min", right_on="ref_min", direction="backward", tolerance=TOL))
    j = pd.concat(parts, ignore_index=True)
    matched = j["ref_rate"].notna()
    log(f"join (merge_asof backward, tolerance {TOL}): {int(matched.sum()):,} / {len(j):,} "
        f"= {matched.mean():.1%}")
    j = j[matched].copy()

    scale = float(np.nanmedian(j["ref_rate"] / j["fixed_rate"]))
    log(f"units detected from the data: median ref_rate/fixed_rate = {scale:.3f} -> "
        f"{'reference PERCENT, tape DECIMAL' if scale > 50 else 'same units'}")
    j["ref_dec"] = j["ref_rate"] / (100.0 if scale > 50 else 1.0)
    j["dev_curve"] = j["fixed_rate"] - j["ref_dec"]

    # ---- join staleness (R0b-8): the sharp reading of a collapse needs this ----
    stale = (j["exec_min"] - j["ref_min"]).dt.total_seconds() / 60.0
    log("")
    log("join staleness, exec_min - ref_min (minutes) — the curve is read at or before T:")
    vc = stale.value_counts().sort_index()
    for v, n in vc.items():
        log(f"    {v:+4.0f} min : {n:9,}  ({n/len(stale):7.3%})")

    # =====================================================================
    # GATE 1..4 — the reference must be sound before it becomes the sign
    # =====================================================================
    log("")
    log("GATE 1 — orientation: rate > mid MUST give dev_curve > 0")
    n_or = int(((j["fixed_rate"] > j["ref_dec"]) == (j["dev_curve"] > 0)).sum())
    log(f"  {n_or:,}/{len(j):,} = {n_or/len(j):.4%}")
    g1 = n_or == len(j)

    log("GATE 2 — the reference must sit ON the tape, not drift against it")
    daymed = (j.assign(day=j["exec_min"].dt.date).groupby("day")["dev_curve"].median() * 1e4)
    drift = float(np.corrcoef(j["dev_curve"], j["ref_dec"])[0, 1])
    log(f"  per-day median dev_curve (bp): n_days {len(daymed)}  p5 {daymed.quantile(.05):+.2f}  "
        f"p50 {daymed.median():+.2f}  p95 {daymed.quantile(.95):+.2f}  "
        f"min {daymed.min():+.2f}  max {daymed.max():+.2f}")
    log(f"  overall median {j['dev_curve'].median()*1e4:+.2f} bp, IQR "
        f"{(j['dev_curve'].quantile(.75)-j['dev_curve'].quantile(.25))*1e4:.2f} bp")
    log(f"  corr(dev_curve, level of the reference rate) = {drift:+.3f}  "
        f"(a tz/units error drives this to +-1)")
    g2 = abs(float(daymed.median())) < 1.0 and abs(drift) < 0.10

    log("GATE 3 — hand-check, eight prints, raw numbers, sign read by eye")
    log(f"  {'tenor':5s} {'exec minute (UTC)':19s} {'fixed_rate%':>11s} {'curve mid%':>10s} "
        f"{'dev_curve bp':>12s} {'dev_median bp':>13s} {'expect':>7s} {'got':>5s}")
    hc = j.iloc[np.random.default_rng(0).choice(len(j), size=8, replace=False)]
    n_hc = 0
    for _, r in hc.iterrows():
        exp = "+" if r["fixed_rate"] > r["ref_dec"] else ("-" if r["fixed_rate"] < r["ref_dec"] else "0")
        got = "+" if r["dev_curve"] > 0 else ("-" if r["dev_curve"] < 0 else "0")
        n_hc += int(exp == got)
        dm = r["dev_median"] * 1e4 if np.isfinite(r["dev_median"]) else np.nan
        log(f"  {r['tenor_lc']:5s} {str(r['exec_min'])[:19]:19s} {r['fixed_rate']*100:11.5f} "
            f"{r['ref_dec']*100:10.5f} {r['dev_curve']*1e4:+12.2f} {dm:+13.2f} "
            f"{exp:>7s} {got:>5s}")
    log(f"  {n_hc}/8 correct by eye")
    g3 = n_hc == 8

    log("GATE 4 — agreement with the median rule must RISE with |dev| (an inverted join falls)")
    j["sign_curve"] = np.sign(j["dev_curve"]).astype(int)
    j["sign_median"] = np.sign(j["dev_median"].fillna(0.0)).astype(int)
    both = j[(j["sign_curve"] != 0) & (j["sign_median"] != 0)]
    agree = (both["sign_curve"] == both["sign_median"])
    log(f"  per-print sign agreement, both non-zero (n={len(both):,}): {agree.mean():.1%}")
    dec_rise = []
    for lab, col in (("|dev_median|", "dev_median"), ("|dev_curve| ", "dev_curve")):
        dec = pd.qcut(both[col].abs(), 10, labels=False, duplicates="drop")
        gg = agree.groupby(dec).mean()
        dec_rise.append(float(gg.iloc[-1] - gg.iloc[0]))
        log(f"  by {lab} decile: " + "  ".join(f"{v:.0%}" for v in gg))
    for thr in (5.0, 10.0, 20.0, 50.0):
        mm = (both["dev_curve"].abs() * 1e4 >= thr) & (both["dev_median"].abs() * 1e4 >= thr)
        if mm.sum():
            log(f"  both deviations >= {thr:4.0f} bp: {agree[mm].mean():6.1%}  (n={int(mm.sum()):,})")
    g4 = all(v > 0.15 for v in dec_rise)

    log("")
    log(f"GATES: orientation [{g1}]  centred [{g2}]  hand-check [{g3}]  rises-with-dev [{g4}]")
    if not (g1 and g2 and g3 and g4):
        log("  A REFERENCE GATE FAILED — refusing to build R0b's X.")
        return 3

    # =====================================================================
    # Build X_R0b
    # =====================================================================
    # scalar cross-check of the vectorised sign, R0's own single source of truth
    _s = np.random.default_rng(1).choice(len(j), size=min(2000, len(j)), replace=False)
    for i in _s:
        rr = float(j["fixed_rate"].iat[i]); mm2 = float(j["ref_dec"].iat[i])
        assert int(j["sign_curve"].iat[i]) == customer_sign_from_mid(rr, mm2), \
            "curve-sign vectorisation drift"
    log("curve sign cross-checked against build_x_tape.customer_sign_from_mid on 2,000 prints: OK")

    # Assign by ROW, never by trade_id: a package prints several legs under one
    # trade_id and they do not share a tenor, so a trade_id map would give them all
    # the same sign.
    sc = np.zeros(len(legs), dtype=np.int8)
    sc[j["_row"].to_numpy()] = j["sign_curve"].to_numpy(np.int8)
    legs["customer_sign_curve"] = sc
    assert int((legs["customer_sign_curve"] != 0).sum()) == int((j["sign_curve"] != 0).sum())
    n_signed = int((legs["customer_sign_curve"] != 0).sum())
    log(f"curve-signed legs: {n_signed:,} of {len(legs):,}")

    x_r0b = bin_x(legs, "customer_sign_curve")
    x_r0b.to_parquet(X_R0B, index=False)
    log(f"wrote {X_R0B}  ({len(x_r0b):,} rows)")

    # gross must be untouched relative to R0's file
    mg = x_r0_disk.merge(x_r0b, on=key, how="outer", suffixes=("_r0", "_r0b"))
    log(f"gross_dv01 identical to R0's X: "
        f"{bool(np.abs(mg['gross_dv01_r0'] - mg['gross_dv01_r0b']).max() < 1e-6)}   "
        f"n_prints identical: {bool((mg['n_prints_r0'] == mg['n_prints_r0b']).all())}")

    # =====================================================================
    # Coverage — reported, not assumed (R0b-3)
    # =====================================================================
    inwin = (legs["execution_timestamp"] >= EMIT_START) & (legs["execution_timestamp"] < EMIT_END)
    e = legs[inwin]
    log("")
    log("COVERAGE, in-window prints (exec clock).  R0 signs on the trailing median; "
        "R0b on the curve.")
    log(f"  {'bucket':8s} {'prints':>9s} | {'R0 signed':>10s} {'R0 dv01':>9s} | "
        f"{'R0b signed':>11s} {'R0b dv01':>9s}")
    cov_rows = []
    for b in BUCKETS + ["ALL"]:
        eb = e if b == "ALL" else e[e["bucket"] == b]
        tot_dv = eb["dv01"].sum()
        r0s = (eb["customer_sign"] != 0)
        rbs = (eb["customer_sign_curve"] != 0)
        log(f"  {b:8s} {len(eb):9,} | {r0s.mean():10.1%} "
            f"{eb.loc[r0s,'dv01'].sum()/tot_dv:9.1%} | {rbs.mean():11.1%} "
            f"{eb.loc[rbs,'dv01'].sum()/tot_dv:9.1%}")
        cov_rows.append(dict(bucket=b, n_prints=len(eb),
                             r0_signed_prints=float(r0s.mean()),
                             r0_signed_dv01=float(eb.loc[r0s, "dv01"].sum() / tot_dv),
                             r0b_signed_prints=float(rbs.mean()),
                             r0b_signed_dv01=float(eb.loc[rbs, "dv01"].sum() / tot_dv),
                             both_signed=float((r0s & rbs).mean())))
    pd.DataFrame(cov_rows).to_csv(os.path.join(OUT, "r0b_coverage.csv"), index=False)

    # per-print frame for the attenuation work (kept on D:)
    j.drop(columns=[c for c in ("mid_key",) if c in j.columns]).to_parquet(JOINED, index=False)
    log(f"wrote {JOINED}  ({len(j):,} joined prints)")

    with open(os.path.join(OUT, "r0b_x_build.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(_L) + "\n")
    log(f"elapsed {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
