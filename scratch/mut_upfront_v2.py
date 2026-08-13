"""Mutation harness for upfront.py, v2 -- patterns rewritten for the post-fix
source, plus mutants for the code the fixes added.

Copied from the reviewer's `mut_upfront.py` rather than edited in place, so the
original evidence stays intact. The plugin raises SystemExit when a pattern is
not found, which the runner would otherwise print as "red" -- a mutant that
never ran, looking exactly like one that was killed. So every result is checked
for an actual "N failed" line, and a missing pattern is reported as MISSING.

Validated in both directions before use: M00_noop must be GREEN and
M01_orientation_global_flip must be red.
"""
from __future__ import annotations

import os
import subprocess
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "SDRUtils", "dealer_direction", "upfront.py")

MUTATIONS = {
    "M00_noop": ("# --- internals ---", "# --- internals ---"),
    "M01_orientation_global_flip": (
        "    s = (1 if npv_pay < 0 else -1 if npv_pay > 0 else 0)\n    return -s if is_lifecycle else s",
        "    s = (-1 if npv_pay < 0 else 1 if npv_pay > 0 else 0)\n    return -s if is_lifecycle else s",
    ),
    "M02_lifecycle_no_inversion": (
        "    return -s if is_lifecycle else s",
        "    return s",
    ),
    "M03_classify_drops_tau_bias": (
        "    z = abs(dev) - u_bps - bias",
        "    z = abs(dev) - u_bps",
    ),
    "M04_classify_drops_mid_bias": (
        "    dev = -float(npv_pay) / dv01 - float(mid_bias_bps)",
        "    dev = -float(npv_pay) / dv01",
    ),
    "M05_residual_bps_drops_bias": (
        "    return (abs(float(npv_pay)) - float(upfront)) / dv01 - float(bias_bps)",
        "    return (abs(float(npv_pay)) - float(upfront)) / dv01",
    ),
    "M06_marginalise_no_lifecycle_flip": (
        "    return 1.0 - p if is_lifecycle else p",
        "    return p",
    ),
    "M07_marginalise_ignores_bias": (
        "    c = float(upfront_bps) + float(bias_bps)",
        "    c = float(upfront_bps)",
    ),
    "M08_marginalise_branch_swap": (
        "        p += _logistic_normal_segment(\n            -_TAIL_SIGMAS, min(t_kink, _TAIL_SIGMAS), beta, (-c - dev) / s)",
        "        p += _logistic_normal_segment(\n            -_TAIL_SIGMAS, min(t_kink, _TAIL_SIGMAS), beta, (c - dev) / s)",
    ),
    "M09_fragile_flag_never_fires": (
        "    elif min(abs(dev), abs(z)) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
        "    elif False:",
    ),
    "M10_fragile_flag_always_fires": (
        "    elif min(abs(dev), abs(z)) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
        "    elif True:",
    ),
    "M11_signed_weight_is_p": (
        "        sw = conventions.signed_weight(p)",
        "        sw = p",
    ),
    "M12_tiny_upfront_never_flagged": (
        "    if upfront < stir_config.PTP_USD_FLOOR:",
        "    if False:",
    ),
    "M13_capped_default_on": (
        "CAPPED_UPFRONT_IS_UNSCALED = False",
        "CAPPED_UPFRONT_IS_UNSCALED = True",
    ),
    "M14_uwin_not_preferred": (
        "        primary, primary_src = uwins, SRC_UWIN\n        if not any(_num(u) > 0 for u in uwins):",
        "        primary, primary_src = uwins, SRC_UWIN\n        if True:",
    ),
    "M15_no_lifecycle_fallback_flag": (
        "                flags.append(FLAG_LIFECYCLE_FEE_FALLBACK)",
        "                pass",
    ),
    "M16_disagree_flag_dropped": (
        "    if disagree:\n        flags.append(FLAG_PTP_UFRO_DISAGREE)",
        "    if False:\n        flags.append(FLAG_PTP_UFRO_DISAGREE)",
    ),
    "M17_tau_recomputed_ignoring_floor": (
        "    tau_bps = float(tau_reported) if tau_reported is not None else s * s / (2.0 * h)",
        "    tau_bps = s * s / (2.0 * h)",
    ),
    "M18_tau_uses_reported_only": (
        "    tau_bps = float(tau_reported) if tau_reported is not None else s * s / (2.0 * h)",
        "    tau_bps = float(tau_reported) if tau_reported is not None else 1.0",
    ),
    "M19_no_population_guard": (
        "    if tau is not None and tau.population != population:",
        "    if False:",
    ),
    "M20_degenerate_fit_accepted": (
        "    if not (h > 0 and s > 0):",
        "    if False and not (h > 0 and s > 0):",
    ),
    "M21_robust_tau_half_spread_zero": (
        'return TauUpfront(tau_bps=scale, bias_bps=med, half_spread_bps=float("nan"),',
        "return TauUpfront(tau_bps=scale, bias_bps=med, half_spread_bps=0.0,",
    ),
    "M22_no_mid_sigma_flag_dropped": (
        "    if mid_sigma_bps is None:\n        flags.append(FLAG_NO_MID_SIGMA)",
        "    if mid_sigma_bps is None:\n        pass",
    ),
    "M23_dealer_sign_from_dev_not_edge": (
        "dealer_sign=conventions.dealer_side(edge),",
        "dealer_sign=conventions.dealer_side(dev),",
    ),
    "M24_no_upfront_returns_a_call": (
        "                           flags=tuple(flags), exclusion=EXCL_NO_UPFRONT)",
        "                           flags=tuple(flags), exclusion=None)",
    ),
    "M25_p_from_edge_uses_abs": (
        "    z = float(edge_bps) / float(tau_bps)",
        "    z = abs(float(edge_bps)) / float(tau_bps)",
    ),
    "M26_edge_from_dev_no_lifecycle": (
        "    return -e if is_lifecycle else e",
        "    return e",
    ),
    "M27_fragile_mult_zero": (
        "FRAGILE_SIGMA_MULT = 2.0",
        "FRAGILE_SIGMA_MULT = 0.0",
    ),
    "M28_zero_dv01_allowed": (
        "    if not dv01 > 0:",
        "    if False:",
    ),
    "M29_upfront_sign_ignored": (
        "    z = abs(dev) - u_bps - bias",
        "    z = abs(dev) - abs(u_bps) - bias",
    ),
    "M30_dev_sign_flip": (
        "    dev = -float(npv_pay) / dv01 - float(mid_bias_bps)",
        "    dev = float(npv_pay) / dv01 - float(mid_bias_bps)",
    ),
    "M31_marginalise_gets_negated_dev": (
        "            p = p_marginalised(dev, u_bps, tau.tau_bps,",
        "            p = p_marginalised(-dev, u_bps, tau.tau_bps,",
    ),
    "M32_orientation_zero_branch_gone": (
        "    s = (1 if npv_pay < 0 else -1 if npv_pay > 0 else 0)",
        "    s = (1 if npv_pay < 0 else -1)",
    ),
    "M33_upfront_bps_not_scaled": (
        "    u_bps = upfront / dv01",
        "    u_bps = upfront / dv01 * 1.10",
    ),
    # ---- new surface introduced by the fixes -----------------------------
    "M34_classify_orients_off_raw_npv": (
        "    edge = _edge_from_dev(dev, u_bps, bias, is_lifecycle)",
        "    edge = orientation(npv_pay, is_lifecycle=is_lifecycle) * z",
    ),
    "M35_mid_bias_not_recorded": (
        "        bias_bps=bias, mid_bias_bps=float(mid_bias_bps), flags=tuple(flags),",
        "        bias_bps=bias, flags=tuple(flags),",
    ),
    "M36_fragile_tests_dev_only": (
        "    elif min(abs(dev), abs(z)) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
        "    elif abs(dev) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
    ),
    "M37_fragile_tests_z_only": (
        "    elif min(abs(dev), abs(z)) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
        "    elif abs(z) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
    ),
    "M38_nan_npv_guard_removed": (
        "    if npv_pay is None or not np.isfinite(float(npv_pay)):",
        "    if False:",
    ),
    "M39_negative_fee_allowed": (
        "    if upfront < 0.0:",
        "    if False:",
    ),
    "M40_fee_list_not_sanitised": (
        "    ufros = [_num(u) for u in (ufros or [])]\n    uwins = [_num(u) for u in (uwins or [])]",
        "    ufros = list(ufros or [])\n    uwins = list(uwins or [])",
    ),
    "M41_quadrature_back_to_one_grid": (
        "    if t_kink > -_TAIL_SIGMAS:         # the d < 0 branch: edge = d + c",
        "    if False:                          # the d < 0 branch: edge = d + c",
    ),
    "M42_panel_width_10_sigma": (
        "_PANEL_SIGMAS = 1.0",
        "_PANEL_SIGMAS = 10.0",
    ),
    "M43_gl_two_nodes": (
        "_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(16)",
        "_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(2)",
    ),
    "M44_saturation_cut_to_one": (
        "_LOGISTIC_SATURATION = 40.0",
        "_LOGISTIC_SATURATION = 1.0",
    ),
    "M45_tail_truncated_at_half_sigma": (
        "_TAIL_SIGMAS = 9.0",
        "_TAIL_SIGMAS = 0.5",
    ),
    "M46_normal_mass_cancels": (
        "    if lo >= 0.0:\n        return 0.5 * (math.erfc(lo / _SQRT2) - math.erfc(hi / _SQRT2))",
        "    if lo >= 0.0:\n        return 0.5 * (math.erfc(-hi / _SQRT2) - math.erfc(-lo / _SQRT2))",
    ),
    "M47_marginalise_non_finite_guard_gone": (
        "    if not (math.isfinite(dev) and math.isfinite(c) and math.isfinite(s)):",
        "    if False:",
    ),
    "M48_marginalise_tau_guard_gone": (
        "    if not tau > 0:\n        raise ValueError(f\"tau must be positive, got {tau_bps!r}\")",
        "    if False:\n        raise ValueError(f\"tau must be positive, got {tau_bps!r}\")",
    ),
    "M49_saturated_wing_dropped": (
        "    total = _normal_mass(hi_sat, hi)",
        "    total = 0.0",
    ),
    "M50_mid_bias_finite_guard_gone": (
        "    if not np.isfinite(float(mid_bias_bps)):",
        "    if False:",
    ),
    "M51_mid_sigma_finite_guard_gone": (
        "    if mid_sigma_bps is not None and not np.isfinite(float(mid_sigma_bps)):",
        "    if False:",
    ),
}

