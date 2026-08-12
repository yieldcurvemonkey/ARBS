# Dealer direction inference on the USD swap SDR tape

## How to work on this

**Long-running task — expect days, not hours.** Keep a ledger, commit often, assume compaction.

**Work autonomously. You have full authority over design and implementation.** I am away and
cannot answer questions or approve anything. Where you would normally stop and ask: pick the
option you can best defend, write down why, continue. Prefer the interpretation that is easiest to
reverse when genuinely torn.

Do not stop to check in. Do not wait for approval before the expensive parts. **Never merge to
`main`** — open a PR and leave it.

---

## Scope

**This task is the direction feature and the risk ladder it produces. Nothing downstream.**

In scope: per-trade direction inference with calibrated confidence, the filters and lifecycle
handling that make it meaningful, and the aggregated signed key-rate DV01 ladder.

Explicitly **out** of scope, but stated because they determine the output contract: mapping the
ladder onto futures hedge buckets, inventory decay fitting, MBO footprint detection, the trading
signal, and any backtest. Build the ladder so that work can begin cleanly; do not start it.

---

## What this is and why the shape matters

The Part 43 tape gives you a printed swap with a rate, notionals, tenors and timestamps, and for
off-market trades an other-payment amount. It gives you **no counterparty and no side.** Direction
is inferred by repricing against the market as it stood just before execution and seeing which
side of mid the print landed.

The core rule, as the desk states it:

- **On-market** (no other-payment amount): reprice to get the curve's mid fixed rate at
  **execution timestamp − 1 minute**. If the **reported rate is higher than mid**, the dealer
  **received** fixed / customer **paid** fixed. And vice versa.
- **Off-market / PV**: reprice the swap. If the **NPV is higher than the reported other-payment
  amount**, the dealer **received** fixed / customer **paid** fixed. And vice versa.

Sign convention, because this is where implementations silently break and every downstream
consumer depends on it: *customer pays fixed → dealer received → dealer is long duration → the
pending hedge is selling futures.* Fix that convention once, write it at the top of the module,
and make every function agree with it.

**A hard sign at mid is the v0, not the target.** It misclassifies heavily near mid, which is
where most prints sit. The feature this is being built for needs a **probability**, not a side:

```
p(customer paid fixed) = σ((rate − mid) / τ)
```

with τ ≈ the rolling D2C half-spread for that tenor bucket, a dead zone under roughly 0.05–0.1 bp
where no call is made, and everything DV01-weighted. Downstream the per-trade `p` multiplies the
DV01 that enters the ladder, so a marginal call contributes proportionally rather than as a coin
flip. Calibrate τ from the data rather than picking it.

Also test the snap sensitivity: **T−1min is the stated rule, but measure T−5s and T−30s too.** If
the classification is materially different at 5 seconds, that is worth knowing before the ladder
is built on one arbitrary choice.

One further consideration worth taking seriously: **snapping mids from the same complex you would
hedge in** (SFR strip and futures-implied, for the front end) makes classification errors
hedge-consistent rather than independent. The Citi curves are the primary source and are now
excellent (below), but a front-end cross-check against the futures complex is cheap and worth
measuring.

---

## The off-market rule is under-determined — this needs care

The stated PV rule compares NPV against the other-payment amount. There is a wrinkle that makes it
not directly decidable: **the payer and receiver of the other payment are not disseminated.** You
see an amount, not who paid it.

The sound formulation is edge capture. Compute the fair upfront under **both** direction
hypotheses. Under the true one the observed fee should sit **dealer-favourable** of fair. Pick the
direction implying non-negative dealer edge, with confidence proportional to the asymmetry between
the two hypotheses — when they are nearly symmetric, you genuinely cannot tell, and the trade
should carry low confidence rather than a coin-flip side.

