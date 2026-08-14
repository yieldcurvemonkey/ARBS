## 1. Instantiating the swap MDP for Citi Velocity Excel data

```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

mdp = IRSwapsMDP(source="CITIVELO_EXCEL")          # rateslib backend (default)
curve = mdp.get_pricer({"curve_name": "USD-SOFR-1D",
                        "timestamp": datetime.date(2026, 8, 6),
                        "offline": True})
```

Constructor (`MDP/IRSwaps/IRSwapsMDP.py:116`):
```python
def __init__(self, source: str = "CME_NY_EOD_LIVE-ql_basic", force_refresh_fixings: Optional[bool] = False, **kwargs: Any):
```
Base class `MDP/MarketDataProvider.py:16` just stores `self.source = source; self.config = kwargs`.

**What `source="CITIVELO_EXCEL"` does.** It selects one branch of a long `if/elif` ladder in `_get_curve` (`IRSwapsMDP.py:2775`) and in `bulk_get_data` (`:4750`). Token set (`IRSwapsMDP.py:39-41`, mirrored in `MDP/IRSwaps/CITIVELO_EXCEL/__init__.py:67-69`):
```python
CITIVELO_EXCEL_RL_TOKENS = ("CITIVELO_EXCEL", "CITIVELO-EXCEL", "CITIVELO_EXCEL-RL", "CITIVELO_EXCEL_RL")
CITIVELO_EXCEL_QL_TOKENS = ("CITIVELO_EXCEL-QL", "CITIVELO_EXCEL_QL")
CITIVELO_EXCEL_SOURCE_TOKENS = CITIVELO_EXCEL_RL_TOKENS + CITIVELO_EXCEL_QL_TOKENS
```
Bare token ⇒ rateslib (`RLIRSwapCurve`); `-QL` ⇒ QuantLib (`QLIRSwapCurve`). It is **deliberately not** `CITIVELO`/`CITI_VELO`/`CITIVELOCITY` — those name the older USD-SOFR-only workbook source.

Three time modes on one primitive (`CITIVELO_EXCEL/__init__.py:8-15`, dispatch documented at `IRSwapsMDP.py:2794-2809`):
- `timestamp="live"` → newest complete one-minute grid
- `timestamp=datetime.date(...)` → that date's close (EOD)
- `timestamp=datetime.datetime(...)` → intraday at that instant (America/New_York wire clock; naive is localised **with a warning**)

Useful request kwargs passed through the same dict: `offline`, `force_refresh`/`ignore_cache`, `no_curve_store`, `min_tenors`, `max_staleness`, `max_constituent_spread`, `method`, `strict_tz`, `interpolation`, `spline_start_tenor`, `extrapolation_years`, `max_reprice_error_bp`, `snapshot_policy` (minute-store only; raises `ValueError` on any non-CITIVELO_EXCEL source, `:2004`).

**Other sources** (all from the `_get_curve` ladder):
`CME_NY_EOD_LIVE-QL_BASIC` / `-RL_BASIC`; `ERIS_EOD_LIVE-RL_BASIC`, `-RL_BASIC-NOJUMPS`, `-QL_BASIC`, `-QL_BASIC-NOJUMPS`; `ERIS_LIVE_INTRADAY`; `SDR_INTRADAY-RL_USD_SOFR_MT_Q12 | _MT_Q16 | _MT_MISC | _STIR_Q12X8 | _STIR_Q13X10 | _STIR_Q12X12 | _STIR_MISC | _MTV2_Q12X11`, `SDR_INTRADAY-RL_USD_OIS_STIR_Q12X9 | _Q12X12 | _MISC`; `SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12X11`; `GSQUANT-RL`; `BARCHART_STIRF-RL`; `CITIVELO` / `CITI_VELO` / `CITIVELOCITY`; and the six CITIVELO_EXCEL tokens. Underscore and hyphen spellings are accepted interchangeably.

---

## 2. Curve identifiers

**Defined in `MDP/IRSwaps/CITIVELO_EXCEL/curve_names.py:110-216`** as `CITIVELO_EXCEL_CURVES: Tuple[CurveNameEntry, ...]`. Exactly 20, retrievable at runtime via `supported_curve_names()`; mapped to Citi index tokens by `CITI_INDEX_BY_CURVE_NAME` / `CURVE_NAME_BY_CITI_INDEX`.

