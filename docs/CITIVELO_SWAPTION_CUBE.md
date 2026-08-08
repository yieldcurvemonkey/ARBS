# The Citi Velocity swaption cube: one object, two backends

Design decision for the consolidation of `MDP/CitiVelocityExcel/vol`. Written before
the code, so the reasoning survives the diff.

## What was there

Four objects, three of them pricers, no two with the same API:

| object | what it is | how you reached it |
|---|---|---|
| `SwaptionCubeData` | the dated record - ATM frame + `skew[offset_bp]` frames, normal vol in bp | `fetch_cube()` / `cube_from_quotes()` |
| `CitiVeloNormalVolCube` | `PPSplineF64` surface priced through `Query.Base.bachelier` | `build_rl_vol_cube(backend="hand")` - **the default** |
| `NativeSwaptionCube` | `rl.IRSplineCube` + `rl.IRSCall` | `build_rl_vol_cube(backend="native")` |
| `QLSwaptionCube` | `ql.InterpolatedSwaptionVolatilityCube` (or SABR) | `build_ql_swaption_cube()` - a **separate call path** |

Three consequences, all measured rather than asserted:

1. **`NativeSwaptionCube` was unreachable from the MDP.** `CitiVeloPricer.rl_vol_cube()`
   calls `build_rl_vol_cube(...)` with no `backend=`, and its own `**kwargs` are routed to
   `cube_data()` (the axis arguments), not to the builder. Every cube the MDP or the
   `Query/CitiVelocity` layer produced was the hand-built one. The native cube existed only
   in `harvest/verify_live.py`, the tests and `vol/_smoke.py`.
2. **The QuantLib "premium" was not a QuantLib price.** `CitiVeloPricer.ql_option_premium`
   took the QL cube's vol but the *rateslib* cube's forward, annuity and time to expiry and
   pushed them through `Query.Base.bachelier` - no `ql.Swaption`, no
   `BachelierSwaptionEngine`. It also divided an already-decimal forward and strike by 100
   while leaving the vol in decimals, so every **off-the-money** premium it returned was
   wrong by a factor of 100 in moneyness. At the money it was right, which is why nothing
   noticed. See "the first kill" below.
3. **Nothing tied any of it to the repo's own swaption product.** `MDP/IRSwaptions` +
   `Query/IRSwaptions` already carry 13 structures, 20 value metrics, a strike grammar
   (`"ATMF+25"`), a backtest position handler and a timeseries builder. Citi's cube reached
   none of it.

## What it is now

### 1. One pricer object

`MDP/CitiVelocityExcel/vol/swaption_cube.py::CitiVeloSwaptionCube`

```python
cube = build_citivelo_swaption_cube(
    cube=cube_data,            # SwaptionCubeData - unchanged, still the data layer
    rl_curve=rl_curve,         # for the rateslib backends
    ql_curve=ql_handle,        # for the QuantLib backend
    backend="rl-native",       # | "rl-hand" | "ql" | "ql-sabr"
)
cube.price("1Y", "10Y", strike=cube.forward("1Y", "10Y") + 25e-4, right="payer")
```

One API - `forward`, `annuity`, `time_to_expiry`, `normal_vol`, `smile`, `price`,
`premium`, `vega`, `implied_normal_vol`, `to_frame`, `implied_vol_surface_frame`,
`swaption` - over **ATM and every OTM offset**, in whichever backend is selected. The three
classes above become the internals it delegates to; they keep their modules, their names and
their entry points, because 31 tests pin them by return type and by module path.

The QuantLib backend now prices with `ql.Swaption` + `ql.BachelierSwaptionEngine` off the
QuantLib curve, which is what it always claimed to do.

Two aliases exist for interoperation rather than for beauty:

* `volatility_at_point(option_time, swap_length, strike) -> decimal` - the protocol
  `Query/IRSwaptions/pricer.py::leg_cube_vol` already speaks (MONKEYCUBE and
  GSQUANT_MC_ENHANCED both implement it).
* `volatility(option_time, swap_length, strike, extrapolate=True) -> decimal` - the
  `ql.SwaptionVolatilityStructure` read signature, so `_surface_model_vol` works against
  this object with no dispatch at all.

### 2. Reachable through the repo's seams

* `CitiVeloPricer.swaption_cube(currency, backend=...)` - the Citi Velocity MDP seam.
  `rl_vol`, `ql_vol`, `rl_option_premium` and `ql_option_premium` are rewritten onto it, so
  `Query/CitiVelocity`'s `RL_VOL` / `QL_VOL` / `RL_OPTION_PREMIUM` / `QL_OPTION_PREMIUM`
  values price through the one object.
* `IRSwaptionMDP.VOL_PROVIDERS["CITIVELO"]` - `source="CITIVELO-QL"` builds an
  `IRSwaptionMarketContext` that the existing, unchanged `Query/IRSwaptions` layer prices.
  Every structure, every value metric, the strike grammar and the backtest handler come for
  free.