**Before you build this, look at what already exists.** The tape carries `opa_sign`,
`opa_signed_amount`, `opa_sign_confidence`, `opa_constrained_net` and `opa_ptp_residual`, and the
packages table carries `dealer_spread_est` / `dealer_spread_bps`. There is already an
other-payment sign solver with a confidence measure. Understand it before writing a second one —
it may be exactly this idea already implemented, or it may be solving an adjacent problem.

Watch **MAC and IMM standardised coupons**, which are off-market by construction rather than by
negotiation, and will otherwise pollute the off-market population. `is_mac` exists on the tape.

---

## Filters that decide whether the ladder means anything

Most of these already exist as enriched columns on the tape — **use them, do not re-derive them
from raw SDR fields.** `SDRUtils/CLAUDE.md` is explicit that aggregators must read the enrichment,
never re-parse `action_type` / `event_type`.

**D2D versus D2C.** IDB SEF prints (BGC, TP/i-Swap, Tradition) are dealers recycling risk among
themselves, not customer flow loading dealer inventory. Exclude them from customer-flow
accumulation — but **keep them as a separate observable series**, because "dealers are
distributing risk" is itself informative. `platform_identifier` and `venue` carry this;
`SDRUtils/stir_flow/config.py` already has a conservative `D2C_PLATFORM_WHITELIST` (`TWSF`,
`BBSF`, `BILT`) and a `D2D_PLATFORMS` set, with unvalidated platforms deliberately falling to
`VENUE_UNKNOWN` rather than being assumed D2C. Extend that whitelist deliberately, with evidence.

**Prime-brokerage mirror pairs** double-count every PB trade if not deduped.

**Compression** is directionally meaningless portfolio maintenance. `is_compression`,
`is_compression_spec` and `economic_class` already classify it; `contributes_to_flow` is the gate
the repo intends aggregators to use.

**Invoice spreads** print as packages priced as spreads. Bucket them separately — they are usually
dealer RV, not customer flow. `is_spreadover`, `is_asset_swap`, `special_tenor_type` and
`matched_ust_maturity` are all populated.

**Capped notionals are right-censoring on exactly the trades you care most about.** Blocks print at
the §43.4 cap with fields proportionally scaled, so the largest and most informative prints are
the ones whose size you cannot read. Fit a lognormal or Pareto tail per tenor bucket from the
sub-cap prints and impute `E[DV01 | capped]`, flagged rather than silently substituted.
`is_capped`, `is_notional_capped`, `notional_source` and `is_block` exist.

---

## Lifecycle: unwinds are signal, not noise

Build a stateful store keyed on **Dissemination ID**, with **Original Dissemination ID** linking
lifecycle events back to the original print. This matters because an unwind — a `TERM`/`ETRM`, or
a `MODI` with amendment and a notional cut — is a customer *exiting*, which is risk transfer in
the **opposite** direction to the original inferred side. With the D2 link you can **flip the
original guess rather than discard the event.**

`EROR` busts remove inventory. `CORR` applies forward-only.

The repo already has much of this: `lifecycle_type`, `lc_*` columns (including
`lc_was_partially_terminated`, `lc_has_partial_unwind`, `lc_inception_notional`,
`lc_current_notional`), the `xd_*` cross-day family, `d2_missing`, and `rc_timeline_json`.
`SDRUtils/stir_flow/unwinds.py` exists but its own docstring records that a 2026-07-14 lineage
probe found no lineage columns and `extract_unwind_events` returned an empty frame — **check
whether that is still true before building on it.** The v3 tape has since been rebuilt with full
enrichment, so that finding may be stale.

---

## Two clocks — do not conflate them

This is the single most dangerous modelling error available here.

- **Direction inference** uses the **execution timestamp**, minus one minute. That is the market
  state when the trade was actually struck, and it is what makes the mid comparison meaningful.
- **Signal availability** uses the **dissemination / event timestamp**. You could not have known
  about the trade until it was published. Any aggregation, any ladder state, any downstream
  research must be stamped on the clock at which the information became public.

