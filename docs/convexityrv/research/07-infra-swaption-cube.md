# ARBS Swaption Vol Cube — Verified Map

Everything below was executed on this machine (`conda env stir`, `C:\Users\chris\anaconda3\envs\stir\python.exe`). Dates/numbers are measured, not quoted from docstrings.

---

## 1. Instantiating the swaption MDP against the Citi Velocity cube

**Recipe of record (verified end-to-end, offline, no Excel):**

```python
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP

mdp = IRSwaptionMDP(source="CITIVELO-RL", curve_source="CITIVELO_EXCEL",
                    request_defaults={"verify": False})
ctx = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 8, 6)})
```

Measured output:
```
ctx.id(): USD-SOFR-1D|2026-08-06|CITIVELO-RL|atmf_normal
curve type: RLIRSwapCurve | curve_handle: Curve
vol_handle: CitiVeloSwaptionCube | pricing_engine: RLSwaptionEngine
metadata keys: ['as_of_date','citivelo_cube','citivelo_provenance','curve_source','surface_type','timestamp_mode']
provenance: {'origin':'swaption_cube_store','asset':'USD-SWAPTIONVOL-CITIVELOEXCEL','as_of':'2026-08-06',
             'smile':'full','n_offsets':13,'offsets_bp':[-200,-100,-75,-50,-25,-10,0,10,25,50,75,100,200],
             'store_source':'citivelo_excel_warm/DAILY'}
```
Context build: **2.4 s** warm. `bulk_get_data({"curve_name":..., "timestamps":[...]})` is the batch form.

**`request_defaults={"verify": False}` is load-bearing.** Per `MDP/IRSwaptions/CITIVELO/provider.py:361-377`: *"the FIRST valuation took 235.8 s and the next 1.54 s, and 236.8 s of the first was `assert_vol_spread_ordering` inside `build_ql_swaption_cube`."* It fires under `-RL` too, because `CitiVeloSwaptionCube.volatility()` is served by the QuantLib surface.

**`source` grammar** — `_parse_source_token` (`IRSwaptionMDP.py:90`) requires `"<PROVIDER>-<ENGINE>"`. Registered: `VOL_PROVIDERS = {GSQUANT, MONKEYCUBE, GSQUANT_MC_ENHANCED, CITIVELO}`, `ENGINE_FACTORIES = {QL, RL}`.

**Documented but NOT run here** (README / `provider.py:11`):
```python
mdp = IRSwaptionMDP(source="CITIVELO-QL", curve_source="ERIS_EOD_LIVE-QL_BASIC")
```

**Verified failure** — `CITIVELO-QL` on a rateslib curve source:
```
TypeError: engine='QL' needs a QuantLib curve, but RLIRSwapCurve.handle() returned Curve.
Use a -QL_BASIC curve_source (e.g. 'ERIS_EOD_LIVE-QL_BASIC'), or 'CITIVELO-RL' if you meant the rateslib engine.
```
Raised by `IRSwaptionMDP._assert_curve_matches_engine` (`IRSwaptionMDP.py:422-445`) **before** the vol provider runs. Conversely `CITIVELO-RL` on a QuantLib curve raises `CitiVelocityError` from `provider.py:321-328`.

Useful provider kwargs (forwarded through `request_defaults` or per-request), from `get_citivelo_vol_objects` (`provider.py:231-254`): `currency`, `citi_index`, `cube=`, `cubes={date: cube}`, `snapshot='usd_cube_2026-08-06.json'`, `expiries`, `tenors`, `offsets_bp`, `strict`, `notional`, `client`, `sabr`, `use_cube_store`, `cube_store`, `verify`.

### Store-miss → Excel COM hazard (important)
`_cube_for_date` (`provider.py:155-228`) order is: `cubes=` → `cube=` → `snapshot=` → **warmed store** → `CitiVelocityExcelClient.connect()`. Verified: `2020-02-03` is **NOT IN STORE**, yet a probe for it built a cube with `smile='atm_only'` — the only remaining path is COM. So **any date absent from the store silently drives the signed-in Excel add-in**, and for the 2020 gap (below) Excel serves ATM-only anyway, so that gap is **not backfillable**.

---

## 2. What the cube contains (measured, `2026-08-06`)

```
CitiVeloSwaptionCube(USD 2026-08-06 via rl-native, 17x9x13,
                     available=['rl-native','rl-hand','ql','ql-sabr'], idx=USD_SOFR)
```

**Expiries (17):** `['1M','2M','3M','6M','9M','1Y','18M','2Y','3Y','4Y','5Y','7Y','10Y','12Y','15Y','20Y','30Y']`
**Swap tails (9):** `['1Y','2Y','3Y','5Y','7Y','10Y','15Y','20Y','30Y']`
**Strike offsets (13, signed bp from ATMF):** `[-200,-100,-75,-50,-25,-10,0,10,25,50,75,100,200]`
→ 17 × 9 × 13 = **1,989 nodes/day**. `skew_offsets()` returns the 12 non-zero ones.

