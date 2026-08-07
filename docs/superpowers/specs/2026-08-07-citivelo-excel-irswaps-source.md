# Citi Velocity swap curves as an `IRSwapsMDP` source — design note

**Branch** `feat/citivelo-irswaps-source` · **worktree** `C:\Users\chris\clee\ARBS-cvcurve`
· **written** 2026-08-07

This is the artefact to read first. It records what was decided, what was measured
live, and what is still inferred. Everything measured has its evidence file named.

---

## 1. What was measured, before anything was built

All live data comes over COM from the user's own signed-in Excel, so the whole
harvest was front-loaded and banked before a line of the source was written. The
probe is `MDP/CitiVelocityExcel/harvest/harvest_curve_modes.py` (79 `CV*` calls
across five invocations); the raw evidence is
`MDP/CitiVelocityExcel/harvest/live_curve_modes/evidence.jsonl` plus a JSON
summary per stage. Every series it fetched went into the tag cache on the call
that fetched it, so Phases 2–4 ran entirely offline.

### 1.1 The timezone — the crux, and it is settled

**Citi Velocity timestamps are `America/New_York` wall clock, and they observe US
daylight saving.**

Three independent pieces of evidence:

| # | evidence |
|---|---|
| 1 | `CVNOW()` returned `2026-08-07 10:47:00` against a wall clock of `10:47:01` ET and `14:47:01` UTC — a −4:00 offset, i.e. EDT. |
| 2 | **The decisive one.** `EUR_EUROSTR`'s session is fixed in Frankfurt but its stamps move with *US* DST. Hourly stamps read `02:00–13:59` on 2026-03-05/06 and `03:00–14:59` on 2026-03-09/11 — the same 08:00–20:00 CET on both sides of the **2026-03-08 US** spring-forward (Europe's is 2026-03-29). No fixed UTC offset can do that, and neither can London time. |
| 3 | Read as ET, three more sessions land exactly on 08:00–20:00 *local to the currency*: `JPY_TONAR` 19:00–06:59 ET = 08:00–19:59 JST, `AUD_AONIA` 18:00–05:59 ET = 08:00–19:59 AEST, `GBP_SONIA` 03:00–14:59 ET = 08:00–19:59 London. |

The **request** side is the same zone: `CVSNAP` at `2026-08-06 10:30` returned
`4.23287`, which is to the digit the `MI01` row stamped 10:30.

**What is still inferred.** This machine is itself in `America/New_York`, so an
add-in that formats in *machine-local* time is observationally identical to one
that formats in *exchange* time. Evidence (2) rules out UTC and London but not
machine-local. The zone is therefore a named constant, overridable with
`CITIVELO_EXCEL_WIRE_TZ`, not a hardcode.

### 1.2 Which `CV*` function backs each mode

| primitive | measured behaviour | verdict |
|---|---|---|
| `CVTSHIST` `DAILY` | 44 tags in one call; `yyyyMMdd` bounds honoured | **backs EOD** |
| `CVTSHIST` `MI01` | intraday `yyyyMMddHHmm` bounds **measured honoured** — a 10:00–11:00 request returned exactly 61 rows; newest row was **1 minute old** at 10:47 ET | **backs intraday and live** |
| `CVLATEST` | *does* serve — a bare column, one row per tag — but with **no timestamp** and only 5 dp (`4.23919`) | rejected for live |
| `CVSNAP` | correct value at a point, cross-checked to the digit against the `MI01` row at the same minute; **no timestamp**; one call per instant | rejected as primary |
| `CVSTREAM` | a genuinely live RTD-style cell: full double precision (`4.23909408453934`) and the value **changed between two reads 20 s apart**. No timestamp | rejected here, right for a daemon |

