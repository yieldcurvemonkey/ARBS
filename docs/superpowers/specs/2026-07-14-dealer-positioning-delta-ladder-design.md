# Dealer Positioning Delta Risk Ladder — Design Spec

**Date:** 2026-07-14
**Scope:** Full framework — positioning ladder → synthetic dealer book MTM → level/gamma research → trigger/sizing/stop framework. Phased implementation; each phase gates the next.
**Status:** Draft
**Depends on:** `arbs_stir_direction_v1` (STIR dealer-direction classifier, merged PR #351, spec `2026-07-12-stir-dealer-direction-classifier-design.md`), `build_delta_risk_ladder` / `build_basis_risk_ladder` (`MDP/IRSwaps/BARCHART_STIRF/risk.py`).

---

## 1. Goal and thesis

Aggregate per-print inferred dealer direction into a single **dealer positioning delta ladder** — the aggregate dealer's net delta expressed as equivalent positions across the first 12 SFR (SR3) futures / first 8+ FF (ZQ) futures and across FOMC meeting buckets — for sub-3Y USD linear flow. On top of the ladder: identify rate levels where cumulative dealer re-hedge need becomes forcing (empirical gamma proxy + structural grid), and trade in front of the implied hedge flow with a full-reval stop/sizing framework.

Honest prior baked into the design: the positioning ladder (Phases 1–3) is a mechanically sound observable regardless of the trading thesis. The "forced hedging level" hypothesis (Phases 4–5) is the speculative layer — the event study in Phase 4 is the designed kill-switch. If post-visibility drift near levels does not survive costs, the framework stops there and reports that.

---

## 2. Architecture

```
arbs_stir_direction_v1  (existing; backfill extended to 6 months)
        ↓
LAYER 1: Projection            SDRUtils/stir_flow/ladder.py
  per print at its snapshot: build_delta_risk_ladder → signed dealer delta vectors
  → arbs_stir_ladder_prints_v1     (one row per print × bucket; absolute keys)
        ↓
LAYER 2: Reval / book MTM      SDRUtils/stir_flow/book.py
  synthetic single-dealer book = all open classified positions
  daily EOD standing marks + arbitrary intraday snapshots
  → arbs_stir_book_marks_v1        (persisted EOD; intraday on demand)
        ↓
LAYER 3: Ladder state          SDRUtils/stir_flow/ladder_state.py
  ladder(ts, half_life, weighting) = decayed·weighted·netted sum of Layer-1 vectors
  pure pandas — NO pricing in this layer
        ↓
RESEARCH/TRADING: BT/dealer_ladder/   (BT/serff subpackage conventions)
  gamma proxy, kinks + structural grid, event study, triggers, sizing, full-reval stops
```

Pricing happens exactly twice per position — once at projection, once per reval date — plus on-demand intraday snapshots. Every research parameter (half-life, confidence weighting, netting toggle, suspect handling) is a read-time transform over persisted vectors, so parameter sweeps never touch the pricer.

---

## 3. Inputs

### 3a. Prints

All rows of `arbs_stir_direction_v1` with `dealer_direction IN ('PAID', 'RECEIVED')` — every classified sub-3Y D2C print: FOMC, IMM, spot, forward, outrights, curves, flies. The solver projection maps any structure onto the same buckets; a 6M spot swap moves the same meeting forwards a meeting-dated swap does. No structure filter beyond what the classifier already applied.

**Venue whitelist (audit revision 2026-07-15).** The tape's `venue` is a heuristic: `classify_venue` labels six known IDB platform codes D2D and EVERYTHING ELSE — including missing/unknown platform IDs — D2C (`SDRUtils/analytics/flow.py:113`, `D2D_PLATFORMS` in `filters.py`). "D2C" is therefore a model label, not observed counterparty identity. The signed universe must use a **validated D2C platform whitelist** (derived empirically from distinct `platform_identifier` counts, validated against the SEF registry); unknown/missing platforms route to `VENUE_UNKNOWN` and are excluded from signed aggregation. All outputs are labelled "model-labelled D2C flow proxy," never "dealer inventory," until external truth labels exist (Section 9, gate G0).

### 3b. Unwind events

Tape rows with `economic_class = 'ECONOMIC_UNWIND'` whose lifecycle lineage (prior UTI / Original Dissemination Identifier chain, `xd_*` columns) resolves to an already-projected print. Used for netting (Section 6). Generic opposite-direction new prints are NOT treated as unwinds — they are new flow and offset naturally in the signed sum; netting them would double-count the dealer's own hedge when it prints D2C.

### 3c. Curves

Same curves and source as the classifier: SOFR → `USD-SOFR-1D-Q12xM12STIRT`, FED_FUNDS → `USD-OIS-Q12xM12STIRT-SERFFX-MIX23`, `IRSwapsMDP(source="BARCHART_STIRF-RL")`.

---

## 4. Layer 1 — Projection

For each input print, at its **classification snapshot** (t−1min curve, identical convention and timestamp as the classifier, so projection and direction share a curve):

1. Rebuild the trade package from tape legs (dates path: effective/maturity + notional + traded fixed rate).
2. Project the package onto **three risk models**:

| bucket_space | Risk model instruments | Bucket key (absolute) | Machinery |
|---|---|---|---|
| `MEETING` | `fomc_1 … fomc_12` tenor strings | meeting effective date, e.g. `2026-10-28` | `build_delta_risk_ladder` |
| `FUTURES` | `SFRCM1 … SFRCM12` STIRFutureQuery | contract symbol, e.g. `SR3Z26` | `build_delta_risk_ladder` |
| `SERFF_BASIS` | SER/FF months (FED_FUNDS prints only) | contract month, e.g. `2026-10` | `build_basis_risk_ladder` — splits pure-SOFR delta from SERFF-basis delta |

3. Extract per-bucket DV01 via `rl.Portfolio(pkg).delta(solver=risk_solver)`.
4. **Sign onto the dealer**: ladder sign = the aggregate dealer's net delta in futures-equivalent terms. Dealer `RECEIVED` fixed → dealer long duration → **positive** (long futures-equivalent). Dealer `PAID` → negative. Anticipated dealer hedge flow = **−ladder** (they sell what they're long).

