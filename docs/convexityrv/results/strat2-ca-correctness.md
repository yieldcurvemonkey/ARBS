All deliverables complete and verified. Writing the report.

**FILES WRITTEN**

- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/ca_diagnostics.py` — extended, existing API intact. New: `imm_forward_map`, `curve_nodes`, `window_resolution`, `annuity_weight_residual_bp`, `control_power_bp`, `compounding_gap_bp` / `COMPOUNDING_GAP_SLOPE=0.375`, `regress_gap_on_rate_squared`, `vol_sensitivity_bp_per_bp`. `synthetic_pack_rate` gained keyword-only `forwards=`.
- `C:/Users/chris/clee/ARBS-cvx/scripts/strat2_ca_quality_scan.py` — 6-worker scan, 67s for 11,900 pack-days.
- `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_ca_quality.parquet` (40 cols, incl. quality flags) + `strat2_ca_quality_skips.json`
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat2_ca_diagnostics.py` + executed `.ipynb` (30 code cells, 0 unrun, 0 errors, 7 plotly figures)
- `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_ca_diagnostics.py` — 30 tests, all pass; **7 mutations each caught** (gap slope 0.375→0.5; shape slope hardwired to 2.0; `spans_window` forced 0; annuity sign flipped; `dσ/dCA` dropping `/2CA`; negative-CA flag disabled; `next_quarterly` year-wrap). Restored file passes clean. `99 passed` across the four convexity suites.
- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat2_sofr_convexity.py` — one-line bug fix: `local_cached_dates` imported `LayeredCacheMixin`, which does not exist in `Caching/DiskCacheMixin.py`; it raised `ImportError` before reaching its own fallback. Now `DiskCacheMixin.default_cache_path`.

**COVERAGE.** 1,207 cached full-strip dates → 1,190 usable (17 holiday-ghost curves, ref-date ≠ requested, skipped; 8 dates missing Q12STIRT). 2019-01-02..2023-12-27, pack ranks 1–10 (T1 ≤ 2.5y). Citi's table is ranks 5–17, so **this covers the near half of the screen; ranks 11+ are not in daily reach.**

---

**TWO FINDINGS THAT ARE ACTION ITEMS**

1. **`strat2_panel.parquet` is the ANNUAL-frequency variant.** It reproduces this scan's `ca_annual_bp` to **1.9e-12 on all 11,750 overlapping rows**, and differs from the correct Q/Q CA by up to **12.0bp**. Bias = `−0.375·r²`: −1.14bp (2019), −0.09 (2020), −0.16 (2021), −3.53 (2022), **−5.46bp (2023)**. On 2023-06-09 it turns the front pack from +0.13bp to −9.34bp; **5 of 10 packs are pushed into a no-arbitrage violation by the frequency alone.** The current `ca_snapshot` code path is correct (matches to 1.1e-12) — the artifact is stale. Rebuild before quoting any Strategy-2 number.
2. **Discard everything before 2019-07-08.** `USD-SOFR-1D` runs on 26 nodes with the second at start+735d until then (measured: 2019-06-20 → 26, 2019-07-01 → 33, 2019-07-08 → 45). On **520 rows a single node interval swallows the whole pack window**: forward spread 8.9e-12bp (machine zero, 514 in 2019), so `CA_synthetic` is **exactly 0** — a perfect control pass — while `CA_observed` spans −91.6 to +27.6bp and 42.7% of them are negative. **The zero-convexity control is structurally blind to this**; that is the report's most important caveat.

---

**MEASURED RESULTS**

**(a) Zero-convexity control.** `CA_synthetic` over 11,900 rows: mean **−0.0529bp**, median −0.0141, sd 0.248, |p95| **0.573bp**; post-break |p95| 0.585. Residual/|CA_observed| (|CA|>1bp, n=7,308): **median 1.51%**, p95 29.9%. By rank |p95| falls 1.36 → 0.10bp (rank 1→9). Better than a bound: the residual **is** the annuity-weighting term (equal-weighted pack rate vs annuity-weighted par rate), predicted with no free parameter — corr 0.636, **regression slope 1.149, intercept +0.005bp**; removing it takes the residual to **mean −0.0032bp, sd 0.204, |p95| 0.448**. Power-conditioned: |p95| is 0.011bp at spread<1bp (uninformative) rising to 1.51bp at >100bp — the interpolation-residual signature, not a convention error.

**(b) Q/Q vs annual.** OLS `gap_bp ~ b·r²` (no intercept): **b = 0.36886 vs predicted 0.375 (−1.64%)**, r² **0.9981**, intercept +0.026bp, n=11,900. Residual to `0.375r²`: mean −0.015bp, sd 0.117. By bucket: 0.003 vs 0.003 (r≈0.08%), 2.28 vs 2.21 (2.43%), 7.11 vs 7.40 (4.44%), 9.89 vs 9.98 (5.16%). The `3q²/8` prediction is confirmed quantitatively.

**(c) No-arbitrage.** CA<0 on **32.3%** overall, 30.3% post-break; by year 41/50/52/8/4%. **99.6% of the 3,844 violations have |CA_synthetic| ≤ 1bp** (median 0.032bp; 69% under 0.1bp) — data, not convention. Worst cluster is **2020-03-03/04/05** (emergency 50bp cut), CA −35 to −48bp with controls of 0.00–0.03bp. Filter incidence: negative-CA 32.3%, convention 0.90%, implausible-vol 6.6%, no-control-power 8.7%. **Survival 56.7% overall; 85.5% in 2022–23; 93.4% in 2022–23 rank≥5.**

**(d) Shape.** Ho-Lee's slope-2 is a *flat-vol* prediction. **Citi's own Fig 58 prints 1.376** (corr 0.9935) because its vols fall 199.5→151.9, and **1.142 over its first six rows** — the T1 span matching ours. Our 2023 median: **1.200** (corr 0.871), a **0.058** difference like-for-like. Pre-break dates: slope −0.181, corr −0.139 — no shape at all.

**(e) Vol conditioning.** `dσ/dCA = σ/(2CA)`: 99.9 → 10.3 bp-vol/bp-CA across ranks 1→10 (2022–23). Combining with the measured noise gives vol error as a share of the vol level: rank 1 **53.7%**, 4 20.0%, 5 **29.7%**, 8 **13.4%**, 9 2.0%. At a 15% budget the first eligible rank is **8 (T1≈1.87y)**; Citi's convention (Reds, rank 5, T1≈1.13y) is a ~30% budget — the **loose** end of what the data supports. Caveat stated in the notebook: ranks 9–10 sit inside one ~365-day node segment (`n_nodes_inside`=1), so their low ΔCA variance is reduced independent information, not accuracy.

**(f1) Cross-source.** Reproduced the orchestrator's 2019 finding: median |futures − Q12STIRT forward| = **9.375bp**, corr(CA_obs, CA_q12) 0.441. **Explained mechanically:** Q12STIRT inherits its node grid from `USD-SOFR-1D`; on 2019-03-15 it has **12 nodes with the second at 2021-03-17** — zero front-end degrees of freedom, so it prints a constant 2.3147% while SR3 declines 2.4300→2.1450. Its own calibration instruments are these settles (`SFRCM1..13` as `rl.STIRFuture`, no convexity term, weight 1e6), and in 2021–23 it does the job: **corr(pack rates) 0.9999, median disagreement 0.881bp**, CA correlation 0.816. **The curve is wrong, not the settles.** Reported as a warning: the CA≥0 and T1² criteria do *not* discriminate — in 2019 the degenerate Q12 version scores *better* on both (CA<0 26% vs 41%; corr(CA,T1²) +0.83 vs −0.21) because a flattened curve manufactures a monotone non-negative profile out of nothing.

**(f2) Timing.** Hard bound (±1 business day of futures against a fixed curve): pooled sd **7.29bp** — but that is just one day of pack-rate vol (sd of daily pack-rate change = **7.115bp**), a gross over-statement of a 2-hour mismatch. Sharp bound from the CA's own daily change, 2022–23: `sd(ΔCA)/√2` and the Roll/MA(1) estimator agree to 2–5%, giving **0.89–2.55bp per pack-day at ranks 1–8 (mean 1.82bp)** against CA levels of 1.34–6.81bp. Decomposition: true adjustment moves 0.55bp/day, noise 1.77bp/day.

**(g) Citi tie-out, 2023-06-09, 13/13 rows.** Q/Q: **mean −0.108bp, median −0.581, sd 1.676, |max| 3.123, corr 0.9667**, 13/13 within ±4bp, **0/13 negative**. Implied-vol ratio ours/Citi: median 0.974 (0.904–1.262). Zero-convexity control on that date: mean −0.058bp, |max| 0.251. **Negative control asserted and it fails as required: annual gives mean −3.887bp / median −4.314**, 4/13 within tolerance. This exactly reproduces the documented −3.89/−4.31 — confirming that offset was the **frequency**, not the CME clearing basis. Post-fix, the clearing basis is bounded at mean −0.11bp / sd 1.68bp.

**(h) What would make this wrong** — ranked table in the notebook: (1) swap-leg frequency, up to 12bp, FOUND LIVE; (2) curve resolution, unbounded, control-blind, FOUND; (3) snapshot timing, 1.7–2.7bp typical / tens of bp on fast days, irreducible; (4) stale deferred settles, filtered by CA<0; (5) CME basis, now bounded <2bp; (6) deep-pack curve smoothing; (7) Ho-Lee flat-vol slope — anyone testing against 2.0 fails a correct implementation; (8) `T1` convention (−0.2 to −0.6% on vol only); (9) universe truncation to ranks 1–10; (10) quarter-tick rounding, sub-noise.

---

**DEVIATIONS / LIMITS**

- `compare_curves` / `trade_dashboard` were **not** imported: this is a diagnostics notebook with no backtest book, so there is no equity curve to pass them. The mandated `pio.renderers.default = "plotly_mimetype+notebook_connected"` is set and all 7 charts are plotly.
- The notebook was executed under a scratchpad `stir` kernelspec via `JUPYTER_PATH` (the only registered kernel points at base anaconda). Base anaconda was verified to import `rateslib` 2.6.0 and the `MDP` stack cleanly, so `run_convexity_rv.py` will still execute it unchanged.
- `_verify_nb.py` reports "0 figures" because it counts only `image/png`; the executed notebook carries 7 `application/vnd.plotly.v1+json` outputs.