Caveat: `MDP/CitiVelocityExcel/vol/cube_data.py:141` `DEFAULT_SWAP_TENORS` lists 11 tenors (adds `4Y`,`12Y`) and its own docstring says the tenor axis is *"UNVERIFIED"*. The **store shows 9**. Use the measured axis.

**Vol convention — NORMAL, annualised, basis points.** Stored constant columns on every partition:
```
measure='NORMAL'  skew_measure='NORMALABSOLUTE'  served_unit='bp'  vol_unit='bp'  strike_unit='bp'
currency='USD'  citi_index='USD_SOFR'  source='citivelo_excel_warm/DAILY'
```
`NORMALABSOLUTE` = the OTM measure serves an **absolute vol level at the offset strike**, not a spread (`ABSOLUTE_SKEW_MEASURES=("NORMALABSOLUTE",)`, `SPREAD_SKEW_MEASURES=("NORMALSKEW",)`, `REJECTED_SKEW_MEASURES=("PREMIUM","RISK_REVERSAL")`). No lognormal/Black surface anywhere — the engines are `ql.BachelierSwaptionEngine` and a Bachelier `RLSwaptionEngine`.

Unit conversions: `VOL_UNIT_TO_BP = {"bp":1.0, "decimal":1e4, "percent":1e2}`. `assert_vol_units` **raises** rather than rescaling. `CitiVeloSwaptionCube.normal_vol()` returns **bp**; `.volatility(option_time, swap_length, strike, extrapolate)` returns **decimal** (the QuantLib read signature).

**ATMF handling.** Offset 0 IS the ATM node. The strike axis is anchored on the *curve*, not on a published forward:
```python
def strike_for(self, expiry, tenor, offset_bp) -> float:
    """``forward + offset/1e4``, the strike Citi's offset refers to."""
    return self.forward(expiry, tenor) + float(offset_bp) / 1e4
```
and `RLSwaptionEngine.normal_vol` inverts it per-leg: `offset_bp = (k - forward) * 1e4`. Hence the provider gets `wants_curves=True` and skips a date with no curve rather than anchoring on another day.

Measured 1Yx30Y on 2026-08-06:
```
F = 0.04477072  annuity = 15.7778 yrs  tte = 1.0
smile {offset_bp: vol_bp} = {-200: 91.4002, -100: 77.9733, -75: 75.7684, -50: 74.4595,
   -25: 74.2761, -10: 74.7569, 0: 75.3207, 10: 76.0685, 25: 77.5051, 50: 80.5998,
   75: 84.3424, 100: 88.5116, 200: 106.94}
strike_for(+25) = 0.04727072
price payer ATM = 4,741,016.51   price receiver ATM = 4,741,016.51   vega payer ATM = 62,944.40
```

Cube API (`MDP/CitiVelocityExcel/vol/swaption_cube.py`): `expiry_date`, `forward`, `annuity`, `time_to_expiry`, `payment_date`, `payment_discount`, `normal_vol(expiry,tenor,strike=None,offset_bp=0.0)`, `smile`, `volatility`, `volatility_at_point`, `implied_vol_surface_frame(offset_bp=...)`, `to_frame()`, `strike_for`, `price`, `premium`, `vega(analytic=False)`, `implied_normal_vol`, `swaption`, `with_backend`, `.ql_handle`, `.native`, `.is_rateslib`/`.is_quantlib`.

Backends: `rl-native` (`rl.IRSplineCube`+`IRSCall`), `rl-hand` (`PPSplineF64`+Bachelier), `ql` (`InterpolatedSwaptionVolatilityCube`), `ql-sabr` (a **fit** — does not reproduce its own nodes).

---

## 3. Pricing a swaption / straddle

**Enums** — `Query/IRSwaptions/IRSwaptionStructure.py:26`:
```python
class IRSwaptionStructure(Enum):
    RECEIVER; PAYER; STRADDLE; STRANGLE; RECEIVER_SPREAD; PAYER_SPREAD;
    RECEIVER_FLY; PAYER_FLY; RECEIVER_1x2; PAYER_1x2;
    RECEIVER_LADDER; PAYER_LADDER; RISK_REVERSAL
```
Risk weights (`_STRUCTURE_RISK_WEIGHTS`): STRADDLE/STRANGLE `[1,1]`; *_SPREAD `[1,-1]`; *_FLY `[-1,2,-1]`; *_1x2 `[1,-2]`; *_LADDER `[1,-1,-1]`; RISK_REVERSAL `[1,-1]`. `side="sell"` multiplies all by −1.

`Query/IRSwaptions/IRSwaptionValue.py:22`:
```python
class IRSwaptionValue(Enum):
    NVOL; SPREAD_NVOL; FWD_NVOL; MIDCURVE_FAIR_NVOL; DAILY_BREAKEVEN_NVOL; ANNUAL_BREAKEVEN_NVOL;
    SPOT_NPV; FWD_NPV; SPOT_PREM; FWD_PREM; DV01; DELTA; GAMMA; GAMMA_01; VEGA_01;
    THETA_1D; CHARM; VETA; SABR_NVOL; SABR_PARAMS
```
(`SABR_NVOL`/`SABR_PARAMS` require `metadata['vol_cube']` — that is MONKEYCUBE/GSQUANT_MC_ENHANCED only. CITIVELO deliberately stores its cube under `metadata['citivelo_cube']`, see `IRSwaptionMDP.py:771-781`.)