The deciding property is the timestamp. Without one, a curve that stopped ticking
four hours ago is indistinguishable from one that ticked a second ago — and two of
the twenty (`EUR_EONIA`, `JPY_TONAR_JSCC`) genuinely have stopped. `CVSTREAM` is
additionally wrong for a request/response path on the add-in's own terms: it would
be 44 calls per curve and would leave 44 live RTD regions to tear down, which is
the add-in's second documented crash trigger.

`CVSTREAM` *is* the right primitive for a polling daemon, following the
`USD-SOFR-1D-ERISLIVE` precedent — sub-minute ticks, full precision, one
permanently-open workbook that is never torn down. That is not built here.

### 1.3 Per-currency coverage

All twenty serve a complete **44-tenor EOD grid**. Eighteen serve a complete
44-tenor **one-minute grid**. The exceptions, and they are findings not defects:

* **`EUR_EONIA`** — discontinued. Daily series stops **2025-08-15**; no intraday
  history at all; no `FWD` tags. Mapped anyway so a request fails with a reason.
* **`JPY_TONAR_JSCC`** — **EOD only**. 44 tenors daily (one business day behind
  the others), zero one-minute rows at any probe date back to 2026-07-08, no `FWD`
  tags.
* **`JPY_TONAR_LCH`** — EOD and intraday in full, but **no `FWD` tags**, so it
  cannot be tied out against a published forward.

One-minute history depth, from five probe dates using **two** session windows
(10:00 ET and 02:00 ET — one window would have reported "no intraday history" for
every Asian curve, which is simply the middle of their night):

| back to | curves with one-minute history |
|---|---|
| ~1 month (2026-07-08) | 18 / 20 |
| ~1 year (2025-08-07) | 19 / 20 |
| ~3 years (2023-08-08) | 15 / 20 |
| ~5 years (2021-08-06) | 12 / 20 |

---

## 2. The 20-entry curve-name map

Shape `<CCY>-<INDEX>-1D` for every one of them.

| Citi index | curve name | | Citi index | curve name |
|---|---|---|---|---|
| `USD_SOFR` | `USD-SOFR-1D` † | | `NZD_NZIONA` | `NZD-NZIONA-1D` |
| `USD_FEDFUND` | `USD-FEDFUNDS-1D` | | `NOK_NOWA` | `NOK-NOWA-1D` |
| `EUR_EUROSTR` | `EUR-ESTR-1D` † | | `SEK_STINA` | `SEK-STINA-1D` |
| `EUR_EONIA` | `EUR-EONIA-1D` | | `DKK_TNDKK` | `DKK-TNDKK-1D` |
| `GBP_SONIA` | `GBP-SONIA-1D` | | `ILS_SHIR` | `ILS-SHIR-1D` |
| `JPY_TONAR` | `JPY-TONAR-1D` | | `MXN_T_FONDEO` | `MXN-FONDEO-1D` |
| `JPY_TONAR_JSCC` | `JPY-TONAR-1D-JSCC` | | `SGD_SORA` | `SGD-SORA-1D` † |
| `JPY_TONAR_LCH` | `JPY-TONAR-1D-LCH` | | `THB_THOR` | `THB-THOR-1D` |
| `CHF_SARON` | `CHF-SARON-1D` † | | `ZAR_ZARONIA` | `ZAR-ZARONIA-1D` |
| `CAD_CORRA` | `CAD-CORRA-1D` | | `AUD_AONIA` | `AUD-AONIA-1D` |

† already a literal in this repo, reused **exactly**.

Four decisions worth disagreeing with, if you want to:

1. **`-1D` on all twenty.** The alternative was to copy the CME feed's spelling
   for the handful it happens to carry (`JPY-TONAR`, `CAD-CORRA`, `AUD-AONIA`,
   `USD-FEDFUNDS` — all without a tenor segment). That produces a set where
   `CHF-SARON-1D` sits next to `AUD-AONIA`, and those CME names are one source's
   `Literal`, not a registry this source has to join.
2. **`EUR_EUROSTR` → `EUR-ESTR-1D`.** Every other name here uses the market's name
   for the index, not a vendor token; €STR's market name is ESTR. `EUR-ESTR-1D`
   also already occurs in the repo.