* `IRSwaptionMDP.ENGINE_FACTORIES["RL"]` - `source="CITIVELO-RL"` prices the same context
  through rateslib.

### 3. Why the context could be widened at all

`IRSwaptionMarketContext`'s fields are annotated with QuantLib types, but the annotations are
not enforced and `tests/test_ir_swaption_mdp.py:66` already proves it: it registers a fake
provider and an engine factory that returns a bare `object()`, and drives
`source="TESTPROV-TESTENG"` end to end. The engine seam is **data**, not a QuantLib type.

What is enforced is the runtime gate at `IRSwaptionMDP.py:396`, which requires the curve to
expose `handle()` and `index()`. `RLIRSwapCurve` exposes both - so the gate passes and then
the wrong types flow downstream (`handle()` returns an `rl.Curve`, `index()` a fixings
`Series`, and `daycounter()` returns `None` because the base-class stub makes `hasattr` true
and the `ql.Actual365Fixed()` fallback unreachable). The widening therefore makes that gate
**engine-aware** rather than removing it: `QL` keeps the old requirement with a better
message, `RL` requires a rateslib curve instead.

Nothing about `GSQUANT-QL`, `MONKEYCUBE-QL` or `GSQUANT-MC-ENHANCED` changes. The one place
providers are handed something new - `curves=` - is opt-in per provider
(`vol_provider.wants_curves = True`), because `MONKEYCUBE`'s provider forwards `**kwargs`
straight into `get_sabr_vol_surfaces` and an unexpected keyword would break it.

## The spot check, and why the old one could not fail

The existing reconciliation reads each node's vol back out of the cube and compares it with
the Citi quote. It scores 2.8e-14 bp, and it is a **tautology**: the interpolator is exact at
its own data sites by construction. It cannot see a wrong annuity, a wrong schedule, a wrong
day count, a wrong discounting convention or a strike/forward misalignment, because none of
those touch the interpolator.

`MDP/CitiVelocityExcel/vol/spot_check.py` closes the loop instead:

1. price the actual swaption at `strike = forward + offset/1e4`, through the pricer object,
   in **both** backends;
2. invert that premium back to a normal vol with
   `RVUtils/ImpliedDistribution/_bachelier.py::bachelier_implied_vol` - a **pure-Python
   bisection over `scipy.stats.norm`**, the only implied-vol inverter in the repo that is not
   QuantLib. `Query.Base.bachelier.implied_normal_vol` is
   `ql.bachelierBlackFormulaImpliedVolChoi`, i.e. the same library that priced it, and is
   therefore useless as a cross-check;
3. **cross the annuities**: the QuantLib premium is inverted with the rateslib
   `(forward, annuity, tte)` and the rateslib premium with the QuantLib ones. A backend's own
   annuity can never be used to invert its own price - `NativeSwaptionCube.annuity()` is
   itself backed out of that same ATM premium, so the error would cancel exactly;
4. compare against **Citi's quoted vol** for that node, and break the error out by expiry, by
   tenor and by offset, naming the worst nodes. A max alone hides a corner;
5. cross-check the rateslib premium against the QuantLib premium at the same node, on a
   **mirrored curve** - `ql.DiscountCurve` built from the rateslib curve's own nodes, both
   log-linear on discount factors - so a price gap means a schedule or annuity difference and
   not an interpolation difference;
6. assert put-call parity at every node, monotonicity of premium in strike, and that the ATM
   node's forward is the curve's forward.

It is mutation-verified against **real Citi quotes** (`tests/fixtures/citivelo_live_cube_snapshot.json`,
USD 2026-08-06, 5 expiries x 4 tenors x 12 offsets + ATM, captured live in 8 `CV*` calls):
shift one node 1 bp, transpose two tenor slices, perturb one forward, scale one annuity by
1.01, and swap payer for receiver on one node. Each must make the check fail; the last two
exist because the first three only exercise the vol-read leg.

## The first kill

The `ql_option_premium` moneyness bug above was found by this design, not by the tests: the
old check could not see it because it never priced anything. It is the reason the unified
object prices QuantLib with `ql.Swaption` rather than by borrowing another backend's
underlying.

## What is deliberately NOT done

* **No renames and no deletions.** `build_rl_vol_cube`, `build_ql_swaption_cube`,
  `CitiVeloNormalVolCube`, `NativeSwaptionCube`, `QLSwaptionCube` and
  `compare_backends` all keep working with unchanged behaviour. Demotion is by
  documentation and by a new entry point, because `test_backend_selector_returns_the_right_class`
  pins the selector by return type and several tests import the modules directly.
* **No new `IRSwapsMDP` curve source.** A QuantLib view of the Citi curve is needed only to
  make the cross-backend premium comparison mean something, so it lives in the spot check as
  `build_ql_mirror_curve(rl_curve)` (~15 lines) rather than as a new MDP branch.
* **`premium_override` is not supported on `CITIVELO-RL`.** The override path inverts through
  `ql.Swaption.impliedVolatility`; the RL engine raises `NotImplementedError` naming it,
  rather than silently returning a number from a different model.
