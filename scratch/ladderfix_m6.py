"""Mutations re-anchored against the fixed module, plus three new ones.

The reviewers' m6 anchor was the pre-fix `_kappa` return line; the degenerate
flag now comes from a variable, so the same mutation needs the new text. m39
restores the pre-fix degenerate condition, m40 the pre-fix `max_lag`-only hole
test, m41 the pre-fix `getattr` defaults in `provenance.build`.
"""
import inspect
import os
import textwrap


def _rewrite(mod, fn_name, old, new):
    src = textwrap.dedent(inspect.getsource(getattr(mod, fn_name)))
    assert old in src, f"{fn_name}: anchor not found: {old!r}"
    exec(compile(src.replace(old, new), f"<mut:{fn_name}>", "exec"), mod.__dict__)


def pytest_configure(config):
    from SDRUtils.dealer_direction import health, provenance

    which = os.environ.get("DDREV_MUT", "")
    if which == "m6b_kappa_is_hit_rate":
        _rewrite(health, "_kappa",
                 "return float((hit - chance) / (1.0 - chance)), hit, chance, degenerate",
                 "return float(hit), hit, chance, degenerate")

    elif which == "m39_degenerate_only_when_chance_is_one":
        _rewrite(health, "_kappa",
                 "degenerate = px in (0.0, 1.0) or py in (0.0, 1.0)",
                 "degenerate = False")

    elif which == "m40_hole_reads_max_lag_only":
        _rewrite(health, "is_overnight_hole",
                 'future = _ALLOW_FUTURE_RE.search(text)\n'
                 '    if future is None or future.group("v").lower() != "false":\n'
                 '        return True',
                 "pass")

    elif which == "m41_build_getattr_defaults":
        src = textwrap.dedent(inspect.getsource(provenance.build))
        for old, new in (
            ("absent = [f for f in _PRICING_FIELDS if not hasattr(pricing, f)]",
             "absent = []"),
            ('curve_name = pricing.curve_name or ""',
             "curve_name = getattr(pricing, 'curve_name', '') or ''"),
            ("curve_ts = pricing.curve_timestamp",
             "curve_ts = getattr(pricing, 'curve_timestamp', pd.NaT)"),
            ("lag = pricing.snapshot_lag_seconds",
             "lag = getattr(pricing, 'snapshot_lag_seconds', None)"),
            ('policy = pricing.snapshot_policy or ""',
             "policy = getattr(pricing, 'snapshot_policy', '') or ''"),
            ("if not str(policy).strip():", "if False:"),
        ):
            assert old in src, f"build: anchor not found: {old!r}"
            src = src.replace(old, new)
        exec(compile(src, "<mut:build>", "exec"), provenance.__dict__)

    elif which == "m42_ladder_excluded_ignored":
        _rewrite(provenance, "coverage_table",
                 "prov = merge_ladder_exclusions(prov, ladder_excluded)",
                 "pass")

    elif which == "m43_no_orphan_krd_check":
        from SDRUtils.dealer_direction import ladder
        _rewrite(ladder, "unit_ladder_rows",
                 "orphans = [k for k in by_unit if k not in population]",
                 "orphans = []")

    elif which == "m44_no_duplicate_unit_check":
        from SDRUtils.dealer_direction import ladder
        _rewrite(ladder, "unit_ladder_rows",
                 "if unit.unit_key in population:",
                 "if False:")

    elif which == "m45_rolling_empty_one_column":
        _rewrite(health, "rolling_recycling_kappa",
                 "return pd.DataFrame(columns=ROLLING_KAPPA_COLUMNS)\n    # trailing",
                 'out["reference_kappa"] = []\n        return out\n    # trailing')

    elif which == "":
        pass
    else:
        raise SystemExit(f"unknown DDREV_MUT={which!r}")

    print(f"\n[ladderfix_m6] applied {which!r}")
