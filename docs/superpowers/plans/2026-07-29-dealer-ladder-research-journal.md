# Dealer Ladder — Cleanup, Backfill, and Signal Research Journal

**Started:** 2026-07-29
**Mission:** (A) clean up + merge PR #354, (B) build the full ~6-month dataset, (C) run the
gate-ordered signal-research program (plan Task 10, G0–G5) and report a verdict.
**Autonomy:** full pre-approval for design/implementation decisions; every fork documented here.

Plan: `docs/superpowers/plans/2026-07-14-dealer-ladder-infrastructure.md`
Specs: `docs/superpowers/specs/2026-07-14-dealer-positioning-delta-ladder-design.md`,
`docs/superpowers/specs/2026-07-12-stir-dealer-direction-classifier-design.md`
Audit: `docs/superpowers/audits/2026-07-15-sdr-dealer-positioning-feasibility-audit.md`

---

## 0. Baseline established 2026-07-29 (read-only probes)

**Branch state** (`feat/stir-dealer-ladder`, worktree `C:\Users\chris\clee\ARBS-ladder`):
38 commits ahead of `origin/main`, 63 behind. Plan Tasks 1–8 + A1 + A2 + the HY module are
recorded complete in `.superpowers/sdd/progress.md`. Task 9 (operational backfill) is partial;
Task 10 (research) not started.

**DB baseline (remote Supabase prod, read-only probe):**

| table | state |
|---|---|
| `arbs_stir_direction_v1` | 5 days only: 07/02 (693u, 26 UNK), 07/09 (550u, 79 UNK), 07/10 (562u, 3 UNK), 07/13 (585u, **192 UNK = 32.8%**), 07/14 (974u, 40 UNK). Mixed vintages (classified_at 07/13→07/24). |
| `arbs_stir_ladder_prints_v1` | 07/02 511/693 units, 07/09 390/550, 07/10 217/562, 07/13 101/585, **07/14 0/974**. FED_FUNDS space only on 07/02 (later vintage). |
| `arbs_stir_book_marks_v1` | ENTRY marks only (1219 rows). **Zero EOD marks.** |
| `arbs_stir_tick_size_v1` | 2026-06-10 → 2026-07-21, 28 days, 6001 rows. |
| `arbs_usd_swap_tape_legs_v2` | 2024-03-01 → 2026-07-29 continuous. **Full 6-month window available.** |

**Consequences for the plan:**
1. The coverage collapse is confirmed (39%/17%/0% on 07/10/13/14) and is the thing the
   dates-path FUTURES risk model is expected to fix.
2. Tick calibration only exists for 06/10–07/21. A 6-month backfill needs calibration for
   the whole window. **Decision (see D1)**: strictly-trailing per-chunk calibration.
3. No EOD marks exist at all — the marks phase has never been run.

---

## Decisions ledger

**D1 — Trailing calibration windows for the 6-month classifier backfill.**
`backfill_stir_direction_range.py` computes calibration ONCE for the window and passes it to
every day-worker. Using one window that overlaps or postdates the classified days injects
look-ahead into `p_flip` / `direction_confidence` / `curve_suspect_trade`, which the ladder's
default `"expected"` weighting consumes. Therefore the backfill runs in **monthly chunks with
a strictly-trailing 30-calendar-day calibration window** (`calib_end = chunk_start − 1 day`).
Cost: one extra `run_calibration` per chunk (ticks-only mode: pure SQL + pandas, no curve
builds — cheap). Benefit: `p_flip` at day *d* uses only data before *d*, so G1's no-lookahead
audit covers the confidence layer too, not just the visibility timestamps.

**D2 — `code_vintage` stamped from the worktree git SHA at CLI start.**
Resolved once per process via `git rev-parse HEAD` on the module's repo root, with a
`"unknown"` fallback so tests and detached environments never crash. Column added to both
`arbs_stir_direction_v1` and `arbs_stir_ladder_prints_v1` via idempotent `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`.

---

**D3 — Sign convention was inverted in three of four bucket spaces (found 2026-07-29).**
The persisted table settled it: over 07/02–07/13 OUTRIGHTs, MEETING is 868/868 PAID-negative
and 249/249 RECEIVED-positive, but FED_FUNDS is 288 PAID-**positive** / 74 RECEIVED-**negative**
and FUTURES is split 348 negative / 461 positive *on PAID alone*. A per-space constant cannot
produce mixed signs inside one space, so `_RL_SIGN_BY_SPACE` was masking a deeper defect: the
legacy `<ROOT>CM<n>` fetch path calibrated the risk curve to vendor settlement prices on nodes
seeded from the decision-time curve, and where those disagreed the Jacobian degraded — giving
deltas that were mis-scaled as well as flipped (|ladder sum| 55,575 and 67,882 against
structure DV01s of 8,274 and 10,126). Collapsed to one `RL_DELTA_TO_FUTURES_EQ = -1.0`.
**Every ladder row written before this is invalid and is being rewritten.**

**D4 — Both futures spaces are now curve-implied; the vendor fetch is gone.**
`contract_grid` mirrors `STIRFutureMDP`'s `<ROOT>CM<n>` resolution exactly, so bucket keys stay
compatible (`SFRU26…`, `FFN26…`). SR3 agrees with the fetch path to ≤0.03%; deferred ZQ buckets
to ~0.001%. The **front ZQ month lands ~14% below** the legacy path because the fetched pricer
carried one extra same-day fixing that was **not yet published** at the decision timestamp — a
one-day look-ahead in the path being replaced. Also fixed `SERFF_BASIS`, which had been failing
for all but the first day or two of each month (only 4 of 456 eligible units on 07/02 produced
basis rows) because the front SR1 contract and its paired IRS leg were built without fixings.

**D5 — 07/13's 192 UNKNOWN (32.8%) are infrastructure, not data.** Flag histogram:
85 `BARCHART_TOS_LIVE_STIRF-RL returned no data`, 80 `maximum recursion depth exceeded`,
27 `403 Client Error: Forbidden`. All three are the vendor-fetch / rate-limit / curve-anchor
family that later fixes addressed. The recursion failure also hit 07/09 (19) and 07/14 (32) and
is tracked as an open item — re-run under the current vintage is the test.

**D6 — Realized window: no shrinkage needed (probed 2026-07-29).** At 14:30 ET on a sparse grid
from 2025-12-15 to 2026-07-15, `USD-SOFR-1D-Q12xM12STIRT` and
`USD-OIS-Q12xM12STIRT-SERFFX-MIX23` both build at every probe point (17–23 nodes), and the Citi
Velocity independent mid resolves at every one. So the planned **2026-01-12 → present** window
stands. One caveat for G0/G3: the Citi workbook's sheets run Mon 00:01 → Fri 11:59, so
**Friday-afternoon prints have no independent mid** (2026-01-30 and 2026-05-15 both fell back to
11:59). Friday PM is therefore an explicit hole in the pseudo-label study, not a silent one.

**D2' — the vintage stamp is a HASH OF THE PIPELINE MODULES, not the repo HEAD.** Superseding
D2. A ~6-month backfill runs for hours, and committing anything at all meanwhile — a research
module, a doc — would change HEAD and split the window into artificial vintages, while a dirty
tree would tar every row `+dirty` regardless of whether the dirt was in this pipeline. So
`code_vintage()` hashes the contents of the 19 output-determining modules, normalising CRLF→LF,
excluding `vintage.py` and `daylog.py`. `git_sha()` survives for logs. Also added
`--purge-stale-vintage`: re-classification upserts on `unit_key`, so rows whose unit is no
longer eligible survive as orphans from an older **tape** vintage — measured on 07/02, a re-run
wrote 678 units of which 568 overwrote old rows, leaving **125 orphans plus 110 genuinely new
units**. The purge is skipped whenever any day in the window errored, because that day wrote
nothing and deleting its previous rows would leave a hole indistinguishable from an empty session.

**D7 — Phase A's re-classification is folded into Phase B, not run twice.** 07/02–07/14 sit
inside the Phase B window, and running them under one calibration convention and then again
under another would leave the verification numbers describing a dataset that no longer exists.
Phase A's verification was therefore taken on a fully rebuilt cold day (2026-03-10) instead.

**D8 — the backfill was ~30 hours because of a vendor-quota pathology; it is now ~9.**
Two independent problems, both measured rather than guessed:

*Curve acquisition.* The per-minute `_get_curve` path costs one Barchart request **per
instrument per minute** — 24 instruments for the SOFR ladder curve, 36 for the FF one — against
an intraday origin quota of ~55 requests per rolling minute. One curve-minute consumes roughly
the whole quota; a 479-minute day needs ~28,700 requests, about eight hours of quota per trading
day even perfectly paced. And the limiter is constructed **per fetch call, not per process**, so
the documented 3×4 warm defaults burst ~6× through the ceiling and park every worker in
`Retry-After` sleeps — the observed ~5% CPU with 19 sockets open and no progress. Compounding
it, `USD-SOFR-1D-Q12xM12STIRT` had **1 day in the local CurveStore against the FF curve's 1376**,
and the barchart single-point path never writes back, so every SOFR minute missed and would have
missed forever. Fix: `warm_pricer` now issues one `bulk_get_data` per curve, which fetches the
whole session once and persists the calibrated day. Measured on a cold day, 5 minutes:
**71.3 s → 0.02 s**, value-identical to **0.000e+00** on both node discount factors and a priced
2Y rate. A cold classifier day went from 30+ min with high UNKNOWN to **~5 min with ZERO
UNKNOWN** (599 units, 411 PAID / 188 RECEIVED), of which ~4 min is the once-per-chunk calibration.

*Projection.* Profiling showed **100%** of the projection's cost in `build_risk_models`
(5.36 s/snapshot; delta was 2 ms, packaging 3 ms). Per space: MEETING 0.11 s, FUTURES 0.24 s,
FED_FUNDS 0.49 s, **SERFF_BASIS 13.81 s — 94%**, because it is the one space still needing ~60
vendor pricer fetches per snapshot. Dropping it (default; `--with-basis` re-enables) took a cold
day from 74–109 min to **7.75 min**. This costs the research nothing: the plan designates
SERFF_BASIS conditioning-only and bars it from ever being a test target, and
`controls.basis_bp` — curve-implied contract rate minus the futures market rate, per contract, on
the 5-minute **decision** grid — is a better conditioner than a basis DV01 split at scattered
print times. The old DB rows confirm the projection was always this slow: 07/02's 511 units ran
15:09→17:20, **2h11m for one day**, long before any change here.

---

## Data-surface constraints found by recon (2026-07-29) — all load-bearing

These change what the study can claim, so they are recorded before the study runs.

**C1 — `venue_status()` is dead code in production.** Its only caller anywhere is
`scripts/diagnose_d2c_venue_skew.py:110`. Nothing in the classifier, projection or ladder path
applies the whitelist, so both tables contain `VENUE_UNKNOWN` units and the research loader must
filter at read time. The only enforced gate is `l.venue = 'D2C'`, which means merely "platform is
not one of the 6 IDB codes" — a NULL platform passes. `VENUE_UNKNOWN` is ~9.6% of the already-D2C
universe, and **the whitelist does not fix the PAID skew**: the cleanest stratum
(`D2C_WHITELISTED × curve-clean × on-market`) still came out ~72% PAID against ~72.3% overall.
So the skew is not a venue artefact, and G0 has to look elsewhere.

