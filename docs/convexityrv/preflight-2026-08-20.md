# Convexity RV — preflight, 2026-08-20/21

Handover report for the second block of convexity relative-value work (workflows 1–4).
Every number below was measured on this machine, with the command that produced it
recorded. Where something was not measured, it says "not measured".

Worktree: `C:/Users/chris/clee/ARBS-cvx2`, branch `feat/convexity-rv2`, based on `main`
at `61fa6d1a`. The handover brief describes `feat/convexity-rv` as three commits ahead of
main; it is not — `git log main..feat/convexity-rv` returns **0**, so every convexity
commit including PR #461 (listed vol, three-way, deep SOFR packs, cache guard), the Q20
node-grid fix (`db95871d`) and the cache-warmer repairs (`88f3a2f1`, `d7055a07`) are
already on main. The new worktree was reset onto main so it carries all of it.

Six investigation agents ran in parallel; their full reports are committed verbatim as
`docs/convexityrv/research/10-…15-preflight-*.md`, and every measured claim below is
traceable to a probe listed in one of them.

---

## 1. Green board

| check | result | command |
|---|---|---|
| convexity test suite | **789 passed, 73 skipped, 0 failed**, 184.6 s | `pytest tests -k convexity_rv -q` |
| skip reasons | all 73 are *"panel not built"* — gitignored data artifacts absent in a fresh worktree, not failures | `pytest … -rs` |
| kernel sign probe | `OUTRIGHT bpv>0 == PAYER` reproduced at **+$2,303,346**, mirror residual **exactly 0** | scout probe `step1_probe.py` |
| kernel payoff profile | all four structures reproduce `DESIGN.md` §0 to **≤0.050 bp**, i.e. its own rounding | same |
| convexity is real | fitted quadratic coefficient positive for all four flatteners, negative for all four steepeners, mirror exact | same |
| env | Python 3.13.5, `gs_quant` **1.4.26** installed | — |

The 73 skips are the fresh-worktree signature. The Aug-19 artifacts from `ARBS-cvx` were
copied to `notebooks/data/convexity_rv/_baseline_prewarm/` (121 MB, 291 files) as the
**pre-warm baseline**, deliberately under a non-canonical path so nothing silently
reloads them — see §6, trap 1.

One correction to the brief: `DESIGN.md` §0's pinned table has 30Y/50Y's profile minimum
at **+50 bp**, not at zero, and that is correct rather than a defect — the profile carries
a linear term, and the pinned row itself shows −1.4 / −1.8 at +25 / +50.

---

## 2. Three live correctness defects in the *shared* CA path — all fixed

These were not in `RVUtils/ConvexityRV/`, which computes its own adjustment and ties out to
Citi. They were in the repo-wide `Query` / `TimeseriesBuilder` path that
`TB/IRSwapsTB.sfr_cvx_adj` and `IRSwapValue.CVX_ADJ` expose — i.e. exactly the
"query, mdp/pricer, timeseriesbuilder pattern" workflow 1 names. Commit `50e5fb29`.

### 2.1 The matched swap was annual/annual — **−4.6 to −5.9 bp**

Citi specifies the matched-maturity swap verbatim as *"both fixed and floating legs of this
swap have a quarterly payment frequency"*, and `curve_ops.matched_forward_swap_rate`
defaults to `Q/Q` for that reason. The shared path read the par rate off a package built by
`RLIRSwapCurve.build_irswap` with `spec=curve_def["ReferenceRate"]` — `usd_irs`, annual
fixed — and passed no override.

| as-of | window | matched Q/Q | spec default | TB query `fair_rate` | TB − Q/Q |
|---|---|---:|---:|---:|---:|
| 2023-06-09 | 2024-03-20 → 2025-03-19 | 4.088820 % | 4.147662 % | 4.147662 % | **+5.884 bp** |
| 2024-06-10 | 2026-03-18 → 2027-03-17 | 3.924418 % | 3.982582 % | 3.982582 % | **+5.816 bp** |
| 2025-06-10 | 2026-03-18 → 2027-03-17 | 3.511796 % | 3.557647 % | 3.557647 % | **+4.585 bp** |

Both legs print schedule frequency `A`. Because `CA = pack_rate − swap_rate`, every
`CVX_ADJ` the production timeseries path published was **too low by 4.6–5.9 bp** — larger
than the Whites/Reds adjustment being measured, which runs 1.3–6.8 bp.

