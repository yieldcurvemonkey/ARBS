# CME MBO Analytics Suite — Design

**Date:** 2026-08-08
**Branch:** `feat/cme-mbo-analytics-suite` (worktree `C:\Users\chris\clee\ARBS-mbos`)
**Supersedes in scope:** `2026-08-07-sr3-mbo-explorer-design.md` (one product, one day). That engine is
kept and extended, not replaced.

## Motivation

`RVUtils/MBO` today is a validated single-day SR3 explorer. It established one result that matters —
the exchange-listed butterfly is quoted **0.506 bp** round trip against the 2.0 bp every backtest in
this repo charges — and it did so on a single session, on one product, with every unit constant
hard-wired to SR3.

There is now 64 GB of GLBX MDP3 MBO on `D:\`: 53 sessions of SR3 and 79 sessions each of the six
Treasury futures. The consumer is **SDR microstructure research — lead-lag and swap-dealer hedging
activity** — which runs as a separate workflow and needs this suite to hand it aligned, trustworthy,
book-resolution panels plus the execution primitives (queue position, iceberg detection, fill
probability) that say whether an observed footprint is real.

So the deliverable is not another finding. It is an engine that is correct across products, correct
across days, and cheap enough per question that the research is not rationed by compute.

## Dataset

Measured by probing every archive (`metadata.mappings` resolves from the parent symbol, so a 0.4 MB
holiday session enumerates the whole listed universe without decoding a full day).

| Product | Sessions | Span | zst | Mapped instruments |
| --- | ---: | --- | ---: | ---: |
| SR3 | 53 | 2026-06-07 → 2026-08-06 | 50.4 GB | 1,188 |
| ZT | 79 | 2026-05-07 → 2026-08-06 | 3.5 GB | 11 |
| ZF | 79 | 2026-05-07 → 2026-08-06 | 3.7 GB | 11 |
| ZN | 79 | 2026-05-07 → 2026-08-06 | 4.7 GB | 11 |
| TN | 79 | 2026-05-07 → 2026-08-06 | 2.7 GB | 9 |
| ZB | 79 | 2026-05-07 → 2026-08-06 | 2.0 GB | 7 |
| UB | 79 | 2026-05-07 → 2026-08-06 | 1.8 GB | 8 |

Every archive is `GLBX.MDP3`, schema `mbo`, **DBN version 3**, `stype_in=parent`,
`stype_out=instrument_id`. The 2026-07-15 file the previous work used was DBN v1; the MBO record
layout is byte-identical between the two, which was checked rather than assumed.

Host: 64 GB RAM, 32 logical cores, `D:` 401 GB free (`C:` has 28 GB free and is not an option).

### Three facts that break the current code

Found by probing, not by reading:

1. **`ZNU6` — the most active instrument in the entire dataset — does not replay.** 6.76 M of that
   session's 7.08 M records are `ZNU6`, and `build_price_grid` raises: the dense ladder would need
   6,977,921 slots. The cause is 57 records (8.4e-6 of the instrument) at ten far-from-market prices —
   one ask at **109,080.00**, stub bids at 50.00 to 88.1875. The live book occupies ~900 ticks and the
   traded range 58.
2. **Every unit constant in `metrics.py` is SR3's.** `USD_PER_BP_PER_LOT = 25`, `BP_PER_POINT = 100`,
   `IMM_TICK_VALUE_USD = 12.50`, and the `tick_float >= 0.1` heuristic that infers bp-per-unit. On the
   probe, `ZNU6-ZNZ6` came back `bp_per_unit = 100.0`, which is not a wrong number so much as a
   meaningless one — a Treasury calendar spread has no bp without a DV01.
3. **The cache collides across days.** `MboSource` writes `inst_{instrument_id}.parquet` into one flat
   directory, and `instrument_id` is not stable across sessions. Two days in one cache silently mix.

A fourth, from the vendor rather than the data: **Databento omits `MDOrderPriority` from normalized
MBO** because it is CME-specific, noting that `ts_event` serves the same purpose except for interest
rate options and instruments with an LMM. Queue position is therefore *reconstructed*, and CME states
that "PriorityID may change if order modified or refreshed". That makes the queue model an inference
carrying a falsifiable test, not a field lookup. See §7.

## Architecture

One package, internal boundaries by sub-package. One import root, one symbol parser, one kernel
family; the validated kernel is extended, never forked.

```
RVUtils/MBO/
  products.py        ProductSpec registry: units, ticks, $ per tick, match algorithm, grammar
  symbols/
    __init__.py      dispatcher: root -> grammar
    _sr3.py          today's parser, behaviour unchanged
    _ust.py          Treasury futures grammar
  book.py            existing L3 kernel + banded ladder and overflow map
  lifecycle.py       second kernel: per-order events, queue rank, fills
  source.py          zip archive index, per-(product, date) source, namespaced cache
  store/
    schema.py        column definitions and file-level metadata, one place
    writer.py        replay -> parquet, per (product, date, kind)
    manifest.py      append-only build log, resume, engine versioning
    reader.py        dataset reads with symbol/row-group pruning
    panel.py         aligned multi-product panels: grid and async
    risk.py          CTD / conversion factor / DV01 per (product, date)
  analytics/
    liquidity.py     spread, depth curve, slope, resilience
    flow.py          signed flow, OFI, MLOFI, trade-sign autocorrelation
    impact.py        effective/realised spread, impact vs size, Kyle lambda
    queue.py         order lifetime, cancel/trade, rank at entry and fill, fill probability
    icebergs.py      native and synthetic detection, Kaplan-Meier size estimation
    leadlag.py       Hayashi-Yoshida, OFI cross-correlation, Hasbrouck, Gonzalo-Granger
  sim/
    queue_model.py   queue-position models
    latency.py       latency models
    simulator.py     would this resting order have filled
  build.py           CLI: python -m RVUtils.MBO.build
  plots.py           charts, on the validated palette