| curve_name | citi_index | modes | published FWD |
|---|---|---|---|
| `USD-SOFR-1D` | USD_SOFR | eod/intraday/live | yes |
| `USD-FEDFUNDS-1D` | USD_FEDFUND | all | yes |
| `EUR-ESTR-1D` | EUR_EUROSTR | all | yes |
| `EUR-EONIA-1D` | EUR_EONIA | eod only | no (**DISCONTINUED**, series stops 2025-08-15) |
| `GBP-SONIA-1D` | GBP_SONIA | all | yes |
| `JPY-TONAR-1D` | JPY_TONAR | all | yes |
| `JPY-TONAR-1D-JSCC` | JPY_TONAR_JSCC | eod only | no |
| `JPY-TONAR-1D-LCH` | JPY_TONAR_LCH | all | no |
| `CHF-SARON-1D` | CHF_SARON | all | yes |
| `CAD-CORRA-1D` | CAD_CORRA | all | yes (pays SEMI-annually) |
| `AUD-AONIA-1D` | AUD_AONIA | all | yes |
| `NZD-NZIONA-1D` | NZD_NZIONA | all | yes |
| `NOK-NOWA-1D` | NOK_NOWA | all | yes |
| `SEK-STINA-1D` | SEK_STINA | all | yes |
| `DKK-TNDKK-1D` | DKK_TNDKK | all | yes |
| `ILS-SHIR-1D` | ILS_SHIR | all | yes (Sun–Thu week) |
| `MXN-FONDEO-1D` | MXN_T_FONDEO | all | yes (28-day roll) |
| `SGD-SORA-1D` | SGD_SORA | all | yes |
| `THB-THOR-1D` | THB_THOR | all | yes |
| `ZAR-ZARONIA-1D` | ZAR_ZARONIA | all | yes |

Lookup is `.strip().upper()`-normalised; an unknown name raises `KeyError` with `difflib` suggestions (`entry_for_curve_name`, `:273`).

Other (non-CITIVELO_EXCEL) curve-name registries, verified by import:
- `Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py` → `RATESLIB_CURVE_DEFINITIONS`, 16 keys: `CAD-CORRA, CHF-SARON, EUR-ESTR, EUR-EURIBOR-3M, GBP-SONIA, JPY-TONA, JPY-TONAR, USD-FEDFUNDS, USD-FEDFUNDS-1D-RISK, USD-FEDFUNDS-RISK, USD-OIS, USD-OIS-RISK, USD-OIS-STIR, USD-OIS-STIR-RISK, USD-SOFR-1D, USD-SOFR-1D-RISK`
- `Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py` → `QUANTLIB_CURVE_DEFINITIONS`, 3 keys: `USD-FEDFUNDS, USD-OIS, USD-SOFR-1D`
- Study-level shortcut `RVUtils/StrikelessVol/citivelo.py:34`: `CITIVELO_MARKET_CURVES = {"USD": "USD-SOFR-1D", "EUR": "EUR-ESTR-1D", "JPY": "JPY-TONAR-1D", "GBP": "GBP-SONIA-1D", "CAD": "CAD-CORRA-1D"}`

Tenor axis served per curve (44, verified on disk, see §5):
`1D 1W 2W 3W 1M 2M 3M 4M 5M 6M 7M 8M 9M 10M 11M 1Y 15M 18M 21M 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y 11Y 12Y 13Y 14Y 15Y 16Y 17Y 18Y 19Y 20Y 25Y 30Y 35Y 40Y 45Y 50Y`

---

## 3. IRSwapQuery / structures / values

### Fields (`Query/IRSwaps/IRSwapQuery.py:104-142`, frozen dataclass over `BaseQuery`)
```python
structure: IRSwapStructure = IRSwapStructure.OUTRIGHT
value: Union[IRSwapValue, List[IRSwapValue]] = IRSwapValue.RATE
tenor: Optional[str] = None
effective_date: Optional[datetime.date] = None
maturity_date: Optional[datetime.date] = None
is_mms: bool = False
curve: Optional[str] = None            # becomes market_request['curve_name']
structure_kwargs: Dict[str, Any] = field(default_factory=dict)
value_kwargs: Dict[str, Any] = field(default_factory=dict)
risk_weight: Optional[float] = None
_curve_name: Optional[str] = None
product: str = field(init=False, default="IRS")
structure_id: Any = field(init=False, default=None)
```
Inherited from `Query/Base/BaseQuery.py:58-67`: `value_id`, `value_ids`, `market_request`, `mdp_time_key="timestamp"`, `name`, `tags`, `meta`.