3. **The JPY CCP split gets a fourth segment.** `USD-SOFR-1D-RISK` is already a
   curve-definition key, so a qualified fourth segment is an established shape.
   The JSCC/LCH basis is real — measured 2026-08-05, the two disagree by ~2 bp at
   10Y — so they must not collapse onto one name.
4. **`MXN_T_FONDEO` → `MXN-FONDEO-1D`.** "Fondeo" uniquely identifies TIIE de
   Fondeo, the overnight index, and distinguishes it from 28-day TIIE.
   `MXN-TIIEFONDEO-1D` was the alternative and is uglier for no gain.

Pinned by `tests/test_citivelo_excel_source.py::test_curve_name_map_is_pinned`.

---

## 3. Source token

**`CITIVELO_EXCEL`**, with `-RL` (default) and `-QL` selecting the backend, exactly
like the repo's other `*-RL_BASIC`/`*-QL_BASIC` pairs.

`CITIVELO` / `CITI_VELO` / `CITIVELOCITY` are **untouched**. They name the older
workbook-based USD-SOFR-only source that ~930 warmed CurveStore partitions and the
dealer-ladder study depend on. Nothing in this work reads or writes that path, and
its `_CITIVELO_STATE` fetcher cache is deliberately separate from the new
`_CITIVELO_EXCEL_STATE`.

---

## 4. Timestamp semantics

```python
mdp = IRSwapsMDP(source="CITIVELO_EXCEL-RL")
mdp.get_data({"curve_name": "GBP-SONIA-1D", "timestamp": "live"})
mdp.get_data({"curve_name": "GBP-SONIA-1D", "timestamp": date(2026, 8, 5)})
mdp.get_data({"curve_name": "GBP-SONIA-1D",
              "timestamp": datetime(2026, 8, 6, 10, 30, tzinfo=ZoneInfo("America/New_York"))})
```

| input | mode | resolution |
|---|---|---|
| `"live"` / `None` | live | newest complete `MI01` grid in a 5-day trailing window; **lag reported, not hidden** |
| `datetime.datetime` | intraday | per-tenor as-of at that instant, from `MI01` |
| `datetime.date` | eod | that date's close, from `DAILY` |

`datetime` is checked **before** `date` because `datetime` subclasses `date`; the
other order silently turns every intraday request into an end-of-day one.

**Naive datetimes are localised to the wire zone with a one-per-process warning**,
not rejected. The spec allowed either; localising is what
`IRSwapsMDP._load_citivelo_curve_store_point` and the ERIS live path already do,
so a caller moving between this repo's intraday sources does not silently change
meaning. `CITIVELO_EXCEL_STRICT_TZ=1` (or `strict_tz=True`) turns it into a raise.

**Everything handed back is tz-aware.** `meta_data["timestamp"]` is a tz-aware
`America/New_York` datetime. This differs from the older `citivelo` source, which
returns naive ET — deliberate, because a naive stamp is exactly what lets a
one-hour error read as a real market move.

### The reference date is the curve's OWN business date, not the ET one

Citi stamps everything in ET, so an Asia/Pacific session straddles two ET dates.
Measured on `JPY_TONAR` over 2026-08-05/07: the session runs **19:00 ET through
06:59 ET the next day as one continuous block** — the 23:59 print and the
following 00:00 print are the same number — and it belongs to Citi's `DAILY` row
for the **later** date (ET 08-06 19:00–23:59 ended at 2.6575 against a DAILY
08-07 of 2.6500; DAILY 08-06 was 2.6300).

So an **intraday or live** snapshot is dated by the curve's own market calendar,
via a `local_timezone` per curve. Without it every JPY, AUD, NZD, SGD and THB
request in its morning session built a curve one business day early, shifting spot
and all 44 maturities.