```

Analytics are **pure functions over the store**. Nothing in `analytics/` opens a DBN file. That is what
lets P2–P5 be built and tested independently once P1 lands, and it is what makes a study cheap to
re-run.

## 1. Product model

```python
@dataclass(frozen=True)
class ProductSpec:
    root: str                              # "SR3", "ZN", "UB"
    grammar: str                           # "sr3" | "ust"
    quote: str                             # "index_points" | "points_32nds"
    contract_unit: float                   # notional
    outright_tick: Fraction                # exact fraction, not a float
    outright_tick_front: Fraction | None   # several USTs tick finer in the lead month
    usd_per_tick: float
    spread_tick: Mapping[str, Fraction]    # per kind
    match_algo: str                        # FIFO | PRORATA | SPLIT | ... — gates the queue model
    usd_per_bp_per_lot: float | None       # 25.0 for SR3; None for USTs
```

**Canonical units are ticks, price points and USD.** SR3 is a rate contract and $25/bp is intrinsic to
it; a Treasury future is a price contract whose bp needs the CTD DV01. Yield-bp is therefore a
*conversion*, applied at the analytics layer (§4.4), never an assumption baked into a price column.

The existing two-signal check generalises and is kept: the tick inferred from the prices an instrument
actually printed (gcd of offsets) must agree with the `ProductSpec` tick, and **a disagreement raises**.
The symbol string and the printed prices are independent sources; when they disagree one of them is
wrong and guessing is how a 100× error gets in silently.

Exact tick and dollar values are in `products.py`, sourced from CME contract specifications, with the
front-month/deferred distinction preserved where it exists. Flattening that distinction would misprice
the most active contract on every Treasury root.

## 2. Symbology

Dispatch on the root, then a per-family grammar. `_sr3.py` is today's parser with its behaviour
unchanged — the 1,188-symbol SR3 universe is the complicated one and it is already correct.

`_ust.py` is new. The grammar is what the archives actually contain:

| Form | Example | Kind | Weights |
| --- | --- | --- | --- |
| `<ROOT><M><Y>` | `ZNU6` | `OUTRIGHT` | (1,) |
| `<A>-<B>`, same root | `ZNU6-ZNZ6` | `CALENDAR` | (1, −1) |
| `<ROOT>:BF a-b-c` | `ZN:BF M6-U6-Z6` | `BUTTERFLY` | (1, −2, 1) |
| `<A>-<B>`, cross root | `TNU6-MTNU6`, `UBU6-MWNU6` | `INTERCOMMODITY` | modelled, legs across roots |

There are no packs, bundles or condors on the Treasury roots. `INTERCOMMODITY` here is a full-size
against its micro (`MTN`, `MWN`), which unlike SR3's unmodelled inter-commodity spreads *is*
synthesisable, so its legs are populated.

An unrecognised root yields `kind="OTHER"` with empty legs. Never a crash: an unparseable symbol must
not be able to stop a 79-day build.

## 3. Book kernel: banded ladder and overflow

The dense ladder is the right structure — it is what makes best-bid maintenance O(1) amortised — and
it needs a bound.

- The ladder covers a **band** `[band_lo, band_hi]` derived from a robust quantile of the instrument's
  live prices (cover 0.9999), then widened to at least ±200 ticks and to contain the full traded
  range. Capped at `MAX_PRICE_SLOTS`.
- An order priced outside the band goes to an **overflow map** keyed by order id holding side, price
  and size, so that a later `C` or `M` on it stays exact. Overflow orders never enter the level arrays.
- **Asserted at every emission:** `max(overflow bid price) < band_lo` and
  `min(overflow ask price) > band_hi`. A violation raises and names the price.

That assertion is the whole design. It converts "an out-of-band order was never at the touch" from a
hope about how the band was chosen into a checked invariant. Choosing the band well is an efficiency
question; the assertion is the correctness one.

When every price fits the band — which is every SR3 instrument seen so far — behaviour is bit-identical
to today, and the existing 30 known-answer tests are the regression gate.

## 4. Store

Root `D:/mbo_store`, overridable by `ARBS_MBO_STORE`. Outside every worktree, so a
`git worktree remove` cannot destroy a multi-hour build.

### 4.1 Layout

```
D:/mbo_store/
  _manifest/build_log.parquet
  catalog/  product=<P>/date=<D>.parquet
  tob/      product=<P>/date=<D>.parquet          wide tier
  trades/   product=<P>/date=<D>.parquet          wide tier
  depth/    product=<P>/date=<D>/freq=<F>.parquet wide tier
  orders/   product=<P>/date=<D>.parquet          deep tier
  mlofi/    product=<P>/date=<D>.parquet          deep tier
  icebergs/ product=<P>/date=<D>.parquet          deep tier
  risk/     product=<P>/date=<D>.parquet
