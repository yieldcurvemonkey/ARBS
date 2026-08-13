"""pytest plugin: extra midprice mutations, selected by ARBS_MUT2.

Companion to scratch/rv_mut_plugin.py. These aim at the seams the post-review
fixes touch, so the new tests can be shown to bite rather than asserted to.
"""
import os

import pandas as pd


def pytest_configure(config):
    mut = os.environ.get("ARBS_MUT2", "")
    if not mut:
        return
    from SDRUtils.dealer_direction import midprice, snapshot as snap

    if mut == "mark_curve_abs_lag":
        # The sign is read HERE, not on the row price_unit returns.
        def mark_curve(self, curve_name, instant):
            policy = self.policy_for_instant(curve_name, instant)
            handle = self._pricers[policy].handle(curve_name, midprice._as_request(instant))
            lag = snap.snapshot_lag_seconds(handle)
            return midprice.CurveMark(
                policy=policy, curve_name=curve_name, requested=pd.Timestamp(instant),
                lag_seconds=None if lag is None else abs(lag),
                served_from_future=snap.served_from_future(handle),
                served_utc=midprice._served_utc(handle), handle=handle)
        midprice.SessionBranchPricer.mark_curve = mark_curve

    elif mut == "telemetry_bool_only":
        # The pre-fix guard: trust the boolean, ignore the signed lag.
        orig = midprice.UnitRepricer._assert_telemetry

        def at(self, mark, flags):
            if mark.lag_seconds is not None and mark.lag_seconds < 0:
                mark = type(mark)(**{**mark.__dict__, "lag_seconds": abs(mark.lag_seconds)})
            return orig(self, mark, flags)
        midprice.UnitRepricer._assert_telemetry = at

    elif mut == "nan_marks_are_ok":
        # The pre-fix contract: `ok` is `failure is None`, values unchecked.
        midprice.LegQuote.__post_init__ = lambda self: None

    elif mut == "stratum_defaults_to_spot":
        midprice._stratum = lambda row, instant: (
            midprice.start_class(row.get("effective_date"), instant)
            if midprice._has_date(row) else midprice.START_SPOT)

    elif mut == "refusal_policy_blank":
        midprice.UnitRepricer._default_policy = lambda self: ""

    elif mut == "refusal_drops_leg_flag":
        orig = midprice.UnitRepricer._refused

        def refused(self, unit, snap, reason, detail, flags, policy=None):
            out = orig(self, unit, snap, reason, detail, flags, policy=policy)
            out.flags = [f for f in out.flags if f != midprice.FLAG_LEG_FAILURE]
            return out
        midprice.UnitRepricer._refused = refused

    else:
        raise SystemExit(f"unknown mutation {mut!r}")
