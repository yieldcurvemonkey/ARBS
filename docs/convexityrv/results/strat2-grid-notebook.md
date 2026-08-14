**FILES WRITTEN**

- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat2_convexity_vs_fly_gridsearch.py` (percent format, CONFIG dataclass first, every knob documented inline)
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat2_convexity_vs_fly_gridsearch.ipynb` — executed, verified **30 code cells, 210 outputs, 0 unrun, 0 errors, 11 plotly figures** (`_verify_nb.py` counts only `image/png`, hence its "0 figures"; the sibling strat3 gridsearch verifies identically)
- `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_gridsearch_cells.csv` (1,890 cells)
- `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_gridsearch_verdict.json`

No module was modified. `pytest tests -k convexity -m "not slow and not network and not db"` → **270 passed**.

---

**THE PANEL HAD TO BE REBUILT — the fly agent's grid numbers are superseded**

`strat2_panel.parquet` reproduced `strat2_ca_quality.parquet`'s `ca_annual_bp` to **1.9e-12 on all 11,750 overlapping rows** and differed from the correct Q/Q CA by up to **12.0bp**. (That file has since been deleted by another agent; §4.1 no longer depends on it — the annual-vs-Q/Q comparison is made from the quality scan's own two columns, and the legacy cross-check is guarded by `Path.exists()`.) Measured gap regressed on `0.375·r²` with no intercept: **slope 1.00000, residual sd 0.0000bp** on 11,900 rows — the `3q²/8` prediction is exact here. Negative-CA incidence on the annual convention vs Q/Q, by year: 2019 44.8/33.1, 2020 50.5/49.6, 2021 51.6/51.5, 2022 **17.9/8.3**, 2023 **31.5/3.7**.

**Everything below is on the rebuilt Q/Q panel and differs materially from the fly agent's report.**

**Data.** Hard-cut at **2019-07-08** (the node-starvation break): 1,280 pack-days discarded, 514 of them control-blind; **10,620 retained**, 2019-07-08..2023-12-27, 1,062 common dates, ranks 2–10 (T1 0.37–2.38y). Rejection counts post-break: `flag_negative_ca` 3,214 (30.3%), `flag_convention` 107 (1.0%), `flag_implausible_vol` 562 (5.3%), `flag_no_control_power` 450 (4.2%); **`survive` rejects 4,149 (39.1%), leaving 6,471 (60.9%) enterable**. By year survive-rate: 54/40/42/84/88%. By rank negative-CA: 37/36/25/34/38/35/23/15/20%.

**Tie-out (§3), asserted.** Recomputed `decompose_ca` from the curve on 6 post-break control-powered dates × 16 traded-rank packs: max |recomputed − stored| = **0.0**; max |CA_synthetic| = **0.684bp** vs |CA_observed| median 2.41bp; max |CA_synthetic − annuity-weight prediction| = **0.465bp**. Full post-break control: mean −0.0573, median −0.0162, sd 0.262, |p95| **0.585bp**, residual/|CA| median **1.51%**. Blind spot shown explicitly: |p95| is 0.011bp at forward spread <1bp, 1.512bp at >100bp.

**Sign probes, all asserted.** FLY `bpv=−21,400` is the **exact** mirror of `+21,400` (max |sum| = 0.0) — this had to be established because most winning cells size a *received* belly. Paid belly agrees in sign with the engine on every probe day. `fly_rate_series` − manual = **0.0 bp** over 1,901 dates. `long_ca` = exact negative of `short_ca` at zero cost (max |daily P&L sum| = 0, max |daily gamma sum| = 0, 1,062 days, 9 epochs).

---

**§5 — DOES FORWARD-STARTING HELP? NO.**

| | measured | predicted |
|---|---|---|
| slope, argmax-T1 on fly forward start (45 cells) | **−0.0180** | +1.0 |
| corr | **−0.0611** | ≈1 |
| corr(T1, argmax start), 2s5s10s alone | **−0.173** | ≈1 |