PLUGIN = r'''
import importlib, sys, types
SRC = {src!r}
OLD = {old!r}
NEW = {new!r}
src = open(SRC, encoding="utf-8").read()
if OLD not in src:
    raise SystemExit("MUTATION PATTERN NOT FOUND")
if OLD != NEW:
    assert src.count(OLD) == 1, "pattern is not unique: %d" % src.count(OLD)
src = src.replace(OLD, NEW)
pkg = importlib.import_module("SDRUtils.dealer_direction")
mod = types.ModuleType("SDRUtils.dealer_direction.upfront")
mod.__file__ = SRC
mod.__package__ = "SDRUtils.dealer_direction"
sys.modules["SDRUtils.dealer_direction.upfront"] = mod
exec(compile(src, SRC, "exec"), mod.__dict__)
setattr(pkg, "upfront", mod)
'''


def main():
    only = sys.argv[1:] or list(MUTATIONS)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    survivors = []
    for name in only:
        old, new = MUTATIONS[name]
        plug = os.path.join(here, "_mutplug_v2.py")
        with open(plug, "w", encoding="utf-8") as fh:
            fh.write(PLUGIN.format(src=SRC, old=old, new=new))
        env = dict(os.environ, ARBS_SUPABASE_ENABLED="0",
                   PYTHONPATH=root + os.pathsep + here)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "_mutplug_v2", "-q",
             "--no-header", "-p", "no:cacheprovider", "--tb=no",
             os.path.join(root, "tests", "test_dealer_direction_upfront.py")],
            cwd=root, env=env, capture_output=True, text=True)
        out = r.stdout + r.stderr
        tail = [l for l in out.splitlines()
                if " passed" in l or " failed" in l or " error" in l.lower()]
        last = tail[-1] if tail else out[-160:].replace("\n", " ")
        if "MUTATION PATTERN NOT FOUND" in out:
            status = "MISSING (pattern stale -- did NOT run)"
        elif r.returncode == 0:
            status = "GREEN (test cannot fail)"
            survivors.append(name)
        elif " failed" in last:
            status = "red"
        else:
            status = "ERROR (crashed, not killed)"
        print(f"{name:42s} {status:38s} {last[:80]}")
    print(f"\nsurvivors: {len(survivors)}  {survivors}")


if __name__ == "__main__":
    main()