Using execution time for availability is lookahead. The tape already carries both, plus the delta:
`execution_timestamp` (#96), `event_timestamp` (#30), `report_lag_seconds`,
`original_execution_timestamp`, `alpha_lag_seconds` and `late_report`. `SDRUtils/CLAUDE.md` states
the rule directly: bucket economic volume on execution/original-execution time, and treat event
time and the deltas as transparency columns — but for *availability* the event clock is the
correct one.

**Measure the report-lag distribution split by block flag** and carry it forward. Blocks arrive
delayed, by which point the dealer has partially hedged, so a block print and an ASAP print of the
same size are not the same event and should not be pooled.

---

## Packages — infer direction at the package level, never per leg

The tape is not a stream of outrights. It carries curves, flies, `PKG-N` with arbitrary leg
counts, spreadovers, matched-maturity, invoice swaps, MAC, compression lists, and PTP-grouped
structures where one package price covers many legs. The v3 backfill produced packages with **17
legs across 13 tenors**, and PTP grouping is present on about 54% of legs.

**Direction must be inferred from net package DV01.** A package has one price, not one price per
leg; an individual leg's reported rate may be nowhere near that leg's own mid because the
*package* is on-market, not the leg. Classifying leg-by-leg and voting produces confident nonsense
on curves and flies, and generates offsetting garbage in the ladder.

Existing machinery to build on rather than replace: `classifier.py::structure_dv01` already knows
a fly's risk is not the sum of three absolute PV01s. `config.py::PTP_USD_FLOOR = 500.0` exists
because sub-floor package prices are notation artefacts rather than dollars, and
`PTP_UFRO_DISAGREE_RATIO` catches upfront and PTP disagreeing by more than 2×.

`config.py::EXCLUDED_TRADE_TYPES` currently drops MAC, SPREADOVER\*, MATCHED_MATURITY\* and
INVOICE\*. Each exclusion had a reason. Some of those reasons mean the direction *question* is
different rather than merely harder — a spreadover's direction is about the spread, not the swap
rate. Revisit them one at a time and decide deliberately; do not blanket-include.

---

## Output contract — what the ladder must expose

The consumer builds an aggregated dealer delta risk ladder and later maps it onto futures. That
imposes requirements the current scalar-DV01 classifier does not meet:

- **Signed key-rate DV01 profile per trade**, not a single DV01. The mapping onto
  `{FF, SFR strip, TU, FV, TY, UXY, US}` needs a KRD vector; a scalar cannot be projected.
- **Per-trade confidence `p`**, so the consumer can DV01-weight by it.
- **Both timestamps** on every row — execution (for the pricing) and event (for availability).
- **Forward-start handling.** IMM and forward-starting trades map cleanly if the effective date is
  respected; `effective_date`, `forward_start_years` and `forward_bucket` exist.
- **The D2D series kept separately**, not merged into customer flow.
- **Provenance per row**: which curve, which snapshot timestamp, what lag was realised, whether
  the notional was imputed, whether the direction came from the rate rule or the upfront rule.
  Without this the consumer cannot gate on quality, and you cannot debug a ladder that looks wrong.

Long-end mapping (20–30y) is messy across US/WN — a coarse long-end bucket is acceptable, but say
so explicitly rather than implying precision you do not have.

---

## Health monitoring — build this early, not at the end

The whole ladder is garbage if the mid drifts off venue. Build a **rolling hit-rate of inferred
direction against subsequent D2D prints**, and treat a degradation as a reason to flatten rather
than a curiosity. This is cheap to add while you are building and very expensive to retrofit.

Also track: fraction of trades in the dead zone, fraction with imputed notional, fraction of legs
whose curve snapshot came from the overnight hole, and the realised-lag distribution.

---

## Curve data — this was the blocker and it is now solved

A dedicated prep task measured and repaired the minute curves. **All of it is merged to `main`**
(PRs #426, #432, #434, #435). Do not re-solve these problems.

### Coverage

| asset | days | span |
|---|---|---|
| `USD-SOFR-1D-CITIVELOEXCELMIN` | 1,535 | 2021-09-14 → 2026-08-10 |
| `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` | 2,708 | 2017-12-05 → 2026-08-07 |

Both now deeply predate the tape (2024-03-01). The Fed Funds shallowness that earlier drafts
treated as the main constraint is gone — Fed Funds is now the *deeper* of the two. Read the local
`CurveStore.default()`, not Supabase, which lags.

### Use the policy API; do not hand-roll the lookup

`MDP/IRSwaps/CITIVELO_EXCEL/snapshot_policy.py` — `SnapshotPolicy` with `method`, `max_lag`,
`allow_future`, `on_miss`; `.strict(...)`, `.legacy()`, `.describe()`, and a `SnapshotMiss`
exception. Defaults reproduce legacy behaviour so valuation callers are unaffected; **strict is
opt-in and strict is what you want.** A backward-only lookup guarantees you never price against a
post-trade curve, which would be circular.

`SDRUtils/stir_flow/pricing.py::CurvePricer` takes `curve_kwargs`, fixed per instance and passed
to `_get_curve`. That is deliberate — `_handles` is keyed on `(curve_name, ts)`, so a per-call
policy would let one caller's terms be silently reused for another's request for the same minute.
Use the public `build()` if you pre-populate the cache.

### The session, measured

`MDP/IRSwaps/CITIVELO_EXCEL/citi_session.py` — `publishes()`, `expected_minutes()`,
`is_truncated()`. Mon–Thu the session runs **01:00 → 22:59 ET**, anchored in New York; the Friday
close and Sunday open are anchored in **UTC** (21:59 and 21:00). The week runs on a UTC clock, the
day on a New York one.

**Citi publishes nothing between 23:00 and 00:59 ET.** Every leg printed in the 00:xx ET hour is
unclassifiable at minute resolution, permanently. The desk has accepted serving the last preceding
curve there, and that was priced: 0.24–0.29 bp median, ≤1.43 bp max, roughly 3× cheaper than an
equivalent 120-minute stretch of the trading day, and stale rather than circular.

**Do not implement that acceptance as a global `max_lag=2h`** — that also admits two-hour
staleness at 10:00 on a Tuesday, worth 2.63 bp p90. Branch on `citi_session.publishes()`: strict
inside the session, a bounded 2 h `asof` outside it.

The **00:01 ET midnight trap is fixed** (PR #432) — `snap_timestamp` floors-and-decrements into
exactly midnight, which sources overloading that value read as *end-of-day*, resolving to that
day's close ~16 h **after** the print. `as_intraday_instant` / `is_ambiguous_midnight` now handle
it and `CurvePricer.build` refuses an ambiguous midnight. Do not undo this.

`MDP/IRSwaps/CITIVELO_EXCEL/density.py` — `day_density()`, `.is_dense()`, `.covers(instant, ...)`.
Use `covers()` to ask whether a *specific instant* is supported rather than inferring from a
day-level count.

The measurement report is `docs/2026-08-09-citivelo-minute-curve-fidelity.md`; remaining known
damage is enumerated per-day with causes in `docs/2026-08-10-citivelo-minute-repair-list.csv`.

### Convention fidelity

Recently rebuilt curves report max reprice error **0.0023–0.0030 bp**. An older tie-out citing
1.6–6.1 bp predates that work. Still measure the bias on the curves you rely on: direction
inference is far more bias-sensitive than valuation, because most prints land within a basis point
or two of mid — a systematic bias inverts calls rather than degrading them.

---

## Where the existing code is

```
SDRUtils/stir_flow/
  classifier.py       <- classify_unit; the current hard-sign rules. Read first.
  pricing.py          <- CurvePricer, snap_timestamp, as_intraday_instant
  config.py           <- CURVE_SOURCE, CURVE_FOR, D2C whitelist, exclusions, SUB3Y_HORIZON_DAYS
  confidence.py       <- existing confidence / flip-probability scoring
  trade_selection.py  <- signed-universe membership, venue status
  ladder.py, book.py, unwinds.py, vintage.py, curve_warm.py, tick_size.py
SDRUtils/_swappulse_scripts/backfill_stir_direction{,_range}.py
SDRUtils/_swappulse_scripts/_stir_direction_golden.py   <- golden regression fixtures
BT/dealer_ladder/                                        <- existing research layer
```

`config.py::CURVE_SOURCE = "BARCHART_STIRF-RL"` with `CURVE_FOR` pointing at Q12xM12STIRT and the
SERFF/MIX23 blend is the seam being replaced by the Citi curves. `SUB3Y_HORIZON_DAYS = 1105` is
the current ~3y maturity cutoff — extending across the whole curve means removing it, but
understand why it was set: the short end was chosen partly because STIR futures give a clean,
tick-quantised reference there, and the long end will not behave the same way. Your confidence
model probably has to change with the horizon.

**Tie out against the existing classifier on the trades it already covers.** A prior investigation
concluded it is correct — an apparent "wrong directions" bug was a charting artefact, SOFR trades
plotted against the Fed Funds line. If your generalised version disagrees with it on a short-end
SOFR trade, yours is probably wrong. Build that tie-out early; it is the best regression test
available.

The tape is on `arbs_usd_swap_tape_*_v3`. Import table names from
`SDRUtils/_swappulse_scripts/_tape_tables.py`; never hardcode a suffix.

---

## Environment

- Python `C:\Users\chris\anaconda3\envs\stir\python.exe`, invoked **directly**. Never `conda run`
  — parallel invocations collide on a temp file and return empty output with exit code 0, which
  looks exactly like a passing test run.
- `ARBS_SUPABASE_ENABLED=0` before anything importing `Caching`.
- Work in a **new git worktree**, short sibling path, never the primary checkout. Always
  `git -C <path> ...`.
- Fast gate: `python -m pytest tests -m "not slow and not network and not db"` (~30 min, ~5,400
  tests). Verify any "pre-existing failure" claim against `main` in a clean worktree.
- The tape DB is remote production Supabase. Reads are cheap; a backfill deletes and rewrites a
  whole `as_of` day.

---

## Method notes — all from real failures in this repo

**Validate a measurement tool against a known-good case before trusting it.** A probe here once
called production's own fetcher and concluded a day was unreachable; it fetched only day D while
production fetches D **plus D+1 forward**. Two agents ran it and both confirmed the wrong answer.
Reusing production's functions is not enough — the call must reproduce production's parameters.

**Exit code 0 is not success.** `cmd | tail` then `$?` is `tail`'s status. That produced a fake
pass twice in one session.

**A job reporting "done" is not evidence it did anything.** A backfill recorded days `ok` on exit
code 0 when the upstream returned an empty frame, destroying six days before it was caught.

**When you relax a threshold or add an exemption, get it checked by something other than
yourself.** Twice recently an independent pass corrected my reasoning or disproved my evidence.
Choosing τ and the dead-zone width is exactly that kind of decision.

**Prefer a test that fails before the fix.**

---

## What "done" looks like

- A PR, not merged, with the design and the options rejected.
- The direction feature producing per-trade `p`, signed KRD, both clocks and full provenance.
- The aggregated ladder, with D2D kept separate.
- A tie-out against the existing short-end classifier, disagreements enumerated and explained.
- A short written note on what the ladder can and cannot support — where confidence is low, which
  package types are excluded and why, what fraction of DV01 is imputed from capped prints. The
  consumer needs to know where not to trust it as much as where to.
- Anything unfinished, stated as such.