```

**One file per (product, date, kind), not one per instrument.** SR3 alone would otherwise produce
~190,000 small files. Instead each day-file is written with **one row group per symbol, in symbol
order**, with column statistics — which the replay loop produces naturally, so no global sort is
needed. A single-symbol read across 53 days is 53 file opens with row-group pruning, and `symbol`
dictionary-encodes to almost nothing.

### 4.2 Top-of-book events

One row per packet boundary at which the touch changed.

| column | type | note |
| --- | --- | --- |
| `symbol` | dict(str) | row-group key |
| `ts_recv`, `ts_event` | int64 ns | parquet v2.6, delta-encoded |
| `sequence` | uint32 | cross-instrument ordering within a packet |
| `bid_idx`, `ask_idx` | int32 | **tick index**, −1 = empty side |
| `bid_sz`, `ask_sz` | int32 | lots at the touch |
| `bid_ct`, `ask_ct` | int16 | resting orders at the touch |

File metadata carries `px_min`, `tick`, `n_slots`, `band_lo`, `band_hi`, `engine_version`, `product`,
`date`, so a tick index round-trips to an exact price.

**Prices are stored as integer tick indices, and the reason is exactness, not size.** Measured on real
ZN instrument-days, tick indices cost 12.9 bytes/row against 13.9 for float — a 7% saving that would
not justify the indirection on its own. What justifies it: SR3's 0.005 tick is not representable in
binary floating point, which is why the existing findings had to ask
`isclose(spread, tick, atol=tick*0.01)` rather than `spread_ticks == 1`. On tick indices, "one tick
wide" is an integer comparison that is either true or false.

Projected from that measurement: SR3 40.7 GB, each Treasury product ~3.1 GB, **~60 GB for the wide
tier**.

### 4.3 Trades

`rec_idx` is deliberately **not** carried on the top-of-book table. Instead each trade row carries the
prevailing book captured during replay — the last `F_LAST`-consistent state strictly before the
trade's packet.

| column | type |
| --- | --- |
| `symbol`, `ts_recv`, `ts_event`, `sequence`, `order_id` | |
| `price_idx` | int32 |
| `size` | int32 |
| `aggressor` | int8, +1 buy-initiated / −1 sell-initiated / 0 unknown |
| `prev_bid_idx`, `prev_bid_sz`, `prev_ask_idx`, `prev_ask_sz` | int32 |

This drops 8 bytes/row from the largest table in the store, and it turns effective spread from a
`merge_asof` into a column subtraction. It also removes the join entirely — and the join was the part
most likely to be got wrong, because every record inside a packet shares a timestamp, so an as-of join
on time can pick up the book the trade itself created.

### 4.4 Risk, and bp for Treasury products

`risk/product=<P>/date=<D>.parquet`: `symbol`, `ctd`, `conversion_factor`, `dv01_per_contract`,
`ctd_dv01`, `source`, `ts_built`. Built from the existing `Query/USTFutures` machinery
(`USTFutureValue.DV01`, `MDP/USTFutures/treasury_conversion_factors`). SR3 rows are synthesised at the
intrinsic $25/bp so that the code path is uniform.

Analytics take `units="ticks" | "points" | "usd" | "bp"`. Requesting `bp` joins `risk/` and **raises
when a requested (symbol, date) has no DV01**. It never yields NaN.

This is a deliberate design decision with a rejected alternative. The alternative — materialise a bp
column inside the event store — was rejected because it makes a 100+ GB immutable artifact depend on a
curve build that can fail, and this repo has already had exactly that failure: a transient curve error
produced an all-NaN DV01 that was published as a successful run
(`project_tape_null_risk_curve_hazard`). Keeping risk in a separate, small, cheaply-rebuilt partition
means a bad DV01 costs one file, not a rebuild — and the raise means it cannot be mistaken for data.

### 4.5 Manifest, resume and versioning

`_manifest/build_log.parquet` is append-only, one row per build unit:
`product, date, tier, kind, engine_version, source_zip, source_member, source_bytes, n_records,
n_symbols, n_rows, bytes_written, wall_s, crossed_events, trades_outside_book, status, error,
ts_built`.

Resume skips units whose `status == "OK"` **and** whose `engine_version` matches the current engine. A
version bump forces a rebuild, visibly. That is the `reference_ladder_vintage_trap` lesson made
structural: a one-line robustness fix applied mid-backfill silently produced two vintages in one store,
and the only defence is to make the vintage a first-class column that the resume logic respects.

The invariant counters (`crossed_events`, `trades_outside_book`) are recorded per unit, not just
asserted, so a bad day is visible in a query rather than only in a log that has scrolled away.

### 4.6 Build pipeline

```
python -m RVUtils.MBO.build --products SR3,ZN,ZF,ZT,TN,ZB,UB \
    --dates 2026-05-07:2026-08-06 --tier wide,deep \
    --workers auto --disk-budget-gb 250