**C2 — `p_flip` is missing for a large minority, and stored as NaN rather than NULL.**
`score_on_market` returns `p_flip=None` in both gate branches (`|dev| > 3S` curve-suspect, and
`|dev| < 0.5·(S/2)` ambiguous→TICK_RULE), so only 1799/4239 classified units carry one, and
`arbs_stir_ladder_prints_v1` holds numeric `'NaN'` in 16740/33948 rows. `ladder_state._weight`
does `(1 − 2·p_flip).fillna(1.0)`, so those prints silently weight 1.0 — the intended fallback,
but it means any SQL `avg()` over the column returns NaN, and the share must be reported.
Both excluded classes are already outside the primary universe, so the primary should be
mostly-populated — **to be verified and reported, not assumed.**

**C3 — the `expected` weighting is close to inert under the current calibration.**
`disp_jns` is NULL on 100% of `arbs_stir_tick_size_v1` (7558 rows) because ticks-only calibration
feeds `s2m_bps = NaN`, so `curve_suspect` is false everywhere in that table and `sigma_mid`
always collapses to its fallback `futures_tick_bps / 2` = 0.125bp (SR3) / 0.25bp (FF). A print a
normal half-spread from mid then scores z≈2, `p_flip ≈ 0.023`, weight ≈ 0.95. So the
`expected`-vs-`unweighted` arm of the secondary grid should show almost nothing, and that is a
property of the calibration, not evidence about the signal. Report it; do not present it as a
robustness result. (Per-print `curve_suspect_trade` on the *direction* table is unaffected — it
comes from the `|dev| > 3S` branch, not from the tick table's `curve_suspect`.)

**C4 — ladder netting is a documented no-op.** No lineage column
(`original_dissemination_identifier` / `prior_uti` / `prior_usi`) exists on the tape, so
`extract_unwind_events` returns an empty frame. Positions therefore decay out via the EWMA
cutoff only; genuine lifecycle terminations are invisible. Also, `extract_unwind_events` passes
only `is_block`, so any unwind it did find would be stamped INDETERMINATE (+60min).

**C5 — `visibility_timestamp` is a modelled legal-delay estimate, not observed tape time.**
There is no `dissemination_timestamp` column anywhere in `arbs_usd_swap_tape_legs_v2` (re-probed
twice). Worse, the `is_capped` field feeding the `CLEARED_OFF_FACILITY_CAPPED` branch is a
**notional**-cap marker, not a Part 43 capped-price/dissemination flag — a semantic mismatch, so
the delay cannot be cited as strictly regulatory. And `visibility_class` compares with
`is True`/`is False`, so numpy/pandas booleans silently fall through to INDETERMINATE (+60min):
any new caller must coerce with `bool()`.

**C6 — no 25bp structural grid or level-proximity implementation exists.** It is spec prose only.
`classify_meeting_proximity` measures meeting *count* distance, not distance in rate space. G4's
level-proximity conditioning therefore has to be built, from the decision-time curve — and
**`SDRUtils/analytics/fomc.py` cannot be used for it**: its whole pricing path is anchored on
`date.today()` (expired meetings skipped, schedule trimmed to today−90d, fixings defaulted to
today), so it is not point-in-time safe. The safe path is
`resolve_central_bank_tenor(..., as_of=d)` against a curve snapshot at *d*, which is what
`ladder.py` already does for `fomc_1..12`.

**C7 — statistics: reuse vs build.** Already present and reused: `BT/signals/deflated_sharpe.py`
(deflated Sharpe, expected max Sharpe under the null, DSR gate) and `RVUtils/SFRRVLab/stats.py`
(`nw_tstat`, `cost_curve`, `nonoverlapping_sharpe`, `grid_distribution`, `deflated_for_grid`,
`neighbourhood_stability`, `verdict`). Absent everywhere and therefore written:
Romano-Wolf / max-t, any reusable day-blocked bootstrap, rank IC. (mlfinlab's bootstrap functions
are `pass` stubs returning `None`.)

**C8 — costs: reuse `RVUtils/MeanRev/contracts.py`.** Per-CONTRACT bp-native model
(`SR3_DV01_USD=25.0`, `SR3_TICK_BP=0.5`, `SR3_HALF_SPREAD_BP=0.25`, `package_cost_bp`), which
documents that the older per-LEG charge understates a fly (true round trip 2.0bp, not 1.5bp).
A single SR3 outright round trip = 0.5bp, matching the locked cost model.
`BT/serff/config.py` supplies the front/back tick split and `point_value`.

**C9 — league-table convention to adopt:** `notebooks/backtests/sfr_fly_meanrev_common.py` writes
**two** rows per framework — *best-config* and *median-config*. The median row is the
anti-selection control, and this study needs it.

**C10 — conditioning series that already exist** (no need to build): `BT/serff/data.build_panel`
(daily SOFR−EFFR bp, H.4.1 reserves/RRP/TGA, five named funding regimes, turn dummies),
`RVUtils/general.realized_bpvol`, `BT/signals/sfr_kink_fade.compute_vol_regime_ts` (rolling vol
percentile), `sfr_fly_triggers.compute_regime_filters` + `days_to_next_fomc`, and per-print
`execution_session` / `fomc_proximity` on the tape. Dead end: the CurveStore analytics panels
nominally holding `par_rate_FOMC_1..7` are 100% NaN in every value column for all 8 assets.

**C11 — join hazards.** For OUTRIGHT units `unit_key == trade_id` but the leg still carries a
non-NULL `package_id` (the FK is NOT NULL, singles get a synthetic package), so
`COALESCE(package_id, trade_id)` is the WRONG way to rebuild `unit_key` — branch on
`direction.package_id IS NULL`. `dv01` means different things in the two tables (direction =
gross Σ|leg risk|; ladder = `structure_dv01`). Tape `risk` is signed and pre-rounded to \$100 —
always `.abs()`. Anchor leg = earliest `(expiration_date, effective_date, trade_id)`, three keys.
`ALL_PKG_LEGS_SQL` applies no eligibility filter, so a package unit can contain legs that would
individually have failed, and its per-unit venue label is an anchor-leg approximation.

## Phase log

### Phase A — PR #354 cleanup

- [x] A.0 Baseline probes + journal (2026-07-29)
- [x] A.1 Worktree hygiene + merge `origin/main` — one conflict (`progress.md`), both ledgers
      kept; fast gate green after the merge at **3060 passed / 42 skipped**
- [x] A.2 FUTURES **and** FED_FUNDS risk models → curve-implied dates path, plus the sign fix
      (see D3/D4) and `SERFF_BASIS` repaired
- [x] A.3 `code_vintage` (content hash, see D2') + `--rewrite` + curve pre-warm + day-parallel
      range drivers + per-day logs
- [x] A.4 07/13's UNKNOWNs diagnosed **and confirmed dead**: the recursion victim
      re-classifies cleanly under the current vintage (PAID via RATE_VS_MID), so all 131
      recursion failures across 07/09–07/14 were a code-vintage artefact. Re-classification is
      folded into Phase B rather than run twice (see D7).
- [x] A.5 Task 9 verification — **clean** (see the table below)
- [x] A.6 **PR #354 MERGED** 2026-07-30 04:50 UTC. Fast gate **3258 passed / 42 skipped**
      (3060 before this work, +198 tests); 7 ladder network goldens green; PR body rewritten
      around the four defects and their measured fixes.

**Task 9 verification, run on a fully rebuilt cold day (2026-03-10, 599 units):**

| check | result |
|---|---|
| sign convention | **MEETING, FUTURES and FED_FUNDS all agree**: 369/369 PAID → negative, 163/163 RECEIVED → positive. No mixed signs anywhere. |
| DV01 consistency (outrights, ±10%) | MEETING 522/532, FUTURES 522/532, FED_FUNDS 491/532 inside. Residual is the expected imperfection of a futures basket as a partition of swap DV01 — the monthly ZQ basket is coarser, hence its larger miss. |
| no-lookahead | 0 rows with visibility earlier than the legal minimum. Delay distribution +1min 14508 / +15min 360 / +30min 1260 / +60min 5436 — genuine Part 43 class variety, not everything collapsing to the conservative fallback. |
| spaces present | all 3 spaces for all 599 units; 0 `RISK_MODEL_ERROR`, 0 `PROJECT_ERROR` |

### Phase B — full-window dataset

- [x] B.1 Curve availability probed — full window viable, no shrinkage (D6)
- [x] B.1b **Performance root-cause and fix** (D8) — this was the difference between a
      feasible backfill and a ~30-hour one
- [~] B.2/B.3 Full-window backfill running via `scripts/backfill_dealer_ladder_window.sh`
      (classify → project → marks, monthly chunks, trailing calibration, per-day logs)
- [ ] B.4 Coverage table

**Phase B live progress:** January chunk classified 20 days in ~31 min (~1.6 min/day at
`day_jobs=2`), every day fully bulk-warmed (`built=0 failed=0`), UNKNOWN ≤ 0.4%/day, weekends
and the MLK holiday correctly empty. PAID share runs **74–82%** in January against ~68–72% in
July — the skew is not stationary, which G0 has to report.

**D9 — the front-six basket must ROLL.** Caught by running `load_context` on real data. "Front
six" is a RANK statement, but the ladder keys buckets on ABSOLUTE contracts (deliberately —
rank-keyed vectors would smear across roll dates). Over the window the contracts behind that rank
change: 2026-01-12 → SFRH26..SFRM27, 2026-06-18 → SFRU26..SFRZ27. Freezing at the window start
spends the last weeks trading an expired contract the ladder never emits; freezing at the window
end looks ahead. Fixed with `window_contract_union` (fetch the union: 8 SR3 + 12 ZQ) plus
`front_rank_panel` (recompute per session) masking the **signal**, so an out-of-basket contract
simply produces no decision.

**D10 — a stale independent curve is NO COVERAGE, not a flip.** The citivelo reader defaults to
`method="asof"`, so a minute it does not cover returns its LAST snapshot rather than failing — a
14:00 Friday request resolved against an 11:59 curve. Scoring that as an independent mid would
book pure data absence as a classification flip, in the one gate whose job is to bound
classification error. Now staleness-checked with a 5-minute cap.

---

## Preliminary G0 signal (1-day smoke, 2026-03-10 — NOT the final number)

Run on 25 sampled SOFR prints with the independent Citi mid. Recorded because the pattern is
strong and directional, and because it is the first evidence bearing on the audit's top kill risk.

- **Flip rate 48%** (12 of 25) — close to a coin flip.
- The mechanism is visible in the rows: our `spread_to_mid_bps` is consistently negative and
  large (−0.09 to −1.31 bp, driving PAID), while the independent `ind_s2m_bps` is small and often
  positive (+0.02 to +0.35). That implies **our curve's mid sits ~0.4 bp ABOVE the Citi swap
  curve**, which is exactly what the direct 2Y comparison showed independently (ours 3.379985%
  vs citivelo 3.376310%, +0.37 bp).
- Against a typical on-market spread-to-mid of roughly half a 0.5 bp tick, **a systematic
  ~0.4 bp mid offset is larger than the signal the direction rule reads**. A positive offset
  makes trades look like they printed below mid → dealer PAID, which is a candidate explanation
  for the entire 70–82% PAID skew.
- Sampled prints fell in the 02:16–03:59 ET overnight window (first 25 by execution time), where
  liquidity is thinnest. The full study must cover the whole session and stratify by time of day
  before this is a finding rather than a lead.
- Exclusion ladder on that day: 599 projected → 345 (on-market methods) → 276 (curve-clean,
  −69) → **243 signed** (whitelist, −33) = 41% of classified units. `p_flip` coverage in the
  signed universe is **93%**, much better than the 42% the raw table suggested — the missing-p_flip
  classes are precisely the ones the universe already excludes.

### Phase C — signal research (G0–G5)

**Code complete and de-risked before the data landed** (2026-07-30 01:10). 233 research tests
green. What was built, and the defects that building it surfaced:

| module | what it is | defect it exposed while being written |
|---|---|---|
| `audit.py` | G1 no-lookahead by differential **poison**, not assertion | — (half its tests use deliberately leaky builders) |
| `stats.py` | day-blocked cluster inference, Romano-Wolf stepdown, rank IC | small-sample correction must be **per column**: a NaN column can be missing whole blocks, measured as a 2% t discrepancy |
| `signals.py` | fast panel builder, pinned to **exact** agreement with `ladder_at` | tz-aware `.to_numpy()` yields object dtype and will not broadcast against timedelta64 |
| `data.py` | loaders + target construction | vendor `one_df=True` returned an EMPTY frame for the whole ZQ strip; sparse bars resolved only **8%** of ZQ 60-min horizons before the minute-grid fix |
| `labels.py` | G0 independent-mid flip study | the citivelo reader's `asof` silently returns its last snapshot — a 14:00 Friday request resolved against an 11:59 curve |
| `controls.py` | G3 controls + the independent basis | no 25bp-grid implementation existed anywhere; `days_to_next_fomc` returns a 999 sentinel a regression would read as "very far away" |
| `study.py` | G2–G5 machinery | **G2 was passing increments to an estimator that differences its own inputs** — a wrong estimand, not a lost signal |
| `gates.py` | the G0→G5 runner | the front-six basket was frozen at the window start, so the last weeks would have traded an expired contract |
| `plots.py`, notebook, `scripts/run_dealer_ladder_gates.py` | render layer | — |

**D11 — the G2 estimand bug is the one worth remembering.** `hy_corr` differences BOTH inputs
itself, because Hayashi-Yoshida is defined on increments living on the intervals between
observations. Passing the already-differenced ladder increments computed the covariance of
*second* differences. It did not crash, and it did not stop a planted lead being detected — a
"does it still find the plant?" test passes either way. The fix is to pass the ladder **level**
and the **cumulative** signed volume, so the required increments are formed inside. Both the
docstring and a test now pin it via the property that with synchronous observations HY reduces to
the ordinary correlation of increments.

**D12 — three protocol items closed after a gap review against the mission text:**
1. *Independent fair value in G3*, not only G0 — a second horse race adding a basis built from
   the Citi swap-quote curve. Run separately from the first because the two bases are highly
   collinear; folding them together would inflate both SEs and confound "survives our basis" with
   "survives an independent one". G3 now requires survival of **both**.
2. *The label-free cell*, now actually wired: the identical rule driven by unsigned print
   intensity. If both it and the signed ladder work, the direction model is carrying nothing.
3. *Conditioning splits* by block share, 25bp level proximity, realised vol, Amihud, SOFR−EFFR
   funding spread, days to FOMC and time of day — terciles, because at ~150 independent epochs an
   interaction term is not identified and the audit asks to **segment**, not merely control.


- [ ] C.0 Pre-registration written before any G4 run
- [ ] C.1 G0 labels/provenance + Citi-mid pseudo-label flip study
- [ ] C.2 G1 arrival integrity
- [ ] C.3 G2 mechanism ordering (HY/LLS)
- [ ] C.4 G3 circularity battery
- [ ] C.5 G4 pre-registered price prediction + secondary grid
- [ ] C.6 G5 economics/capacity
- [ ] C.7 Findings doc + notebook + completeness pass

### Adversarial review of the research harness (2026-07-30 02:40) — CLOSED

Before pointing any of this at the real window, the harness was reviewed by four independent
adversarial passes (correctness, no-lookahead, statistics, data-and-costs) plus a verify pass.
**Fifteen findings survived verification. The existing 233 tests passed throughout all fifteen.**
That is the fact worth recording: a green suite over a research harness certifies that the code
does what its author believed, not that the belief was right.

All fifteen are fixed and each is now pinned by a test whose docstring names the failure rather
than the property (`tests/test_dealer_ladder_review_fixes.py`, 25 tests). Commits `45a6d797`
and `acf0706c`.

**The two that would have produced a confidently wrong verdict:**

1. **The no-lookahead poison audit was vacuous.** `run_g1` handed `audit_future_poison` a
   one-element grid, so `ladder_panel`'s per-session chunk window (`hi = grid.max()`) dropped
   every future print *before the decay matrix was built*. The `age >= 0` gate that **is** the
   no-lookahead mechanism was therefore never evaluated. The audit reported PASS on a builder
   leaking five hours of future flow. It now builds the whole session and reports
   `max_future_prints`, so a vacuous pass is visible as one. This is the single most important
   fix in the batch: G1 is the gate everything downstream leans on, and it was certifying
   nothing.
2. **The pre-arrival placebo reported the inverse of its own statistic.** It passed
   `trade_ledger` a *change* panel, which the ledger differences again — so the measured
   quantity was `r(t+h) − 2r(t) + r(t−h)`: the forward window **minus** the backward one. A
   genuine forward-only effect would have been condemned as leakage, and genuine anticipation
   reported as clean. Both directions of error, from one wiring mistake.

**Verdict-direction findings.** G2's verdict came from LLS, which is built from *squared*
correlations and is therefore direction-blind — a lead in the anti-hedging direction, which
*refutes* the channel, was reported as PASS. G3 passed on `|t| ≥ 2`, admitting a coefficient
opposite the pre-registered hypothesis. Both now check sign against the hypothesis and report
timing and direction separately.

**The lockout was protecting nothing.** G2 and G3 ran over the whole window including the
holdout. A G3 failure is exactly the verdict that prompts re-specifying controls, so doing that
with lockout data in the sample would have burned the holdout silently. Both are now in-sample
by default, with `in_sample=False` available deliberately.

**Two findings that both trace to the PAID skew** — worth stating together, because the skew is
a property of this dataset and will keep generating bugs of this shape:
- `trade_ledger` signed direction from `z = level − trailing mean`. With 68–82% of prints PAID
  (and PAID meaning *negative* `delta_dv01`), that mean is systematically negative, so
  `sign(z)` and `sign(level)` disagree across the whole region `μ < level < 0` — measured at
  ~35% of triggers on a realistically skewed bucket. A third of trades took the position
  **opposite the hypothesis**. Direction now comes from the ladder level, the trigger stays
  `|z|`, and the frame records `sign_disagrees` so it can never be silent again.
- `ladder_panel` filled no-data cells with `0.0`, which `trailing_zscore` turns into the
  constant `z = −μ/sd` — systematically *positive* for the same reason, and above the trigger.
  A bucket with no visible prints all session produced a full session of same-signed trades at
  full weight in the primary ledger. No-data is now NaN.

**Sample-integrity findings.** `horse_race` dropped NaN-control rows from the controlled spec
only, so an unchanged coefficient lost ~1.3× of its t to sample shrinkage alone — read by G3 as
"does not survive"; both specs now fit on identical complete cases. `curve_shape` picked
front/belly/back *positionally* over a window-union panel, selecting an expired front contract,
so slope and curvature were structurally NaN for long stretches. `run_grid` and `run_placebos`
rebuilt the signal and dropped the front-N mask, trading the window union (8 SR3 contracts)
rather than the pre-registered front six. The staleness guard checked only the entry, so a fresh
entry against a 25-minute-stale exit measured a 35-minute move and called it a 60-minute one.
`trailing_zscore` used `pd.unique` (arrival order) for its session window — and
`audit_trailing_moments` cannot catch that, because it poisons by *position* and so assumes the
very property at issue.

**Reporting findings.** 192 of 288 declared grid variants silently produced no row (MEETING is
never built; cross-space bucket namespaces are disjoint). A reader saw 96 rows with nothing to
say the rest were untested rather than weak — now `g4_skipped_variants.csv`, which accounts for
every declared variant.

**D13 — point-in-time is verified, not assumed.** The decision curve is calibrated from Barchart
bars selected with `method="nearest"` and then `ffill().bfill()`, so a request for an uncovered
minute can resolve against a bar from *after* it. G1's battery cannot see this: it poisons the
**ladder**, and this path feeds the **controls**. A control carrying future information breaks
the horse race in either direction — absorbing variance the signal should have explained, or
manufacturing a basis reversal that reads as "the signal was really trading curve-fit error".
`curve_implied_contract_rates` now reads the handle's own stamp, NaNs any minute whose curve is
stamped later than the decision, and reports the drop rate to `g3_point_in_time_*.csv`. Rows
whose stamp cannot be read at all are **kept and counted** rather than dropped: dropping every
unverifiable row would empty the control panel on any pricer without `meta()`, which is a scope
cut disguised as a safety measure.

**D14 — staleness is reported, not tuned.** `run_primary`'s docstring promised a
`run_staleness_sensitivity` that did not exist. It does now: the primary spec re-run at caps of
none/30/15/10/5/2/0 minutes with the mean *realised* horizon beside the nominal one. It is not a
knob to choose from — the pre-registration fixed no cap. It exists because carry biases a
measured move toward zero, so a result that strengthens as the cap tightens was being diluted,
and one that vanishes was living in the carry. The figure is two stacked panels rather than twin
axes, and the sample panel is there to stop the right-hand edge being over-read: at a 0-minute
cap only the busiest contract-minutes survive, which is a different population.

Notebook now 37 cells (staleness, skipped variants, point-in-time), normalized with cell ids.

#### Second batch — the two gates that were not gates (2026-07-30 04:10)

The review workflow completed after the first batch was already committed: **31 candidates, 12
confirmed** across four dimensions plus an adversarial verify pass. Eight were the ones already
fixed above. Four were new, and three of those were rated *invalidates-a-result*. Commit
`1c1737c1`.

**D15 — Romano-Wolf was not controlling its own error rate.** `romano_wolf` passed the ORIGINAL
block labels for the resampled rows, so a day drawn *m* times collapsed into **one** cluster
instead of *m*. The cluster meat became `sum(m² S²)` instead of `sum(m S²)`; with `E[m]=1` and
`E[m²]≈2` that doubles the bootstrap variance and shrinks `|t*|` by ~1/√2 — while the *observed*
t is computed correctly, so the null it was compared against was simply too narrow. Measured on
pure-null panels at a nominal 0.05:

| panel | before | after |
|---|---|---|
| `run_grid` shape: 104 sessions × 24 variants | **0.190** | 0.057 |
| intraday: 40 sessions × 8 rows × 12 variants | **0.190** | 0.057 |
| 104 sessions × 40 variants, `n_boot=1000` | **0.233** | 0.058 |

So `g4_romano_wolf.csv` — the artifact the pre-registration names as the family-wise gate — had
roughly a **1-in-4 chance of certifying a spurious winner on data with no edge at all**. The
calibration test that existed to prevent exactly this could not: it observed 2 rejections in 12
trials against `assert rejections <= 2`, sitting precisely on its own tolerance, and at the true
0.19 it passed 59% of the time. It is re-armed at 60 trials with tolerance 6 — p(pass) = 0.96 at
a true 0.05 and 0.02 at 0.19. Also switched to `(B+1)` bootstrap p-values, because the shipped
form could report `p_fwer` as **exactly 0.0**, which is not a p-value.

**D16 — the economics gate could not fail.** The `(2a−1)` haircut was applied to the **net**
number. It models a direction label right with probability `a`: a wrong label reverses the
position and earns `−gross`, but the round trip is paid **either way**. So
`E[net | a] = (2a−1)·gross − cost`, and attenuating net overstates every row by `2·cost·(1−a)` —
an error that *grows* as accuracy falls, largest exactly where the report is trying hardest to be
conservative. At `a = 0.5` it printed 0.000 where the truth is `−cost`: you trade noise and pay
every tick. On gross 0.9776 against the config's 0.5bp round trip, G5 computed **+0.0955 and
pass=True** where the correct worst case is **−0.3045 and pass=False**. A 0.4bp overstatement is
most of the edge this study is trying to measure, and the error always ran toward "economic".

**D17 — volume was sampled, not aggregated.** `load_context` reindexed a **1-minute** volume
panel onto the 5-minute decision grid, keeping one minute in five and discarding the rest: 21% of
true traded volume. Capacity was understated **4.7×** ($3,250 vs $15,250 per trade at 10%
participation), and G2's signed flow multiplied a 5-minute price direction by the volume of a
single minute the move did not touch — attenuating a gate that must *pass* for a price result to
be attributable to hedging. Price is a level, so sampling it is right; volume is a flow, so it
needs `data.to_grid_sum`, which sums the interval **ending** at each stamp.

**D18 — the "trailing 60-minute" Amihud was a trailing 5-hour Amihud.** A minute count was passed
to `rolling`, which counts observations, so on the 5-minute grid it reached back 300 minutes —
through the previous session's close, with the overnight gap entering as one `diff`. `G3`'s
"survives the liquidity control" was a claim about a different control than the documented one.
Both this and `realized_vol_bp` now infer the step from the panel's own spacing (inferred rather
than defaulted, since the defect *was* a units assumption) and difference, roll and shift within
the ET session.

