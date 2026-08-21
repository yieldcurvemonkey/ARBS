"""Adversarial pass 11: consolidate every re-derived number into one verdict table."""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
R = []


def row(claim, reported, recomputed, unit, verdict, note):
    R.append(dict(claim=claim, reported=reported, recomputed=recomputed, unit=unit,
                  verdict=verdict, note=note))


g = pd.read_csv(DATA / "tsgrid_grid.csv")
real = g[g.kind == "real"]; nc = real[real.signal != "resid"]; pl = g[g.kind == "placebo"]
hold = g[g.signal.isin(L.HOLDINGS_SIGNALS)]
nul = pd.read_csv(DATA / "adv_ts_permutation_null.csv")
bnd = pd.read_csv(DATA / "adv_ts_deletion_boundary_placebo.csv")
dpn = pd.read_csv(DATA / "adv_ts_deletion_perm_null.csv")
st = pd.read_csv(DATA / "adv_ts_stale_rerun.csv")

row("gross cells evaluated", 23040, len(g), "count", "CONFIRMED", "17,280 real + 5,760 placebo")
row("inert-lag duplicate cells", 1920, 480, "count",
    "REFUTED", "only `resid` is lag-inert (480 coord groups); `deletion` lag IS active "
               "(0.009417 vs 0.009327). Distinct cells = 22,560, not 21,120")
row("real cells with gross>0 (mult=0)", "8,212/16,320 = 50.3%",
    "%d/%d = %.2f%%" % ((nc.gross_bp > 0).sum(), len(nc), 100 * (nc.gross_bp > 0).mean()),
    "%", "CONFIRMED", "")
row("placebo cells with gross>0", "50.99%",
    "%.2f%%" % (100 * (pl.gross_bp > 0).mean()), "%", "CONFIRMED", "")
row("HOLDINGS-only cells with gross>0", "not reported",
    "%.2f%%" % (100 * (hold.gross_bp > 0).mean()), "%", "ADDITION",
    "holdings signals lean NEGATIVE gross, 44.7%")
row("real cells net>0 at measured cost x0.25", 0,
    int((real.gross_bp - 0.25 * real.cost_measured > 0).sum()), "count", "CONFIRMED", "")
row("holdings max gross", 0.0278, float(hold.gross_bp.max()), "bp", "CONFIRMED",
    "but that cell rests on n_dates=96 of 1,682 (the grid floor is 50)")
row("holdings max |HAC t|", 2.80, float(hold.t_nw.abs().max()), "|t|", "CONFIRMED", "")
row("holdings best break-even", 0.042,
    float((hold.gross_bp / hold.cost_measured).max()), "x", "CONFIRMED", "")
row("best real break-even anywhere", 0.0645,
    float((nc.gross_bp / nc.cost_measured).max()), "x", "CONFIRMED",
    "the deciding number; all of it is `deletion` orth")
row("placebo max |HAC t| (3 draws)", 3.36, float(pl.t_nw.abs().max()), "|t|", "CONFIRMED",
    "but calibrated on N_PLACEBO=3 permutations, not 5,760 independent cells")
row("permutation null max|t| over 960-cell search", "not run (3 draws)",
    "med %.2f p95 %.2f max %.2f over 40 draws" % (nul.max_abs_t.median(),
                                                  nul.max_abs_t.quantile(.95),
                                                  nul.max_abs_t.max()),
    "|t|", "WEAKENED->CONFIRMED", "properly drawn null is HIGHER; report's conclusion is conservative")
row("sqrt(2 ln K) hurdle = 4.48", 4.48, 4.48, "|t|", "WEAKENED",
    "assumes K independent cells; cells are ~99% correlated, so 4.48 is meaningless. "
    "Use the 40-draw empirical null (max 3.66) instead")
row("deletion-orth cell gross / t / cost", "0.0094 / 4.58 / 1.048",
    "0.009417 / 4.575 / 1.0485", "bp,|t|,bp", "CONFIRMED", "exact tie-out, re-derived independently")
row("deletion raw was searched too", "implied (orth is a grid axis)",
    "0 raw cells: 3 distinct values per date < MIN_DISTINCT_SCORES=12", "count", "REFUTED",
    "`deletion` enters the grid ONLY orthogonalised; the orth axis is not optional for it")
row("deletion-orth is a fit-edge artefact", "asserted from the daily study",
    "matched-boundary placebo: 19y t=7.57, 24y t=5.71, 25y t=5.76 all EXCEED the real 20y t=4.58",
    "|t|", "CONFIRMED (mechanism now proven)",
    "max break-even at a meaningless 25y boundary 0.0692x > real 0.0645x")
row("deletion-orth label-permutation null", "not run",
    "40 draws: med 2.86 p95 3.71 max 4.31; real 4.58 -> p=0.000", "|t|", "ADDITION",
    "label permutation does NOT kill it; the matched BOUNDARY placebo does")
row("H1(a) pooled mean seam move", "+0.00000 bp, 0/63 bonds |t|>2",
    "fly: +0.0000 bp CONFIRMED; OUTRIGHT yield 14:59->15:59 -0.0700 bp (date-level HAC t "
    "-2.00), preceding 13:59->14:59 +0.1135 bp (t +3.59)", "bp",
    "WEAKENED", "the test object is a BUTTERFLY, level- and slope-neutral by construction, so it "
                "CANNOT see a 15:00-vs-16:00 mark difference. Yields rise into the 15:00 cash mark "
                "and fall after it; absent on last-BDs (+0.004 vs -0.074 bp)")