**Absolute bucket keys, never rolling ranks.** `SFRCM1` re-resolves per as-of date; persisting rank-keyed vectors would smear buckets across roll dates. Persist by absolute contract / meeting date; CM-rank and `fomc_k` views are derived at read time.

**Solver batching:** one `build_delta_risk_ladder` per (curve_name, snapshot minute) group — the same batching the classifier uses. Risk-model solvers are cheap (< 100ms each, per the notebook) once the dense curve is cached.

### Table: `arbs_stir_ladder_prints_v1`

| Column | Type | Notes |
|---|---|---|
| `unit_key` | TEXT | FK to `arbs_stir_direction_v1.unit_key` |
| `bucket_space` | TEXT | `MEETING` / `FUTURES` / `SERFF_BASIS_SOFR` / `SERFF_BASIS_SPREAD` |
| `bucket_key` | TEXT | absolute meeting date / contract symbol / contract month |
| `delta_dv01` | NUMERIC | signed dealer delta ($/bp), + = dealer long futures-equivalent |
| `as_of_date` | DATE | |
| `execution_timestamp` | TIMESTAMPTZ | |
| `visibility_timestamp` | TIMESTAMPTZ | Section 8 — when the print became publicly knowable |
| `p_flip` | NUMERIC | copied from direction row |
| `direction_confidence` | TEXT | |
| `curve_suspect_trade` | BOOLEAN | |
| `is_block` | BOOLEAN | |
| `dv01` | NUMERIC | structure DV01 of the print |
| `projected_at` | TIMESTAMPTZ | |

PK `(unit_key, bucket_space, bucket_key)`. Indexes on `(bucket_space, bucket_key, visibility_timestamp)` and `(as_of_date)`.

---

## 5. Layer 2 — Reval / synthetic dealer book MTM

Treat all open classified prints as one aggregate dealer's swap book and mark it to market. The book's unrealized P&L is the *pain* proxy — hedging pressure is inventory size × how hard it is bleeding.