```

- A process pool over `(product, date)` units. Each worker opens its zip member, decodes, replays
  every instrument, writes its day-files, appends one manifest row.
- **Memory is the binding constraint, not CPU.** One SR3 session is 72.9 M records ≈ 4 GB held whole;
  eight such workers would exceed the host. `--workers auto` derives concurrency per product from a
  measured bytes-per-session figure, defaulting to `floor(0.6 * free_ram / session_gb)`.
- **Disk budget is enforced before the build starts**, from the pilot's measured bytes-per-record,
  and again per unit. A projected overrun fails at the gate. Nine hours in and out of disk is the
  failure mode this exists to prevent.
- Measured throughput: a full decode pass runs at 5.3 M records/s on ZN and 3 M/s on SR3, and a
  108 MB member extracts in 4.7 s.
- **Invoke with the environment's python directly, never `conda run`.** Parallel `conda run`
  invocations collide on a temp file and return empty output with exit 0 — a fake pass
  (`reference_conda_run_concurrency`).

### 4.7 Panels

```python
mbo.panel(symbols, dates, freq="1s", fields=(...), units="bp",
          session="RTH", clock="ts_recv")     # regular grid, forward-filled
mbo.panel_events(symbols, dates, units="bp") # union-of-events, no grid
```

Both are provided, and that is a considered choice rather than generosity. The grid panel is what
`RVUtils/lead_lag.py` and every bar-based study need. The event frame is what the Hayashi-Yoshida
estimator needs, because imposing a grid on asynchronous data is precisely the thing that biases
high-frequency comovement downward (the Epps effect). Offering only the grid would silently push every
lead-lag result toward zero at exactly the resolution this dataset exists to reach.

Forward-fill starts at each symbol's first real quote; before that the value is NaN, not a fabricated
flat line.

## 5. Analytics — book state, flow, impact

`liquidity.py` — time-weighted quoted spread (event-weighted is not the spread you face), two-sided
time fraction, depth curve and book slope over N levels, and **resilience**: how fast displayed size at
the touch returns after a trade consumes it.

`flow.py` — signed trade flow using MBO's true aggressor side, so no Lee-Ready or tick-rule proxy is
needed and their misclassification error is simply absent; touch OFI (Cont-Kukanov-Stoikov); **MLOFI**
(Xu-Gould-Howison) as a per-level vector computed inside the kernel; trade-sign autocorrelation;
aggressive-versus-passive volume split.

MLOFI is computed in-kernel and only the OFI vector is stored (M = 5 levels, int32). Storing the
M-level ladder at every touch change instead would cost roughly 3 GB per SR3 session, which is not
worth it when the vector is the thing every downstream regression actually consumes.

`impact.py` — effective and realised spread at horizons and their difference (price impact), impact
against trade size, permanent/temporary decomposition, and Kyle lambda per instrument-day.

## 6. Analytics — order lifecycle, queue, icebergs

A second numba kernel (`lifecycle.py`) over the same records, emitting **one row per order lifetime**:
entry timestamp/price/size, **queue size ahead at entry**, resting orders ahead, modification counts,
price moves, exit timestamp and reason (`FILLED_FULL`, `FILLED_PARTIAL_CANCEL`, `CANCEL`, `RESET`,
`END_OF_DAY`), filled size, first-fill timestamp, queue ahead at first fill, and time to first fill.

That one table answers order lifetime, cancel-to-trade ratio, queue rank distributions, fill
probability by rank, and it is the substrate for both iceberg detection and the simulator.

**The queue model is an inference, and it is tested as one.** Databento does not carry
`MDOrderPriority`; priority is reconstructed from arrival order under CME's modify rules, and those
rules differ by whether size increased, decreased, or the price moved. The validation is on real data
and does not depend on the vendor: **orders resting at the same price should fill in modelled rank
order.** Rank inversions are counted per instrument-day and recorded in the manifest. A queue model
that is wrong about the modify rules produces inversions immediately, on the busiest instruments,
where the statistics are strongest. The `match_algo` field in `ProductSpec` gates this: a FIFO queue
model must refuse to run on a pro-rata product rather than produce a plausible wrong number.

`icebergs.py` — native detection (executed size at a level exceeding displayed size, and the
post-fill replenishment signature), synthetic detection (patterned limit arrivals shortly after
trades at the same price and side), and Kaplan-Meier estimation of full iceberg size, which is the
right tool because an iceberg cancelled after partial execution is a **censored** observation of its
own size, and treating it as a complete one biases every estimate downward.

## 7. Analytics — lead-lag

`leadlag.py` adds what the SDR work needs and the existing grid-based
`RVUtils/lead_lag.py` cannot provide at book resolution:

- **Hayashi-Yoshida** cumulative covariance and its lead-lag extension, on the async event frame.
- Lagged cross-correlation of **order-flow imbalance**, not only of mid returns — dealer hedging shows
  up in flow before it shows up in price.
- **Hasbrouck information share** and **Gonzalo-Granger** permanent-transitory shares for price
  discovery across the curve.

Every estimator ships with a **placebo**: on timestamp-shuffled input it must return no lead. This is
not optional decoration. Twelve of twelve defects found post-hoc in previous research in this repo all
happened to favour the hypothesis (`feedback_adversarial_review_flatters`), and a lead-lag estimator
run on a common grid at high frequency has a known, directional bias.

## 8. Fill simulator

`sim/` composes a **queue-position model** and a **latency model** over the order-lifecycle store and
the book replay, answering whether a specified resting order would have filled, and when.

Its purpose is to convert a *quoted* spread into an *achievable* cost. The 0.506 bp listed-fly number
is what the book showed; it is not what a strategy earns unless the fill was reachable.

Bounds that must hold, and are tested:

- Simulated fills at a price level never exceed the volume actually traded there.
- An order joining the back of a queue that was never fully consumed does not fill.
- An order at the front of a level whose displayed size was entirely consumed does fill.
- Adding latency can only weakly reduce fills.

## 9. Verification

The rule this repo runs on: a checking tool is first run against an input whose answer is already
known, and for a test suite, the code it covers is mutated to confirm the test actually fails.

**Known-answer unit tests**, extending the existing hand-built-sequence pattern:

| file | covers |
| --- | --- |
| `test_mbo_book.py` | existing 30 sequences, unchanged, plus banded-ladder and overflow cases |
| `test_mbo_products.py` | spec tick versus observed tick; the raise on disagreement |
| `test_mbo_symbols_ust.py` | UST grammar, including the micro inter-commodity forms |
| `test_mbo_store.py` | store round-trip equals in-memory replay; resume; symbol slug injectivity |
| `test_mbo_lifecycle.py` | queue rank under each modify rule; exit-reason classification |
| `test_mbo_icebergs.py` | synthetic sequences with known hidden size; KM on censored samples |
| `test_mbo_leadlag.py` | recovers an injected lag; returns no lead on shuffled input |
| `test_mbo_sim.py` | the four bounds in §8 |

Every kernel change is mutation-tested: a deliberate defect must be caught by the test named for it.

**Real-data verification**, run by `python -m RVUtils.MBO.build --verify` and reported in the findings
document, not in the fast gate:

- **OHLCV tie-out.** Session and intraday bars rebuilt from MBO trade prints against the Barchart
  panels already in the repo. The previous work established the convention — bars are stamped in
  Chicago time and labelled by their start, which reproduced 100% of closes exactly, against 23% for
  end-labelling. Both conventions get tested and both get reported.
- **Replay invariants**, per instrument-day, into the manifest: crossed books at packet boundaries,
  trades outside the prevailing book, queue rank inversions.
- **Cross-checks that use independence.** A structure's leg-implied mid against its listed mid is four
  separately replayed books agreeing on an arithmetic identity none of them knows about; it held to
  half a tick on the SR3 day and should be run per product.

Tests that need `D:\` are marked and skipped when it is absent, so the fast gate
(`pytest tests -m "not slow and not network and not db"`) stays clean and fast.

## 10. Phasing

Each phase is independently shippable and has its own gate. Nothing later depends on a gate that has
not passed.

| Phase | Scope | Gate |
| --- | --- | --- |
| **P1** | `products`, `symbols/`, banded book, `source`, `store/`, `build` CLI; wide tier for all 7 products | `ZNU6` replays; OHLCV ties out; store read equals in-memory replay |
| **P2** | panels; `liquidity`, `flow` (incl. MLOFI), `impact` | placebo: shuffled input yields no signal |
| **P3** | `lifecycle` kernel; `queue`; `icebergs` | modelled rank predicts realised fill order; inversions counted |
| **P4** | `leadlag` | recovers an injected lag; no lead on shuffled input |
| **P5** | `sim` | the four bounds in §8 |

A **pilot build** runs between P1 and the full build: one full session per product, measuring real
bytes per record and per row, extrapolating the total, and enforcing the disk budget. The 401 GB free
against a deep tier covering every active instrument is comfortable but not unlimited, and the
projection has to come from measurement.

## Out of scope

- Ingestion into `CurveStore` / MDP. This store serves research, and its shape is wrong for a curve
  cache.
- The SDR join itself. This suite exports panels and detection primitives; the lead-lag and
  dealer-hedging study that consumes them is a separate workflow.
- Live/streaming MBO. Everything here is historical batch.
- Options MBO. The archives are futures parents only.
