# CITI_VELOCITY_INTRADAY — intraday USD-SOFR OIS rateslib curves

Turns the **Citi Velocity `CVTSHIST`** intraday export of USD SOFR OIS **par**
swap rates into fully-calibrated rateslib discount curves, following the IRSwaps
RL (rateslib) curve-building patterns already in the repo
(`SDR_INTRADAY/rl_curve_utils/rl_usd_sofr_mt_builder.py`,
`ErisFuturesFetcher.fetch_intraday_discount_curve`).

## Source workbook schema

Each weekly sheet is named `YYYYMMDDHHMM-YYYYMMDDHHMM` (Mon 00:01 → Fri 11:59) and
laid out as:

| row | content |
|-----|---------|
| 1 | start timestamp int, e.g. `202607130001` |
| 2 | end timestamp int, e.g. `202607171159` |
| 3 | (blank) |
| 4 | `=CVTSHIST("RATES.OIS.USD_SOFR.PAR.1D,...","MI01",,"...","...","CLOSE")` |
| 5 | header: `Date | RATES.OIS.USD_SOFR.PAR.1D - CLOSE | … | ….50Y - CLOSE` |
| 6+ | `<datetime>` + 44 par rates (percent), **newest first** |

The 44 tenors (short → long): `1D 1W 2W 3W 1M 2M 3M 4M 5M 6M 7M 8M 9M 10M 11M 1Y
15M 18M 21M 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y 11Y 12Y 13Y 14Y 15Y 16Y 17Y 18Y 19Y 20Y
25Y 30Y 35Y 40Y 45Y 50Y`.

Most weekly sheets in `db.xlsx` are **empty templates** carrying only the two
boundary timestamps; only populated sheets (`max_col > 1`) are parsed.

## How the curve is built

For a single snapshot (one minute of par rates):

1. `ref_date` = the snapshot date (the curve anchor node, DF = 1.0).
2. `spot` = `ref_date` + 2 good business days (`nyc`).
3. One `rl.IRS(effective=spot, termination=<tenor>, spec="usd_irs", fixed_rate=<par%>)`
   per tenor — SOFR RFR-compounded, act/360, annual, MF, matching the repo
   `USD-SOFR-1D` definition.
4. One curve node pinned at each swap maturity; DFs solved with `rl.Solver`.
5. Default interpolation `log_linear` (always converges for the dense par grid);
   optional log-cubic spline from a chosen tenor via `spline_start_tenor`.

The result is the repo's `RLCurveBase` container, so downstream pricing/risk code
consumes it exactly like the other RL builders. Solver non-convergence **raises**
(no silent bad curves).

## Usage

```python
from MDP.IRSwaps.CITI_VELOCITY_INTRADAY import CitiVelocityIntradayFetcher

f = CitiVelocityIntradayFetcher()                     # defaults to db.xlsx (env: CITI_VELOCITY_INTRADAY_DB)

rlc  = f.build_curve()                                # latest snapshot -> RLCurveBase
rlc  = f.build_curve("2026-07-17 11:30")              # nearest snapshot
curve, ts = f.fetch_intraday_discount_curve("2026-07-17 11:30")   # Eris-style (rl.Curve, timestamp)

for ts, rlc in f.iter_curves("2026-07-17 09:00", "2026-07-17 16:00", freq="15min"):
    dv01 = ...  # rlc.rl_pricing_curve / .rl_pricing_curve_solver

# smoother long end:
rlc = f.build_curve(spline_start_tenor="2Y")
```

Lower-level entry points: `load_intraday_par_rates`, `CitiVelocityWorkbook`,
`build_rl_usd_sofr_intraday_curve`, `par_reprice_errors_bp`.

## Notes

- Timestamps are kept **naive** as stored (Citi `CVTSHIST` close times); pass
  `tz=` to localize.
- Legacy `.xls` (OLE2/BIFF) exports are rejected — convert to `.xlsx` first
  (openpyxl cannot read BIFF).

## Tests

```
conda run -n stir python -m pytest tests/test_citi_velocity_intraday_curve.py -q
```

Hermetic unit tests build a synthetic workbook in `tmp_path`; one
`integration`-marked test exercises the real `db.xlsx` and self-skips if absent.