`__post_init__` also: aliases `coupon→fixed_rate`, `front_coupon→front_fixed_rate`, `belly_coupon|mid_coupon→mid_fixed_rate`, `back_coupon→back_fixed_rate`; defaults OUTRIGHT to `notional=1_000_000` when neither `notional` nor `bpv` given; and **auto-detects structure from slashes in `tenor`** (0 slashes → OUTRIGHT, 1 → CURVE, 2 → FLY) when no explicit multi-leg kwargs are present. Verified: `IRSwapQuery(tenor="2Y/10Y", ...)` ⇒ `IRSwapStructure.CURVE`; `tenor="5Y/10Y/30Y"` ⇒ `FLY`.

### `IRSwapStructure` — complete (`IRSwapStructure.py:39-44`)
```python
class IRSwapStructure(Enum):
    OUTRIGHT = auto()
    CURVE    = auto()
    FLY      = auto()
    SPREAD   = auto()          # maps to _build_outright (IRSwapStructure.py:63)
```

### `IRSwapValue` — complete (`IRSwapValue.py:11-48`)
`RATE, PV01, DV01, GAMMA_01, NPV, NOTIONAL, CARRY_BPS_RUNNING, ROLL_BPS_RUNNING, CARRY_AND_ROLL_BPS_RUNNING, SPREADOVER, MMSS, SPREADOVER_CARRY_ADJUSTED, MMSS_CARRY_ADJUSTED, SPREADOVER_ROLL_ADJUSTED, MMSS_ROLL_ADJUSTED, SPREADOVER_CR_ADJUSTED, MMSS_CR_ADJUSTED, PAR_PAR_ASW, TRUE_ASW, PROCEEDS_ASW, MARKET_ASW, CVX_ADJ, CVX_ADJ_EMPIRICAL, ROLL_ADJ_DIFFERENCE, ROLL_ADJ_RATIO, ROLL_ADJ_CALENDAR_WEIGHT, CITIVELO_SWAP_SPREAD`

Only these have entries in `IRSwapValueFunctionMap._create_map` (`:120-134`): `RATE, PV01, DV01, GAMMA_01, NPV, NOTIONAL, CARRY_BPS_RUNNING, ROLL_BPS_RUNNING, CARRY_AND_ROLL_BPS_RUNNING, CVX_ADJ, CVX_ADJ_EMPIRICAL, CITIVELO_SWAP_SPREAD`. The `SPREADOVER`/`MMSS`/ASW family is handled elsewhere (`MDP/IRSwapSpreads/IRSwapSpreadsMDP.py` + `Query/IRSwaps/adapter.py::IRSProductAdapter.edit_query`).

### Exact `structure_kwargs` per shape (all verified on `USD-SOFR-1D`, 2026-08-06)

**Spot swap**
```python
IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.RATE,
            tenor="10Y", curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 100_000.0})     # or {"notional": 100_000_000}
```
→ `RATE = 4.25759` (percent), `PV01 = +100000.0`, `NPV ≈ 0`.

**Forward swap** — the tenor token is `"<forward>x<tail>"`; split at `IRSwapStructure.py:129-131`.
```python
IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.RATE,
            tenor="20Yx10Y", curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 100_000.0})
```
→ `RATE = 4.31956`, effective `2046-08-06`, maturity `2056-08-07`. Also accepted: `"IMM_H27x5Y"`, `"IMM_3x2Y"`, central-bank-meeting tokens (`resolve_central_bank_tenor`), and CUSIP/`CT10`/`Ox110`/`MMYY` MMS tokens (USD only, via `adapter.edit_query`).

**Curve spread / flattener between two forward swaps**
```python
IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.RATE,
            curve="USD-SOFR-1D",
            structure_kwargs={"front_tenor": "15Yx5Y",
                              "back_tenor":  "20Yx10Y",
                              "bpv": 100_000.0,
                              "risk_weights": [1, -1]})
```
Verified: resolved weights `[-1.0, +1.0]`, leg PV01s `[-100000, +100000]`, `RATE = -57.338` **bp** (`back − front`). Full `_build_curve` signature at `IRSwapStructure.py:226-243` — accepts `front_/back_` × `tenor|effective_date|maturity_date|notional|fixed_rate`, plus `bpv`, `risk_weights` (len 2, default `[1,1]`), and an alternative N-leg `tenors=[...]` form. Exactly one of `front_notional`, `back_notional`, `bpv` must be given (assert at `:254`); with `bpv` the **back leg** is the constrained one (`:271`).

