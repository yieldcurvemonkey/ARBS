"""Do the new tests actually bite? Mutate the code they cover and check.

A checking tool that is itself wrong reports success and hides the thing it was
built to find. Each mutation below is a plausible edit that would produce a
complete, working, wrong repricing pass; the named test must go red for it.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

SRC = pathlib.Path("C:/Users/chris/clee/ARBS-dd/SDRUtils/dealer_direction/midprice.py")
PY = "C:/Users/chris/anaconda3/envs/stir/python.exe"

MUTATIONS = [
    # (label, find, replace, test that must fail)
    ("structure_dv01 becomes gross/2 for every kind",
     "    top = max(abs(w) for w in q)\n"
     "    return max(v for v, w in zip(a, q) if abs(w) == top)",
     "    return sum(a) / 2.0",
     "test_structure_dv01_reproduces_the_frozen_classifier"),
    ("a missing lag is silently tolerated",
     "        if self.require_lag_telemetry:",
     "        if False:",
     "test_missing_lag_telemetry_raises_on_a_snapshot_governed_pricer"),
    ("one global bounded-asof policy instead of the session branch",
     '        return POLICY_STRICT if snapshot.in_session(curve_name, instant) else POLICY_HOLE',
     '        return POLICY_HOLE',
     "test_in_session_picks_strict_and_out_of_session_picks_the_bounded_asof"),
    ("the printed rate is handed over as a percent",
     "                fixed_rate=float(rate) if want_npv else None,",
     "                fixed_rate=float(rate) * 100.0 if want_npv else None,",
     "test_printed_rate_reaches_the_pricer_as_a_decimal"),
    ("a curve from the future is accepted",
     "        if mark.served_from_future:",
     "        if False and mark.served_from_future:",
     "test_a_curve_from_the_future_is_refused_because_it_contains_the_print"),
    ("a failed leg records a NaN with no reason",
     "        except Exception as exc:  # noqa: BLE001 - every failure gets a named reason\n"
     "            return LegQuote(**base, failure=EXCL_PRICING_ERROR,\n"
     "                            failure_detail=f\"{type(exc).__name__}: {str(exc)[:200]}\")",
     "        except Exception:  # noqa: BLE001\n"
     "            return LegQuote(**base, mid_pct=float('nan'), pv01=float('nan'))",
     "test_a_rateslib_error_is_reported_as_a_pricing_error_with_the_type_named"),
    ("the spec notional sentinel is priced like any other row",
     "        bad = _implausible(unit.legs)",
     "        bad = None",
     "test_the_spec_notional_sentinel_is_refused_rather_than_priced"),
    ("the T-1min snap is dropped and the trade time used directly",
     "        snap = snapshot.snap_instant(unit.clocks.pricing) if instant is None else instant",
     "        snap = unit.clocks.pricing if instant is None else instant",
     "test_prices_at_the_snapped_instant_not_at_the_trade_time"),
    ("the handle cache is never cleared",
     "        for p in self._pricers.values():\n            p._handles.clear()",
     "        pass",
     "test_the_handle_cache_can_be_cleared_and_reports_its_size"),
]


def run(test_name: str) -> bool:
    """True when the named test PASSES."""
    env = dict(os.environ, ARBS_SUPABASE_ENABLED="0")
    r = subprocess.run(
        [PY, "-m", "pytest", "tests/test_dealer_direction_midprice.py",
         "-k", test_name, "-q", "-m", "not slow", "--no-header", "-p", "no:cacheprovider"],
        cwd="C:/Users/chris/clee/ARBS-dd", capture_output=True, text=True, env=env,
    )
    return r.returncode == 0


def main() -> None:
    original = SRC.read_text(encoding="utf-8")
    ok = True
    try:
        for label, find, repl, test in MUTATIONS:
            if original.count(find) != 1:
                print(f"  SKIP  {label}: anchor matched {original.count(find)}x")
                ok = False
                continue
            SRC.write_text(original.replace(find, repl), encoding="utf-8")
            passed = run(test)
            print(f"  {'FAILS TO CATCH' if passed else 'caught':>14s}  {label}")
            print(f"                  -> {test}")
            ok = ok and not passed
    finally:
        SRC.write_text(original, encoding="utf-8")
    print(f"\nrestored; every mutation caught: {ok}")
    print("control (unmutated suite still green):",
          run("test_dealer_direction_midprice" if False else "structure_dv01"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