An **EOD** snapshot deliberately keeps the ET date: a daily row carries the label
Citi assigned it, and re-deriving that label through a local zone would move it
backwards for any market west of New York — midnight ET is the previous day in
Mexico City.

### Guards

| guard | default | why |
|---|---|---|
| `max_staleness` (intraday/live) | 12 h | an as-of search is backward and *unbounded*; on this repo's other Citi source a request 365 days past the end of the data silently resolved to the last row |
| `max_eod_gap` (EOD) | 7 days | measured separately **in days**, because a daily row is stamped at midnight and the 12 h intraday limit rejected every EOD snapshot |
| `max_constituent_spread` | 6 h (warn at 30 min) | intraday tenors are taken as-of independently, so one illiquid tenor can be much older than the rest |
| `min_tenors` | 4 | a curve from two points solves trivially and means nothing |

A live request for a curve outside its session is **served with its lag stated**,
not refused: `JPY-TONAR-1D` at 10:50 ET is legitimately ~246 minutes old.

An **EOD request for today** warns: Citi's daily series already carries a row for
the current, incomplete session (measured — a `2026-08-07 00:00` row existed at
10:47 ET), so it is a running level, not a settled close.

---

## 5. Curves are built from every tenor Citi serves

The grid is the full `RATES.OIS.<idx>.PAR.*` axis for that index — 44 tenors from
`1W` to `50Y` — and the curve is calibrated to **every tenor that returned a
quote**, per currency, with the ones that did not named on the snapshot rather
than dropped silently. Both backends are supported and both consume the same
grid: `build_rl_ois_curve` (rateslib `Curve` + `Solver`) and `build_ql_ois_curve`
(QuantLib `OISRateHelper` bootstrap).

The rateslib reprice guard is kept unchanged. Under rateslib 2.7.1
`solver.result['status'] == 'SUCCESS'` no longer proves a solve — a bad grid
returns SUCCESS from a curve that misprices its own inputs by 4.9e+05 bp — so the
builder re-prices its calibration swaps and raises. Nothing on the new path
relaxes that.

---

## 6. Curve definitions are projected, not duplicated

`RLIRSwapCurve` and `QLIRSwapCurve` look their conventions up in
`RATESLIB_CURVE_DEFINITIONS` / `QUANTLIB_CURVE_DEFINITIONS`; a name absent from
those raises `KeyError` the first time anything prices. All twenty are therefore
registered — **generated from `MDP/CitiVelocityExcel/curves/conventions.py`**, the
same table the curve builders calibrate with, rather than hand-copied. Sixty
hand-written blocks across three maps is sixty places for the *pricing*
conventions to drift from the *calibration* conventions, and that drift is silent:
the curve still solves, the swap still prices, and the number is wrong.

**Registration never overwrites.** `USD-SOFR-1D` already exists and is referenced
597 times; the existing definition wins and ours is discarded. The report from
`register()` names what was added and what was kept (measured: rateslib +19 / kept
1, quantlib +19 / kept 1).

**The five currencies rateslib has no spec for** (DKK, ILS, SGD, THB, ZAR) get a
spec **registered at runtime** under `<ccy>_ois_citivelo`, built from the same
`CurveConvention` fields `make_rl_irs` uses in its no-spec branch. Verified on
rateslib 2.7.1: `rl.defaults.spec` is a plain dict, an added entry is honoured by
`rl.IRS(spec=...)`, a `rl.Cal` object is accepted as the `calendar` value (which is
what the five synthesised calendars are), and an unknown spec name **raises**
rather than silently defaulting. The alternative — substituting a near-neighbour's
spec — is how a Copenhagen curve ends up rolling on the TARGET calendar.

---

## 7. Caching

The existing `CitiVeloTagCache` (parquet, keyed `(tag, freq, price_point)`) is
reused unchanged, through `CitiVeloQuotes`. A fully-cached request **never opens a
workbook and never needs a signed-in Excel**, which is what makes the verification
suite runnable offline.

