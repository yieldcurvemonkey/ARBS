"""Mutate the three new modules and confirm the tests catch each mutation.

A suite that passes on the first run is not evidence it tests anything. Each
entry below is a real defect the file is supposed to prevent; the harness
applies it, runs the named test, restores the file, and reports whether the
test noticed.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = r"C:/Users/chris/anaconda3/envs/stir/python.exe"

LADDER = ROOT / "SDRUtils/dealer_direction/ladder.py"
HEALTH = ROOT / "SDRUtils/dealer_direction/health.py"
PROV = ROOT / "SDRUtils/dealer_direction/provenance.py"

MUTATIONS = [
    ("weight p not 2p-1", LADDER,
     "        weight = float(call.signed_weight)",
     "        weight = float(call.p)",
     "test_a_coin_flip_contributes_nothing_to_the_ladder"),

    ("stamp on execution not visibility", LADDER,
     '        "visibility_date": visibility_date(c.visibility),',
     '        "visibility_date": visibility_date(c.execution),',
     "test_the_ladder_date_is_the_visibility_date_not_the_execution_date or "
     "test_a_stale_execution_stamp_cannot_reach_the_ladder_date"),

    ("bucket the day on UTC", LADDER,
     '    return t.tz_convert(NY).date()',
     '    return t.tz_convert("UTC").date()',
     "test_the_ladder_date_is_a_new_york_date_not_a_utc_date"),

    ("read a naive EOD-fallback stamp as UTC", LADDER,
     "    if t.tzinfo is None:\n        return t.date()\n"
     "    return t.tz_convert(NY).date()",
     "    if t.tzinfo is None:\n        t = t.tz_localize(\"UTC\")\n"
     "    return t.tz_convert(NY).date()",
     "test_a_date_only_event_stamp_keeps_the_day_it_was_reported_on"),

    ("fold D2D into the customer series", LADDER,
     'LADDER_KEYS = ("bucket_space", "bucket_key", "visibility_date",\n'
     '               "venue_class", "series")',
     'LADDER_KEYS = ("bucket_space", "bucket_key", "visibility_date",\n'
     '               "series")',
     "test_d2c_d2d_and_venue_unknown_are_three_series_not_two"),

    ("pool lifecycle into flow", LADDER,
     '        "series": SERIES_LIFECYCLE if unit.is_lifecycle else SERIES_FLOW,',
     '        "series": SERIES_FLOW,',
     "test_lifecycle_prints_are_their_own_series"),

    ("consume a dealer-signed risk frame", LADDER,
     '    if "dealer_sign" in krd.columns:\n        raise DoubleSignedKRD(',
     '    if False:\n        raise DoubleSignedKRD(',
     "test_a_dealer_signed_krd_is_refused_rather_than_double_signed"),

    ("silently drop a unit with no risk row", LADDER,
     "            excluded.append(dict(meta, failure_reason=T.EXCL_PRICING_ERROR))\n"
     "            continue",
     "            continue",
     "test_a_unit_with_no_risk_row_is_excluded_not_silently_dropped"),

    ("accumulate with a default half-life", LADDER,
     "def decayed_flow(ladder, *, half_life_days, reconciliation=None)",
     "def decayed_flow(ladder, *, half_life_days=float('inf'), reconciliation=None)",
     "test_accumulation_is_never_silent"),

    ("decay on row order not calendar days", LADDER,
     "                gap = (pd.Timestamp(day) - pd.Timestamp(prev)).days",
     "                gap = 1",
     "test_the_decay_is_applied_on_calendar_days_and_travels_with_the_output"),

    ("kappa scores a degenerate marginal as perfect", HEALTH,
     "        return 0.0, hit, chance, True",
     "        return 1.0, hit, chance, True",
     "test_a_mid_biased_off_venue_scores_zero_not_one"),

    ("kappa reduced to a raw hit rate", HEALTH,
     "    return float((hit - chance) / (1.0 - chance)), hit, chance, False",
     "    return hit, hit, chance, False",
     "test_a_78_22_split_on_both_sides_is_not_skill"),

    ("read the overnight hole off the served stamp", HEALTH,
     "    return float(m.group(\"v\")) > snapshot.IN_SESSION_MAX_LAG.total_seconds()",
     "    return False",
     "test_the_overnight_hole_is_read_off_the_policy_that_fired"),

    ("pool the report lag across the block flag", HEALTH,
     "    for flag in (False, True):\n"
     "        mask = legs[\"is_block\"].fillna(False).astype(bool) == flag",
     "    for flag in (False, True):\n"
     "        mask = legs[\"is_block\"].notna()",
     "test_report_lag_is_never_pooled_across_the_block_flag"),

    ("count a pricing failure as an overnight hole", HEALTH,
     "    return pol.notna() & pol.astype(str).str.strip().ne(\"\")",
     "    return pd.Series(True, index=prov.index)",
     "test_a_unit_that_never_priced_is_not_an_overnight_hole"),

    ("price a BASIS leg and call it a success", HEALTH,
     "            status = NO_DATA if n == 0 else (ALARM if n_priced > 0 else OK)",
     "            status = NO_DATA if n == 0 else OK",
     "test_a_priced_basis_leg_is_the_alarm_not_the_success"),

    ("one-sided dead-zone threshold", HEALTH,
     '            name="dead_zone_fraction", direction="outside",\n'
     "            warn=(0.5 * reference, 2.0 * reference),\n"
     "            alarm=(0.25 * reference, 4.0 * reference),",
     '            name="dead_zone_fraction", direction="above",\n'
     "            warn=2.0 * reference,\n"
     "            alarm=4.0 * reference,",
     "test_the_dead_zone_alarm_is_two_sided"),

    ("rolling monitor ignores degradation", HEALTH,
     '    out.loc[degraded, "status"] = ALARM',
     '    out["_degraded"] = degraded',
     "test_a_halving_against_its_own_reference_alarms_before_the_link_is_gone"),

    ("benchmark includes the window it judges", HEALTH,
     '    out["reference_kappa"] = out["kappa"].shift(1).expanding().median()',
     '    out["reference_kappa"] = out["kappa"].expanding().median()',
     "test_the_rolling_monitor_sees_a_classifier_that_stops_working"),

    ("vintage blind to rateslib", PROV,
     '        "rateslib": _rateslib_version(),',
     '        "rateslib": "pinned",',
     "test_the_vintage_changes_when_rateslib_or_the_tape_generation_changes"),

    ("vintage blind to the curve source", PROV,
     '        "curve_source": curve_source or _default_curve_source(),',
     '        "curve_source": "pinned",',
     "test_the_vintage_sees_the_rateslib_upgrade_the_old_one_missed"),

    ("drop the sizeless units from the coverage table", PROV,
     "    missing = size.isna()\n    if missing.any():",
     "    missing = size.isna()\n    if False:",
     "test_a_unit_with_no_size_cannot_be_counted_as_a_zero_share"),

    ("let one unit carry two reasons", PROV,
     "    if dup.any():",
     "    if False:",
     "test_a_unit_counted_twice_breaks_the_accounting_loudly"),

    ("size a forward start as a spot of the same end date", PROV,
     "    return float(notional) * (_a(start_years + tenor_years) - _a(start_years)) * 1e-4",
     "    return float(notional) * _a(start_years + tenor_years) * 1e-4",
     "test_the_annuity_proxy_is_the_fallback_size_and_not_a_tenor_times_1e4"),
]


def main() -> int:
    bad = []
    for label, path, old, new, test in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"SKIP  {label}: anchor not found in {path.name}")
            bad.append(label)
            continue
        try:
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            proc = subprocess.run(
                [PY, "-m", "pytest", "tests/test_dealer_direction_ladder.py",
                 "-k", test, "-q", "--no-header", "-p", "no:cacheprovider"],
                cwd=ROOT, capture_output=True, text=True,
            )
        finally:
            path.write_text(original, encoding="utf-8")
        caught = proc.returncode != 0
        print(f"{'CAUGHT' if caught else 'MISSED':7s} {label}  ({test.split(' or ')[0]})")
        if not caught:
            bad.append(label)
            print(proc.stdout[-1500:])
    print()
    print(f"{len(MUTATIONS) - len(bad)}/{len(MUTATIONS)} mutations caught")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