- **Open position at ts:** projected, EWMA weight > ε (default: within 3 half-lives of `visibility_timestamp`), and not lifecycle-unwound before ts.
- **Entry mark:** repriced NPV at the entry snapshot, signed to the dealer side (already computed for off-market prints by the classifier; computed at projection time for on-market prints — by construction ≈ ±spread_to_mid × PV01).
- **Standing EOD marks:** for each mark date, reprice every open position on the 5pm-ET curve → per-position NPV → persist.
- **Intraday snapshot API:**

```python
book_snapshot(ts, *, half_life, weighting, include_suspect=False) -> BookSnapshot
# e.g. ts = NY(2026, 7, 14, 8, 29)
```

Reprices the open book on the curve **at ts** (not t−1min — MTM wants the mark, not the dealer's decision-time curve) and returns: per-bucket positioning (from Layer 3), per-bucket and total **gross** P&L (full notional — the real swaps book), and **residual** P&L (EWMA-weighted — the presumed-unhedged remainder). Cached intraday curves make a snapshot minutes-fast. Snapshots may be persisted with a `snapshot_ts` key but are not required to be.

### Table: `arbs_stir_book_marks_v1`

| Column | Type | Notes |
|---|---|---|
| `unit_key` | TEXT | |
| `mark_ts` | TIMESTAMPTZ | 5pm ET for EOD rows; arbitrary for persisted intraday |
| `mark_kind` | TEXT | `EOD` / `INTRADAY` |
| `npv_usd` | NUMERIC | dealer-signed NPV at mark |
| `pnl_since_entry_usd` | NUMERIC | npv − entry mark |
| `curve_name` | TEXT | |
| `marked_at` | TIMESTAMPTZ | |

PK `(unit_key, mark_ts)`.

---

## 6. Layer 3 — Ladder state (pure query)

```
ladder(ts, hl, w) = Σ_prints visible by ts   w(print) · exp(−λ·(ts − visibility_ts)) · delta_vector(print)
                    − Σ lifecycle-linked unwinds before ts: reversal of the source print's
                      REMAINING decayed contribution at the unwind's visibility time

λ = ln(2)/hl;  separate hl for is_block vs non-block (calibrated, Section 9)
w(print) default = (1 − 2·p_flip)                 # expected-direction weight
                 × 0 if curve_suspect_trade        # excluded unless include_suspect=True
```

Everything is a parameter: half-lives, weighting scheme (expected-direction / tier weights / unweighted), suspect handling, netting toggle. The function is pure pandas over `arbs_stir_ladder_prints_v1` — instant re-evaluation across parameter grids.

Derived views: meeting-bucket ladder (signal space), futures-contract ladder + CM-rank view (execution space), SERFF-basis ladder (how much FF positioning is basis rather than outright SOFR delta).

---

## 7. Curve quality as first-class input

POC facts (07/10): `curve_suspect_trade` concentration sits exactly on the buckets this signal cares about — FOMC_OCT26 100% (8/8), FOMC_JUL26 55%, 2Y 51%. The notebook's OCT26/DEC26 example (custy steepen printed 10.2bp vs 7.0bp mid) is consistent with OCT26 node staleness.

- Default ladder excludes `curve_suspect_trade` prints; `include_suspect=True` override exists for sensitivity analysis.
- Bucket-day `curve_suspect` (DispJNS/DispVW gate from the tick table) is surfaced alongside ladder values so consumers see which buckets are degraded.
- Curve-node improvement is tracked as an upstream dependency: the DispJNS/DispVW ratio per bucket-day is the acceptance metric for any curve fix. Ladder quality inherits classifier mid quality; this spec does not fix the curve.

---

## 8. No-lookahead framework

Positioning backtests die of lookahead; these rules are load-bearing:

1. **Visibility timestamp per print (audit revision 2026-07-15).** The ladder at ts includes only prints publicly knowable by ts:
   - `visibility_ts = dissemination timestamp` from the raw SDR feed if the loader carries it (**verify at implementation** — DTCC disseminates it; whether the tape persists it must be checked, else it must be added or approximated);
   - fallback: the **legal delay class per 17 CFR Part 43 Appendix C**, derived from (platform-facility, cleared, block/cap flags) — NOT a two-bucket block rule: on-facility non-block `+1min` (ASATP); SEF/DCM block `+15min`; cleared large-notional off-facility `+15min`; uncleared dealer off-facility `+30min`; other/uncleared non-dealer `+60min`; indeterminate fields → the most conservative applicable class (`+60min`).
   A print must never appear in the ladder before the market could legally have seen it.
2. **Decision curve at decision time.** Signal evaluation and entry pricing use the curve at decision ts. Only MTM and stops use later curves.
3. **Walk-forward calibration.** EWMA half-lives, kink locations, z-score thresholds, trigger parameters: fit on trailing windows only (reuse `BT/serff/walkforward.py` conventions). The final ~6 weeks of the backfill are a temporal holdout untouched until final validation.
4. **Live-parity mode.** Production classification runs at a 15-minute delay; the backtester supports flooring ALL visibility at `execution_ts + 15min` as a conservative live-parity mode. Both modes reported side by side.

---

## 9. Phase 4 — Levels and empirical gamma (research layer, `BT/dealer_ladder/`)

### 9-0. Gate ordering (audit revision 2026-07-15 — supersedes any study order below)

Per the external feasibility audit (`docs/superpowers/audits/2026-07-15-sdr-dealer-positioning-feasibility-audit.md`), Phase 4 runs as ordered gates; price-prediction tests run LAST and only on what survives:

- **G0 Labels/provenance:** venue whitelist derivation (Section 3a); direction accuracy is UNCERTIFIED without external truth labels — the cheapest source is the desk's own tickets matched to their SDR prints (user action). Until then every result carries attenuation sensitivity (signed exposure scales by 2a−1; report a ∈ {0.6, 0.7, 0.8}) and the "model-labelled flow proxy" label. Off-market (NPV-vs-upfront) prints are a separately reported stratum — the rule imposes non-negative dealer edge by construction and cannot self-validate.
- **G1 Arrival integrity:** dissemination-timestamp probe of the raw feed; replay on actual arrival times where available, else legal delay classes (Section 8); all-+15min parity variant.
- **G2 Mechanism ordering (FIRST study, before any price test):** does the signed ladder *precede* measurable aggressive futures flow? Proxy signed aggressive flow from minutely Barchart futures volume + tick-direction. No flow-leads-flow evidence ⇒ the forced-hedge channel is unsupported and any price result is relabelled basis/flow continuation.
- **G3 Circularity battery:** matched-basis horse race (basis level/sign×DV01/|basis|, curve level/slope/curvature, recent returns, realized vol, liquidity, time-of-day, roll, FOMC indicators); independent fair value from the `SDR_INTRADAY-RL` swap-print-derived curves (futures-independent); leave-one-contract-out; residualized flow.
- **G4 Price prediction, pre-registered:** ONE locked primary spec (horizon, bucket space, strata, arrival convention, cost model, exposure rule) with raw t ≥ 3; the secondary variant grid judged by day-blocked bootstrap max-t / Romano-Wolf family-wise p < 0.05; a trial ledger including manual searches; the 6-week lockout's burn rule decided in advance.
- **G5 Economics:** costs use CME's actual tick structure — SR3 0.25bp/$6.25 applies only near expiry, deferred quarterlies trade 0.5bp/$12.50 (the `BT/serff/config.py` `tick_front`/`tick_back` split); capacity from historical depth, not daily volume.

Passing every gate supports a paper-traded pilot, not production.

### 9a. Candidate levels

- **Structural grid:** per meeting, implied-rate levels at 0/25/50/75/100% of a ±25bp policy move (via `SDRUtils/analytics/fomc.py` cut-probability utilities), plus round SFR price levels (0.25 / 0.125 increments).
- **Empirical kinks:** per bucket, local slope of Δladder vs Δrate binned in rate space; kink = statistically significant slope change (segmented regression / CUSUM) detected walk-forward. Kinks coinciding with grid points get elevated conviction; grid points with no empirical support stay dormant.

### 9b. Decay calibration

Event study over historical prints: post-`visibility_ts` drift of the mapped futures at 5/15/30/60min horizons, split block vs non-block → the drift decay horizon calibrates the EWMA half-lives used everywhere (Layer 3, sizing).

### 9c. The go/no-go event study

Episodes where rate approached a candidate level with |ladder z-score| above threshold: forward returns at 5/15/30/60min, split by ladder-sign agreement, block share, proximity, conditioning on liquidity regime (Amihud from the tick table). Net of costs using `SerffTradeConfig` conventions with the front/back tick split (SR3: 0.25bp/$6.25 near expiry only, 0.5bp/$12.50 deferred; ZQ/SR1: 0.5bp/$20.84; DV01 $25.0/$41.67 per contract) — an 8-leg deferred SR3 strip carries ~0.45-0.5bp round-trip quoted spread in DV01 terms before slippage. **If drift does not survive costs, Phase 5 does not ship** — the deliverable becomes the ladder observable plus a written negative result.

## 10. Phase 5 — Trigger / sizing / stops (trading layer)

Only built if Phase 4 passes.

- **Entry:** rate within δ of an active level AND ladder imbalance z-score (vs its own trailing distribution) beyond threshold AND trade direction = front-run the implied hedge (−ladder direction through the level). Optional confirmation filter: residual-book P&L bleeding at an accelerating rate (Layer 2).
- **Sizing:** participation fraction κ of the implied remaining hedge DV01 (`|residual ladder bucket| × κ`), hard-capped; expressed in SFR/FF contracts via the futures-space ladder.
- **Stops:** full-reval P&L via `book_snapshot`-style minutely reval of the trade (never DV01 × Δrate). Stop distance = f(local empirical gamma): tighter and smaller in high-gamma zones, wider or no-trade in flat-gamma stretches (no forcing function = no trade). Floors and modifiers: carry/roll to horizon sets the minimum stop distance (`CARRY_AND_ROLL_BPS_RUNNING`); stops tighten mechanically into the FOMC date as meeting swaps pin (post-blackout pin toward the realized increment).
- **Primary invalidation (thesis stop):** price trades through the level WITHOUT the ladder slope steepening as the gamma proxy predicted, or without confirming flow within N minutes of prints → exit regardless of P&L. Hard P&L stop remains as backstop for "right but early."

## 11. Backfill plan

1. **Classifier backfill:** run the existing `backfill_stir_direction` CLI per-day over 2026-01-12 → present (~125 trading days). Serialized; curve-cache-bound. Known failure modes (seasoned-leg fixings, curve_suspect) land as UNKNOWN/flagged per the classifier spec and are excluded/marked downstream.
2. **Projection backfill:** Layer 1 over all classified prints in the window.
3. **EOD marks backfill:** Layer 2 daily marks over the window (book size bounded by the 3-half-life ε cutoff).
4. **Research:** Phase 4 on the first ~4.5 months; final ~6 weeks held out.

Runtime expectation: dominated by classifier backfill (each day ≈ the 07/10 POC run); projection adds ~2 cheap solver builds per (curve, minute); EOD marks add one value-map call per open position per day.

## 12. Testing

- Layers 1/3: pure-function tests with synthetic prints — projection sign conventions (RECEIVED → +), additivity (curve print ≈ sum of leg outrights), absolute-key stability across roll dates, EWMA/netting arithmetic, no-lookahead filtering (a block print invisible before exec+15min).
- Layer 2: golden reval test on a known print (reuse classifier golden trades — book mark at a later known snapshot).
- `BT/dealer_ladder/`: walk-forward harness tests with synthetic ladder histories containing planted kinks; event-study machinery on synthetic drift.
- Fast gate unchanged: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`; pricer/DB tests marked.

## 13. Out of scope (this spec)

- Fixing the Q12xM12 curve nodes (tracked as upstream dependency; acceptance metric defined in Section 7).
- Imported-convexity source modeling (swaption OI, issuance calendars) — the empirical gamma proxy is deliberately agnostic to the convexity source; external convexity data is a future conditioning input.
- Dashboard/UI and a live 15-min ladder service — deferred until Phase 4 verdict.
- Options/swaptions in the traded instrument set.