**Butterfly**
```python
IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.RATE,
            curve="USD-SOFR-1D",
            structure_kwargs={"front_tenor": "5Y", "belly_tenor": "10Y", "back_tenor": "30Y",
                              "bpv": 100_000.0,
                              "risk_weights": [1.0, 2.0, 1.0]})
```
Verified: resolved weights `[-1.0, 2.0, -1.0]`, leg PV01s `[-50000, +100000, -50000]`, `RATE = -5.791` bp (= `2·belly − front − back`). `_build_fly` (`:286-306`) takes `front_/belly_/back_` × `tenor|effective_date|maturity_date`, `front_fixed_rate|mid_fixed_rate|back_fixed_rate`, exactly one of `front_notional|belly_notional|back_notional|bpv` (constrains the belly), `risk_weights` (len 3, default `[1,2,1]`).

The production idiom for a spread of forwards is often **two OUTRIGHT legs with opposite `bpv` and a shared tag**, not one CURVE query — see `notebooks/backtests/citivelo_rv/sv_h13_qdb.py:258-265`:
```python
legs = [
    IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                tenor=SHORT_LEG, curve=CURVE,
                structure_kwargs={"bpv": +PKG_DV01}, tags=(tag,)),
    IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                tenor=LONG_LEG, curve=CURVE,
                structure_kwargs={"bpv": -PKG_DV01}, tags=(tag,)),
]
```

### What `bpv` means, and its sign — MEASURED, not read off comments

`bpv` is **PV01 in currency per basis point on the constrained leg**. `RLIRSwapCurve.build_irswap:287-296`:
```python
if bpv and not notional:
    unit_delta = rl.IRS(..., notional=1, ...).analytic_delta(curves=self._rl_curve_handle)
    notional = bpv / unit_delta
```
Verified exactly: `bpv=+100_000` ⇒ `curve.pv01(swap) = +100000.0000`, notional `+123,003,719`; `bpv=-100_000` ⇒ `pv01 = -100000.0000`, notional `-123,003,719`.

**Sign rule (verified by repricing across 2022-09-12 → 2022-09-15, USD 5Y par +23.4 bp):**

> **`bpv > 0` ⇒ the package makes money when its quoted `RATE` rises.** For an OUTRIGHT that is **PAYER (pay fixed)**.

| structure | `bpv` | measured P&L | implication |
|---|---|---|---|
| OUTRIGHT 5Y | `+100,000` | **+$2,303,346.5** | payer; ≈100k × 23.4 bp ✔ |
| OUTRIGHT 5Y | `-100,000` | **−$2,303,346.5** | exact mirror (receiver) |
| CURVE 2Y/10Y (2s10s −26.93 bp) | `+100,000` | **−$2,594,382.6** | pay back / rec front = **steepener**, ~$96.3k per bp of `10Y−2Y` |
| CURVE 2Y/10Y | `-100,000` | **+$2,594,382.6** | flattener |
| FLY 5/10/30 (fly −2.05 bp) | `+100,000` | **−$104,472.9** | long the fly rate; **$/bp = bpv/2 ≈ $51k** under default `[1,2,1]` |

Two committed artifacts contradict this and are **wrong relative to measured P&L** — flag before trusting them:
- `IRSwapQuery._format_struct_kwargs:34` labels `bpv > 0` as `"REC"` (so `col_name()` prints `Rec 100k … OUTRIGHT RATE` for what is actually a payer).
- `IRSwapStructure._build_curve:271` comment `# relative to the back leg e.g. rec 2s10s => rec 10s, pay2s flattener` — the measured direction for `bpv>0` is the opposite (steepener).
The committed sign probe in `sv_h13_qdb.py:107` (`assert plus > 0, "payer must gain in the 2022-09 selloff"` for `bpv=+PKG_DV01`) agrees with the measurement.

Backend caveat: on the **QuantLib** wrapper the same `bpv=+100_000` request returned `pv01 = -100000.0`, i.e. the raw-wrapper sign is inverted vs rateslib. `resolve_pricable` re-signs from `risk_weight` before valuation, but do not assume raw `curve.pv01()` signs carry across backends.

---

## 4. Getting numbers out of a pricer

Interface: `Query/IRSwaps/_IRSwapGenericCurve.py`. Concrete: `Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py`, `.../quantlib/QLIRSwapCurve.py`.

