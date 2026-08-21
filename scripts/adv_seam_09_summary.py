r"""Collect the adversarial verification into one table."""
from __future__ import annotations

import pathlib

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

rows = [
 ("panel tie-out", "bond-dates", 114024, "count", "CONFIRMED", "exact match to the report"),
 ("panel tie-out", "dates", 1636, "count", "CONFIRMED", ""),
 ("panel tie-out", "early-close dates excluded", 89, "count", "CONFIRMED", "flagged list is the SIFMA calendar"),
 ("panel tie-out", "seam mean |dy|", 0.8049, "bp", "CONFIRMED", "report 0.805"),
 ("panel tie-out", "13->14 mean |dy|", 0.9209, "bp", "CONFIRMED", "report 0.921"),
 ("panel tie-out", "14->15 mean |dy|", 0.7900, "bp", "CONFIRMED", "report 0.790"),
 ("panel tie-out", "16->17 mean |dy|", 0.7444, "bp", "CONFIRMED", "report 0.744"),
 ("1 lookahead", "conditioned discriminating cells", 277944, "count", "CONFIRMED", "their test was unconditioned"),
 ("1 lookahead", "start-stamped match rate", 0.9940, "fraction", "CONFIRMED", "bar H = last MI01 print in [H,H+1)"),
 ("1 lookahead", "end-stamped match rate", 0.0001, "fraction", "CONFIRMED", "hypothesis dead"),
 ("1 lookahead", "16:00 mark actual clock time", 15.97, "hours NY", "CONFIRMED", "15:58-15:59, at-or-before, conservative"),
 ("1 lookahead", "holdings asof strictly < mark date", 1.0, "fraction", "CONFIRMED", "73,274 joined bond-dates"),
 ("1 lookahead", "holdings business-day gap min", 1, "bdays", "CONFIRMED", ""),
 ("2 stale", "median mark age at hour boundary", 1.0, "minutes", "CONFIRMED", "MI01, 39,010 bond-days"),
 ("2 stale", "both marks fresher than 5 min", 0.9890, "fraction", "CONFIRMED", ""),
 ("2 stale", "median MI01 prints per hour window", 33.5, "count", "CONFIRMED", ""),
 ("2 stale", "idio sd, all MI01 cells", 0.0821, "bp", "CONFIRMED", ""),
 ("2 stale", "idio sd, fresh <=5 min only", 0.0809, "bp", "CONFIRMED", "goes DOWN; staleness is not the driver"),
 ("2 stale", "idio sd, exact-clock 15:00/16:00 asof", 0.0881, "bp", "WEAKENED", "+7% vs the hourly proxy, immaterial"),
 ("3 timezone", "FOMC/ordinary |dy| ratio, MI01 5-min bin", 5.29, "ratio", "CONFIRMED", "peaks exactly at the 14:00 bin"),
 ("3 timezone", "unconditional |dy| peak bin", 8.5, "hours", "CONFIRMED", "08:30 NY = 0.4101 bp; 10:00 second"),
 ("4 downsampling", "tags with minimum gap > 60 min", 0, "of 97", "CONFIRMED", "min gap exactly 60.0 on all"),
 ("4 downsampling", "session rows/day, worst year-tag", 5.395, "of 8", "CONFIRMED", "no daily-stamped era in any year"),
 ("5 cost", "fly round trip used", 0.535, "bp", "CONFIRMED", "FedInvest measured; SR1170 tail implies ~33bp"),
 ("6 multiple testing", "E[max|t|] over 56 independent", 2.546, "t", "CONFIRMED", "their max 2.473 does not clear"),
 ("6 multiple testing", "E[max|t|] over 236 independent", 3.018, "t", "CONFIRMED", ""),
 ("6 multiple testing", "permutation null, single cell p95 |t|", 1.886, "t", "CONFIRMED", "NW t is well calibrated"),
 ("6 multiple testing", "permutations reaching |t|>=2.473", 0.0, "fraction", "CONFIRMED", "of 200"),
 ("7 arithmetic", "spot check seam by hand", 3.9990, "bp", "CONFIRMED", "2023-10-31 US912810SR05, exact"),
 ("7 arithmetic", "spot check idio by hand", 0.7508, "bp", "CONFIRMED", "refit residual matches exactly"),
 ("Q2 deciding", "idio sd median per date, deg-1", 0.0826, "bp", "CONFIRMED", "= 0.154x cost, the report's number"),
 ("Q2 deciding", "idio sd MEAN per date, deg-1", 0.1032, "bp", "WEAKENED", "= 0.193x cost"),
 ("Q2 deciding", "idio sd POOLED, deg-1", 0.1343, "bp", "WEAKENED", "= 0.251x cost; the honest generous number"),
 ("Q2 deciding", "BUTTERFLY idio sd, median per date", 0.0636, "bp", "CONFIRMED", "= 0.119x cost; LOWER than one bond"),
 ("Q2 deciding", "fly sd / single-bond sd, measured", 0.770, "ratio", "CONFIRMED", "1.2247 if independent; neighbours co-move"),
 ("Q1 controls", "seam idio minus 13->14 idio", 0.0140, "bp", "REFUTED", "NW t 5.96; the seam IS the largest of the four"),
 ("Q1 controls", "seam idio minus 14->15 idio", 0.0077, "bp", "REFUTED", "NW t 4.47"),
 ("Q1 controls", "seam idio minus 16->17 idio", 0.0122, "bp", "REFUTED", "NW t 8.05; excess is 0.015-0.026x cost"),
 ("Q1 reversal", "CLEAN idio reversal", 11.51, "%", "CONFIRMED", "report 10.9%"),
 ("Q1 reversal", "disjoint placebo", 3.49, "%", "CONFIRMED", "report 3.5%"),
 ("Q1 reversal", "clean minus placebo, paired per date", -0.1039, "beta", "CONFIRMED", "NW t -3.01; test the report never ran"),
 ("Q1 persistence", "per-bond split-half corr, chronological", -0.083, "corr", "CONFIRMED", "report -0.006"),
 ("Q1 persistence", "per-bond split-half corr, odd/even day", 0.627, "corr", "REFUTED", "a stable bond component DOES exist"),
 ("Q1 persistence", "sd of per-bond mean idio seam", 0.0072, "bp", "CONFIRMED", "= 0.013x cost; real but nil"),
 ("Q3 holdings", "their w_f/+richness/lag1 coef", 0.00109, "bp per 1sd", "WEAKENED", "t 2.47"),
 ("Q3 holdings", "my independent replication of it", 0.00058, "bp per 1sd", "WEAKENED", "t 1.31; depends on the robust local control"),
 ("Q4 monthend", "month-end / ordinary idio dispersion", 1.434, "ratio", "CONFIRMED", "report 1.428"),
 ("Q4 monthend", "month-end idio sd", 0.1006, "bp", "CONFIRMED", "= 0.188x cost"),
 ("Q4 monthend", "month-end seam level move", -0.1555, "bp", "CONFIRMED", "NW t -0.59 vs ordinary; not significant"),
 ("Q4 fomc flag", "registry meetings in panel span", 45, "count", "CONFIRMED", "44 flagged, 1 date absent from the tape"),
 ("Q4 fomc flag", "FOMC days before the registry starts", 9, "approx count", "WEAKENED", "2019-12..2020-12 unflagged, sit in ordinary"),
 ("DECIDING", "seam-fade fly, every fly", 0.00505, "gross bp/trade", "DEAD", "NW t 5.12 vs 0.535 cost = 0.009x"),
 ("DECIDING", "seam-fade fly, top decile", 0.02493, "gross bp/trade", "DEAD", "NW t 8.47 = 0.047x cost"),
 ("DECIDING", "seam-fade fly, best per date", 0.04829, "gross bp/trade", "DEAD", "NW t 6.97 = 0.090x cost"),
 ("DECIDING", "seam-fade fly, month-end top decile", 0.04088, "gross bp/trade", "DEAD", "NW t 4.87 = 0.076x cost"),
 ("DECIDING", "break-even cost multiple, best selection", 0.090, "x", "DEAD", "costs must fall 11x"),
 ("DECIDING", "perfect-direction ceiling on the exit leg", 0.1117, "bp", "DEAD", "= 0.209x cost; a perfect signal still loses"),
]
S = pd.DataFrame(rows, columns=["section", "metric", "value", "unit", "verdict", "note"])
S.to_csv(DATA / "adv_seam_VERDICTS.csv", index=False)
print(S.to_string(index=False))
print(f"\nwrote adv_seam_VERDICTS.csv ({len(S)} rows)")