Independently confirmed by a second agent on a different instant and a different route:
WHITES at 2026-08-19 15:00 ET returned **−5.81 bp** shipped and **+0.19 bp** with a Q/Q
matched leg.

Reproduce: `notebooks/backtests/convexity_rv/_probe_ca_matched_swap_frequency.py`.

### 2.2 `_as_percent` corrupted every sub-1 % SR3 rate — up to **9,405 bp**

`Query/IRSwaps/IRSwapValue.py` ran both legs through
`lambda x: x * 100.0 if abs(x) < 1.0 else x`. That is correct for `curve.fair_rate`, which
returns a decimal by this wrapper's contract, and wrong for `rl.STIRFuture.fixed_rate`,
which rateslib already carries in percent.

| code | price | `fixed_rate` | `_as_percent` | truth | verdict |
|---|---:|---:|---:|---:|---|
| H21 | 99.9500 | 0.050000 | 5.000000 | 0.0500 % | CORRUPT, +495 bp |
| M21 | 99.8000 | 0.200000 | 20.000000 | 0.2000 % | CORRUPT, +1,980 bp |
| Z21 | 99.5000 | 0.500000 | 50.000000 | 0.5000 % | CORRUPT, +4,950 bp |
| H22 | 99.0500 | 0.950000 | 95.000000 | 0.9500 % | CORRUPT, +9,405 bp |
| M22 | 98.9500 | 1.050000 | 1.050000 | 1.0500 % | OK |
| H24 | 95.0000 | 5.000000 | 5.000000 | 5.0000 % | OK |

The trip threshold is an SR3 price above 99.00 — the whole ZIRP window, **2020-03 to
2022-06**, for Whites/Reds/Greens, and the deferred strip into 2021. One heuristic, two
quantities, two units.

Reproduce: `notebooks/backtests/convexity_rv/_probe_ca_as_percent_zirp.py`.

### 2.3 The price panel was back-filled, and failures were swallowed

`get_barchart_timeseries` did an unconditional `.bfill().ffill()`. `bfill` carries a price
**backwards in time** — look-ahead inside the price panel, before any strategy code runs —
and `ffill` manufactures a print where there was genuine absence, which is what made a
sparse CA series look interpolated. `fill` now defaults to `False`; there is exactly one
caller in the repo, so the blast radius was zero.

Both per-date loops in `sfr_cvx_adj` were bare `except Exception: pass`, so "the vendor has
no print" and "the pricer raised" produced the same gap — and they need different fixes.
Failures now land in `sfr_cvx_adj_failures` with a reason.

### 2.4 How the fix avoids serving the old numbers

The convention travels in the query's `value_kwargs`, which is part of
`_query_fingerprint` and therefore of both the mapping-cache key and the `data/ts` symbol.
The cache version is **derived from the inputs rather than hand-bumped**, so rows computed
under the old convention are orphaned rather than silently served — which matters here,
because `data/ts` is read *before* the curve store.

### 2.5 What the mutation harness caught

Mutation-checked **4/4**, and two of those kills were the harness earning its keep:

* Reverting the *default* frequency **survived** the first draft. Every tie-out passed
  `matched_frequency="Q"` explicitly, so none of them exercised the default — which is what
  every production caller gets. The suite pinned the knob and left the wire loose.
* The swallow mutation survived a source-text assertion, because replacing the recorder
  with `pass` leaves `except Exception as exc:` in place. Rewritten behaviourally, it
  immediately found a live `NameError` no source-text test could have.

---

## 3. SOFR futures settle coverage

The brief's picture is superseded in one important way: **the 2024–2026 hole is already
closed.** `scripts/warm_sr3_deferred.py` was run manually to completion on 2026-08-19
(635 dates, 9,448/9,476 cells, 0 errors, 5.48 h). Measured depth ≥20 is now 2024 **248/252**,
2025 **247/251**, 2026 **156/159**. The remaining gap is **2021–2023, plus 2018–19**.

Contiguous front-strip depth, `BARCHART_STIRF-RL`, 17:00 NY-readable, measured against the
repo's own reader (`n_diff = 0` versus the shipped `strip_depth_by_date`):

