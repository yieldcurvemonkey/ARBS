# CA time-axis audit — do the two legs mark at the same instant?

Measured 2026-08-26. Question: does `IRSwapsTB(...).sfr_cvx_adj(COLOURS, ...)` pair a
3pm-settlement futures leg with a 3pm swap leg?

## Verdict

**Yes — the notebook path is co-timed at 15:00 America/New_York on both legs.**
A sibling production path (`RVUtils.ConvexityRV.strat2_*`) is **not**: its futures leg
is the 17:00 ET Globex close against the same 15:00 ET swap curve.

| leg | code | instant (measured) |
|---|---|---|
| swap curve | `IRSwapsMDP("citivelo_excel_rl")._get_curve(timestamp=<date>)` → EOD store, warmed from CVTSHIST `DAILY` | **15:00 ET** |
| SR3 futures (`sfr_cvx_adj`) | `get_barchart_timeseries(interval=None)` → `queryeod.ashx?data=daily` | **CME settle**, struck 13:59:30–14:00:00 CT = 15:00 ET |
| SR3 futures (`strat2_*`) | `STIRFutureMDP("BARCHART_STIRF-RL")`, date → 17:00 NY key | **15:59 CT bar** = Globex close = 17:00 ET |
| model vol (`_MODEL`/`_MODEL2`) | swaption cube store, warmed `freq="DAILY"` off the same Citi series | 15:00 ET (inferred from the shared path) |

## Evidence

**1. Citi DAILY = 15:00 ET.** Pooled RMSE(daily − MI01(t)) across minutes of day,
4 par tenors × 18 days — the tag cache holds MI01 for these tags only from 2026-08
(`scratchpad/citi_daily_vs_minute.py`):

| ET minute | 14:00 | 14:59 | **15:00** | 15:01 | 16:00 | 17:00 |
|---|---|---|---|---|---|---|
| RMSE bp | 0.624 | 0.163 | **0.146** | 0.170 | 0.701 | 0.818 |

Repeated at curve level over the notebook's whole range (stored EOD curve vs stored
10-min curves, zero-rate bp, `scratchpad/eod_vs_minute_curve2.py`), 40 EST days
2023-01-03..2026-01-02 and 40 EDT days 2023-03-13..2026-06-22 — median RMSE by ET bucket:

| ET | 11:00 | 13:00 | 14:00 | **14:50** | **15:00** | 16:00 | 17:00 |
|---|---|---|---|---|---|---|---|
| EST | 1.622 | 1.074 | 0.880 | **0.591** | **0.614** | 0.750 | 1.041 |
| EDT | 1.198 | 0.854 | 0.739 | **0.444** | **0.464** | 0.676 | 0.821 |

Same 14:40–15:20 ET minimum in both regimes: **no DST shift ⇒ a New York clock, not a
UTC anchor**, and the 15:00 snap holds back to 2023-01 (EOD store is warm to 2023-01-10).

**2. `queryeod` daily Close = the CME settle, not the session close.** 60 days × front 3
SR3, restricted to the 69 (date,contract) pairs where the 13:59 CT and 15:59 CT bars
differ (`scratchpad/barchart_daily_vs_minute.py`):

* mean |daily − 13:59 CT bar| = **0.201 bp**, exact on **57/69**
* mean |daily − 15:59 CT bar| = **0.907 bp**, exact on **16/69**

(Barchart minute bars are start-stamped, so the 13:59:30–14:00:00 CT settle window sits
inside the 13:59 bar.)

**3. `BARCHART_STIRF-RL` at a date = the Globex close.** 9 days × 3 contracts
(`scratchpad/settle_source_compare.py`): equals the **15:59 CT bar on 24/27, mean
0.093 bp**; against the settle, 0.389 bp. Mechanism: `STIRFutureMDP` fetches 1-minute
bars for the whole Chicago day and takes `get_indexer(method="nearest")` to the request
instant, and a date request is keyed 17:00 NY = 16:00 CT, i.e. the last bar of the
session. `warm_sr3_settles.py` and `assert_settle_source` both call this "the settle".

