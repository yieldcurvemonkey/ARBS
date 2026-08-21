# Convexity RV — preflight, 2026-08-20

Handover report for the second block of convexity relative-value work (workflows 1–4).
Every number below was measured on this machine, with the command that produced it
recorded. Where something was not measured, it says "not measured".

Worktree: `C:/Users/chris/clee/ARBS-cvx2`, branch `feat/convexity-rv2`, based on `main`
at `61fa6d1a`. The handover brief describes `feat/convexity-rv` as three commits ahead of
main; it is not — `git log main..feat/convexity-rv` returns **0**, so every convexity
commit including PR #461 (listed vol, three-way, deep SOFR packs, cache guard), the Q20
node-grid fix (`db95871d`) and the cache-warmer repairs (`88f3a2f1`, `d7055a07`) are
already on main. The new worktree was reset onto main so it carries all of it.

---

## 1. Green board

| check | result | command |
|---|---|---|
| convexity test suite | **789 passed, 73 skipped, 0 failed**, 184.6 s | `python -m pytest tests -k convexity_rv -q` |
| skip reasons | all 73 are *"panel not built"* — the gitignored data artifacts absent in a fresh worktree, not failures | `pytest ... -rs` |
| stir env | Python 3.13.5, `gs_quant` **1.4.26** installed | `python -c "import gs_quant"` |

The 73 skips are the fresh-worktree signature. The Aug-19 artifacts from `ARBS-cvx` were
copied to `notebooks/data/convexity_rv/_baseline_prewarm/` (121 MB, 291 files) as the
**pre-warm baseline**, deliberately under a non-canonical path so nothing silently
reloads them — see §5, trap 1.

---

## 2. Two live correctness defects in the *shared* CA path

These are not in `RVUtils/ConvexityRV/` — that package computes its own adjustment and is
clean. They are in the repo-wide `Query` / `TimeseriesBuilder` path that
`TB/IRSwapsTB.sfr_cvx_adj` and `IRSwapValue.CVX_ADJ` expose, i.e. exactly the
"query, mdp/pricer, timeseriesbuilder pattern" workflow 1 is asked to fix.

### 2.1 The matched swap is annual/annual, not quarterly/quarterly — **−4.6 to −5.9 bp**

`DESIGN.md` §5 records that Citi specifies the matched-maturity swap verbatim as *"both
fixed and floating legs of this swap have a quarterly payment frequency"*, and that
`usd_irs` quotes **annual** fixed. `RVUtils/ConvexityRV/curve_ops.matched_forward_swap_rate`
defaults to `Q/Q` for that reason. `TB/IRSwapsTB.sfr_cvx_adj` (`TB/IRSwapsTB.py:1391-1399`,
`:1591-1599`) builds its matched swap through `IRSwapQuery(structure=OUTRIGHT,
effective_date=…, maturity_date=…)`, which reaches
`RLIRSwapCurve.build_irswap` (`Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py:307`) and
uses `spec=curve_def["ReferenceRate"]` with **no frequency override**.

Measured, `USD-SOFR-1D` on `CITIVELO_EXCEL`, a rank-9..12 (Greens) window:

| as-of | window | matched Q/Q | spec default | TB query `fair_rate` | TB − Q/Q |
|---|---|---:|---:|---:|---:|
| 2023-06-09 | 2024-03-20 → 2025-03-19 | 4.088820 % | 4.147662 % | 4.147662 % | **+5.884 bp** |
| 2024-06-10 | 2026-03-18 → 2027-03-17 | 3.924418 % | 3.982582 % | 3.982582 % | **+5.816 bp** |
| 2025-06-10 | 2026-03-18 → 2027-03-17 | 3.511796 % | 3.557647 % | 3.557647 % | **+4.585 bp** |

Both legs print schedule frequency `A`. Because `CA = pack_rate − swap_rate`, every
`CVX_ADJ` the production timeseries path has published is **too low by 4.6–5.9 bp**.
Citi's own Blues adjustment on 2023-06-09 is 15.4 bp and the front packs run 1.3–6.8 bp,
so on Whites and Reds this is larger than the quantity being measured and flips its sign.

Reproduce: `notebooks/backtests/convexity_rv/_probe_ca_matched_swap_frequency.py`.

### 2.2 `_as_percent` corrupts every sub-1 % SR3 rate — up to **9,405 bp**

`Query/IRSwaps/IRSwapValue.py:199-201`:

```python
def _as_percent(x: float) -> float:
    x = float(x)
    return x * 100.0 if abs(x) < 1.0 else x
```

It is applied to `rl.STIRFuture.fixed_rate`, which rateslib already carries in **percent**.
The heuristic therefore multiplies any contract implying less than 1 % by a hundred:

| code | price | `fixed_rate` | `_as_percent` | truth | verdict |
|---|---:|---:|---:|---:|---|
| H21 | 99.9500 | 0.050000 | 5.000000 | 0.0500 % | CORRUPT, +495 bp |
| M21 | 99.8000 | 0.200000 | 20.000000 | 0.2000 % | CORRUPT, +1,980 bp |
| Z21 | 99.5000 | 0.500000 | 50.000000 | 0.5000 % | CORRUPT, +4,950 bp |
| H22 | 99.0500 | 0.950000 | 95.000000 | 0.9500 % | CORRUPT, +9,405 bp |
| M22 | 98.9500 | 1.050000 | 1.050000 | 1.0500 % | OK |
| H24 | 95.0000 | 5.000000 | 5.000000 | 5.0000 % | OK |