row("H1(a) richness level shift 15->16", "median |mean| 0.0028 bp, 3/63 |t|>2",
    "median |mean| 0.00217 bp, 4/94 |t|>2", "bp", "CONFIRMED", "")
row("pond peak/trough ratio", 1.27, 1.266, "x", "CONFIRMED", "table reproduces to 4dp")
row("pond 15->16 seam", "0.1484 (sec 3) / 0.1514 (SUMMARY)", 0.1484, "bp", "CONFIRMED",
    "SUMMARY.csv's 0.1514 disagrees with the report body's 0.1484")
row("last-BD seam perfect foresight", 0.272, 0.3139, "bp", "WEAKENED",
    "0.272 INCLUDES SIFMA early closes; the report's own sec 6 says cite the excluded "
    "version, which is 0.3139 bp = 0.398x cost, not 0.344x")
row("H3 minute seam ratio lastBD/other", 1.74,
    1.756, "x", "CONFIRMED", "own permutation, 59 lastBD vs 472 other, p=0.0002")
row("H3 is not a whole-day vol effect", "implied",
    "midday ratio 1.008 (p=0.46); late/midday ratio-of-ratios 1.720 (p=0.0000)", "x",
    "CONFIRMED", "")
row("H3 is ETF-specific plumbing", "'a US Treasury butterfly moves ~1.75x more per minute'",
    "fly 1.756x; OUTRIGHT |dy| 1.579x (p=0.0000) -- the fly is level- AND slope-neutral by "
    "construction, so these are DIFFERENT factors: month-end late-session vol is up market-wide, "
    "RV-specific excess only 1.756/1.579 = 1.11x",
    "x", "CONFIRMED as a fact / WEAKENED as evidence",
    "the amplification is not specific to the RV object an ETF reconstitution would move")
row("H3 not driven by a few days", "not tested",
    "leave-one-out 1.612..1.786; present every year 1.50..2.24", "x", "ADDITION", "")
row("cost: measured median package round trip", 0.790, 0.7896, "bp", "CONFIRMED",
    "per-leg 0.4637 yield bp = 7.13 price bp on 15.07y mod dur; 3 legs, |1|+|a|+|1-a| = 2x")
row("cost: mean", 0.973, 0.9726, "bp", "CONFIRMED", "")
row("stale marks: hourly stale fraction", "0.3% midday -> 3.4% from 15:00",
    "0.24% at 10:00 -> 2.6% at 15:00-17:00", "%", "CONFIRMED", "")
row("effect lives on stale marks?", "no",
    "fresh-only rerun: deletion 0.00942->0.00953 bp (t 4.58->4.95); "
    "resid 0.01650->0.01618; flow 0.00325->0.00305", "bp", "CONFIRMED", "nothing lives on staleness")
row("hourly close print age (MI01 ground truth)", "not measured",
    "median 0 min, p90 2 min, p99 4 min, 0.57% older than 5 min", "min", "ADDITION",
    "386,942 bond-hours on 801 overlapping days")
row("stamp convention: HOURLY H == last minute print <= H:59", "100.0% on 3,804 bond-day-hours",
    "99.44% on 386,942 bond-day-hours", "%", "CONFIRMED", "")
row("LOOKAHEAD: does the bar ever use the (H+1):00 print?", "not tested",
    "on the 149,834 rows where it would matter, hourly matches the CLEAN candidate 99.82% "
    "and the lookahead candidate 0.00%", "%", "CONFIRMED - NO LOOKAHEAD", "")
row("timezone = America/New_York", "4 indirect readings",
    "FOMC/non-FOMC |move| ratio peaks at exactly 14:00 (6.74x), next 7 buckets all 14:05-15:20",
    "x", "CONFIRMED", "16 FOMC days in the MI01 tape; statement time is 14:00 NY")
row("MI01 downsampling", "1-minute resolution",
    "min gap = 1 minute on 96/96 tags; median gap 2.0 min = liquidity", "min", "CONFIRMED", "")
row("HOURLY downsampling", "not tested",
    "3 of 2,400 hourly dates carry <=2 distinct stamps; NONE of them reaches the panel",
    "count", "CONFIRMED", "")
row("exec_lag >= 1 business day", "axis is lag in (1,2)",
    "60/60 sampled panel rows source a holdings file stamped <= t-1 day", "count",
    "CONFIRMED", "")
row("intraday curve refit uses only same-hour prices", "asserted",
    "curve.fit_residuals groups by date INSIDE a single-hour frame; y_col='ytm_h'", "-",
    "CONFIRMED", "ttm/cpn/mod_dur/spread carried from the SAME-DAY EOD file: minor "
                 "future info, touches only leg construction and cost")
row("ASSERT gross <= perfect foresight, 0 violations", "presented as a check",
    "max gross/pf over the whole grid = 0.1046", "x", "REFUTED as a check",
    "gross is the mean of 6 SIGNED returns, pf the mean of the 6 largest ABSOLUTE returns "
    "from the same matrix and eligibility -- the inequality is an identity, not a test")
row("FALSE-DEAD check (holdings join alive?)", "not run",
    "held frac 0.82, ownership median 1.76%% (matches RESULTS.md 1.7%%); active_w 63d IC "
    "-0.0356 at mark 16 vs the daily study's -0.065, same sign", "-", "ADDITION",
    "the pipeline carries information; DEAD is genuine, not manufactured")

v = pd.DataFrame(R)
v.to_csv(DATA / "advts_verdict.csv", index=False)
print(v.to_string(index=False))
print("\ncounts:", v.verdict.value_counts().to_dict())