```python
curve.build_irswap(fwd=None, tenor=None, effective_date=None, maturity_date=None,
                   fixed_rate=-0, notional=None, bpv=None)  -> rl.IRS
curve.fair_rate(irswap)                    -> float   # DECIMAL par/forward rate
curve.npv(irswap)                          -> float   # currency
curve.pv01(irswap)                         -> float   # analytic_delta, $/bp  <-- the DV01/PVBP in practice
curve.dv01(irswap, shift=1e-4)             -> float
curve.gamma(irswap, shift=1e-4)            -> float
curve.dollar_carry(irswap, horizon)        -> float
curve.carry_bps_running(irswap, horizon)   -> float
curve.roll_bps_running(irswap, horizon)    -> float
curve.carry_and_roll_bps_running(irswap, horizon) -> float
curve.notional(irswap); curve.fixed_rate(irswap); curve.effective_date/maturity_date(irswap)
curve.reference_date(); curve.nodes(); curve.meta(); curve.calendar_advance(dt, "2D")
curve.resolve_pricable(irswap, risk_weight=None)
```

**rateslib backend (`source="CITIVELO_EXCEL"`) — measured:**
- `fair_rate` = decimal (0.042576 for 10Y); `IRSwapValue.RATE` multiplies by 100 for 1 leg, by 10,000 for 2/3 legs (`_swap_structure_legs_mapper`, `IRSwapValue.py:62-66`) ⇒ outright RATE is **percent**, curve/fly RATE is **bp**.
- `pv01` works (`= analytic_delta`).
- **`dv01()` and `gamma()` raise `NotImplementedError`** (`RLIRSwapCurve.py:220-234`): *"IRSwapValue.DV01 is not available on the rateslib backend (needs a calibrated rl.Solver…). Use IRSwapValue.PV01, or a QuantLib-backed source."* Verified live.
- `dollar_carry` also raises `NotImplementedError`; `CARRY_BPS_RUNNING`/`ROLL_BPS_RUNNING`/`CARRY_AND_ROLL_BPS_RUNNING` work and need `horizon` in `value_kwargs` (measured 10Y @ 3M: `+1.1482 / +0.9696 / +2.1178` bp).

**QuantLib backend (`source="CITIVELO_EXCEL-QL"`) — measured offline on 2026-08-06 USD 10Y, `bpv=100_000`:**
`fair_rate 0.04257484`, `pv01 -100000.0`, **`dv01 -103798.83`**, **`gamma -79.935`**. Note this branch is not CurveStore-eligible (`_store_eligible` requires `backend == "rl"`, `IRSwapsMDP.py:2841`) so it rebuilds from the tag cache — still fully offline.
**Bug found:** `QLIRSwapCurve.dollar_carry` raises `TypeError: calc_dollar_carry() got an unexpected keyword argument 'curve'` (`QLIRSwapCurve.py:83`).

**Convexity measures.** `IRSwapValue.GAMMA_01` → `curve.gamma()` (QL only). `IRSwapValue.CVX_ADJ` (`IRSwapValue.py:176`) is futures-vs-swap and requires `value_kwargs={"sfr": [rl.STIRFuture, ...]}` on a 1-leg rateslib package; returns `(implied_fut_yield_pct − swap_yield_pct) * 100` bp. `IRSwapValue.CVX_ADJ_EMPIRICAL` (`:360`) requires a spread-style pricer exposing `pricer_a`/`pricer_b` and returns the risk-weighted `fair_rate` difference × 10,000.

Value-map call form (what the engine does — `Query/IRSwaps/position_handler.py:69-73`, `BT/position_handler.py:38-41`):
```python
package, weights = q.resolve_package(pricer_or_curve=curve)
package = [curve.resolve_pricable(p, rw) for p, rw in zip(package, weights)]
vmap = q.build_value_map(pricer_or_curve=curve, package=package, risk_weights=weights)
vmap.apply(value=IRSwapValue.NPV)                 # or .apply(value=..., horizon="3M")
```

Grid convenience (`IRSwapsMDP.py:1948`), verified:
```python
mdp.get_grid(request, *, fwds=None, swap_tenors=None, flip_axes=False) -> pd.DataFrame
```
returns forward-rate percent, rows = swap tenor, cols = forward tenor.

---

## 5. Historical coverage and where the cache actually lives

**It is a local parquet cache. No COM call to Excel is involved for any date that is already banked.** Two distinct on-disk layers, both verified to exist:

**(a) CurveStore — warmed EOD curves (discount-factor nodes), Hive-partitioned**
`Caching/curve_store.py:381-531`, asset name from `CITIVELO_EXCEL/warm.py:75` (`asset_for`).
```
C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw\asset=<CURVE>-CITIVELOEXCEL\date=YYYY-MM-DD\<sha256>.parquet
C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw\asset=<CURVE>-CITIVELOEXCELMIN\...   (one-minute)
```
Counted on disk (each `date=` dir is one day):