**Verified working call, 1Yx30Y ATMF straddle, 2026-08-06:**
```python
from Query.IRSwaptions import IRSwaptionQuery, IRSwaptionStructure, IRSwaptionValue
from Query.Base.query_resolution import resolve_query

q = IRSwaptionQuery(
    curve="USD-SOFR-1D",
    shorthand="1Yx30Y",                       # or expiry="1Y", tail="30Y"
    strike="ATMF",                            # "ATMF+25", "ATMS-50", "25DPAYER", or a float
    structure=IRSwaptionStructure.STRADDLE,
    value=IRSwaptionValue.SPOT_NPV,           # or a list -> return_query() fans out
    structure_kwargs={"notional": 100e6},
)
qq   = resolve_query(q, timestamp=dt.datetime.combine(D, dt.time()), pricer_or_curve=ctx)
pkg, w = qq.resolve_package(pricer_or_curve=ctx)
vmap = qq.build_value_map(pricer_or_curve=ctx, package=pkg, risk_weights=w)
vmap.apply(value=IRSwaptionValue.VEGA_01)
```

Resolved package:
```
[('receiver', 2027-08-06, 2027-08-06, 2057-08-06, 0.04477050425710954, 1e8),
 ('payer',    2027-08-06, 2027-08-06, 2057-08-06, 0.04477050425710954, 1e8)]   weights [1.0, 1.0]
```

Measured values (notional 100 mm/leg):
```
NVOL                  =  75.3207          (bp, annual normal — exactly the cube ATM node)
SPOT_NPV              =  9,486,857.75     (currency, PV at as_of)
FWD_NPV               =  987,653,252.58   (spot/DF * 100 — see leg_fwd_npv)
SPOT_PREM             =  948.6857751599   (SPOT_NPV/|notional| * 10_000)
FWD_PREM              =  987.6532525827   (FWD_NPV/|notional| * 100)
DELTA                 =  0.0              (Bachelier fwd delta; straddle nets to 0 at ATMF)
GAMMA                 =  0.01059273
GAMMA_01              =  1,672.15
DV01                  =  0.0
VEGA_01               =  125,952.86       (PV change per 1 bp of normal vol)
THETA_1D              = -13,004.61
CHARM                 =  0.0
VETA                  = -172.66
DAILY_BREAKEVEN_NVOL  =  0.2064996        (= -THETA_1D / VEGA_01)
ANNUAL_BREAKEVEN_NVOL = 52.0379           (= daily * 252)
```

`structure_kwargs` keys actually read by the builders (`IRSwaptionStructure.py:371-560`):
`expiry`, `tail` (`"30Y"` or midcurve `"1Yx10Y"`), `exercise_date`/`underlying_effective_date`/`underlying_maturity_date`, `strike`, `side` (`"buy"`/`"sell"`), `notional` (default **1e8**), `vega_01`|`vega01`|`vega` (target-vega scaling — ignored if `notional` given), `wing_bps` (STRANGLE/1x2, default 25), `spread_bps` (spreads/flies, default 25), `receiver_strike`, `payer_strike`, `high_strike`, `low_strike`, `wing_strike`, `costless` (1x2, default True), `premium`/`premiums`, `premium_type`/`premium_types` (`'spot_cash'|'spot_bps'|'fwd_bps'`). `IRSwaptionValue.FWD_NVOL`/`MIDCURVE_FAIR_NVOL` additionally take `rho`, `wa`, `wb`, `use_fair_midcurve` via `value_kwargs`.

Strike grammar — `Query/IRSwaptions/utils.py:15-19, 307-351`:
```python
_ATM_RE   = re.compile(r"^\s*(ATMF|ATMS)\s*(?:([+-])\s*(\d+(?:\.\d+)?)\s*B?P?S?)?\s*$", re.IGNORECASE)
_DELTA_RE = re.compile(r"^\s*(?P<delta>\d+(?:\.\d+)?)\s*D(?:\s*(?P<side>PAYER|PAY|P|RECEIVER|REC|R))?\s*$", re.IGNORECASE)
```
`"ATMF+25"` → `base + 25/10_000`. Sign infers option type for outrights (`+`→payer, `−`→receiver). Bare floats go through `strike_value_to_decimal`: `>200 → /1e4`, `>2 → /100`, else as-is.

