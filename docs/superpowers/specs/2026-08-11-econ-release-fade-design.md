# Fade the initial move after tier-1/tier-2 economic data releases

Design, 2026-08-11. Branch `feat/econ-release-fade`, worktree `ARBS-eco`.

## The claim under test

A scheduled macro release lands at a known minute. Rates futures move within seconds. The
hypothesis is that some fraction of that first move is liquidity — a thin book absorbing a
one-sided burst — rather than information, and therefore reverts.

The trade: measure the move over a short window after the print, take the **opposite** side,
hold for a configured horizon, exit. Every one of those choices is a knob.

## What is already known before any number is produced

Three things are measured, not assumed, and they bound the whole study.

**The calendar is on disk and needs no network.** `ForexFactoryCalendarFetcher` has 2,779 day
partitions covering 2018-12-31 → 2026-08-09 under `%LOCALAPPDATA%\ARBS\Cache\forex_factory_calendar_store`.

**Tier is `Impact`.** `high` (ImpactRank 3) = tier 1, `medium` (2) = tier 2, `low` (1), `holiday` (0).

**A release is distinguished from a speech by having a number.** `Actual != "" or Forecast != ""`
is true for data releases and false for speeches, pressers and minutes. On USD tier-1+2, 2019-2026:
3,275 releases against 968 non-data events. The releases occupy 2,040 distinct minutes on 1,332
days, 1,821 of them at 08:30 ET and 767 at 10:00 ET.

**Releases cluster.** Of those 2,040 minutes, 437 carry two events, 223 carry three, 75 four,
29 five, and two carry six and seven. CPI and Core CPI print together; NFP, unemployment rate and
average hourly earnings print together. The unit of trading is therefore the **minute**, not the
event, and a config that filters to "CPI" is selecting a minute that also contains Core CPI.

## Two defects that must be fixed rather than inherited

**1. Look-ahead in both MDPs.** `STIRFutureMDP` and `USTFuturesMDP` both resolve an intraday
timestamp with `index.get_indexer([ts], method="nearest")` (`USTFuturesMDP.py:791`). The selected
bar can be one that had not yet printed. The FOMC configurable notebook's §2 traced this to 64 of
783 trades — one tick each, and every one of them explained by the engine marking against a future
bar. For a strategy whose entire signal is measured in the first minutes after a print, marking
against a bar from after the entry is not a rounding error; it is the signal.

**2. Cost of the intraday path.** `USTFuturesMDP` keys its cache on the *requested* ISO timestamp
and clamps every fetch to one Chicago day, and `bulk_get_data` is a `for` loop over `get_pricer`.
Barchart's intraday ceiling is 55 requests / 60 s. A single config would spend hours; a grid is
impossible.

Both are fixed by the same construction, which already has precedent in this directory
(`CitiVeloSTIRFutureMDP`, `global_hawk_dove_common.py:1258`): a **bar-cache MDP shim** that
implements the `get_pricer` surface, serves the real pricer classes, and resolves every timestamp
to the **last bar at or before it**. Measured: a 3-month 1-minute range fetch is 48,151 rows in
3.6 s for SR3 and 79,044 rows in 5.3 s for ZN, so the entire 2019-2026 universe warms in minutes.

## Architecture

```
notebooks/backtests/econ_release_fade/
    econ_fade_common.py        instrument registry, event book, bar cache, MDP shims,
                               causal gate, make_query, run_backtest, stats
    econ_fade_config.py        CONFIG schema, run_config (engine), run_config_fast
                               (closed form), compare
    econ_fade_prewarm.py       CLI: warm minute bars by range, measure UST DV01s,
                               build the raw event book
    _make_backtest_notebook.py -> econ_release_fade_backtest.ipynb
    _make_grid_notebook.py     -> econ_release_fade_gridsearch.ipynb
    _cache/                    bars.pkl, events_raw.pkl, ust_dv01.json
```

No file under `BT/` is modified. The engine is used exactly as shipped.

### Pipeline, in order

```
FF calendar frame
  -> event filters          (currency, impact, title, surprise, date, weekday)
  -> cluster by minute      (one trade per release minute, not per event)
  -> attach instrument      (family, root, contract for that date)
  -> re-time                (measure / entry / exit offsets, session clamp)
  -> overlap rule           (one position at a time)
  -> causal bar gate        (a real bar at or before every stamp, staleness bound)
  -> measure initial move   (rate bp)
  -> side = -sign(move)     (fade) or +sign(move) (momentum placebo)
  -> STIRFutureQuery / USTFutureQuery -> QueryDrivenBacktest
```