| asset | days | first | last |
|---|---|---|---|
| `USD-SOFR-1D-CITIVELOEXCEL` | **5,506** | 2005-01-03 | 2026-08-07 |
| `EUR-ESTR-1D-CITIVELOEXCEL` | 5,565 | 2005-01-04 | 2026-08-07 |
| `JPY-TONAR-1D-CITIVELOEXCEL` | 5,160 | 2006-01-02 | 2026-08-07 |
| `GBP-SONIA-1D-CITIVELOEXCEL` | 4,067 | 2010-11-26 | 2026-08-07 |
| `CAD-CORRA-1D-CITIVELOEXCEL` | 2,820 | 2012-01-03 | 2026-08-07 |
| `JPY-TONAR-1D-LCH-CITIVELOEXCEL` | 1,108 | 2017-11-09 | 2026-08-07 |
| `USD-SOFR-1D-CITIVELOEXCELMIN` | 1,538 | 2021-09-14 | 2026-08-13 |
| `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` | 2,710 | 2017-12-05 | 2026-08-10 |
| `JPY-TONAR-1D-CITIVELOEXCELMIN` | 2,489 | 2017-12-06 | 2026-08-10 |
| `CAD-CORRA / EUR-ESTR / GBP-SONIA / JPY-TONAR-LCH …MIN` | 531–636 | 2024-08-01 | 2026-08-13 |
| `EUR-EONIA-1D-CITIVELOEXCELMIN` | 103 | 2021-06-03 | 2021-09-30 |
| `EUR-EURIBOR-6M-CITIVELOEXCELMIN` | 260 | 2025-08-12 | 2026-08-10 |
| `*-CITIVELOSTREAM` (USD/EUR/GBP) | 1 | 2026-08-07 | 2026-08-07 |

**Only 6 of the 20 curves have a warmed EOD CurveStore asset.** The other 14 fall through to a from-quotes build.

**(b) Citi tag cache — the raw wire par grids, one parquet per `(tag, freq, price_point)`**
`MDP/CitiVelocityExcel/cache.py:69-86, 141-148`. Layout `<base>/<FREQ>/<PRICE_POINT>/<sanitised-tag>.parquet` (+ `.meta.json`). Resolved root on this machine (note the **doubled `ARBS\ARBS`** — real, caused by `platformdirs.user_cache_dir(appname="ARBS")` *without* `appauthor=False`, unlike `CurveStore`):
```
C:\Users\chris\AppData\Local\ARBS\ARBS\Cache\citivelo_excel\DAILY\CLOSE\RATES.OIS.USD_SOFR.PAR.10Y.parquet
```
Inventory (measured): `DAILY` **14,535 parquet files / 214.4 MB**, `MI01` **1,502 files / 217.3 MB**, `HOURLY` 2 files. Each file has columns `["timestamp", "value"]` (value = par rate in **percent**).

Per-index DAILY `PAR` coverage (all 44 tenors present for every index):

| index | span | max rows |
|---|---|---|
| `EUR_EUROSTR` | 2004-12-13 → 2026-08-07 | 5,579 |
| `USD_SOFR` | **2005-01-03** → 2026-08-07 | 5,538 |
| `GBP_SONIA` | 2005-01-04 → 2026-08-07 | 5,562 |
| `CAD_CORRA` | 2005-01-04 → 2026-08-07 | 5,505 |
| `JPY_TONAR` | 2005-01-04 → 2026-08-07 | 5,215 |
| `JPY_TONAR_LCH` | 2015-10-08 → 2026-08-07 | 1,632 |
| `EUR_EONIA` | 2025-08-08 → 2025-09-08 | 22 |
| all 13 others (CHF/AUD/NZD/NOK/SEK/DKK/ILS/MXN/SGD/THB/ZAR/USD_FEDFUND/JPY_TONAR_JSCC) | **2025-08-08 → 2026-08-07** | 260–261 |

**USD short-end caveat (measured):** `USD_SOFR` `PAR` tenors `1D…21M` only print from **2019-07-01/08** (n≈1,851–1,856); `2Y…50Y` go back to 2005-01-03 (n≈5,497–5,538). Pre-2019 USD curves are therefore calibrated from 2Y+ only. This is consistent with `warm.py:22-28`: the gate is `min_tenors=20`, not 44 ("USD has 5,540 daily rows but only 1,835 where all 44 tenors print").