**Size of that mis-timing**: |15:59 CT − 13:59 CT| per contract, 122 pairs — mean
**0.81 bp**, median 0.5, p90 1.5, max 4.5, against a pack CA of 1.3–6.8 bp. The swap leg
drifts ~0.7 bp over the same two hours (from (1)), correlated, so it partly cancels —
but it is not cancelled by construction.

## Defects found, and what was done (branch `fix/ca-time-axis`)

1. **`IRSwapsMDP._wrap_citivelo_excel_eod` (`:3046`) stamps every store-served EOD curve
   `time(17, 0)`.** Measured instant is 15:00. `meta["timestamp"]` and `curve_id` carry
   the fiction; `MDP/IRSwaps/CITIVELO_EXCEL/warm.py:204` writes the same 17:00 into the
   store's `timestamp_utc` and `session_minute=17*60`. (The store's `timestamp_local`
   column reads 16:00 because that writer renders it in **Chicago** — deliberate, not a
   bug, though `session_minute` next to it is New York.) No pricing consumer
   found — the stamp is provenance and `curve_id` only — but it does propagate into the
   CurveStore row's `timestamp_utc`/`session_minute` and onto `rl_curve_handle.timestamp`.
2. **`strat2_sofr_convexity` pairs a 17:00 ET futures leg with a 15:00 ET swap leg**,
   and its guard function is named for preventing exactly this. Verified in `build_panel`:
   the same `datetime.date` goes to `futures_mdp.get_data({"symbols": …, "timestamp": d})`
   → 17:00 NY key → 15:59 CT bar, and to
   `swaps_mdp.get_pricer({"curve_name": …, "timestamp": d})` → EOD mode → the 15:00 ET
   Citi curve. The two sources read the same date differently.
3. Today's row (`end = 2026-08-26`) is a running mark on both legs, not a settle — the
   MDP already warns and `sfr_cvx_adj` refuses to cache it, but it is returned.

### The fix

| commit | what |
|---|---|
| `196d127b` | `timestamps.EOD_SNAP_TIME` — one named constant carrying the measurement, used by both the served-curve wrapper and the CurveStore writer. Rows written earlier keep a 17:00 stamp; reads key on `trading_date`, so `force=True` restamps if wanted. |
| `f6126351` | `BARCHART_STIRF_SETTLE-RL` — a source that asks Barchart's DAILY endpoint, keys a bare date at 15:00 ET, refuses an instant and a primed minute frame, and never fills or nearest-matches a missing settle. `warm_settles()` warms by contract. `BARCHART_STIRF-RL` is untouched. |
| `fc6bb75e` | every CA futures leg defaults to the settle source (`Strat2Config`, `Q20Config`, cavf/gv/citi engines, `CvxSuite.board`, `ca_intraday`); `assert_settle_source` rejects the Globex close by name (`allow_globex_close=True` to reproduce an old panel); the key scanners derive their hour from the source; `warm_sr3_settles` rewritten around the bulk warm. |

Verified after the change: the settle source reproduces the `queryeod` daily Close on
**27/27** cells while the old source reproduces the 15:59 CT bar. `tests/test_ca_time_axis.py`
(17 tests) pins the behaviour and was mutation-checked — reverting the stamp, the
`interval=1` hardcode, the date match, the fill, or the per-source hour each fails it.

**Two consequences to carry.** The settle cache is a new namespace, so a panel must be
re-warmed before it rebuilds offline; and any recorded conclusion from these modules was
measured under the Globex-close mark, so a re-run may move its numbers.

## Scripts

`scratchpad/{citi_daily_vs_minute,barchart_daily_vs_minute,settle_source_compare,eod_vs_minute_curve2,eod_coverage}.py`