Verified OTM: `strike="ATMF+25"` PAYER → strike `0.04727050`, **NVOL 77.5051** (= the cube's +25 node), SPOT_NPV 3,159,504.93.

**ATMF forward rate** — three equivalent routes, all measured `0.04477050425710954` / `0.04477072008816152`:
```python
from Query.IRSwaptions.pricer import leg_forward_rate, leg_model_vol, leg_tte_years
leg_forward_rate(ctx, pkg[0])        # 0.04477050425710954  (decimal)
leg_model_vol(ctx, pkg[0])           # 0.007532056606727104 (decimal normal vol)
leg_tte_years(ctx, pkg[0])           # 1.0
ctx.pricing_engine.forward(ctx, pkg[0])          # RL engine, same number
ctx.metadata["citivelo_cube"].forward("1Y","30Y")  # 0.04477072008816152 (cube node dates)
```
(The 2e-7 difference is node tenor tokens vs the leg's own calendar-advanced dates.)

Leaf helpers in `Query/IRSwaptions/pricer.py`: `leg_metrics`, `leg_spot_npv`, `leg_fwd_npv`, `leg_implied_normal_vol_bps`, `leg_delta`, `leg_gamma`, `leg_gamma_01`, `leg_dv01`, `leg_vega_01`, `leg_theta_1d`, `leg_charm`, `leg_veta`, `leg_pvbp`, `swap_pvbp`, `build_underlying_swap`, `build_ql_swaption`, `discount_factor`.

`premium_override` is **refused** on `-RL` (`rl_engine_for`, `pricer.py:55-77`) — use a `-QL` source.

---

## 4. Implied terminal distribution from ATMF + OTM swaption prices

**There is no swaption-native RND code in this repo.**

- `RVUtils/StrikelessVol/` is the ultra-long **forward-slope convexity** study (delta-hedged flattener replication, PCA/key-rate ladders, carry-per-vega). Not distribution extraction. The only cube-adjacent pieces: `straddle_book.SmileSurface` (linear in offset, linear in log-expiry, **refuses to extrapolate**), `premium_mark.{forward_and_annuity, straddle_premium_usd, straddle_delta, implied_from_straddle_usd}`, `panels.vol_panel`, `citivelo.citivelo_atm_vol_panel`, `conventions.{annual_normals_to_bp_day, bp_day_to_annual_normals, VolQuote}` (`TRADING_DAYS=252.0`).
  ⚠️ `citivelo_atm_vol_panel` reads `C:/Users/chris/clee/ARBS/notebooks/data/citivelo_rv/vol_panel.parquet` — **verified NOT to exist**. Rebuild: `conda run -n stir python notebooks/backtests/citivelo_rv/build_vol_panel.py`.

- `RVUtils/ImpliedDistribution/` is written for **3M SOFR futures options in price space**, but its two extractors take a plain `RNDInput` dataclass with no SFR coupling, so they are reusable:
```python
extract_rnd_breeden_litzenberger(rnd_input, *, smoothing_param=1e-4, scale_smoothing_by_n=False,
    spline_order=4, n_ghost_points=10, ghost_extension_bps=5.0, bin_width_bps=25.0,
    grid_points=2000, rate_floor=0.0, fit_space="price", vol_smoothing_param=None,
    anchor_wings=False, ghost_anchor_weight=100.0) -> BreedenLitzenbergerResult
extract_bkm_moments(rnd_input, *, interpolation_points=500) -> BKMResult          # Bakshi-Kapadia-Madan
extract_gaussian_mixture(rnd_input, scenarios, ...) -> GaussianMixtureResult      # Fed-scenario weights
```
`RNDInput(symbol, as_of, forward_price, forward_rate, time_to_expiry, expiry_date, discount_factor, strikes_price, call_premiums, strike_source, warnings=())`.
`SFRImpliedDistribution` and `_data_prep.smile_to_rnd_input(smile: STIRFutureOptionSABRSmile, ...)` are the only SFR-bound layers — bypass them.

**The trap:** `_finalize_bl_result` hard-codes `rate = 100.0 - price` (`_breeden_litzenberger.py:287-289`), and `build_ghost_wings` uses `step = extension_bps / 100.0` — i.e. **price units**, so `ghost_extension_bps=25` means 250 bp of ghost reach.

**Verified working recipe** (USD 1Yx30Y, 2026-08-06 — recovers the terminal swap-rate distribution **under the annuity measure**):
```python
offs  = np.arange(-200., 200.001, 5.)                       # densify — BL needs > 13 points
vols  = np.interp(offs, offs_q, vols_q) / 1e4               # linear in offset (SmileSurface rule)
K     = F + offs / 1e4
recv  = [(bachelier_call_price(k, F, s, T, 1.0) - (F - k)) * 100. for k, s in zip(K, vols)]  # receiver, rate-%
ri = RNDInput(symbol="USD 1Yx30Y", as_of=D,
              forward_price=100. - F*100., forward_rate=F*100.,
              time_to_expiry=T, expiry_date=cube.expiry_date("1Y"),
              discount_factor=1.0,                          # premia already per unit annuity
              strikes_price=(100. - K*100.)[order], call_premiums=np.array(recv)[order],
              strike_source="citivelo_cube_smile_interp_5bp")
bl = extract_rnd_breeden_litzenberger(ri, smoothing_param=1e-6, spline_order=4,
        n_ghost_points=10, ghost_extension_bps=5.0, bin_width_bps=25.0,
        grid_points=4000, rate_floor=None)
```
Receiver → price-space call because `price = 100 − rate`, so a call on price is a floor on rate.

Measured:
| params | mean | fwd tie-out | std | skew | kurt | pre-norm mass | ghost frac |
|---|---|---|---|---|---|---|---|
| ghost 25bp, s=1e-8, 13 raw nodes | 1.3911% | **−308.60 bp** ✗ | 0.8767% | 0.747 | 3.99 | 61.86 | 0.867 |
| ghost 5bp, s=1e-6, 81 nodes | 4.4400% | −3.70 bp | 0.7080% | +0.042 | 3.307 | 0.978 | 0.008 |
| ghost 5bp, s=1e-8, 81 nodes | 4.4377% | −3.94 bp | 0.7138% | +0.012 | 3.401 | 0.979 | 0.008 |
| ghost 2bp, s=1e-8, 81 nodes | 4.4499% | **−2.72 bp** | 0.7019% | +0.129 | 3.239 | 0.976 | 0.004 |

Row 1 is the failure mode — report it so it isn't repeated. Forward = 4.4771%. BL std 70–71 bp/yr vs cube ATM **75.32 bp** (BL truncates at ±200 bp). BKM on the same input: `std_rate=0.8041%` → **80.41 bp/yr**, `skew=+0.3394`, `excess_kurt=+1.0406`, hawkish/dovish tail variance 0.5465/0.4535, no warnings.
`BreedenLitzenbergerResult` also gives `.percentile(p)`, `strike_grid_rate`, `rnd_density`, `rnd_cumulative`, `bin_edges_rate`, `bin_probabilities`, `bin_labels`, `pre_normalization_mass`, `forward_residual_bp`, `ghost_mass_fraction`, `warnings`.

Pure-Python Bachelier (no QuantLib, so an independent cross-check): `RVUtils/ImpliedDistribution/_bachelier.py` — `bachelier_call_price/put_price`, `put_to_call_parity`, `bachelier_vega`, `bachelier_implied_vol` (bracketed bisection, NaN outside the no-arb band), `bachelier_implied_vols_vectorized`, `bachelier_call_prices_vectorized`.

---

## 5. Cap/floor vols

**There are no real cap/floor vol quotes in this repo.** `MDP/STIRCapFloors/` builds a **synthetic cap/floor as a strip of listed quarterly SR3 (SOFR futures) options**. The Citi Velocity catalog has `RATES.SPREAD_OPTIONS.<ccy>.OPT_CAP.{PRICE,VOL}` (single-look CMS *spread* caps, 1M–5Y) — not a rates cap/floor surface. Excel constants list `CVDCAPFLOOR`/`CVDCMSCAPFLOOR` sheets, but nothing under `MDP/` builds from them.

**Verified working, offline (2026-08-06, 3Mx2Y cap):**
```python
from MDP.STIRCapFloors import STIRCapFloorMDP
from Query.STIRCapFloors.STIRCapFloorQuery import STIRCapFloorQuery      # __init__.py is EMPTY —
from Query.STIRCapFloors.STIRCapFloorStructure import STIRCapFloorStructure  # import from submodules
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValue

mdp = STIRCapFloorMDP(source="STIRCAPFLOOR-QL",
                      curve_source="ERIS_EOD_LIVE-QL_BASIC",
                      option_source="BARCHART_STIRFO-QL")
ctx = mdp.get_pricer({"curve_name":"USD-SOFR-1D", "timestamp": D, "structure":"CAP",
                      "expiry":"3M", "tail":"2Y",
                      "weight_method":"equal", "strike_convention":"atm_per_caplet",
                      "contracts":1.0})
```
```
ctx.id(): CAP|USD-SOFR-1D|2026-08-06|2026-12-16|2028-12-20|equal|atm_per_caplet|1
n legs: 8   SFRZ26|9600P P K=96.0 Krate=4.0 src=market
            SFRH27|9575P P K=95.75 Krate=4.25 src=market ...
PRICE       = 3.145        NPV         = 3.145
BPVOL       = 95.6005      (unit-weighted mean per-caplet normal vol, bp)
FLAT_BP_VOL = 97.8302      (the single flat normal vol that reprices the whole strip, bp)
VEGA_01     = 80.5584      DV01 = -93.9872      GAMMA_01 = 0.8493
```

`STIRCapFloorStructure`: `CAP`, `FLOOR` (a CAP is a strip of **puts** on price; `_capfloor_right`: CAP→`"P"`, FLOOR→`"C"`).
`STIRCapFloorValue`: `PRICE, NPV, BPVOL, FLAT_BP_VOL, DV01, DELTA, GAMMA, GAMMA_01, VEGA, VEGA_01, THETA, BREAKDOWN`.
`BREAKDOWN` returns per-caplet dicts including `iv_normal_bps`, `forward_rate`, `strike_rate`, `fomc_loading`, `quarter_end_flag`, `quote_source` — this is the per-caplet vol vector you'd feed a calibration.

Query kwargs: `expiry`/`tail` (must be **multiples of 3M**), or `shorthand`, or explicit `swap_start`+`swap_end`; `weight_method` (`"equal"`), `strike_convention` (`"atm_per_caplet"` | `"flat_swap_rate"`), `contracts`. Under `flat_swap_rate` a missing listed strike falls back to `_sabr_fallback_pricer` and tags `quote_source="sabr_fallback"`.

**For Ho-Lee: there is no Ho-Lee (or Hull-White/G2++) code anywhere in the repo** — the only short-rate file is `RVUtils/Interpolation/Vasicek.py` (curve interpolation). What you have to calibrate against:
- **Caplet-level normal vols** — `STIRCapFloorValue.BREAKDOWN[i]['iv_normal_bps']` with `forward_rate`, `strike_rate`, `expiry_date`. Horizon is bounded by listed SR3 contracts (~3–5 y), quarterly grid only.
- **Flat strip vol** — `STIRCapFloorValue.FLAT_BP_VOL` (bisection over `ql.bachelierBlackFormula`, `STIRCapFloorValue.py:_flat_bp_vol`).
- **Swaption ATM term structure** — the far better Ho-Lee target given `sigma_HL` is a single short-rate vol: the Citi cube's 17×9 ATM grid, daily to 2015 (§6).
- **Realised cap/floor trades** — `SDRUtils/products/_capfloors/pricing.py::strip_cap_vol(trade, curve, valuation_date)` backs a flat normal vol out of an SDR-reported cap/floor premium; plus `bachelier_caplet`, `bachelier_floorlet`, `build_caplet_schedule`, `build_capfloor_upi_set`.
- **SABR** — `MDP/sabr_calibration.py::calibrate_sabr_normal(forward, time_to_expiry, strikes_arr, vols_arr, beta=0.5, method="nelder-mead"|"de-gn") -> (alpha, rho, nu, rmse)` and `calculate_calibration_rmse(...)`. Normal-SABR (Hagan), used today only by `STIRFutureOptionMDP` and `USTFutureOptionMDP`; it is model-agnostic and would take the Citi 13-offset smile directly.

---

## 6. Historical coverage — measured on disk

**Store:** `Caching/swaption_cube_store.py::SwaptionCubeStore` (content-addressed parquet, one long row per node).
```
Base dir : C:\Users\chris\AppData\Local\ARBS\Cache\swaption_cube_store
Raw dir  : C:\Users\chris\AppData\Local\ARBS\Cache\swaption_cube_store\vol_raw
Partition: vol_raw\asset=<ASSET>\date=<YYYY-MM-DD>\<sha256>.parquet
Asset    : USD-SWAPTIONVOL-CITIVELOEXCEL   (the ONLY asset present — no EUR/GBP/JPY)
```
Resolution chain (`_default_base_dir`): `$ARBS_CACHE_DIR/swaption_cube_store` → `platformdirs.user_cache_dir("ARBS", appauthor=False)/swaption_cube_store` → `%LOCALAPPDATA%\ARBS\Cache\swaption_cube_store`. `ARBS_CACHE_DIR` is **unset** here, so path 2 applies. Supabase L2 is **opt-in** (`ARBS_SWAPTION_CUBE_L2`, default `off`).

```python
from MDP.IRSwaptions.CITIVELO.cube_store import stored_coverage, load_stored_cubes
stored_coverage("USD")
# {'asset':'USD-SWAPTIONVOL-CITIVELOEXCEL','n_days':2702,
#  'first':datetime.date(2015,10,8),'last':datetime.date(2026,8,12)}
```

**All 2,702 stored days scanned. Distinct shapes:**
```
nex ntn nof   rows  source                              cnt    first        last
 17   9   1    153  citivelo_excel_warm/DAILY/atm_only  1067  2015-10-08  2020-01-23
 17   9  13   1989  citivelo_excel_warm/DAILY           1575  2020-04-22  2026-08-11
  8   9  13    936  citivelo_excel_warm/DAILY              4  2020-01-24  2020-03-24
  7   9  13    819  citivelo_excel_warm/DAILY             20  2020-01-27  2020-02-27
  6   9  13    702  citivelo_excel_warm/DAILY              6  2020-02-28  2020-03-18
  5   9  13    585  citivelo_excel_warm/DAILY              5  2020-03-06  2020-03-19
  4   8  13    416  citivelo_excel_warm/DAILY              3  2020-03-12  2020-03-20
  3   9  13    351  citivelo_excel_warm/DAILY              1  2020-03-11
 17   4  13    884  citivelo_excel_warm/DAILY              6  2020-03-25  2020-04-14
 17   3  13    663  citivelo_excel_warm/DAILY              9  2020-03-26  2020-04-20
 17   2  13    442  citivelo_excel_warm/DAILY              4  2020-03-27  2020-04-21
  1   5  13     65  citivelo_excel_warm/DAILY              1  2020-03-09
  1   2  13     26  citivelo_excel_warm/DAILY              1  2026-08-12   <- partial (2Y x 7Y,10Y)
```
Offset axis: **1 offset** (`[0.0]`) for 1,067 days `2015-10-08..2020-01-23`; **13 offsets** for 1,635 days `2020-01-24..2026-08-12`. Full 17×9 axes on 2,661 of 2,702 days.

Per-year day counts: 2015:57, 2016:248, 2017:248, 2018:249, 2019:250, 2020:249, 2021:249, 2022:249, 2023:250, 2024:250, 2025:249, 2026:154.

**Curve store** (needed to price — the cube is deliberately curve-free):
```
C:\Users\chris\AppData\Local\ARBS\Cache\curve_store
asset USD-SOFR-1D-CITIVELOEXCEL: n=5506, 2005-01-03 .. 2026-08-07
```
⚠️ **The curve lags the cube.** End-to-end pricing is verified only through **2026-08-07** even though the cube holds 08-11/08-12.

Warm scripts: `scripts/citivelo_swaption_vol_warm.py` (writes the cube store), `scripts/citivelo_swaption_ts_warm.py`, `scripts/citivelo_swaption_ts_warm_deep.py`.

---

## 7. Is 1Yx30Y ATMF straddle vol available daily 2019-01 → 2026-08?

**Two different answers depending on the layer.**

### Data layer — essentially yes
```
1Yx30Y ATM node present on 2,661 / 2,702 stored days   (2015-10-08 .. 2026-08-11)
In window 2019-01-01..2026-08-31: 1,859 / 1,900 stored days
vs. NYSE-ignorant business days 2019-01-02..2026-08-12: 1,986 bdays, 1,859 present, 127 missing
```
The 127 missing decompose exactly:
- **43 consecutive business days `2020-01-24 → 2020-03-24`** — one contiguous run. These days **exist** in the store with the full 13-offset smile, but the **expiry axis truncates to ≥4Y** (e.g. 2020-01-24: `['4Y','5Y','7Y','10Y','12Y','15Y','20Y','30Y']`). There is no 1Y row. Since 2020-02-03 etc. are also simply absent, and Excel serves ATM-only for that era, **this gap is not backfillable**.
- **83 single days, every one a US holiday** — verified list: 2019-01-21, 02-18, 04-19, 05-27, 07-04, 09-02, 10-14, 11-11, 11-28, 12-25; 2020-01-01, 01-20, 04-10, 05-25, 07-03, 09-07, 10-12, 11-11, 11-26, 12-25; 2021-01-01, 01-18, 02-15, 03-19, 04-29, 05-31, 07-05, 09-06, 10-11, 11-11, 11-25, 12-24; … 2026-01-01, 01-19, 02-16, 05-25, 06-19, 07-03. **Zero missing runs of length > 1 outside the 2020 window.**
- **2026-08-12** (partial 2Y-only day) and **08-13/08-14** (not yet warmed; today is 2026-08-14).

**Smile (OTM offsets) at 1Yx30Y: 1,594 days, first `2020-03-25`, last `2026-08-11`.** Per year: 2020:194, 2021:249, 2022:249, 2023:250, 2024:250, 2025:249, 2026:153.

Spot values sampled straight from parquet: 2015-10-08 → 82.22; 2016-12-23 → 84.1112; 2018-03-12 → 64.5472; 2019-05-23 → 54.0873; 2019-06-03 → 59.2795; 2020-01-23 → 60.6853; 2020-10-02 → 72.4023; 2021-12-17 → 71.3268; 2023-03-03 → 91.1230; 2024-05-13 → 90.4341; 2025-07-28 → 89.6575; 2026-08-06 → 75.3207.

### Full `Query/IRSwaptions` stack — **only from 2020-03-25 onward**

Probed dates, `IRSwaptionMDP(source="CITIVELO-RL", curve_source="CITIVELO_EXCEL")`, 1Yx30Y ATMF STRADDLE:
```
2019-01-03 atm_only  PRICE-ERR ValueError: A swaption CUBE needs strike offsets...
2019-06-03 atm_only  PRICE-ERR (same)
2020-01-23 atm_only  PRICE-ERR (same)
2020-03-25 full  n_off=13  ATMF=0.6266%  NVOL=83.2258bp  SPOT_NPV=18,364,809  VEGA_01=220,662
2021-06-01 full  n_off=13  ATMF=1.8213%  NVOL=70.1251bp  SPOT_NPV=13,122,523  VEGA_01=187,130
2023-03-03 full  n_off=13  ATMF=3.0792%  NVOL=91.1230bp  SPOT_NPV=13,170,099  VEGA_01=144,531
2025-07-28 full  n_off=13  ATMF=4.1176%  NVOL=89.6575bp  SPOT_NPV=11,808,754  VEGA_01=131,710
2026-08-07 full  n_off=13  ATMF=4.4697%  NVOL=73.6503bp  SPOT_NPV= 9,315,713  VEGA_01=126,486
```
The context builds fine on ATM-only days (provenance `origin='swaption_cube_store'`, `smile='atm_only'`); the **strike resolution** is what fails. Traced chain:
```
IRSwaptionQuery.resolve_package -> _resolve_strike -> _strike_inputs -> leg_model_vol
  -> _surface_model_vol -> CitiVeloSwaptionCube.volatility(option_time, swap_length, strike)
  -> self.with_backend("ql") -> QLSwaptionPricer.__init__ (ql_pricing.py:219)
  -> build_ql_swaption_cube (ql_cube.py:466)
ValueError: A swaption CUBE needs strike offsets; this cube data has none.
```
So it is not an engine problem — the `-RL` path still routes the vol read through the QuantLib surface (as `provider.py:369-375` warns).

**Verified workarounds for 2015-10-08 → 2020-01-23** (both produce real numbers on 2019-06-03):

*(a) Raw ATM vols, no pricing:*
```python
from MDP.IRSwaptions.CITIVELO.cube_store import load_stored_cubes
s = load_stored_cubes("USD", [dt.date(2019,6,3)])[dt.date(2019,6,3)]
s.smile          # 'atm_only'
s.data.atm_vol("1Y","30Y")   # 59.2795   (bp)
s.data.to_frame()            # 153 rows, cols: as_of currency expiry tenor offset_bp vol_bp
                             #                 atm_bp spread_bp expiry_years tenor_years
```

*(b) Full ATM pricing via the rl-native cube + `RLSwaptionEngine` with an explicit strike:*
```python
cube = build_citivelo_swaption_cube(cube=s.data, rl_curve=curve.handle(), ql_curve=None,
                                    backend="rl-native", verify=False)
# CitiVeloSwaptionCube(USD 2019-06-03 via rl-native, 17x9x1, available=['rl-native','rl-hand'])
cube.normal_vol("1Y","30Y")   # 59.2795
cube.forward("1Y","30Y")      # 0.019788045945095527   annuity 22.4523   tte 1.00274
cube.price("1Y","30Y", F, right="payer")     # 5,317,046.99  (= receiver, ATM)
cube.vega ("1Y","30Y", F, right="payer")     #    89,694.53
```
and the engine off the context directly (bypassing `_resolve_strike`):
```
forward=0.019787479977361286  annuity=22.453215875359906  normal_vol=0.00592795
spot_npv=5,316,616.84  implied_normal_vol_bps=59.2795  delta=0.49996  gamma=0.0067207
vega_01=89,697.99  dv01=112,257.54  theta_1d=-7,268.97
```
Note the `ql`/`ql-sabr` backends are **absent** from `backends_available` on ATM-only days — that is data, not a cache miss. `MDP/IRSwaptions/CITIVELO/cube_store.py::explain_missing_smile(stored, backend=...)` writes the reason out in full and is what the provider raises for QL backends.

**Bottom line:** 1Yx30Y ATMF **normal vol** is available daily (US business days) from 2015-10-08 to 2026-08-11 with two exceptions — the 43-day 2020-01-24→03-24 window and 2026-08-12→14. Full straddle **pricing through the Query stack** is daily from **2020-03-25** to **2026-08-07** (curve-store-limited); before 2020-01-24 you must use route (a) or (b) above.

---

### Files
- `C:\Users\chris\clee\ARBS\MDP\IRSwaptions\IRSwaptionMDP.py`
- `C:\Users\chris\clee\ARBS\MDP\IRSwaptions\CITIVELO\{provider,cube_store,rl_engine,__init__}.py`
- `C:\Users\chris\clee\ARBS\Query\IRSwaptions\{IRSwaptionQuery,IRSwaptionStructure,IRSwaptionValue,pricer,utils,adapter,position_handler,__init__}.py`
- `C:\Users\chris\clee\ARBS\MDP\CitiVelocityExcel\vol\{__init__,cube_data,swaption_cube,ql_cube,ql_pricing,rl_cube,rl_native_cube,spot_check,live_snapshot}.py`
- `C:\Users\chris\clee\ARBS\Caching\swaption_cube_store.py`
- `C:\Users\chris\clee\ARBS\MDP\sabr_calibration.py`
- `C:\Users\chris\clee\ARBS\RVUtils\ImpliedDistribution\{_types,_bachelier,_bkm,_breeden_litzenberger,_data_prep,_gaussian_mixture,implied_distribution}.py`
- `C:\Users\chris\clee\ARBS\RVUtils\StrikelessVol\{citivelo,conventions,premium_mark,straddle_book,panels,greeks,replication}.py`
- `C:\Users\chris\clee\ARBS\MDP\STIRCapFloors\STIRCapFloorMDP.py`, `C:\Users\chris\clee\ARBS\Query\STIRCapFloors\{STIRCapFloorQuery,STIRCapFloorStructure,STIRCapFloorValue,pricer,adapter}.py`
- `C:\Users\chris\clee\ARBS\SDRUtils\products\_capfloors\pricing.py`
- `C:\Users\chris\clee\ARBS\notebooks\backtests\citivelo_rv\build_vol_panel.py`, `C:\Users\chris\clee\ARBS\notebooks\backtests\citivelo_rv\sv_h16b_qdb.py`
- `C:\Users\chris\clee\ARBS\docs\superpowers\specs\2026-08-08-citivelo-rv-loop-findings.md` (§H16b — recipe of record)

Scratch scripts used (rerunnable): `C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee\fd598297-c759-4904-8a06-2f2d2a03d199\scratchpad\{probe_store,scan_all,scan2,e2e2,e2e3,e2e4,e2e5,rnd_demo,rnd_demo2,capfloor}.py`