`MI01` (one-minute) for `USD_SOFR` spans 2005-01-03 00:00 → **2026-08-13 20:11**, 44 tenors, ~17–22k rows/tag.

Also present, unrelated pre-extract: `C:\Users\chris\AppData\Local\ARBS\Cache\citivelo_par_extract\YYYY-MM-DD.parquet` (from 2023-01-02). The repo-local `C:\Users\chris\clee\ARBS\.cache\curve_store` holds only 3 non-Citi assets and is **not** the active store.

Verified live-path proof of the two tiers:
- `USD-SOFR-1D` @ 2026-08-06 offline ⇒ meta `{'from_curve_store': True, 'asset': 'USD-SOFR-1D-CITIVELOEXCEL', 'mode': 'eod'}`
- `CHF-SARON-1D` @ 2026-08-06 offline ⇒ builds from the tag cache, `{'n_tenors': 44}`, no `from_curve_store`, 10Y = 0.61875%
- `CHF-SARON-1D` @ 2015-01-05 offline ⇒ `SparseCurveError: no DAILY quotes … in the window ending eod 2015-01-05` (confirms the 2025-08-08 floor for the 14 unwarmed currencies)

---

## 6. Offline operation and env vars

**Yes — fully offline, no Excel, no COM, no add-in sign-in**, for any date already banked. Two mechanisms:

1. **`"offline": True` in the request dict.** Forwarded to `CitiVeloExcelCurveFetcher(offline=...)` (`IRSwapsMDP.py:2899-2904`) → `CitiVeloQuotes(offline=True)`. On a cache miss it raises rather than connecting (`quotes.py:152-158`): *"CitiVeloQuotes is offline and the request is not fully cached (cache root: …)"*. `sv_h13_qdb.py:347-348` uses exactly this: `mdp.bulk_get_data({"curve_name": ..., "timestamps": grid_days, "offline": True})`.
2. **The CurveStore fast path bypasses the fetcher entirely** for `backend == "rl"` + EOD/intraday + no `force_refresh`/`ignore_cache`/`no_curve_store` (`IRSwapsMDP.py:2841-2877`). A warmed day never constructs a `CitiVeloQuotes` at all — the fetcher (and therefore the COM client) is only built lazily on a store miss.

Excel/COM is reached only when: the request is `"live"`, or the day is cold in both layers, or `force_refresh`/`ignore_cache`/`no_curve_store` is set, **and** `offline` is not `True`.

Env vars:

| var | effect | default |
|---|---|---|
| `ARBS_SUPABASE_ENABLED` | Supabase L2 tier for the CORE cache. `Caching/supabase_engine.py:67` reads it **at import time** as a module global — hence the `os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")` as literal first statement in `sv_h13_qdb.py:42` and ~20 other scripts. Setting it after any `Caching/` import is a no-op. `_env_enabled` treats everything outside `{0,false,f,no,n,off}` as **enabled** | **enabled (1)** |
| `ARBS_CACHE_DIR` | overrides both roots: `<dir>/curve_store` (`curve_store.py:516`) and `<dir>/citivelo_excel` (`cache.py:74`). **Not set in the repo `.env`**, so both fall through to the `platformdirs` branches shown in §5 | unset |
| `CITIVELO_EXCEL_CACHE_DIR` | overrides the tag-cache root outright (`cache.py:71`) | unset |
| `ARBS_CURVE_STORE_BG_PUSH_WORKERS` | background L2 push threads (`curve_store.py:425`) | 2 |
| `SWAPTION_CUBE_L2_ENV` / `Caching/l2_policy.py` | newer three-state (`off`/`read`/`read_write`) L2 gate, read at call time, strict vocabulary; default `OFF` | off |

---

## 7. Tidy pandas DataFrame of daily par rates by tenor — three verified helpers