| yr | ≥4 | ≥8 | ≥12 | ≥16 | ≥20 |
|---|---:|---:|---:|---:|---:|
| 2020 | 253 | 253 | 253 | 253 | 253 |
| 2021 | 252 | 252 | 252 | 252 | **187** |
| 2022 | 252 | 252 | 252 | **195** | **52** |
| 2023 | 258 | 258 | **231** | **51** | **51** |
| 2024 | 252 | 251 | 249 | 248 | 248 |
| 2025 | 251 | 250 | 249 | 248 | 247 |
| 2026 | 159 | 159 | 159 | 157 | 156 |

**Whites and Reds need no fetch anywhere** — 2 and 4 dates short across nine years. Greens
is marginal (35 dates). Blues and Golds are the job.

### The warm now running

`scripts/warm_sr3_deferred.py --start 2020-01-01 --end 2026-08-20 --depth 20
--protect-min-depth 21 --max-calls 600`. The default `--protect-min-depth 12` exists so a
repair moves no previously-published `ca_bp_q20`; the brief says *fully fix*, so this run
deliberately deepens everything and the deliverable is a quantified before/after against
`_baseline_prewarm/` rather than a "nothing moved" assertion.

Progress at the time of writing: **28 of 486 dates, 219/221 cells resolved, 0 errors**,
median 2.8 s/date, projecting ~2 h. Two facts worth recording:

* A cold date returns the **full 20-deep strip** (`depth_before: 0 → resolved: 20`), so the
  2021–2023 repair is not limited by vendor coverage.
* Before launching, an agent settled the open question that decides the whole plan — every
  fetch on record was 2024+, and the one pre-2024 datapoint had returned nothing. Two
  deliberate calls at ladder position depth+2 (so no published value could move) resolved
  **SR3Z26 for both 2023-06-26 and 2022-08-09**, and both wrote the NY-stamped 17:00 alias
  the panel reads. The 2018-12-06 failure is one decayed date, not a pre-2024 cliff.

### The largest coverage win costs no network at all

The only rebuilt panel on this machine was produced in worktree `ARBS-cvx` at `a9bc31a7`,
which does **not** contain `db95871d` — so it carries the pre-fix `max_tenor = 60` and its
Golds column is the pre-fix number (2024/25/26 gate-passed = 41 / 20 / **0**). Sampling 15
depth-20 dates through this worktree's code:

| | rank-17 median `max_settle_diff_bp` | pass at the 2.0 bp gate |
|---|---:|---:|
| shipped panel (tenor 60) | 2.86 | 6/15 |
| this worktree (tenor 66) | **1.05** | **15/15** |

**A panel rebuild is therefore a required work item independent of any fetch.**

---

## 4. Data availability, measured

| series | verdict | window measured | accessor |
|---|---|---|---|
| swap curve `USD-SOFR-1D` (Citi EOD) | **GREEN** | 5,511 partitions 2005-01-03..2026-08-14; **1,466/1,470 business days in 2021-2026 (99.73 %)**, the 4 misses being the unwarmed tail | CurveStore `…-CITIVELOEXCEL` |
| swap curve, **minute** | **GREEN** | 1,543 days 2021-09-14..2026-08-19; 2026-08-19 holds 1,077 rows, 05:00Z–23:16Z | CurveStore `…-CITIVELOEXCELMIN` |
| ultra-long forwards | **GREEN** | 20Yx10Y, 25Yx10Y, 30Yx20Y, 20Yx30Y, 30Y, 40Y, 50Y — **7/7 price on 9/9 sampled dates**, none out of band | `IRSwapQuery(OUTRIGHT, RATE)` |
| swaption ATMF | **GREEN** | 1Yx30Y / 1Yx20Y / 3Mx30Y / 6Mx30Y / 1Yx10Y all **99.43 %** of holiday-adjusted business days 2021-2026 | `swaption_cube.load_vol_panel` |
| swaption smile | **GREEN from 2020-04-22** | 99.36 % of 2021-2026. First OTM offset is **2020-04-22**, not DESIGN.md's 2020-03-25 — threshold-insensitive from ≥2 to ≥13 offsets | same |
| SR3 settles | **AMBER, repairing** | §3 | `STIRFutureMDP(BARCHART_STIRF-RL)` |
| SR3 **minute** tape | **GREEN** | keyed under `BARCHART_TOS_LIVE_STIRF-RL`; SR3H27 alone holds 1,386 minute keys on 2026-08-19 | same MDP, different source token |
| **CME-LCH basis** | **GREEN — entitled, live** | `IR_SWAP_RATES_V1_STANDARD`; USD SOFR/OIS/LIBOR carry both CCPs, ladder 1y–30y, catalogue `historyStartDate` 2018-04-27. Live read: **USD SOFR 10y LCH−CME = −2.00 bp (08-10), −2.05 (08-11/13/14)** | `IRClearingHouseBasisSwapsMDP` |
| **dealer positioning** | **AMBER — on disk, 14 weeks stale** | CFTC TFF, weekly, **2020-01-07..2026-05-12**, 332 report dates, 154 markets, fully offline. Carries `Dealer_Positions_Long/Short_All` and `SOFR-3M` | `BT/signals/cftc_positioning.py` |
| **open interest** | **AMBER — survivorship-shaped** | only the ~21 contracts live today (SR3U26..SR3M31) carry history, at 0.976–0.996; every expired contract sits at 0.004–0.028 | `STIRFutureValue.OPEN_INTEREST` |