**One pre-existing test had to change rather than be preserved**: it asserted five NaN rows from
`window_min=5`, which only held while the window was counted in rows. That expectation *was* the
bug, so it is updated with a note saying so.

**What this batch is really evidence of.** Twelve confirmed defects, and the suite was green
before every one of them. Four separate mechanisms by which a null result could have been
manufactured (attenuating net, merging bootstrap clusters, signing from z, decimating volume) and
two by which a real one could have been destroyed (sample-mismatched horse race, second-difference
placebo). None was a crash, none was a type error, and no amount of re-running would have
surfaced any of them — which is the argument for adversarial review of research code
specifically, where the output is a number nobody can independently check.

### C1' — a gap in `VINTAGE_SOURCES`, deliberately NOT closed mid-backfill (2026-07-30 02:30)

While quieting a benign teardown traceback in `MDP/IRSwaps/IRSwapsMDP.py`
(`_FilteredWriteStream.flush` on a stream the per-day log context manager had already closed —
Python reports it as *Exception ignored in…*, and January's chunk log contains the same line and
still finished `0 day-errors`, so it never failed anything) I checked whether that file feeds the
content-hash vintage. **It does not**, which is why the edit was safe to make with the backfill
running.

But it *should*. `VINTAGE_SOURCES` includes `BARCHART_STIRF/risk.py` and `RLIRSwapCurve.py` while
omitting `IRSwapsMDP.py`, which is the module that fetches the bars those two price against — an
edit to its curve-fetch logic would change what gets written without bumping the vintage, which is
exactly what the hash exists to prevent.