**(1) Model-priced rates through the query layer** — `TB/IRSwapsTB.py:715`. Returns a `Date`-indexed frame, one column per query named by `IRSwapQuery.col_name()`.
```python
def get_timeseries(
    self,
    start: DateLike,
    end: DateLike,
    queries: List[IRSwapQuery | List[IRSwapQuery] | IRSwapQueryWrapper],
    *,
    n_jobs: Optional[int] = 1,
    ignore_cache: Optional[bool] = False,
    ignore_cache_miss: Optional[bool] = False,
    freq: Optional[str] = None,
    timestamps: Optional[List[datetime.datetime]] = None,
    _prefetched_ts_rows_by_symbol: Optional[Mapping[str, Sequence[Tuple[DateLike, str, float]]]] = None,
) -> pd.DataFrame:
```
Constructor: `IRSwapsTB(mdp, *, date_col="Date", cache_stem=None, force_refresh=False, use_btree=True, show_tqdm=True, logger=None, use_ts_cache=True, ts_base_dir="./data/ts", ts_row_group_size=256_000, ts_compression="zstd", use_duckdb=True, duckdb_path=None)`. Verified:
```python
tb = IRSwapsTB(IRSwapsMDP(source="CITIVELO_EXCEL"), show_tqdm=False,
               use_ts_cache=False, use_duckdb=False, use_btree=False)
df = tb.get_timeseries(date(2026,7,27), date(2026,8,6),
                       [IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.RATE,
                                    tenor=t, curve="USD-SOFR-1D",
                                    structure_kwargs={"bpv": 10_000.0})
                        for t in ("2Y","5Y","10Y","30Y")])
# -> (9, 4), Date index, cols "Rec 10k USD-SOFR-1D 10Y OUTRIGHT RATE" ... ; 2026-08-06 10Y = 4.25759
```
Note it does **not** forward an `offline` flag to the MDP; historical dates still resolve from the CurveStore, but a cold day would attempt a live build.

**(2) Raw wire par grid straight off the tag cache (fastest, fully offline)** — `MDP/CitiVelocityExcel/curves/par_grid.py:78`
```python
def fetch_par_grid(*, client: Any, citi_index: str, freq: str = "DAILY",
                   period: Optional[str] = None,
                   start: Optional[DateLike] = None, end: Optional[DateLike] = None,
                   tenors: Optional[Sequence[str]] = None,
                   cache: Optional[CitiVeloTagCache] = None,
                   price_point: str = "CLOSE") -> pd.DataFrame:
```
Index `timestamp` ascending, columns = tenor tokens in maturity order, values = **par rates in percent**. Pass `client=None` with `cache=CitiVeloTagCache()` to serve purely from disk. Verified:
```python
fetch_par_grid(client=None, cache=CitiVeloTagCache(), citi_index="USD_SOFR",
               freq="DAILY", start=date(2000,1,1), end=date(2026,8,13))
# -> (5544, 44), 2005-01-03 -> 2026-08-12; 2024-01-02 10Y = 3.53035
```

**(3) The reader the warm/panel scripts use** — `MDP/CitiVelocityExcel/quotes.py:266`
```python
def frame(self, tags: Sequence[str], freq: str = "DAILY", **kwargs: Any) -> pd.DataFrame:
```
```python
q = CitiVeloQuotes(offline=True)
f = q.frame(tags.ois_par_grid("GBP_SONIA"), "DAILY", start=..., end=...)
f = f.rename(columns={t: t.rsplit(".", 1)[-1] for t in f.columns})   # tags -> tenor tokens
```
Verified (5, 44) for GBP 2026-08-03..07; 10Y on 2026-08-07 = 4.52327. Same three lines are `MDP/IRSwaps/CITIVELO_EXCEL/warm.py::_par_frame` (`:79`) and `notebooks/backtests/citivelo_rv/build_curve_panel.py` (which writes `notebooks/data/citivelo_rv/par_grid_<INDEX>.parquet` — **that directory does not currently exist on disk**, so those panels and every `DATA / ...` artifact `sv_h13_qdb.py` reads must be regenerated before that notebook will run).

Related: `MDP/IRSwaps/CITIVELO_EXCEL/swap_spreads.py:1283` `swap_spread_history(citi_index, tenors=None, *, start, end, freq="DAILY", quotes=None, offline=False, catalog=None, force_refresh=False, client_kwargs=None, window=None) -> pd.DataFrame` — Citi's *published* swap-spread axis, columns named by tenor. Verified axes: `USD_SOFR` = `('1M','3M','6M','1Y','2Y','3Y','5Y','7Y','10Y','20Y','30Y')` (11), `GBP_SONIA` = `('2Y','3Y','5Y','7Y','10Y','15Y','20Y','30Y','40Y','50Y')` (10), `EUR_EUROSTR` raises `UnknownTagError` (no `SWAP_SPREAD` sub-type). Zero `SWAP_SPREAD` tags are currently cached and the unit is literally `UNIT = "as_published"` — bp-vs-decimal is unmeasured (`IRSwapValue.py:305-314`); do not difference it against `MMSS`/`SPREADOVER` until `scripts/citivelo_swap_spread_tieout.py` has run.