### Three findings that change what can be built

1. **The CME-LCH basis is genuinely available** — the least likely of the three signal
   families to exist. It needs a caching layer first: `IRClearingHouseBasisSwapsMDP` has
   none and refetches on every call, and its default `coverage_path` hardcodes the primary
   checkout rather than the worktree.
2. **Per-contract open interest is not recoverable for history** from what is on disk. The
   panel is a fixed set of still-live codes drifting forward, not vendor coverage: the
   boundary sits exactly at the live/expired line (SR3M26 = 0.008, SR3U26 = 0.980). Whether
   Barchart serves OI for expired contracts was **not measured**. The usable historical
   substitute is CFTC TFF `Open_Interest_All` for `SOFR-3M` — weekly, whole-strip, no
   per-contract dimension. A related defect was measured: the last-bar zero-OI trap reaches
   the futures path (42 zero rows on 3 dates, all of them the most recent session), because
   `blank_unpublished_open_interest` is called only from the options path.
3. **An intraday convexity adjustment already computes, offline, today** — Citi minute curve
   under `SnapshotPolicy.strict(minutes=5, on_miss="raise")` for the swap leg, the
   `BARCHART_TOS_LIVE_STIRF-RL` minute tape for the futures leg, and the identical value
   call `sfr_cvx_adj` makes, with `network_calls_blocked == 0`.

---

## 5. What the new research notes propose, and the tie-outs they carry

### The STIR side (workflow 2)

Citi's pack-convexity trades are published **with tickets** — which the existing strat 2
never had; it had no target and no stop.

| note | date | entry | hedge | exit | P&L |
|---|---|---|---|---|---|
| Turning Green from Blue | 2017-02-09 | Blues, 2000 H0-Z0 packs vs $2bn, CA **8.8 bp** | **2s5s10s fly** $147mm / −$85.6mm / $20.89mm at **−18.2 bp** | 2017-06-06 CA **6.6**, fly **−16.5** | gross (8.8−6.6)×$200k = **$440,000** (verified); net **+$500,000** |
| Turning Green from Blue | 2017-06-06 | Greens, 3000 M9-H0 packs vs $3bn, CA **4.3 bp** | sell 500 EDM9 / buy 424 EDM8 (ratio 1.1792 vs DV01 1.18) | target **+$450k** / stop **−$225k** on $300k DV01 | roll +0.7 bp/3m |
| Take off the hedge | 2017-07-13 | — | — | M9-H0 CA **3.35 bp** | CA leg (4.3−3.35)×$300,000 = **$285,000**, verified exact |

And the relationship the brief asks for is **already published as a regression**:

> Blues, Figure 4, monthly 2013-01-01..2017-12-26: change in (Blues CA − model) on change
> in dealer positioning, **y = 2e−06·x − 0.1053, R² = 0.2724**.

with the fair-value model printed twice, re-fit a month apart — a natural out-of-sample
check on the fitting procedure itself:

* May-2017: `Blues CA = 9.7 + 20.6 · (−0.705·2y + 5y − 0.465·10y)`
* Jun-2017: `Blues CA = 10.2 + 21.4 · (−0.70·2y + 5y − 0.46·10y)`