The filters run **before** the overlap rule, on the raw book. This is deliberate and it is the
same decision the FOMC configurable notebook documents: a CPI-only config resolves its own
overlaps and therefore trades more CPI prints than a CPI-shaped slice of a mixed book does. The
two answer different questions and this pipeline answers "what if I only traded CPI".

### Instrument registry

| family | root | contract rule | bp conversion |
|---|---|---|---|
| `stir` | `USD_STIR` | Nth quarterly IMM, GE before 2022-01-01, SR3 after | exact: price 0.01 = 1 bp |
| `stir` | `ZQ` | Nth serial monthly | exact |
| `ust` | `TU` `FV` `TY` `US` | front contract, roll 6 business days before the delivery month | measured DV01 per contract |

USD STIR splices GE → SR3 at 2022-01-01 because SR3 barely traded before then (measured
2021-03: GE 541 bars/day against SR3 37). ZQ minute bars begin around 2024-11; that is surfaced
in the funnel as an exclusion count rather than hidden.

### Units

Every trade carries `dv01_usd`, the dollars-per-basis-point of the position at entry, and
`pnl_bp = realized_pnl / dv01_usd`. For STIR that is exact by construction — the query is sized in
`bpv` and the handler computes `(Δprice/0.01) × PV01`. For UST the handler returns dollars via
`(Δprice/tick_size) × tick_value × contracts`, and `dv01_usd` comes from a table measured once per
(root, contract) with `RLUSTFuturePricer.pv01`. Measured 2025-10-15: TU $17.52, FV $42.59,
TY $59.44, US $127.45 per bp per contract; TY ranges $58.08 (2022) to $69.05 (2019), so the table
is per contract and not per root.

`pnl_bp` is the only unit in which a 2-year note future and a SOFR future belong in one book.

### CONFIG

```python
CONFIG = {
    "name": "baseline",
    "instrument": {"family": "stir", "root": "USD_STIR", "rank": 3},
    "events": {
        "currencies": ["USD"], "impacts": ["high"],
        "titles_include": None, "titles_exclude": None,
        "require_actual": True, "include_cb_decisions": False,
        "start": None, "end": None, "weekdays": None,
        "cluster_minutes": 0, "surprise": "any",
    },
    "timing": {
        "measure_start_min": 0, "measure_end_min": 1,
        "entry_offset_min": 1, "exit_offset_min": 60,
        "max_staleness_min": 5, "session_clamp": True,
    },
    "signal": {"direction": "fade", "source": "move",
               "min_move_bp": 0.0, "max_move_bp": None},
    "sizing": "equal",
    "cost_bp": 0.0,
}
```

## Honesty machinery

There is no published baseline to reproduce, so §2 of the notebook is replaced by three checks
that are stronger than a tie-out to a prior number:

1. **Engine against closed form.** The same book is priced by `QueryDrivenBacktest` and by an
   arithmetic pricer reading the same causal bars, and the two must agree trade for trade. A
   disagreement is a defect in one of them and is accounted for individually, not averaged away.
2. **Wrong-calendar placebo.** Every release timestamp is shifted by +1 day onto a minute with no
   release. If the edge survives that, the edge is a time-of-day effect and not a release effect.
3. **Momentum flip.** `direction: "momentum"` must lose roughly what `fade` makes, gross. If both
   make money the P&L is coming from somewhere other than the sign of the move.

The grid notebook adds the deflated Sharpe over every configuration it ran, using
`expected_max_sharpe` / `deflated_sharpe`, because the cheapest way to manufacture a Sharpe here is
to try enough windows.

## Cost

`cost_bp` is charged per unit of gross risk, round trip. Reference points already measured in this
repo: the listed SR3 butterfly trades one tick, 0.506 bp round trip; the SR3 outright tick is
0.5 bp. UST futures trade in 32nds and half-32nds. Cost is reported as a sensitivity curve rather
than a single assumption, and the break-even round-trip cost is printed for every book.

## Deliverables

- `econ_release_fade_backtest.ipynb` — one CONFIG dict, run end to end through the engine, with
  the knob sweeps (instrument, timing, event set, cost), the honesty checks, and a trade log.
- `econ_release_fade_gridsearch.ipynb` — the closed form over hundreds of configs, tied out to the
  engine on a sample, ranked by Sharpe / hit rate / bp per trade, deflated.
