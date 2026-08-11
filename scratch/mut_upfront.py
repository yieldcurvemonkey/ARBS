"""Source-level mutation harness for SDRUtils/dealer_direction/upfront.py.

Loads a string-mutated copy of the module into sys.modules BEFORE pytest
collects the test file, then runs the test file. A mutation that leaves the
suite green is a test that cannot fail.

Validated first on a NO-OP mutation (must stay green) and on a mutation whose
answer is known (global orientation flip -- must go red).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import types

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "SDRUtils", "dealer_direction", "upfront.py")

MUTATIONS = {
    # name: (old, new)
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
        "    if is_lifecycle:\n        edges = -edges",
        "    if False:\n        edges = -edges",
    ),
    "M07_marginalise_ignores_bias": (
        "        d - (float(upfront_bps) + float(bias_bps)),\n        d + (float(upfront_bps) + float(bias_bps)),",
        "        d - float(upfront_bps),\n        d + float(upfront_bps),",
    ),
    "M08_marginalise_branch_flip": (
        "        d - (float(upfront_bps) + float(bias_bps)),\n        d + (float(upfront_bps) + float(bias_bps)),",
        "        d + (float(upfront_bps) + float(bias_bps)),\n        d - (float(upfront_bps) + float(bias_bps)),",
    ),
    "M09_fragile_flag_never_fires": (
        "    elif abs(dev) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps) and u_bps > abs(dev):",
        "    elif False:",
    ),
    "M10_fragile_flag_always_fires": (
        "    elif abs(dev) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps) and u_bps > abs(dev):",
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
        '        return UpfrontCall(None, None, None, None, 0, population=population,\n                           flags=tuple(flags), exclusion=EXCL_NO_UPFRONT)',
        '        return UpfrontCall(None, None, None, None, 0, population=population,\n                           flags=tuple(flags), exclusion=None)',
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
}

PLUGIN = r'''
import importlib, os, sys, types
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
    for name in only:
        old, new = MUTATIONS[name]
        plug = os.path.join(here, "_mutplug.py")
        with open(plug, "w", encoding="utf-8") as fh:
            fh.write(PLUGIN.format(src=SRC, old=old, new=new))
        env = dict(os.environ, ARBS_SUPABASE_ENABLED="0",
                   PYTHONPATH=root + os.pathsep + here)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "_mutplug", "-q",
             os.path.join(root, "tests", "test_dealer_direction_upfront.py")],
            cwd=root, env=env, capture_output=True, text=True)
        out = r.stdout + r.stderr
        tail = [l for l in out.splitlines() if " passed" in l or " failed" in l
                or "error" in l.lower()]
        status = "GREEN (test cannot fail)" if r.returncode == 0 else "red"
        print(f"{name:42s} {status:26s} {tail[-1][:90] if tail else out[-200:]}")


if __name__ == "__main__":
    main()