CME-LCH levels for tie-out: 30Y **+1.90 bp** (2015-05-18); 5Y **+1.25**, 30Y **+2.40**
(2015-06-17); 5y5y forward **+2.9** vs spot **+1.85**; max roll-down **1.1 bp/yr**.

### The long end (workflows 3 and 4)

The single most useful item in the corpus for workflow 4 — it is exactly the
**risk-adjusted carry** the brief singles out, and it **flips sign at a printed threshold**,
which is the direct cure for strat 1's measured degeneracy ("the curve breakeven is below
1Yx30Y ATMF on every day a vol exists"):

> Citi, *Taking profits on delta-hedged 15y5y/20y10y flatteners*, close **2019-12-04**.
> Fifteen USD curve pairs × eight columns: `curve bp`, `1y ZS`, `3y ZS`, `ZS since 2000`,
> `1y carry bp`, `daily BE bp` (**zero when carry is positive**), `1y realized vol bp`,
> `BE / realized vol`. *"the ratio of the daily breakeven — the daily move in rates that
> yields a convexity gain offsetting a negative daily carry — to realized daily volatility"*.

Every cell is published for USD and GBP: **120 USD cells of known answer**. The rule has
both sides — enter the flattener when the ratio is low **and** carry ≥ 0, exit at **≈0.8**,
enter the steepener above **1.0** (observed 1.17–1.38) — so unlike strat 1 it is a timing
rule rather than a permanent position.

Three further anchors from the same family:

* **A curve check that needs no strategy at all**: on 2019-10-16 the DV01-neutral
  15y5y : 20y10y notional ratio is **149.5 / 81.97 = 1.824**.
* **Costs, measured rather than assumed**: that book ran +$187K gross to **+$155K net** on
  $50K DV01 — **≈$32K of round-trip cost including every resize**.
* **A convexity-vs-direction split Citi published itself**: the GBP 15y10y/25y10y book made
  GBP 445K = **115K from the curve move and 330K from convexity (74 %)**. An external anchor
  for the `sharpe_ex_mtm` attribution this codebase already runs.

JPM's risk-adjusted carry for workflow 3 is recovered exactly (arithmetic-verified on all
four rows of its OAT exhibit): `RAC = E[3M return in bp] / (3M realised daily bp vol ×
√252)`, with `E[return] = carry + slide + ½·σ²·Cvx/PVBP`. The published **caption
contradicts the published arithmetic**; the arithmetic reproduces the printed column.

---

## 6. Feasibility verdict and ordering

| workflow | verdict | the measurement that decides it |
|---|---|---|
| **W1** CA data for all five colours | **FEASIBLE, in progress** | 2024-2026 already ≥20; the 2021-2023 gap is 486 dates; the vendor still serves them, 100 % cell resolution, 0 errors |
| **W2a** intraday CA | **FEASIBLE** | demonstrated offline end to end; minute curve 1,543 days, minute SR3 tape present |
| **W2b** CA vs swap fly 2021-2026 | **FEASIBLE, one caveat** | front packs intact ~250 days/yr throughout; **deep packs are 2021-2023** until the warm lands. Basis GREEN, positioning GREEN-but-stale, per-contract OI unavailable pre-2025 |
| **W3** CA vs ultra-long curves as vol RV | **FEASIBLE** | ultra-long forwards 7/7, cube ATMF 99.43 % |
| **W4** ultra-long curve vs fly, risk-adjusted carry | **FEASIBLE, best-specified of the four** | curve-only, full window at full density, 120 published cells of known answer |

**Ordering.** W4 and the curve half of W3 depend on nothing being repaired, and read a
*different diskcache directory* from the one the warm writes (`IRSwapsTB_v2_CITIVELO_EXCEL`
and the CurveStore, versus `STIRFuturePricer_Cache`), so they proceed during the warm. W1's
panel rebuild, W2b, and W3's CA leg wait for it. W2a is code and unit tests and is not
blocked either way.

---

## 7. Two things to raise with a human

1. **A live credential is committed to this repository.** `gs_quant` authenticated using a
   client id and secret hardcoded at `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py:7-8`
   — no `GS_*` environment variable is set and there is no `.env`. The values are not
   reproduced anywhere in this work. Rotating them is not something to do unattended, but it
   should be done.