The cache stores **naive** timestamps and that was left alone. Retrofitting it to
tz-aware mid-harvest would have silently mixed conventions with the rows already
on disk. The timezone is attached at the source boundary instead
(`CITIVELO_EXCEL/timestamps.py`), which is the only place that needs to know.

**No CurveStore warm is included.** The existing `USD-SOFR-1D-CITIVELO` asset
belongs to the other source and must not be shared; a `citivelo_excel` asset per
curve is a separate, larger piece of work (20 curves × ~930 days) whose value
depends on a usage pattern that does not exist yet.

---

## 8. What was deliberately not done

* **No `CVSTREAM` daemon.** The evidence says it is the right primitive for one
  (§1.2); building it is a separate deliverable with its own operational surface.
* **No CurveStore warming** (§7).
* **No fixings for the nineteen non-USD curves.** This repo has a SOFR fixings
  source and nothing else, so those curves get an **empty** fixings series. That
  is correct for everything this source is built to price — a par or
  forward-starting swap begins at or after spot and needs no history — and it
  fails loudly rather than silently for a seasoned swap, because rateslib raises
  when a float period needs a fixing it does not have. Substituting zeros, or
  another currency's SOFR fixings, is the silent-wrong-number alternative.
* **No change to `CVMETADATA` usage.** It is not a sound validator and is not used
  as one.
* **No repurposing of the old `CITIVELO` aliases** (§3).

---

## 9. Verification — what the numbers are worth

Run: `python MDP/IRSwaps/CITIVELO_EXCEL/verify_matrix.py --offline`. Output lands
in `MDP/IRSwaps/CITIVELO_EXCEL/verification/`.

Four checks, all through `IRSwapsMDP → IRSwapQuery → IRSwapStructure` — a
different code path from the builder, reading a different conventions table:

| check | what it can catch | what it cannot |
|---|---|---|
| `npv` at the curve's own fair rate | a float leg that silently lost its fixings, a schedule that does not match the curve — both of which still *build* | anything about the level, which it is blind to by construction |
| `par` | a registered curve definition that disagrees with `conventions.py` about calendar, frequency, settlement lag or day count | anything about the curve itself — it is near-circular on the curve |
| `forward` vs Citi's published `FWD.<e>.<t>` | **everything**: this is independent data | only runs on the 17 curves that have `FWD` tags, and in EOD mode |
| `interpolation` (drop-one-out) | interpolation error between nodes | conventions, which the reduced curve shares |
| `backends` (rateslib vs QuantLib) | schedule, day-count and annuity divergence | a convention both libraries are told the same wrong thing about |

A sixth check runs against a **live** Excel rather than the cache
(`verify_live.py`): everything above runs on a tag cache this repo wrote, so it
proves self-consistency with data already held. `verify_live.py` drives the whole
path for real — `IRSwapsMDP` → fetcher → `CitiVeloQuotes` → COM → Excel → Citi →
parser → cache → both builders → `IRSwapQuery` — in one `CVTSHIST` call per curve.

The `forward` check runs **EOD only**. Citi publishes `FWD` on the daily series;
comparing a 10:50 intraday curve against a daily forward measures the time of day,
and reporting that as a curve error would flatter or damn the result for the wrong
reason.

**`IRSwapQuery`'s `"5Yx10Y"` shorthand is not Citi's `FWD.5Y.10Y`.**
`RLIRSwapCurve.build_irswap` measures the forward from the curve's *reference
date* adjusted modified-following; Citi (and `rl_builder.forward_rate`, and
QuantLib's `MakeOIS`) measures it from *spot* adjusted following — a two-business-day
difference in the start. The tie-out therefore prices the forward with explicit
Citi-convention dates and reports the shorthand's answer alongside as
`fwd_shorthand_bp`, so the convention gap is a number rather than a claim. On
USD at 2026-08-06 it is worth up to ~0.13 bp.

Results are in `docs/superpowers/specs/2026-08-07-citivelo-excel-verification.md`.
