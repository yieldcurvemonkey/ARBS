"""pytest plugin: mutate midprice before collection, selected by ARBS_MUT."""
import os, dataclasses
import pandas as pd


def pytest_configure(config):
    mut = os.environ.get("ARBS_MUT", "")
    if not mut:
        return
    from SDRUtils.dealer_direction import midprice

    if mut == "control_dv01_sum":
        orig = midprice.structure_dv01
        def bad(kind, pv01s):
            vals = list(pv01s)
            if any(v is None for v in vals):
                return None
            return sum(abs(float(v)) for v in vals)
        midprice.structure_dv01 = bad

    elif mut == "always_strict_pricer":
        # mark_curve / price_leg ignore the session and always use the strict pricer
        def mark_curve(self, curve_name, instant):
            policy = midprice.POLICY_STRICT if self._governed else midprice.POLICY_NONE
            handle = self._pricers[policy].handle(curve_name, midprice._as_request(instant))
            from SDRUtils.dealer_direction import snapshot as snap
            return midprice.CurveMark(
                policy=policy, curve_name=curve_name, requested=pd.Timestamp(instant),
                lag_seconds=snap.snapshot_lag_seconds(handle),
                served_from_future=snap.served_from_future(handle),
                served_utc=midprice._served_utc(handle), handle=handle)
        def price_leg(self, curve_name, instant, effective_date, maturity_date,
                      notional, fixed_rate=None):
            policy = midprice.POLICY_STRICT if self._governed else midprice.POLICY_NONE
            return self._pricers[policy].price_leg(
                curve_name, midprice._as_request(instant), effective_date,
                maturity_date, notional, fixed_rate=fixed_rate)
        midprice.SessionBranchPricer.mark_curve = mark_curve
        midprice.SessionBranchPricer.price_leg = price_leg

    elif mut == "gross_pv01_unsigned":
        orig = midprice.UnitRepricer.price_unit
        def price_unit(self, unit, *, instant=None):
            out = orig(self, unit, instant=instant)
            if out.gross_pv01 is not None:
                out.gross_pv01 = sum(p for p in out.pricing.leg_pv01)  # no abs
            return out
        midprice.UnitRepricer.price_unit = price_unit

    elif mut == "clock_execution":
        orig = midprice.UnitRepricer.price_unit
        def price_unit(self, unit, *, instant=None):
            unit = dataclasses.replace(
                unit, clocks=dataclasses.replace(unit.clocks,
                                                 pricing=unit.clocks.execution))
            return orig(self, unit, instant=instant)
        midprice.UnitRepricer.price_unit = price_unit

    elif mut == "spot_window_10":
        midprice._SPOT_WINDOW_DAYS = 10

    elif mut == "lag_abs":
        orig = midprice.UnitRepricer._assert_telemetry
        def at(self, mark, flags):
            return orig(self, mark, flags)
        # record abs lag on the row
        origpu = midprice.UnitRepricer.price_unit
        def price_unit(self, unit, *, instant=None):
            out = origpu(self, unit, instant=instant)
            if out.pricing.snapshot_lag_seconds is not None:
                out.pricing.snapshot_lag_seconds = abs(out.pricing.snapshot_lag_seconds)
            return out
        midprice.UnitRepricer.price_unit = price_unit
    else:
        raise SystemExit(f"unknown mutation {mut!r}")