**Deliberately deferred, with the reason.** Adding it now would change the vintage mid-run, which
does two bad things at once: it splits the dataset across two vintages, and the next
`--purge-stale-vintage` invocation would delete every day classified under the old one. So the
addition belongs at the **start of the next backfill cycle**, not the end of this one — and it must
be paired with a full re-classification, since after the addition the existing dataset reads as
stale. Recorded here rather than fixed silently, because the hazard is in the sequencing, not the
one-line change.

### C12 — the decision grid was NOT warm, and it is a scheduled step (2026-07-30 02:45)

Probed five January decision minutes directly against the pricer, deliberately bounded, because
a cold single-point build is ~14 s and ~24 Barchart requests and the backfill is using the same
quota:

| curve | 01-13 09:35 | 01-13 14:05 | 01-21 10:00 |
|---|---|---|---|
| `USD-OIS-…-SERFFX-MIX23` (FF/ZQ) | 0.03 s | 0.02 s | 0.02 s |
| `USD-SOFR-1D-Q12xM12STIRT` (SR3) | **6.83 s** | 2.40 s | **57.90 s** |

The FF curve is fully warm; the **SOFR ladder curve is not warm at grid minutes**. That is
consistent with the store census recorded during Phase A (SOFR had one partition against FF's
1,376) and with how the backfill warms: it seeds the minutes prints actually happened at (~445 per
session), and the decision grid is a *different* set — 5-minute marks across the session.

**Not a blocker — a scheduled step.** `warm_decision_grid` already fetches the whole session once
per curve (`bulk_get_data`, ~60 requests) and serves every grid minute from those bars, instead of
~24 requests per minute. Measured on 2026-01-13, concurrent with the running backfill:

- first pass: **26.7 s**, 96/96 minutes bulk-seeded, **0 single-point builds, 0 failures**;
- FF curve: 0.0 s (already present);
- **re-run in a FRESH process: 1.0 s** — so the calibrated day really is persisted to the local
  CurveStore, which is the part Phase C depends on. Seeded-into-this-process and
  persisted-for-the-next-one are different claims and only the second one helps.

At ~27 s per session, the full window is **138 sessions ≈ 62 minutes**, against ~13,400
single-point builds if left to the gate run to discover. `scripts/warm_dealer_ladder_grid.py`
drives it session by session with a resume ledger.

**Sequenced deliberately after the classify/project backfill, not alongside it.** Both draw on the
same Barchart origin quota, and the limiter is constructed per API call rather than per process, so
two warm fronts burst through the ceiling and park every worker in `Retry-After` sleeps — measured
during Phase A at ~5% CPU with nineteen sockets open and no progress. The backfill is the long pole;
stalling it to save an hour later would be a bad trade. Order is: backfill → warm (~1 h) → gates.

**The script's first version warmed nothing and reported success in 0.0 s.** `trading_days` yields
Timestamps, the grid mask is built from `.date` objects, and `Timestamp == date` is False, so every
session selected zero minutes. A warm pass that silently does nothing is worse than one that fails,
because the cost reappears as thousands of cold builds in the middle of the gate run. There is now
a guard that exits if any session maps to zero grid minutes, and ten tests including one that pins
the `Timestamp != date` comparison itself.

### G0 preliminary, on the completed January slice (2026-07-30 03:05) — the biggest result so far

Run standalone (`scripts/dealer_ladder_flip_study.py`), which costs **no Barchart quota**: the
independent source is the Citi Velocity swap-quote store, so this could run against a finished
month while the rest of the backfill was still going. It calls the same `labels.flip_study` the
gate calls — extracted from `run_g0` for exactly this reason, because two copies of the study that
adjudicates the PAID skew would eventually disagree about which prints were in the pool.

**14 sessions, 5,026 on-market signed units, 560 sampled (time-of-day stratified), 488 compared
(87.1% coverage). Overall flip rate 33.4%.**

**1 — The PAID skew is substantially a mid artefact.** On the *same* 488 prints:

| | our mid | independent mid |
|---|---|---|
| PAID share | **86.7%** | **60.7%** |

Twenty-six points of the skew come from which curve you ask. Some skew survives an independent
mid (60.7% is still not 50%), so this is not the whole story — but the headline "dealers are
overwhelmingly paying" is mostly our curve talking.

**2 — The two mids differ by more than the edge being read.**

| stratum | n | mean offset (bp) | median | share \|offset\| > 0.25bp |
|---|---|---|---|---|
| ALL | 488 | −0.469 | −0.278 | **63.9%** |
| CURVE_CLEAN | 339 | −0.393 | −0.261 | 58.7% |
| CURVE_SUSPECT | 149 | −0.644 | −0.486 | 75.8% |

Negative means **our curve sits above theirs** — the same direction the 25-print overnight probe
suggested, now on 488 prints across a month. Against a typical half-spread of about a quarter of a
basis point, **64% of prints have a curve gap larger than the signal the direction rule reads**.

**3 — And the flips are ENTIRELY that gap, not noise.** The mechanism is checkable, so it was
checked. Predicting a flip purely from `|mid offset| > |distance to mid|`:

| | observed agree | observed flip |
|---|---|---|
| rule says agree | 317 | **0** |
| rule says flip | 8 | 163 |

**98.4% agreement, zero false negatives.** Every observed flip is a case where the two curves
disagree by more than the trade's own printed edge. That converts "the label is uncertain" from an
assertion into a measured mechanism with a closed form.

Consistent with it, the flip rate collapses to **12.2%** in the top quintile of `|spread-to-mid|`
(median 3.88 bp): a trade that printed four basis points from mid is unambiguous no matter which
curve you hold.

**4 — `direction_confidence` does not predict agreement.** HIGH 33.7%, MEDIUM 44.7%, LOW 30.3%.
The confidence tier says nothing about this failure mode, so it cannot be used to select a
higher-quality stratum for it.

**5 — CURVE_SUSPECT flips LESS than CURVE_CLEAN (28.2% vs 35.7%), and that is not an inversion.**
Suspect prints sit far from mid (mean `|s2m|` 4.73 bp against 0.49 bp for clean), and a trade that
printed far from mid survives a 0.5 bp curve disagreement. The gate is selecting on distance, so
the lower flip rate is mechanical, not a quality signal. Reporting it the other way round would
have been a real misread.

**What it implies for the study.** With a 33.4% disagreement rate and no truth label, if each mid
is right half the time where they disagree, direction accuracy is bounded above by ~83% and the
signed exposure retains at most ~0.64. The pre-registered attenuation grid {0.6, 0.7, 0.8}
brackets that, which is luck rather than foresight, but it means the grid does not need moving.

**Caveats, stated with the result.** January only, 488 comparisons. A flip is a *disagreement*, not
proof our label is wrong — neither curve is truth, and the accuracy ceiling assumes symmetric
error on disagreements. Coverage misses (12.9%) are dominated by `STALE_INDEPENDENT_CURVE`, whose
source runs Monday 00:01 to Friday 11:59, so hours 0 and 23 ET are almost uncovered and the
comparison is not uniform across the session. **To be re-run on the full window as the real G0.**

#### February replicates it, and sharpens the skew reading (2026-07-30 03:20)

Run on February the moment its classify chunk finished. **Provisional**: the projection phase was
still running, so `arbs_stir_ladder_prints_v1` covered only 15 of the month's sessions when this
ran, and it must be re-run on the complete month.

| | January | February (partial) |
|---|---|---|
| sessions / on-market signed units | 14 / 5,026 | 15 / 4,718 |
| sampled → compared (coverage) | 560 → 488 (87.1%) | 600 → 524 (87.3%) |
| **flip rate** | **33.4%** | **40.3%** |
| PAID share, our mid | 86.7% | 81.7% |
| **PAID share, independent mid** | **60.7%** | **48.7%** |
| mean mid offset (bp) | −0.469 | −0.499 |
| median offset (bp) | −0.278 | −0.320 |
| share \|offset\| > 0.25bp | 63.9% | 67.2% |
| **mechanism agreement** | **98.4%** | **96.9%** |
| **false negatives** | **0** | **0** |