2. **A pre-existing test failure, unrelated to this work but relevant to W2a.**
   `tests/test_citi_velocity_intraday_curve.py::test_irswapsmdp_citivelo_source` expects a
   pinned minute snapshot to resolve to 11:58 and gets 11:57. It fails with every change on
   this branch stashed, so it is not a regression here — but it is the exact
   nearest-snapshot machinery the intraday CA will depend on.

---

## 8. Risk register

1. **A cached artifact fakes a successful re-run.** Several convexity notebooks do
   `if _F.exists(): X = pd.read_parquet(_F)`. Every notebook written in this block gets a
   `FORCE_REBUILD` flag that unlinks its own outputs first. The Aug-19 baseline is parked
   under `_baseline_prewarm/` so it can never be picked up by that pattern.
2. **`QueryDrivenBacktest.run()` swallows exceptions and prints them** — a failing backtest
   looks like a flat equity curve. Assert on `mtm_history` afterwards, always.
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
   inside `cache_only()` turns contention into an exception. The Citi Velocity swap caches
   are separate diskcache directories, so pure-swap-curve work proceeds during the warm.
8. **`IRSwapQuery.return_query()` rebuilds a list-valued query without `value_kwargs`.**
   Any per-value convention passed that way is silently dropped on the list path.
9. **`SnapshotPolicy.legacy()` is nearest-in-either-direction with unbounded lag** and can
   serve a *future* snapshot. Intraday work uses `strict(..., allow_future=False)`.
10. **Exact midnight resolves to EOD**, not to the instant.
11. **CFTC TFF is published on a lag** — position date and publication date differ by days.
    Lag to the publication date, not the report date.
12. **Do not `git checkout --` a file with uncommitted work.** Doing exactly that during
    this session silently reverted a finished fix; it was only caught because the following
    test run was inspected rather than assumed.

---

## 9. Repairs landed in this block

| commit | what |
|---|---|
| `59bc9b2e` | this report, plus the two defect probes |
| `50e5fb29` | the three shared-CA-path defects (§2), mutation-checked 4/4 |
| `87edd3e6` | `Q12STIRT` / `Q16STIRT` node horizons, and a rule test across the whole curve table |
| `897f69dd` | the recurring SR3 warm: blind depth scan, a test that never called the function it named, and no unsettled-session guard |

### On the node-horizon fix

`db95871d` measured the defect on `Q20STIRT`, fixed that one curve and flagged the rest;
`test_q20_curve_horizon.py` then pinned the rule for `Q20STIRT` only, which is why the same
defect sat undetected in six siblings. Measured: `Q12STIRT` needs 45 and had 39,
`Q16STIRT` needs 57 and had 51. Both are fixed — they are the curves the nightly
`warm_stirf_cme_session` actually builds, so the defect was live in the production curve
store rather than latent, and the existing Q12/Q16 vintages there predate the fix.

Seven mixed curves (including the `MIX23` family) are also short, by 6–18 months, and are
**not** changed: each interleaves a monthly ladder with the quarterly one and feeds the
production intraday store, so widening the horizon moves a live series and needs its own
before/after. They go on an explicit allowlist carrying the measured shortfall, so the
defect is recorded in code and cannot grow.

The rule is derived from the ladder, not from a length. A first draft applied
`3·n_instruments + 6` to every curve and reported nine violations, **seven of them false** —
the mixed curves interleave `SERCM`/`FFCM`/`RACM` monthlies, so `n_instruments` is not the
quarterly depth. The binding quantity is the highest `SFRCM` index. The test guards its own
parser first, because a regex that matched nothing would make every assertion pass vacuously.

### On the recurring warm

The nightly job `WarmJob("SR3 EOD settles (depth 20)")` **is** wired into
`scripts/daily_cache_warmer.py:1416`, so the decay does not recur by construction — but it
has never actually executed (12 nightly logs, no match), and it carried three defects that
would have blunted it: a depth scan blind to every date below depth 4 (the common case for
a cold date — the manual warm's ledger recorded 213 such dates), a test named for that
helper that never called it, and no guard against warming a session that has not settled.

The last one is worth recording as a design point. `warm_sr3_deferred` refuses any date
`>= today`, and copying that rule would have made the nightly a **no-op every single
night**, since its whole purpose is the session that just closed. The hazard is fetching
before the settle exists, not the calendar date, so the guard is on the clock.
