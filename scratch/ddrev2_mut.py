"""Mutation battery for the ladder / health / provenance review.

One plugin, one mutation per run, selected by the ``DDREV_MUT`` environment
variable. Mutations are applied by rebinding module attributes at
``pytest_configure`` so that NO file on disk is edited -- other agents are
running tests in this same worktree.

Body mutations go through ``inspect.getsource`` -> textual replace -> ``exec``
into the module's own ``__dict__``, so the replacement closes over the real
module globals.
"""
import inspect
import os
import textwrap


def _rewrite(mod, fn_name, old, new):
    src = textwrap.dedent(inspect.getsource(getattr(mod, fn_name)))
    assert old in src, f"{fn_name}: anchor not found: {old!r}"
    exec(compile(src.replace(old, new), f"<mut:{fn_name}>", "exec"), mod.__dict__)


def pytest_configure(config):
    from SDRUtils.dealer_direction import health, ladder, provenance

    which = os.environ.get("DDREV_MUT", "")

    if which == "m2_weight_guard_noop":
        ladder._assert_weight_agrees_with_side = lambda call: None

    elif which == "m3_orient_abs":
        _rewrite(ladder, "orient_to_received",
                 'krd[KRD_VALUE_COL] = krd[value_col].astype("float64") * signs',
                 'krd[KRD_VALUE_COL] = krd[value_col].astype("float64") * signs.abs()')

    elif which == "m4_weight_is_p":
        _rewrite(ladder, "unit_ladder_rows",
                 "weight = float(call.signed_weight)",
                 "weight = float(call.p)")

    elif which == "m5_decay_row_order":
        _rewrite(ladder, "decayed_flow",
                 "gap = (pd.Timestamp(day) - pd.Timestamp(prev)).days",
                 "gap = 1")

    elif which == "m6_kappa_is_hit_rate":
        _rewrite(health, "_kappa",
                 "return float((hit - chance) / (1.0 - chance)), hit, chance, False",
                 "return float(hit), hit, chance, False")

    elif which == "m7_hole_always_false":
        health.is_overnight_hole = lambda policy: False

    elif which == "m8_drop_series_key":
        ladder.LADDER_KEYS = ("bucket_space", "bucket_key", "visibility_date",
                              "venue_class")
        ladder.LADDER_COLUMNS = list(ladder.LADDER_KEYS) + [
            "delta_dv01", "abs_dv01", "n_units", "mean_abs_signed_weight"]

    elif which == "m9_no_dup_check":
        _rewrite(provenance, "coverage_table",
                 'dup = prov["unit_key"].duplicated()',
                 'dup = prov["unit_key"].duplicated() & False')

    elif which == "m10_served_all_true":
        import pandas as pd
        health.served_mask = lambda prov: pd.Series(
            True, index=pd.DataFrame(prov).index)

    elif which == "m11_no_placebo":
        health._placebo_p95 = lambda sx, sy, shift_days, max_placebo: None

    elif which == "m12_dead_zone_one_sided":
        _rewrite(health, "dead_zone_fraction",
                 'name="dead_zone_fraction", direction="outside",',
                 'name="dead_zone_fraction", direction="above",')

    elif which == "m13_report_lag_pools":
        _rewrite(health, "report_lag_by_block",
                 'mask = legs["is_block"].fillna(False).astype(bool) == flag',
                 'mask = legs["is_block"].notna()')

    elif which == "m14_basis_ok":
        _rewrite(health, "pricing_success_by_stratum",
                 "status = NO_DATA if n == 0 else (ALARM if n_priced > 0 else OK)",
                 "status = NO_DATA if n == 0 else OK")

    elif which == "m15_naive_proxy":
        _rewrite(provenance, "annuity_dv01_proxy",
                 "return float(notional) * (_a(start_years + tenor_years) - _a(start_years)) * 1e-4",
                 "return float(notional) * float(tenor_years) * 1e-4")

    elif which == "m16_vintage_code_only":
        _rewrite(provenance, "vintage_components",
                 '"rateslib": _rateslib_version(),',
                 '"rateslib": "PINNED",')

    elif which == "m17_build_drops_failure":
        _rewrite(provenance, "build",
                 "if failure_reason is None and call is not None:\n        failure_reason = call.exclusion",
                 "if False:\n        pass")

    elif which == "m18_visibility_naive_as_utc":
        _rewrite(ladder, "visibility_date",
                 "    if t.tzinfo is None:\n        return t.date()",
                 "    if t.tzinfo is None:\n        t = t.tz_localize('UTC')")

    elif which == "m19_no_missing_size_check":
        _rewrite(provenance, "coverage_table",
                 "missing = size.isna()",
                 "size = size.fillna(0.0)\n    missing = size.isna()")

    elif which == "m20_mean_weight_is_one":
        _rewrite(ladder, "aggregate",
                 'out["mean_abs_signed_weight"] = (\n        out["_abs_delta"] / out["abs_dv01"].where(out["abs_dv01"] != 0)\n    )',
                 'out["mean_abs_signed_weight"] = 1.0')

    elif which == "m21_no_krd_double_sign_guard":
        _rewrite(ladder, "_validated_krd",
                 'if "dealer_sign" in krd.columns:',
                 "if False:")

    elif which == "m22_lifecycle_series_ignored":
        _rewrite(ladder, "_unit_meta",
                 '"series": SERIES_LIFECYCLE if unit.is_lifecycle else SERIES_FLOW,',
                 '"series": SERIES_FLOW,')

    elif which == "m23_no_risk_row_silently_dropped":
        _rewrite(ladder, "unit_ladder_rows",
                 "excluded.append(dict(meta, failure_reason=T.EXCL_PRICING_ERROR))\n            continue",
                 "continue")

    elif which == "":
        pass
    else:
        raise SystemExit(f"unknown DDREV_MUT={which!r}")

    print(f"\n[ddrev2_mut] applied {which!r}")