Three things this replication settles.

**The mid offset is a stable property of our curve, not a January accident.** Mean −0.47 then
−0.50 bp, median −0.28 then −0.32, with our curve above Citi's both months. Two thirds of prints
have a curve gap wider than the quarter-basis-point edge the direction rule is trying to read.

**On February data the PAID skew is essentially ALL artefact.** The independent mid gives
**48.7% PAID — a coin flip**. In January it left 60.7%, so some skew survived there; in February
none does. Whatever "dealers are overwhelmingly paying" is measuring, it is not something both
curves see.

**The mechanism holds out of sample.** `|offset| > |distance to mid|` again predicts the observed
flip with **zero false negatives** in every stratum, and again agreement is weakest in the tightest
`|s2m|` quintile (87.6%) and exactly 100% in the widest. Every flip is the curve gap.

**And `direction_confidence` is worse than uninformative.** January: HIGH 33.7%, MEDIUM 44.7%,
LOW 30.3%. February: HIGH **49.0%**, MEDIUM 61.7%, LOW **24.7%** — the HIGH tier flips *twice as
often* as the LOW tier. Whatever the confidence label ranks, it is not agreement with an
independent mid, and it must not be used to select a cleaner stratum for this failure.

### Self-review of the post-review code (2026-07-30 03:25)

The adversarial pass found twelve confirmed defects in code that had a green suite throughout, so
the code written *after* it — lockout, report splicing, the two generators, the coverage report,
the warm pass, the flip study, the bars cache — was reviewed on the same assumption. Four defects,
three of them found by writing the test rather than by reading the code.

**D19 — the report named artifacts nothing writes, and missed four that are written.** The findings
renderer and the completeness inventory both declared `g0_flip_rate` and `g0_direction_skew`, which
no code path produces, while `run_g0` writes `g0_skew_vs_independent`,
`g0_skew_vs_independent_by_hour`, `g0_flip_by_trade_type` and `g0_skew_by_stratum`, which neither
declared. Three stages that *do* run would have been reported MISSING; four that run would not have
appeared at all. **That is the failure the completeness pass exists to prevent, committed by the
completeness pass.** `implied_accuracy` is a dict, so it was never written at all.

Fixed structurally rather than by hand: `tests/test_dealer_ladder_artifact_names.py` reads the
names out of the **source** — the writer's `_write` calls, the renderer's `SECTIONS`, the
inventory's `STAGES` — and asserts the three agree, with a guard test so the regexes cannot pass
vacuously. Restating the list in the test would have drifted exactly like the list it guards.

**D20 — the ZQ cross-check was never run.** `run_g2` and `run_g3` both take `space=` and both write
per-space artifacts, but the runner only ever called them for FUTURES. The FED_FUNDS tables existed
in the code and were produced by nothing — which is how the name test found them, as
written-but-never-rendered. This is not decoration: the brief makes ZQ **the comparison the
mechanism turns on**, since a ladder that leads SR3 but not ZQ reads as liquidity-routed hedging
while one that leads ZQ specifically reads as meeting-targeted. Now `G2-ZQ` and `G3-ZQ` stages.

**D21 — the coverage report crashed on an empty window**, which is exactly when it is most needed,
since telling a missing session from an empty one is its whole purpose. A query returning no rows
contributes no *columns*, so every later reference raised `KeyError`; and `pd.NA` does not survive
`.astype(float)`. An empty window now reports zeros with a loud anomaly.

**D22 — the warm pass warmed nothing and reported success in 0.0s** (recorded above at C12).

**A process note worth keeping.** Three of these four were found by *writing the test*, not by
reading the code — the artifact-name test found two the moment it first ran, and the warm-pass bug
surfaced the first time its output was checked against expectation rather than against exit status.
The pattern across this whole engagement is consistent: on research code, a green suite certifies
that the code does what its author believed. The defects live in the beliefs, and only an
independent statement of what *should* be true — a differential audit, a closed-form prediction, a
cross-check between two representations of the same list — reaches them.

### Phase status at 03:25

- **Phase A — DONE.** PR #354 merged.
- **Phase B — running.** January complete and verified (14 sessions, 7,632 classified, 0.18%
  UNKNOWN, 99.8% projected, 100% marked per unit, single vintage `468474ca6f84`, zero anomalies).
  February classify done, projection at 02-19. Five chunks remain, ETA ~09:30.
- **Warm pass — chained**, fires automatically when the last chunk reports `range done`; ~62 min.
- **Phase C — code complete, reviewed twice, de-risked.** The notebook executes end to end against
  fixtures with 0 errors and 5 figures. G0 has a strong preliminary result replicated across two
  months.

### Incident — "task killed" did NOT mean the work stopped (2026-07-30 03:29)

Both the backfill and the chained warm pass were reported killed. The correct response looked
obvious — restart the backfill from the last completed chunk — and it would have been the damaging
one.

`Get-CimInstance Win32_Process` showed the whole tree still alive and orphaned: the shell script
running the chunk loop, its `backfill_stir_ladder --phase project` child, and four
`multiprocessing spawn_main` workers. What the harness killed was the **task wrapper**, not the
processes. Ninety seconds later the orphan finished February's projection normally
(`range done: 20 days, 0 day-errors`) and moved on to the marks phase by itself.

**Restarting would have produced two concurrent writers.** The project and marks phases run
delete-then-rewrite against `arbs_stir_ladder_prints_v1` and `arbs_stir_book_marks_v1`, so a second
process would have interleaved deletes with the first one's inserts — corruption that would not
have surfaced until the coverage report much later, and would have looked like a data gap rather
than a self-inflicted one.

A static log is not evidence of death either: a projection day takes minutes, and the file sat
unchanged for a full 20-second sample while the process was working normally. What settled it was
the process tree, not the log.

**What was actually lost is the wake-up path.** With the wrappers gone no task notification can
arrive, so a `Monitor` watching the log files directly is now the only signal. Its first version
immediately cried wolf on the benign `_FilteredWriteStream` teardown traceback (the one quieted in
`7c383320`) — so the filter now excludes that specific line while still emitting on
`day-errors: [1-9]`, driver errors, and, importantly, on the orchestrator disappearing before the
warm pass completes. A monitor that only reports success cannot distinguish a crash from a slow
chunk.

Saved to memory as `reference-background-task-orphans`, since the next long backfill in this repo
will meet the same trap.

#### Combined Jan+Feb, both months COMPLETE — the definitive preliminary G0 (2026-07-30 03:45)

February finished all three phases, so this supersedes the two single-month runs above.
Dataset verified first: `dealer_ladder_coverage.py --strict` exits 0 on 2026-01-12 → 2026-02-28 —
**33 sessions, 18,029 classified, 0.22% UNKNOWN, 99.8% projected, 100% marked per unit, 5,154 EOD
marks, single vintage `468474ca6f84`, zero anomalies.**

**1,320 sampled → 1,155 compared (87.5% coverage). Flip rate 34.9%.**

| | value |
|---|---|
| PAID share, our mid | **84.4%** |
| PAID share, independent mid | **55.4%** |
| mean / median mid offset | **−0.475 / −0.331 bp** |
| share \|offset\| > 0.25bp | **67.5%** |
| mechanism agreement | **97.8%** (403 TP, 25 FP, **0 FN**, 727 TN) |
| CURVE_CLEAN flip rate | 40.8% |
| **implied accuracy ceiling** | **79.6%** |
| attenuation at ceiling | 0.592 |

**The a = 0.8 row of the attenuation grid is now marginally ABOVE the measured ceiling** (0.796).
Not a reason to move the grid — it was fixed before any of this was measured, and moving it after
seeing G0 is the re-specification the lockout rule exists to prevent — but the top row must be read
as unreachable rather than optimistic, and the honest range is a = 0.6–0.7.

**Twenty-nine points of the PAID skew is the mid.** 84.4% under our curve, 55.4% under an
independent one, on the same 1,155 prints.

**`direction_confidence` is mildly ANTI-informative, and distance explains only part of it.**

| tier | n | flip rate | median \|s2m\| | flip rate within 0.2–0.8bp |
|---|---|---|---|---|
| HIGH | 588 | 40.0% | 0.442 bp | 41.9% |
| MEDIUM | 117 | 47.9% | 0.156 bp | 62.5% |
| LOW | 450 | 24.9% | 1.096 bp | 29.8% |

Part of this *is* the distance mechanism: MEDIUM sits closest to mid and flips most, LOW sits
furthest and flips least, exactly as a curve gap of fixed size predicts. But the ordering does not
recover when distance is held roughly constant — within the 0.2–0.8 bp band HIGH still flips 41.9%
against LOW's 29.8% at almost the same median distance. Spearman(tier rank, flipped) = **+0.141**,
i.e. the *higher* the stated confidence the *more* likely the independent mid disagrees. So the tier
cannot be used to select a cleaner stratum for this failure, and the temptation to do so — it is the
obvious move — has to be resisted explicitly.

#### `p_flip` is miscalibrated by an order of magnitude (2026-07-30 03:55)

The ladder's `expected` weighting is `1 − 2·p_flip`. Since the confidence *tier* turned out to be
mildly anti-informative and `p_flip` comes from the same model, the weighting was measured against
the independent mid rather than assumed. 750 of the 1,155 compared units carry a `p_flip` (64.9%).

**Mean `p_flip` = 0.041. Observed flip rate on the same rows = 0.416.** Off by a factor of ten.

| p_flip quintile | n | mean p_flip | observed flip rate | gap |
|---|---|---|---|---|
| ≈ 0 (2.5e−11) | 150 | 0.0000000000 | **0.360** | +0.360 |
| 5.4e−05 | 150 | 0.0000542 | 0.327 | +0.327 |
| 0.0026 | 150 | 0.0026 | 0.407 | +0.404 |
| 0.025 | 150 | 0.0255 | 0.513 | +0.488 |
| 0.175 | 150 | 0.1755 | 0.473 | +0.298 |

**Prints the model calls essentially certain — `p_flip` ≈ 2×10⁻¹¹ — disagree with an independent
mid 36% of the time.** Rank order is weakly right (Spearman +0.129), so `p_flip` does carry a
little signal; the failure is entirely in LEVEL, and the distinction decides what the weighting can
be used for. A quantity that orders error correctly but is ten times too small can rank prints; it
cannot correct them.

**So the `expected` weighting does almost nothing.** Mean weight 0.919, and it separates the prints
that actually agree (0.927) from the ones that flip (0.907) by **0.02**. It is a near-uniform 8%
haircut, not a correction for label error. That matters for reading the secondary grid: `expected`
and `unweighted` are not two hypotheses about how to handle classification uncertainty, they are
the same trade scaled by ~0.92, and neither addresses the 35–41% disagreement.

A caveat that must travel with this: `p_flip` may be modelling a different event — the chance the
classifier's own rule misfires given its inputs, rather than the chance our mid is on the wrong side
of an independent one. Those are different quantities. The honest statement is that `p_flip` is not
calibrated against independent-mid disagreement, and since that is the dominant label-error channel
we can actually measure, the weighting cannot be relied on to correct for it.

Now a permanent artifact (`g0_pflip_calibration`), computed every G0 run, reporting rank and level
separately so the two failure modes cannot be conflated.

### March classify returned rc=1 — two weekend days, and the pipeline did the right thing (04:43)