The trip threshold is an SR3 price above 99.00. That is the whole ZIRP window,
**2020-03 to 2022-06**, for Whites/Reds/Greens, and the deferred strip into 2021 as well —
precisely the years workflow 2's 2021–2026 backtest starts in.

The swap side of the same function is fine: `curve.fair_rate` returns a decimal by this
wrapper's own contract, so `abs(x) < 1.0` is the correct branch there. The bug is that one
heuristic is applied to two quantities carried in two different units — the
"same column name is not the same quantity" trap in a single function.

Reproduce: `notebooks/backtests/convexity_rv/_probe_ca_as_percent_zirp.py`.

### 2.3 The same path swallows every pricing failure

`TB/IRSwapsTB.py:1565` and `:1614` are both bare `except Exception: pass` inside the
per-date loop. A date that fails to price is dropped from the series with no record, so
"the CA series is sparse" cannot be distinguished from "the CA series errored". This is
the mechanism behind the original complaint that the CA series looked interpolated, and it
must be fixed before any coverage number computed off that path can be believed.

---

## 3. SOFR futures settle coverage — the warm, measured

`scripts/warm_sr3_deferred.py --dry-run`, `--depth 20`, `--protect-min-depth 21`
(nothing protected, i.e. the full repair the brief asks for):

| window | dates with EOD | dates short of depth 20 | cells to fetch |
|---|---:|---:|---:|
| 2018-01-01 → 2026-08-19 | 2,098 | **872** | 4,398 |
| 2020-01-01 → 2026-08-19 | 1,678 | **485** | 2,385 |

The script's `est_seconds` (4,039 s / 2,236 s) comes from its own fitted
`t(n) = 3.38 + 0.169n`. The **realised** rate from the previous run's ledger is
`4,108.6 s / 103 dates = 39.9 s/date`, an order of magnitude slower, so budget on the
realised figure: pass 1 ≈ **5.4 h**, the 2018–2019 tail ≈ **4.3 h**.

`--protect-min-depth` defaults to 12 precisely so a repair moves no previously-published
`ca_bp_q20`. The brief says *fully fix*, so this run deliberately sets it to 21 and
deepens everything; the deliverable therefore includes a quantified before/after diff
against `_baseline_prewarm/`.

Shipped coverage before this warm (`ca_coverage_by_rank.csv`, "after" column — dates per
year at which each rank is buildable):

| rank | colour | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Whites | 251 | 250 | 249 | 249 | 250 | 178 | 106 |
| 5 | Reds | 251 | 250 | 249 | 249 | 180 | **3** | 106 |
| 9 | Greens | 251 | 250 | 249 | 222 | **19** | **3** | 106 |
| 13 | Blues | 251 | 250 | 195 | **51** | **19** | **3** | 104 |
| 17 | Golds | 251 | 187 | **52** | **51** | **19** | **2** | 103 |

The holes are real absence, not a gate: nothing has ever scheduled a warm of SR3 **settle**
depth, so post-2022 depth is whatever incidental front-end work happened to touch.

---

## 4. Sections filled in from the parallel investigation

*(populated below — data availability, new research notes, feasibility, ordering)*

---

## 5. Risk register carried forward

1. **A cached artifact fakes a successful re-run.** Several convexity notebooks do
   `if _F.exists(): X = pd.read_parquet(_F)`. Any notebook written in this block gets a
   `FORCE_REBUILD` config flag that unlinks its own outputs first. The Aug-19 baseline is
   parked under `_baseline_prewarm/` so it can never be picked up by that pattern.
2. **`QueryDrivenBacktest.run()` swallows exceptions and prints them** — a failing
   backtest looks like a flat equity curve. Assert on `mtm_history` afterwards, always.
3. **`rateslib.Curve.translate()` cannot age a struck swap.** Carry enters as
   `payoff_profile(carry_ccy=…)`.
4. **`GAMMA_01` / `DV01` raise `NotImplementedError`** on the rateslib backend. Measure
   convexity by repricing on a shifted curve.
5. **Parallel `conda run` collide on a temp file and return empty output with exit 0.**
   Call `C:/Users/chris/anaconda3/envs/stir/python.exe` directly.
6. **Never call `IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name":
   "USD-SOFR-1D-Q20STIRT"})`** — 52–57 outbound requests per date, and `offline=True` is
   accepted then ignored.
7. **The warm writes `STIRFuturePricer_Cache`**; a panel build reading the same shards
   inside `cache_only()` converts contention into an exception. Verified that the Citi
   Velocity swap caches are *separate* diskcache directories
   (`IRSwapsTB_v2_CITIVELO_EXCEL`, `citivelo_par_extract`) from `STIRFuturePricer_Cache`,
   so pure-swap-curve work can proceed during the warm; SR3 panel builds cannot.