Mean peak R² falls monotonically with forward start: **0.1049 (spot) / 0.0679 (1Y) / 0.0403 (2Y) / 0.0148 (3Y) / 0.0145 (5Y)**. The 5Y over-shoot control is not the worst only because 3Y already is. Mean R² over ranks, spot column, by shape: **1s2s3s 0.3517**, 2s10s30s 0.0220, 3s5s7s 0.0213, 2s7s30s 0.0189, 2s3s5s 0.0169, 5s7s10s 0.0148, **2s5s10s (Citi's) 0.0124**, 5s10s30s 0.0120, 10s20s30s 0.0106.

**1s2s3s spot R² by rank is NOT the rank-5 spike the fly agent found on the annual panel** — it is broad: 0.552/0.511/0.186/0.517/0.488/0.490/0.419 at ranks 2–8, then 0.002/0.001 at 9–10.

**§5.1 mechanism (exact identity, `dCA ≡ d(pack) − d(swap)`, residual 2.7e-15).** The mechanism *flips with rank*:

| rank (T1) | slope dCA | R² dCA | slope d(pack) / R² | slope d(swap) / R² |
|---|---|---|---|---|
| 2 (0.37y) | **+1.318** | 0.552 | +2.276 / 0.175 | +0.958 / 0.028 |
| 5 (1.12y) | **−1.264** | 0.517 | +2.982 / 0.254 | +4.246 / **0.485** |
| 7 (1.62y) | **−1.821** | 0.490 | +2.681 / 0.222 | +4.502 / **0.525** |
| 8 (1.88y) | **−1.457** | 0.419 | +2.478 / 0.198 | +3.935 / **0.433** |

At the front the futures leg drives it (β>0); from rank 5 out the **swap leg is the larger beta and the CA beta turns negative** — so at the ranks that actually work the "hedge" is a bet on curve shape at the pack's own maturity, **not** the volatility exposure Citi's rationale is about.

**§5.2 realised variance reduction** (rolling weights, Citi's β/100 sizing, frozen at entry): positive in only **15.8%** of 405 fly×rank cells on the changes basis (median −0.015) and 25.9% on levels (median −0.007). Citi's own 2s5s10s is negative at 7 of 9 ranks on the changes basis (worst −0.492 at rank 10). 1s2s3s spot is positive at ranks 2–8 (0.13–0.46) and collapses at 9–10 (−0.33, −0.48).

---

**§6 THE GRID — 1,890 cells, 1,569 scored (≥5 epochs, hedged)**

Top rows always carry effectiveness + carry + cost. Winner: **1s2s3s, rank 8, changes basis, regression weights, β/100 sizing, 63d window, `ca_z` entry, short_ca** — Sharpe 1.329, VR 0.405, hedge R² 0.211, mean β **−76.6** (received belly $76.6k, not Citi's paid $21.4k), P&L $14.0m/$13.9m/$13.6m at 0×/1×/2× cost, break-even cost **10.75bp**, **n_epochs 7, hit rate 1.000** — flagged "only 7 epochs" by the notebook's own `verdict` column.

**The honest headline is the 7 survivors of 1,569**, and their concentration is the finding: *all seven* are `1s2s3s` / `changes` / `regression` weights / `regression_beta` / `short_ca` at ranks 5 and 8. The two with real epoch counts:
- rank 5, w=63, `always`, **13 epochs, Sharpe 0.869, VR 0.601, R² 0.089, $6.58m at 2× cost, break-even 3.26bp**
- rank 5, w=126, `always`, **12 epochs, Sharpe 0.756, VR 0.639, R² 0.512, $5.32m at 2× cost, break-even 2.87bp**

Axis medians over every cell that varies them (Sharpe / VR / frac Sharpe>0): basis levels 0.048/−0.007/0.795 vs changes 0.023/−0.011/0.587; weighting dv01_neutral 0.057/−0.002/0.896 vs regression 0.030/−0.011/0.632; entry `vs_model_z` 0.122, `ca_z` 0.079, `carry` 0.058, `always` 0.027; window 63 → 0.074, 126 → 0.062, 252 → 0.027. **Median VR is negative on every single axis value.**

**Citi's own cell (2s5s10s, regression, β/100, always-on)** across 18 rank×basis×window combinations: Sharpe −0.216..+0.489, hedge R² **0.000–0.010**, VR **−0.214..+0.005**, and fitted β ranges −6.6..+30.8 — i.e. its *sign* flips. Carry check: Citi claims ~+4bp/3m on a sold spot 2s5s10s; on this sample it is **−0.67bp**.

**§7 stability.** Winner Sharpe 1.329 vs neighbourhood medians: fly shape 0.146 (next best 0.173 — the shape axis is a cliff, not a plateau), forward start 0.088 (1s2s3s@1Y is **−0.209**), pack rank 0.207 (min −0.280), window 1.222, holding days 1.154, basis 1.008, weighting 0.905, sizing 0.112 (`dv01_ratio` −0.056), entry 0.747. It is stable in the *execution* knobs and a knife-edge in *which fly*.

**§8 multiple testing.** 1,569 cells; cross-sectional Sharpe sd 0.205; **E[max Sharpe | zero skill] = 0.692**; winner 1.385 (own window; 1.329 on the full axis), daily skew 1.447, kurtosis 18.57; **deflated Sharpe p(true SR>0) = 0.924 — DOES NOT clear the 0.95 bar.** 68.0% of cells have Sharpe>0; only 32.7% have VR>0.

**§9 ENGINE CERTIFICATION — the strongest result, and it is an attribution.** Each top cell run twice through `QueryDrivenBacktest` (4 SR3 legs + matched swap ± fly), epochs/weights/DV01s lifted verbatim from the grid's `Epoch` objects, zero cost, epochs ending ≤2023-09-15, `assert_ran` after every run:

| cell | epochs | full-package corr / slope / gap | **CA leg alone** corr / slope / gap |
|---|---|---|---|
| #1 1s2s3s r8 w63 ca_z | 6 | 0.896 / 1.302 / **−63.1%** | **0.999 / 1.008 / $1,560 on $1.200m** |
| #2 1s2s3s r8 w126 ca_z | 5 | 0.932 / 1.425 / **−68.3%** | **0.999 / 1.007 / $41,355 on $1.033m** |
| #3 1s2s3s r5 w63 vs_model_z | 6 | 0.848 / 1.201 / **−51.0%** | **0.997 / 1.036 / $103,695 on $1.524m** |

**The panel's model of the strategy is right to three decimals; the entire disagreement is the hedge leg.** The engine keeps only **32–49%** of the panel's headline dollars on the full package, with an intercept of −$11k to −$40k/day. Diagnosed independently: the panel prices the fly off constant-maturity par rates while the engine holds struck swaps that age — on a single held 2Y payer (bpv $100k) that drift is **−1.44bp** over 2022-09-12..12-12 and **−2.97bp** over 2021-03-01..06-01, and it does **not** equal the quoted carry+roll (−3.58bp, +3.33bp), so it is aged-swap repricing, not carry. Nothing was un-certifiable: all 3 cells expressed in the engine (forward-start fly legs and negative-bpv bellies both verified priceable first).

---

**WHAT DID NOT WORK / LIMITS**

- **Applying the quality filter as holes in the CA series is not viable.** Measured: `INP_STRICT` takes finite `ca_z1y` from 4,848 → **0** and `vs_model_z1y` from 4,037 → **0** — a `min_periods=252` window never refills. That silently disables Citi's own "three sigmas wide to the model" metric. The notebook therefore applies the filter as an **entry gate** (a flagged pack cannot be struck; a held position still marks against the full series) and reports `frac_held_days_flagged` per top cell — **11–29%** on the top 15. `INP_STRICT` is retained as a robustness object.
- **Ranks 11+ / Blues (T1≈3.25y), where Citi actually traded this, are not in daily offline reach.** Every "the hedge fails" statement is about T1 ≤ 2.38y.
- **Hedged-cell dollar levels are not trustworthy** per §9; the 3 certified cells kept their relative order, but that is evidence about 3 cells, not about a 1,569-cell ranking whose Sharpe/VR both depend on the fly leg.
- `regression_target="label"` is starved at deep ranks (only 18 scored cells survive it), as the module warns; `"rank"` is the default.
- Neither ledger contains carry; `carry_3m_usd` in §6.2 is an ex-ante curve-implied quote, signed for the position (`sign × belly_DV01 × quote`) plus the CA leg's own 3m roll — the raw `fly_carry_3m_bp` would be wrong in exactly the winning rows, which carry a received belly.