`canceling statement due to statement timeout` on the eligible-legs query against the remote
Supabase prod DB, for **2026-03-28 and 2026-03-29 — a Saturday and a Sunday**. The chunk finished
`31 days, 15421 units, 2 day-errors`.

Three things went right, and they are worth recording because each is a place this could have gone
quietly wrong instead:

1. **The vintage purge refused to run**: `purge SKIPPED: 2 day-errors in window -- rerun those days
   first`. Purging on a window it could not fully verify is exactly how a partial failure becomes a
   deleted month. Verified afterwards that nothing stale was left behind anyway — the March slice of
   `arbs_stir_direction_v1` holds 15,421 rows under a single vintage `468474ca6f84`.
2. **The orchestrator recorded the failure and carried on** rather than aborting the remaining four
   chunks on two non-trading days.
3. **The failure monitor fired once, with the actionable line** (`2 day-errors`) and no false
   positive from the benign teardown traceback — which is what the earlier filter rewrite was for.

**Why the two lost days do not matter, and how that is guaranteed rather than assumed.**
`data.trading_days` drives the decision grid, so a weekend never enters the study; and the coverage
report enumerates sessions from that same trading calendar and flags any with zero classified
units. So a weekend failure is invisible to the report *by construction*, and a trading-day failure
is caught *by construction*. No judgement call is needed at the point where one would be easy to
get wrong.

**The residual risk is a timeout landing on a trading day.** It is transient DB load, not something
about those dates, so it can. The remediation is already in place and needs no new code: after the
backfill, `dealer_ladder_coverage.py --strict` over the full window exits non-zero on any trading
session with zero classified units, and those specific days get re-run through
`backfill_stir_direction_range.py`. Deliberately NOT retried automatically mid-run — a retry loop
against a DB that is timing out is how a transient problem becomes a sustained one.

### Revised backfill ETA — ~16:30, not ~10:00 (06:15)

Measured per-chunk wall clock, end of one phase to the end of the next:

| month | units | classify | project | marks | chunk total |
|---|---|---|---|---|---|
| Jan (20d) | 7,632 | — | 45 | 1 | ~91 |
| Feb (28d) | 10,397 | 51 | 62 | 3 | **116** |
| Mar (31d) | 15,421 | 69 | 88 | 1 | **158** |

**Cost is linear in UNITS, not degrading**: 0.0112 min/unit for February, 0.0102 for March. The
slowdown is entirely volume growth — flow doubled from January to March — so the earlier ~80
min/chunk figure was an artefact of extrapolating from the two thinnest months. With four chunks
left at roughly 15k units each, the realistic finish is **~16:30**, about seven hours later than the
estimate quoted in the last two status notes. Correcting it here because a wrong ETA quietly
reshapes every decision about what to do while waiting.

Projection is now **4 min/trading-day** (88 min / 22 sessions), comfortably better than the 7.75
min/day measured before SERFF_BASIS was made opt-in, so nothing has regressed.

**Not speeding it up, deliberately.** The obvious lever is raising `DAY_JOBS`, and the obvious
second one is starting the decision-grid warm pass on the months already finished. Both spend the
same Barchart origin quota the backfill is spending: the warm needs ~60 requests per session
against a ~55-per-rolling-minute ceiling, so overlapping 49 warmed sessions with April's classify
would push both into `Retry-After` sleeps and conserve total time at best. The sequencing stays
backfill → warm → gates.

### The pre-registered rule is 80% one-sided, measured (06:25)

A question worth measuring rather than assuming, since the answer changes how G4 can be read.
The spec triggers on `|z| >= 1` but signs the position from the ladder **LEVEL**, because the
hypothesis is about the level. But 84% of prints are PAID and PAID means *negative* `delta_dv01`,
so the decayed level may be negative nearly everywhere — in which case the rule takes the same side
on almost every trade and the day-blocked t is measuring the window's rate drift.

Measured on the signed universe over Jan+Feb (prints only, no vendor): 33 sessions, 3,168 decision
minutes, 12 SR3 buckets, 32,256 finite cells.

- **94.6% of all (minute, bucket) cells have a NEGATIVE ladder level.**
- At the pre-registered `|z| >= 1.0`, **25.0% of cells trigger** (8,056 of 32,256).
- **Among triggers, 80.2% have level < 0** — so four trades in five take the short-rates side.
- `sign(level) != sign(z)` on **20.0%** of triggers, and the disagreement is entirely
  one-directional: `level < 0, z > 0` happens 1,610 times, `level > 0, z < 0` happens **zero**
  times. A positive level is rare enough that it is always far above the (negative) trailing mean.

And the imbalance is strongly increasing in maturity:

| bucket | triggers | share level < 0 |
|---|---|---|
| SFRH26 | 679 | 54.1% |
| SFRM26 | 624 | 66.5% |
| SFRU26 | 831 | 82.2% |
| SFRZ27 | 803 | 93.2% |
| SFRU28 | 493 | 94.9% |
| SFRZ28 | 668 | **97.3%** |

The front of the strip is near-balanced; the back is a constant short-rates bet.

**Two additions, because a number this one-sided must not be reportable without it.**
`evaluate_trades` now returns `share_long`, and the primary verdict states it inline. And
`constant_position_benchmark` re-prices the *same* entries, exits and costs with the position held
at +1 and at −1, so the rule can be read against what pure direction would have earned. If the
strategy does not beat the better constant, the ladder is contributing nothing beyond direction —
which is a conclusion the mean and the t alone cannot deliver.

**The pre-registration is NOT changed.** Signing from the level is what the hypothesis says, the
threshold and horizon are locked, and this is a diagnostic added alongside rather than a
re-specification. It also does not rescue anything: if G4 passes only because rates fell, the
benchmark will say so.

### Full-stage review of the gate code (07:10) — six more defects

Having found twelve in the adversarial pass and four in the reporting layer, every gate stage got
read line by line rather than trusted. Six more, in the order found. The pattern is by now
consistent: none was a crash, all had a green suite, and each was caught by asking "what would this
number have to be for the claim to hold" rather than by reading for correctness.

**D23 — the label-free cell built its intensity in the wrong space.** It used the configured SIGNAL
space while taking rates from the TARGET space. Whenever those differ — exactly the ZQ cross-check
stages added an hour earlier — the SR3 and ZQ bucket namespaces are disjoint, the reindex matched
nothing, and the cell would have reported "no trades". Indistinguishable from a real null, on the
ONE diagnostic that survives the labelling problem, which G0 had just made the most load-bearing
number in the study. It was also missing from the trial ledger despite being a tradable rule.

**D24 — conditioning splits could vanish.** A conditioner whose panel could not be read was dropped
by a bare `continue`. Every declared conditioner is now split or skipped-with-a-reason, with a test
asserting `split + skipped == declared`. Also documented what the table is NOT: the tercile
boundaries are full-sample, which is right for "does the effect survive in every vol regime" but is
not a tradable filter, and a reader lifting a strong stratum out as a trading rule would silently
add a fitted parameter to a locked spec.

**D25 — capacity counted volume traded before the position existed.** The volume panel is
right-closed, so the bar stamped at the entry minute covers the interval *ending* there. A `[entry,
exit]` slice therefore counted thirteen bars for a twelve-bar holding period: ~8% overstatement of a
headline number, in the optimistic direction, and the same class of error as the flow-response
event-bar bug one stage over. It also dropped unpriceable trades silently, so the median was taken
over a reduced subset.

**D26 — `horse_race` hid its own rank deficiency.** `pinv` absorbs a degenerate design and returns
standard errors that mean very little, and G3's whole verdict is "does the coefficient SURVIVE the
controls". The collinearity is plausible rather than hypothetical here: `basis_bp` and
`abs_basis_bp` coincide whenever the basis rarely changes sign. Rank, column count, condition number
and a `rank_deficient` flag are now on every row. (Checked the rest of that path and it holds: the
CGM correction omits only a 1.001 factor at this N, and normal-vs-t(103) moves the threshold by
0.02.)

**D27 — the placebo reference matched the primary only by coincidence.** All five placebos are read
as a distance FROM the reference, and the reference was recomputed with
`buckets=list(rates.columns)` while `load_context` had built the signal from the contract calendar.
Those sets diverge whenever a contract returned no bars, so a reference off by one bucket would
silently shift all five comparisons at once. It now takes the primary's result verbatim. Each row
also carries `share_long`, because the sign shuffle removes the PAID skew as well as the direction
signal — the shuffled rule is near-balanced while the real one is 80% one-sided, so part of any gap
is position balance, not lost information, and reading the whole gap as "direction was carrying it"
would be wrong.

**D28 — the SR3-vs-ZQ comparison was never assembled, and G2's threshold sat outside the locked
config.** Both spaces wrote their own tables and nothing combined them, even though the brief makes
this the comparison the mechanism turns on. Leaving a reader to hold two tables side by side and
infer the label is precisely where a preferred reading gets chosen, so the comparison now carries
its own interpretation — including the two outcomes easy to gloss: leading BOTH is undiscriminating
and must not be quoted as if it discriminated, leading NEITHER is no evidence at all. Separately,
G2's timing gate was a literal `3.0`, which put it OUTSIDE the configuration fingerprint the lockout
ledger records — so it could have been moved after seeing the holdout without the burn rule
noticing. It reads `config.primary.t_pass` now, with a test that the literal is gone.

**Running total: 22 defects, across three review rounds, in code that was green throughout.**

### First end-to-end run of the gate runner on real data (07:25)

The runner had accumulated a lot of change — bars cache, ZQ cross-check stages, primary threaded
into the placebos, ledger sink into the label-free cell — and had never once been executed against
the database. Ran it on five January sessions, writing to a scratch results directory, no `--lockout`.

**It found a defect no fixture test could have.** `independent_implied_contract_rates` masked stale
minutes with `.where(mask.to_numpy()[:, None])`, and pandas 2.3 rejects that with *"Array conditional
must be same shape as self"* because an `(N,1)` conditional will not broadcast to `(N,M)`. The
exception was swallowed by `load_context`'s guard around the independent source, which printed a
FAILED line and continued — so `ctx.indep_implied_bp` was simply absent and **G3b, the horse race
against a basis our own curve did not produce, would have run with no independent controls at all.**

That is the brief's headline G3 upgrade and the most likely benign explanation for any effect we
find, so having it quietly not exist would have been an expensive route to a wrong verdict. The
regression test uses a **two**-column frame deliberately: a single-column fixture cannot reproduce
this, since `(6,1)` broadcasts to `(6,1)` without complaint. That is precisely why every existing
test missed it.

**Zero trades, and that is NOT a bug.** `trailing_zscore` has `min_days=5`, documented: a session
with fewer than five complete trailing sessions yields NaN rather than a z-score fitted on almost
nothing. The smoke window held five sessions and four in-sample, so z was NaN throughout, nothing
triggered, and G3 correctly reported "no aligned observations". Checked rather than assumed, because
"zero trades" is exactly the symptom a real masking bug would also produce. A second smoke over
Jan 12 – Feb 27 (33 sessions) now runs to exercise the trading path properly; it also pre-warms 33
sessions of curves, so the work is not thrown away.

**Everything else ran, and the verdict text reads as designed.** `context loaded in 255s`, G0 on
1,150 signed units (flip rate 0.435 on a per-day-10 sample, consistent with the larger study), G1
PASS, G2 producing its full explanatory headline, the cross-check correctly reporting
*"leads NEITHER"*, and each downstream stage degrading to a stated N/A rather than an exception.

