"""Second mutation batch -- the public functions no test appears to reach."""
import inspect
import os
import textwrap


def _rewrite(mod, fn_name, old, new):
    src = textwrap.dedent(inspect.getsource(getattr(mod, fn_name)))
    assert old in src, f"{fn_name}: anchor not found: {old!r}"
    exec(compile(src.replace(old, new), f"<mut:{fn_name}>", "exec"), mod.__dict__)


def pytest_configure(config):
    from SDRUtils.dealer_direction import health, ladder, provenance
    import SDRUtils.dealer_direction.types as T

    which = os.environ.get("DDREV_MUT", "")

    if which == "m24_series_disjoint_noop":
        ladder.assert_series_disjoint = lambda ladder_frame: None

    elif which == "m25_interdealer_returns_d2c":
        _rewrite(ladder, "interdealer_flow",
                 'ladder["venue_class"] == T.VENUE_D2D',
                 'ladder["venue_class"] == T.VENUE_D2C')

    elif which == "m26_in_session_over_policy_blind":
        _rewrite(health, "snapshot_lag_metrics",
                 "n_in_over = (int(((served & ~hole).to_numpy()",
                 "n_in_over = 0 * (int(((served & ~hole).to_numpy()")

    elif which == "m27_health_report_best_first":
        _rewrite(health, "health_report",
                 'out.sort_values("_rank", ascending=False)',
                 'out.sort_values("_rank", ascending=True)')

    elif which == "m28_past_start_not_clamped":
        _rewrite(provenance, "annuity_dv01_proxy_from_dates",
                 'start = max(0.0, (pd.Timestamp(effective) - as_of).days / 365.25)',
                 'start = (pd.Timestamp(effective) - as_of).days / 365.25')

    elif which == "m29_orient_allows_zero_sign":
        _rewrite(ladder, "orient_to_received",
                 "if (signs == 0).any():",
                 "if False:")

    elif which == "m30_missing_call_silently_skipped":
        _rewrite(ladder, "unit_ladder_rows",
                 'raise ValueError(\n                f"unit {key!r} has no direction call; every unit must carry one, "\n                "including an excluded one, or the coverage accounting has a hole"\n            )',
                 "continue")

    elif which == "m31_degenerate_scores_one":
        _rewrite(health, "_kappa",
                 "return 0.0, hit, chance, True",
                 "return 1.0, hit, chance, True")

    elif which == "m32_abs_dv01_is_abs_delta":
        _rewrite(ladder, "aggregate",
                 'work["_abs"] = work[KRD_VALUE_COL].abs()',
                 'work["_abs"] = work["delta_dv01"].abs()')

    elif which == "m33_dead_zone_flag_ignored":
        _rewrite(ladder, "unit_ladder_rows",
                 "if drop_dead_zone and call.in_dead_zone:",
                 "if False:")

    elif which == "m34_lag_dist_drops_unserved":
        _rewrite(health, "snapshot_lag_distribution",
                 '("UNSERVED", (~served).to_numpy())',
                 '("UNSERVED", (served & False).to_numpy())')

    elif which == "":
        pass
    else:
        raise SystemExit(f"unknown DDREV_MUT={which!r}")

    print(f"\n[ddrev2_mut_b] applied {which!r}")
