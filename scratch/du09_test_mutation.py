"""Do the universe tests actually fail when the code is wrong?

A suite that passes against a broken implementation is worse than no suite.
Each mutation below is a plausible defect; the named test must fail on it.
"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tests"))

from SDRUtils.dealer_direction import types, universe as un
import test_dealer_direction_universe as T


def run(fn, *args):
    try:
        fn(*args)
        return None
    except Exception as e:  # noqa: BLE001 - a failure is the expected outcome
        msg = (str(e).splitlines() or [""])[0][:100]
        return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


CASES = []


def case(name, mutate, restore, tests):
    CASES.append((name, mutate, restore, tests))


# 1. partial leg order -- drop the effective-date tiebreaker
_orig_sort = list(un._SORT_KEYS)
case("drop `effective_date` from the sort key (partial order)",
     lambda: un._SORT_KEYS.__setitem__(slice(None),
                                       ["_unit_group", "_exp", "leg_order"]),
     lambda: un._SORT_KEYS.__setitem__(slice(None), _orig_sort),
     [("leg_order_is_total", T.test_leg_order_is_total_and_independent_of_input_row_order)])

# 1b. maturity order dropped entirely -- sort on trade_id alone
case("sort legs on trade_id alone (no maturity order)",
     lambda: un._SORT_KEYS.__setitem__(slice(None), ["_unit_group", "trade_id"]),
     lambda: un._SORT_KEYS.__setitem__(slice(None), _orig_sort),
     [("fly_belly", T.test_fly_belly_is_iloc_1_and_curve_front_is_iloc_0),
      ("leg_order_is_total", T.test_leg_order_is_total_and_independent_of_input_row_order)])

# 2. exclusion precedence reversed
_orig_prec = un.EXCLUSION_PRECEDENCE
case("reverse the exclusion precedence",
     lambda: setattr(un, "EXCLUSION_PRECEDENCE", tuple(reversed(_orig_prec))),
     lambda: setattr(un, "EXCLUSION_PRECEDENCE", _orig_prec),
     [("basis_reads_as_index", T.test_basis_leg_reads_as_unsupported_index_not_missing_rate),
      ("one_pinned_reason", T.test_a_unit_failing_several_gates_reports_exactly_the_pinned_one)])

# 3. venue table: promote a fingerprint-tier platform to D2C
_orig_venue = dict(un.VENUE_EVIDENCE)


def _promote():
    un.VENUE_EVIDENCE["RTXF"] = (types.VENUE_D2C, un.EVIDENCE_FINGERPRINT)


case("promote the fingerprint-tier platform to D2C",
     _promote,
     lambda: (un.VENUE_EVIDENCE.clear(), un.VENUE_EVIDENCE.update(_orig_venue)),
     [("asymmetry", T.test_no_fingerprint_evidence_platform_is_ever_promoted_to_d2c)])

# 4. re-introduce the maturity cutoff
_orig_uf = un.unit_frame


def _cutoff():
    import pandas as pd

    def cut(legs):
        u = _orig_uf(legs)
        if not u.empty:
            u.loc[u["n_legs"] > 0, "exclusion"] = u["exclusion"]  # no-op guard
        return u

    def cut2(legs):
        u = _orig_uf(legs)
        return u
    # the real mutation: put MAC back in the excluded trade types
    un.EXCLUDED_TRADE_TYPES = ("MAC",) + un.EXCLUDED_TRADE_TYPES


_orig_ett = un.EXCLUDED_TRADE_TYPES
case("put MAC back into EXCLUDED_TRADE_TYPES",
     _cutoff,
     lambda: setattr(un, "EXCLUDED_TRADE_TYPES", _orig_ett),
     [("mac_with_upfront_kept", T.test_mac_with_an_upfront_is_kept)])

# 5. UWIN never routed in
_orig_res = un._resolve_upfront_vec


def _no_uwin():
    def patched(u):
        u = u.copy()
        u["uwin_sum"] = 0.0
        return _orig_res(u)
    un._resolve_upfront_vec = patched


case("stop routing UWIN in (the stir_flow behaviour)",
     _no_uwin,
     lambda: setattr(un, "_resolve_upfront_vec", _orig_res),
     [("uwin_on_termination", T.test_termination_upfront_comes_from_uwin_when_it_is_there),
      ("uwin_on_new_trade", T.test_uwin_on_a_new_trade_is_still_a_fee)])

# 6. sanity: the naive tenor bound instead of the annuity
from SDRUtils.dealer_direction import sanity as S
_orig_exp = S.expected_dv01


def _naive():
    import numpy as np

    def naive(notional, tenor_years, forward_start_years=None, flat_yield=None):
        return np.asarray(notional, dtype=float) * np.asarray(
            tenor_years, dtype=float) * 1e-4
    S.expected_dv01 = naive


case("swap the annuity for the naive tenor*1e-4 bound",
     _naive,
     lambda: setattr(S, "expected_dv01", _orig_exp),
     [("deep_forward_start_clean", T.test_annuity_form_does_not_flag_a_deep_forward_start),
      ("synthetic_cases", T.test_synthetic_cases_match_the_frame_api)])

# 7. visibility measured from the frozen #96
_orig_clocks = un.build_clocks


def _vis_from_96():
    import pandas as pd

    def patched(row, **kw):
        c, f = _orig_clocks(row, **kw)
        delta = c.visibility - pd.Timestamp(c.pricing)
        return type(c)(
            pricing=c.pricing, execution=c.execution, event=c.event,
            visibility=pd.Timestamp(row.get("execution_timestamp")) + delta,
            visibility_source=c.visibility_source,
            report_lag_seconds=c.report_lag_seconds), f
    un.build_clocks = patched


case("measure visibility from the frozen #96 instead of the pricing instant",
     _vis_from_96,
     lambda: setattr(un, "build_clocks", _orig_clocks),
     [("lifecycle_visibility",
       T.test_lifecycle_visibility_is_measured_from_the_event_not_the_frozen_exec)])

# 8. no exercise/novation gate
_orig_flags = un.EXERCISE_NOVATION_FLAGS
case("delete the exercise/novation gate",
     lambda: setattr(un, "EXERCISE_NOVATION_FLAGS", ()),
     lambda: setattr(un, "EXERCISE_NOVATION_FLAGS", _orig_flags),
     [("exer_gate", lambda: T.test_single_gate_reasons(
         {"is_exercise_born": True}, types.EXCL_EXERCISE_OR_NOVATION))])

# 9. Term SOFR left in
_orig_tok = un.TERM_SOFR_TOKEN
case("stop excluding Term SOFR",
     lambda: setattr(un, "TERM_SOFR_TOKEN", "\x00NEVER\x00"),
     lambda: setattr(un, "TERM_SOFR_TOKEN", _orig_tok),
     [("term_sofr", lambda: T.test_single_gate_reasons(
         {"leg_tape_label": "USD CME Term SOFR 3M 5Y"}, types.EXCL_UNSUPPORTED_INDEX))])

# 10. amortisers left in
_orig_sched = un.NON_CONSTANT_SCHEDULES
case("stop excluding non-constant notional schedules",
     lambda: setattr(un, "NON_CONSTANT_SCHEDULES", frozenset()),
     lambda: setattr(un, "NON_CONSTANT_SCHEDULES", _orig_sched),
     [("amortizing", lambda: T.test_single_gate_reasons(
         {"upi_notional_schedule": "Amortizing"}, types.EXCL_PRICING_ERROR))])


print("=" * 92)
print("MUTATION SWEEP -- every line must read CAUGHT")
print("=" * 92)
n_bad = 0
for name, mutate, restore, tests in CASES:
    # baseline: the tests must pass unmutated
    base = [(t, run(f)) for t, f in tests]
    assert all(e is None for _, e in base), f"{name}: baseline already failing: {base}"
    mutate()
    try:
        got = [(t, run(f)) for t, f in tests]
    finally:
        restore()
    # A mutation is caught if ANY listed test fails: a test can legitimately
    # be insensitive to a mutation another test covers.
    caught = [t for t, e in got if e is not None]
    status = "CAUGHT " if caught else "MISSED "
    if not caught:
        n_bad += 1
    print(f"  {status} {name}")
    for t, e in got:
        print(f"            {t:<28} {'fails: ' + e if e else 'insensitive'}")
    # and the restore must put it back
    after = [(t, run(f)) for t, f in tests]
    assert all(e is None for _, e in after), f"{name}: restore failed: {after}"

print()
print(f"{len(CASES) - n_bad}/{len(CASES)} mutations caught")
raise SystemExit(1 if n_bad else 0)