**A first, underpowered look at the mechanism.** On four sessions, SR3 LLS mean **−14.87** (t = −1.14)
— *negative*, meaning the ladder LAGS futures rather than leading — with mean peak rho **+0.046**
where hedging requires negative. ZQ likewise: LLS −16.2, peak rho −0.006. Four sessions is far too
little to conclude anything and this is recorded only so it cannot look like a surprise later. But
the direction of the early evidence is not favourable to the forced-hedge channel.

### April marks failed at STARTUP, and the fix must NOT be applied yet (07:50)

`marks rc=1`. Not a per-day failure — the phase died before touching a single day:

```
_stir_ladder_schema_v1.py line 51, in ensure_schema
    cur.execute(stmt)
psycopg2.errors.QueryCanceled: canceling statement due to statement timeout
```

`ensure_schema` re-asserts the idempotent DDL (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`) on **every phase invocation** — twenty-one times
across seven chunks — against a remote Supabase instance, and DDL takes locks. So there are
twenty-one chances to lose a whole phase to a lock wait on a schema that has existed since Phase A.
That is the actual defect; the timeout is just how it surfaced.

**April therefore has projections but NO EOD marks.** It does not touch the signal — the ladder
prints and futures prices are what the study trades on — but marks are part of the stated dataset
deliverable and the coverage report will show April at 0% marked.

**Why the obvious fix is wrong right now.** Making `ensure_schema` tolerant means editing
`_stir_ladder_schema_v1.py` or `backfill_stir_ladder.py`, and **both are in `VINTAGE_SOURCES`**. Any
edit changes the content hash from `468474ca6f84`, which would split the dataset across two vintages
mid-run and, worse, make every subsequent `--purge-stale-vintage` treat the first four months as
stale. A one-line robustness fix would cost a full re-classification of the window.

**Sequenced instead:**

1. Leave the code untouched. May, June and July keep running at `468474ca6f84`.
2. After the backfill finishes and DB contention drops, **re-run April marks with the unchanged
   code**, so the new rows carry the same vintage as the rest.
3. `dealer_ladder_coverage.py --strict` over the full window is the check that this actually closed —
   it exits non-zero on any trading session with zero marks, so the gap cannot be forgotten by being
   remembered.
4. Only then, as a follow-up for the NEXT backfill cycle, make `ensure_schema` check
   `information_schema` first and skip the DDL when the tables and columns already exist. Paired with
   adding `MDP/IRSwaps/IRSwapsMDP.py` to `VINTAGE_SOURCES` (see C1'), since both are vintage-changing
   edits and should land together, once, with a re-classification.

**Pending remediation list** (the thing that must survive an interruption):

- [ ] re-run April 2026 EOD marks at vintage `468474ca6f84`
- [ ] `coverage --strict` over 2026-01-12 → 2026-07-29 and re-run any trading session it flags
- [ ] deferred to next cycle: tolerant `ensure_schema` + `IRSwapsMDP.py` into `VINTAGE_SOURCES`

### My own read-only connection blocked the production backfill (07:55)

Two chunk phases died on `ensure_schema` DDL timeouts within ten minutes of each other, so instead of
guessing I asked the server. `pg_stat_activity` and `pg_locks` gave the answer immediately:

```
pid 1234908  idle in transaction  xact_age 00:35:51   AccessShareLock  arbs_stir_ladder_prints_v1
pid 1238422  active  wait Lock/relation  00:00:50     AccessExclusiveLock  NOT GRANTED
             ALTER TABLE arbs_stir_ladder_prints_v1 ADD COLUMN IF NOT EXISTS code_vintage TEXT
```

**PID 1234908 was my end-to-end smoke test.** `data.connect()` did not set autocommit, so psycopg2
opened a transaction on the first `SELECT` and held it — with `AccessShareLock` on every table
touched — for the life of the process, and the runner keeps one connection open for the whole run.
That read lock blocked the backfill's `ALTER TABLE` from taking its `AccessExclusiveLock`, the DDL
waited out the server's 2-minute `statement_timeout`, and the phase died. Twice.

Killed the smoke; the 35-minute session vanished and ungranted locks went to zero immediately.
`BT/dealer_ladder/data.py` is **not** in `VINTAGE_SOURCES`, so unlike the `ensure_schema` issue this
one was safe to fix mid-run: `connect()` now autocommits. A read-only consumer of a shared
production database must not be able to stall a writer, and the fix is one line — the cost was
entirely in not having thought about it.

**The lesson is about the diagnosis, not the bug.** The visible symptom was a DDL timeout inside the
backfill, which points at the backfill, the schema, and the remote instance — three plausible
suspects, none of them the cause. Nothing in the failing process's own logs could have identified a
lock held by a different process. Asking the database what was blocking took one query and ended it.

### The dataset has two holes, and they read as SUCCESS (07:56)

| month | direction rows | days | ladder rows | ENTRY marks | EOD marks |
|---|---|---|---|---|---|
| 2026-01 | 7,632 | 14 | 274,248 | 7,618 | 2,100 |
| 2026-02 | 10,397 | 19 | 373,392 | 10,372 | 3,054 |
| 2026-03 | 15,421 | 22 | 553,932 | 15,454 | 4,706 |
| 2026-04 | 10,016 | 22 | 359,388 | 9,916 | **0** |
| **2026-05** | **absent** | — | **absent** | — | — |
| 2026-06 | running | | | | |
| 2026-07 | 4,239 | 6 | 33,948 | 1,219 | 0 (chunk not yet run) |

**April lost only its EOD marks.** ENTRY marks are written by the *projection* phase, which
succeeded; only the marks phase died. So the gap is narrower than the `rc=1` suggested.

**May is entirely absent, and this is the part worth dwelling on.** Its classify failed, and then
`project rc=0` and `marks rc=0` — in thirteen seconds — because there was nothing to project or
mark. **An empty month exits zero.** Both my progress monitor and my failure monitor read that as
success: one echoes the script's `rc`, and the other greps chunk logs for day-errors and exception
lines, of which an empty run has none. This is exactly the silence-is-not-success failure, one level
up from where I had been guarding against it.

The only check that catches it is the one that enumerates sessions from the **trading calendar** and
demands each be populated — `dealer_ladder_coverage.py --strict`. That is now the gate before any
gate: the dataset is not complete until it exits zero over the full window.

**Pending remediation, updated:**

- [ ] **May 2026: the whole chunk** (classify → project → marks) at vintage `468474ca6f84`
- [ ] **April 2026: EOD marks only** (ENTRY marks are already correct)
- [ ] `coverage --strict` over 2026-01-12 → 2026-07-29; re-run every session it flags
- [ ] deferred to next cycle: tolerant `ensure_schema`, `IRSwapsMDP.py` into `VINTAGE_SOURCES`

### The monitor that was supposed to catch May would not have (08:05)

Having established that an empty month exits zero, I hardened the watcher — and then tested it
against the actual May logs rather than trusting it. **It still missed May, for two independent
reasons**, and both are worth recording because each is a general trap.

**The exception filter matched the wrong shape.** It looked for
`^Name(Error|Exception):`, which is what Python exceptions usually look like. May's classify died
with `psycopg2.errors.QueryCanceled` — a name ending in neither word — so a genuine crash produced
no event at all. The filter now extracts the **first unindented line after the indented traceback
body**, whatever the exception is called, which is structural rather than a guess at naming.

That correction had its own bug, caught the same way. Taking the *last* unindented line in the file
returned January's closing `range done: 20 days, 7632 units` — because normal output resumes after
the benign teardown traceback and kept overwriting the capture — so a perfectly healthy chunk would
have been reported as a FAILURE. Verified against every chunk log: silent on January, February, March
and April's healthy phases; catches May classify and April marks.

**The emptiness check tested presence rather than quantity.** May's project log contains 21
`projected 0/0` lines, so "does it have projected lines" passed. Emptiness has to be **measured** —
the totals are now summed, and a chunk that projected zero units or wrote zero EOD marks is reported
even though it exited 0 with a clean log.

Also added: a phase with **no `range done` at all** once a later phase has started, which is how a
death-at-startup looks from outside.

**The general point.** Twice now the monitoring has been the thing that failed, and in both cases the
fix came from running the filter against a log I already knew the answer for. A filter's job is to
distinguish states, and until it has been shown a known-bad and a known-good input it is an
assumption, not a check. The Monitor guidance puts it as *"if this crashed right now, would my filter
emit anything?"* — and here the honest answer was no, twice.

### Runbook for everything still outstanding (08:10)

Written down as an ordered sequence with a gate at each step, so the remaining work is executable
rather than reconstructed. Everything is **serial**: running two things at once against this database
is what cost May.

| # | step | how | ~time | gate before moving on |
|---|---|---|---|---|
| 1 | finish June + July chunks | already running (PID 110568) | ~3h | monitor silent; each chunk logs `range done` with non-zero units |
| 2 | decision-grid curve warm | fires automatically (PID 110760, chained on July's marks) | ~62 min | `done in ...` with `failed: 0`; 276 session-curves |
| 3 | close whatever is missing | `python scripts/dealer_ladder_remediate.py` (dry-run first) | ~150 min | its own `coverage --strict` exits 0 |
| 4 | the real gate run | `python scripts/run_dealer_ladder_gates.py --bars-cache <dir>` (**no** `--lockout`) | ~2h | `verdicts.csv` written; `render_findings_tables.py --check` exits 0 |
| 5 | read G0–G3 and G4-in-sample | against §7, which was written before any number existed | — | every gate's outcome recorded, pass or fail |
| 6 | the one-shot lockout | same runner **with** `--lockout` | ~10 min | `LOCKOUT_USED.json` written once; a second spec is refused by construction |
| 7 | execute the notebook | `nbconvert --execute` against the real results dir | ~2 min | 0 errors, figures rendered |
| 8 | assemble the findings | `render_findings_tables.py --inject` + `dealer_ladder_completeness.py --inject` | ~2 min | no UNEXPLAINED gap without a written reason |
| 9 | verdict + push | per spec 9c: (i) mechanism and edge survive, (ii) effect but no mechanism, (iii) no robust effect | — | journal current, everything pushed |

**Order of steps 2 and 3 matters and is deliberate.** The warm pass touches only CURVES, which are
independent of whether May's ladder rows exist — so warming all 138 sessions first and filling May's
data afterwards costs nothing and needs no re-warm. Both steps compete for the same Barchart quota,
so they do not overlap.

**Step 6 is the only irreversible one.** By the burn rule the holdout is evaluated once; the ledger
makes a second specification impossible rather than merely discouraged. It runs only after step 5 has
recorded the in-sample verdicts, so the lockout cannot inform them.

**If step 4 shows the primary with n = 0 trades**, check the z-score warmup before suspecting a bug:
`min_days = 5`, so the first five sessions of any window produce no signal by design. That symptom
already cost one investigation.

### 2026-06-09 — the timeout finally landed on a TRADING day (08:30)

June's classify finished `30 days, 14124 units, 1 day-errors`. The one failure was **2026-06-09, a
Tuesday**, lost to the same tape-query `DatabaseError` statement timeout that had previously only hit
weekend days. So the risk flagged when March failed — *"the residual risk is a timeout landing on a
trading day"* — has now materialised, and the reasoning that made March harmless does not apply.

June's vintage purge was also skipped for the same reason (`1 day-errors in window`), exactly as
March's was.

**This is what made the hardcoded remediation script wrong, twenty minutes after I wrote it.** It
named May and April's EOD marks, because those were the gaps I knew about. The set of gaps had
already moved. Rewritten to **discover** them: `scripts/dealer_ladder_remediate.py` asks the database
which trading sessions are incomplete, distinguishes the three kinds by which phase they need, and
uses the same query as its acceptance test.

Its dry run against the live database is also a demonstration that it reads reality rather than a
plan — 138 trading sessions, 83 incomplete: April's 22 days needing marks only, all 20 of May needing
classify, 2026-06-09 needing classify, and June/July showing project/marks because the orchestrator
has not reached them yet. That last group is precisely why the script **refuses to run while the
orchestrator is alive**: a month not yet attempted is indistinguishable from a month that failed, so
running early would "remediate" work that was never tried, while its `--rewrite` phases fought the
orchestrator for the same rows.

**Pending remediation is now a query, not a list.** Re-running the script is safe and idempotent
because it re-derives the gaps each time. The checklist earlier in this journal is superseded by it.

### July classify: 1 day-error, on a market holiday (10:15)

`range done: 29 days, 15484 units, 1 day-errors`. The failure is **2026-07-03**, which
`data.trading_days` excludes — Independence Day observed, the Friday before a Saturday 4th. So it is
harmless for the same reason March's two were and June's was **not**: the decision grid is built from
the trading calendar, so a non-trading day cannot enter the study, and the gap query in
`dealer_ladder_remediate.py` enumerates from that same calendar and will never list it.

Checked rather than assumed. The three timeout failures so far are 2026-03-28 (Sat), 2026-03-29
(Sun), 2026-06-09 (**Tue — a real gap**) and 2026-07-03 (holiday), and the only way to tell them
apart is to ask the calendar.

July's purge was skipped for the same day-errors reason as March's and June's. Harmless in all three
cases, verified for March by census; the full-window vintage census after remediation is the check
that closes it for all of them.

### Backfill done, curves warmed (11:30 → 13:04)

`BACKFILL DONE rc=1` at 11:30:14 — rc=1 reflecting the known phase failures, not a late surprise.
The chained warm pass then fired on its own and finished cleanly:

```
done in 89.4min: {'bulk_seeded': 26496, 'built': 0, 'reused': 0, 'failed': 0}
```

**26,496 decision-grid minutes seeded, zero single-point builds, zero failures.** That is the bulk
path doing exactly what it was built for: had these fallen through to the per-minute path, at ~24
Barchart requests each, it would have been ~636,000 requests against a ~55-per-minute ceiling.

**Two more self-inflicted checker bugs, both found by running the check.**

*The remediation guard could never pass.* `_orchestrator_running()` shelled out to PowerShell
matching command lines against `backfill_dealer_ladder_window` — and the PowerShell process running
that query has the string in its **own** command line, so it matched itself and reported the backfill
as running for ever. Filtered on `Name -eq 'bash.exe'` now; verified it aborts while the orchestrator
lives and passes once it exits. That is the fourth checking tool today to be the broken thing, after
the awk exception filter, the emptiness test, and the notebook audit regex.

*It re-ran whole months for a single day.* June needs only 2026-06-09; month granularity would have
re-classified and re-projected the other twenty sessions for about two and a half hours of nothing.
Ranges are now the span of missing days per month — safe because every phase is idempotent over a
range (classify upserts on `unit_key`, project and marks use `--rewrite`), **but the calibration
window still comes from the month**, so the single-day June re-run is calibrated with
2026-05-01..05-31 exactly as June's original chunk was. Narrowing the range without pinning the
calibration would have given the repaired day a different `p_flip` from its neighbours.

**Remediation running** (discovered, not hardcoded): classify May 05-01..05-29 and 06-09 alone;
project the same; marks for April, May, 06-09 and 07-24. Its own `coverage --strict` is the gate.

### The guard that aborted the run its own fix enabled (13:10)

Three versions of "is a conflicting writer running", the first two wrong for the same underlying
reason: **any process whose command line merely MENTIONS the target matches it.**

1. Matched the window-script name with no process-name filter — so the PowerShell process running
   the query matched *itself*, and the guard could never pass.
2. Added `Name -eq 'bash.exe'`. Then the shell **launching** this script matched, because the git
   commit message in that same command line quoted the string while describing bug (1). The guard
   aborted the very run that its own fix had enabled.

The second is the instructive one. It is not a typo or an oversight; it is the predictable
consequence of using a substring of a command line as a proxy for "a process is doing X". A shell
that *talks about* the backfill is not a backfill, and no amount of care in writing the pattern fixes
that — the pattern was correct, the instrument was wrong.

Version three matches the python processes that actually **write rows** (the backfill modules,
matched on the `-m` invocation). Those are unambiguous, and they are the thing that would genuinely
conflict. It is safe against self-match because it runs once at startup, before this script spawns
any phase of its own. Verified both ways: aborts while writers are alive, passes once they are gone.

Relaunched with a deliberately minimal command line, and the commit describing the fix was made in a
**separate** shell invocation so its text could not contaminate the launcher's command line — which
is a slightly absurd sentence to have to write, and exactly the point.

**Running tally of checking tools that were themselves the bug today: five.** The awk exception
filter (matched the wrong line), the emptiness test (tested presence not quantity), the notebook
audit regex (could not match uppercase), and this guard twice. Every one was found by running the
check against an input whose answer I already knew. None would have been found by reading it.

### Adversarial data-quality audit — response rule, written BEFORE the findings (13:45)

Six agents are attacking the dataset along independent surfaces (session/bucket completeness,
vintage provenance, referential integrity, value sanity, temporal integrity, distributional
continuity), each finding is then handed to a separate agent whose job is to **refute** it, and a
final critic is asked what nobody checked. The known-and-pending gaps are given to every agent up
front so they cannot spend effort rediscovering them.

**How I will respond is fixed now, before I know what they find.** Deciding afterwards is how an
inconvenient finding becomes "expected behaviour".

| severity | response — not negotiable after the fact |
|---|---|
| **blocks-the-study** | fix the data and re-run whatever depended on it, **before** the gate run. No gate result is reported on a dataset with an open finding at this level. |
| **biases-a-result** | fix if fixable at the current code vintage; if not, it becomes a stated limitation in §8 **with its measured magnitude**, and every affected gate result carries it. |
| **cosmetic** | record in the journal, do not fix, do not let it delay the run. |
| **refuted** | record the claim and the refutation both. A refuted finding is evidence the audit was adversarial, and hiding it would make the clean surfaces look unearned. |

Two commitments that matter more than the table.

**A clean surface only counts if it names its checks.** An agent reporting "no problems found"
without listing what it ran has told me nothing, and I will treat it as an un-audited surface rather
than a clean one.

**The critic's "what was not checked" is a finding in its own right.** If it names a plausible
failure nobody tested, that gap goes into §8 as a limitation even if I never get to test it. The
alternative — quietly enjoying six clean reports — is exactly the failure this whole engagement has
been guarding against.

**Sequencing.** The audit runs read-only and concurrently with the remediation. A watchdog is
alerting on ungranted locks and on any transaction held past seven minutes, because a held read lock
from a research connection is precisely what destroyed May, and there are now seven processes on
this database at once.

## THE LOCKOUT IS CONFOUNDED BY A DATA-REGIME CHANGE (17:20)

The adversarial audit returned seven `blocks-the-study` findings. Its verify phase was destroyed by
a session limit (17 of 25 agents died), so I verified the most consequential one myself with my own
queries. **It holds, and it changes what this study can claim.**

### The finding: the classification mid is displaced from 2026-05-07

2Y on-market OUTRIGHTs, median **signed** spread-to-mid — signed, because a widening of genuine
dealer spreads moves the ABSOLUTE value and leaves the signed median near zero:

| month | n | median signed | curve-suspect |
|---|---|---|---|
| 2026-01 | 801 | −0.322 bp | 16.5% |
| 2026-02 | 1,303 | −0.350 | 17.7% |
| 2026-03 | 2,050 | −0.321 | 14.0% |
| 2026-04 | 1,301 | −0.357 | 12.6% |
| **2026-05** | 1,301 | **−5.857** | **79.7%** |
| **2026-06** | 1,388 | **−8.153** | **79.5%** |
| 2026-07 | 1,562 | −0.719 | 43.4% |

A one-sided 6–8 bp median spread-to-mid in 2Y SOFR is not a market state. Daily resolution shows it
is **intermittent, not a step**: 05-07 (−1.01), 05-08 (−4.61), 05-11 (−0.22), 05-12 (+0.04),
05-14 (−5.25). Some sessions are fine and some are badly displaced, which is why no monthly average
caught it.

### Why it reaches the study even though the filter "works"

The universe excludes curve-suspect trades, so most displaced prints never enter. That is not a
rescue — it converts a pricing error into a **selection effect that tracks the calendar**:

| | Jan–Apr | May–Jun |
|---|---|---|
| curve-suspect share | 20–31% | 48–51% |
| signed share of all units | 40.3% | **27.1%** |
| signed units per session | 225 | **167 (−26%)** |

### The consequence, which is the real finding

**The lockout is 2026-06-10 → 07-29. Every one of its 34 sessions sits inside the degraded
regime.** The in-sample segment is 74% clean-regime. So the two halves of the pre-registered split
differ in **data quality**, not only in time, and three further audit findings land in the holdout
as well: the tape package grouping collapses on 2026-07-21 (7 lockout sessions, ~21% of it, where
multi-leg structures are torn into standalone OUTRIGHTs), 2026-07-24 is missing its entire US cash
session from the tape, and 2026-07-29 has 8 package units orphaned by a tape re-grouping.

A lockout failure would therefore be **uninterpretable**: indistinguishable between "the signal does
not generalise" and "the holdout is drawn from a different data-generating process". That is a
confound, and it is not one the burn rule contemplates.

### What I am doing about it, decided before any G4 number is read

1. The pre-registered primary **still runs on the full window**, unchanged. It is the locked spec.
2. **The confound is written down here and in §8 BEFORE the lockout is opened.**
3. The lockout **will still be opened**, once, as pre-registered. Declining to open it after finding
   a reason it might fail would be indistinguishable from avoiding a bad answer — the confound is
   stated first precisely so that the decision to open cannot be contaminated by the result.
4. A **data-regime split** (pre/post 2026-05-07) becomes a mandatory reported conditioning
   dimension, and the clean-regime subset (2026-01-12 → 2026-05-06, ~77 sessions) is reported
   alongside the full-window primary as the honest robustness check.
5. No verdict of type **(i)** — mechanism plus priced edge — can be issued from this dataset. The
   holdout cannot certify generalisation when it is not drawn from the same regime. The reachable
   verdicts are (ii) and (iii).

### Audit accounting

Seven `blocks-the-study` findings, cross-corroborated across independent surfaces: the 07-21 package
break was found by both the completeness and distributional auditors, and the 07-24 truncation by
both the completeness and temporal auditors. Independent agents converging on the same break from
different angles is much stronger evidence than one agent finding it twice.

**The audit was itself degraded and I will not pretend otherwise**: 17 of 25 agents died on a
session limit, so five of six surfaces never had their findings adversarially refuted, and the
completeness critic never ran. The findings above are therefore *auditor claims that I verified
personally*, not claims that survived independent refutation — except the VINTAGE_SOURCES one, which
did, and which its verifier correctly downgraded to "could-mislead" after establishing that only one
logging-only commit touched those modules inside the stamped window and no session straddles it.
