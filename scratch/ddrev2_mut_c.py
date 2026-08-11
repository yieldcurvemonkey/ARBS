"""Third batch: the escalation branches the asserts may not actually reach."""
import inspect
import os
import textwrap


def _rewrite(mod, fn_name, old, new):
    src = textwrap.dedent(inspect.getsource(getattr(mod, fn_name)))
    assert old in src, f"{fn_name}: anchor not found: {old!r}"
    exec(compile(src.replace(old, new), f"<mut:{fn_name}>", "exec"), mod.__dict__)


def pytest_configure(config):
    from SDRUtils.dealer_direction import health

    which = os.environ.get("DDREV_MUT", "")

    if which == "m35_no_dv01_escalation":
        _rewrite(health, "imputed_notional_fraction",
                 "if dv01_share is not None:\n        if dv01_share >= IMPUTED_DV01_ALARM:\n            status = _worse(status, ALARM)\n        elif dv01_share >= IMPUTED_DV01_WARN:\n            status = _worse(status, WARN)",
                 "if False:\n        pass")

    elif which == "m36_no_abs_dead_zone_override":
        _rewrite(health, "dead_zone_fraction",
                 "if not np.isnan(value) and value > DEAD_ZONE_ABS_ALARM:\n            status = ALARM",
                 "pass")

    elif which == "m37_hole_lag_p90_untested":
        _rewrite(health, "snapshot_lag_metrics",
                 'warn=3600.0, alarm=snapshot.OUT_OF_SESSION_MAX_LAG.total_seconds(),',
                 'warn=1e18, alarm=1e18,')

    elif which == "m38_kappa_alarm_uses_warn_only":
        _rewrite(health, "d2d_recycling_kappa",
                 "warn=0.10, alarm=placebo_p95,",
                 "warn=0.10, alarm=None,")

    elif which == "":
        pass
    else:
        raise SystemExit(f"unknown DDREV_MUT={which!r}")

    print(f"\n[ddrev2_mut_c] applied {which!r}")
