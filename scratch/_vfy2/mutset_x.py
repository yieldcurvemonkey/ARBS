"""Adversarial mutants written for THIS verification -- deliberately not taken
from either the reviewer's set or the fixer's.

The fixer wrote the tests and then wrote the mutants that check them, so its
survivor count is a self-assessment. These target the seams a self-assessment
tends to miss: the exact successor to the one v1 mutant the fixer renamed
(a full branch swap, not a half one), the boundaries of the new guards rather
than their removal, and the two failure modes the new code conflates or could.
"""

MUTATIONS = {
    "X00_noop": ("# --- internals ---", "# --- internals ---"),

    # v1's M08 swapped BOTH branch offsets. The fixer's M08 successor changes
    # only the d<0 branch, which is half the mutation.
    "X01_branch_full_swap": (
        "    if t_kink > -_TAIL_SIGMAS:         # the d < 0 branch: edge = d + c\n"
        "        p += _logistic_normal_segment(\n"
        "            -_TAIL_SIGMAS, min(t_kink, _TAIL_SIGMAS), beta, (-c - dev) / s)\n"
        "    if t_kink < _TAIL_SIGMAS:          # the d >= 0 branch: edge = d - c\n"
        "        p += _logistic_normal_segment(\n"
        "            max(t_kink, -_TAIL_SIGMAS), _TAIL_SIGMAS, beta, (c - dev) / s)",
        "    if t_kink > -_TAIL_SIGMAS:         # the d < 0 branch: edge = d + c\n"
        "        p += _logistic_normal_segment(\n"
        "            -_TAIL_SIGMAS, min(t_kink, _TAIL_SIGMAS), beta, (c - dev) / s)\n"
        "    if t_kink < _TAIL_SIGMAS:          # the d >= 0 branch: edge = d - c\n"
        "        p += _logistic_normal_segment(\n"
        "            max(t_kink, -_TAIL_SIGMAS), _TAIL_SIGMAS, beta, (-c - dev) / s)",
    ),

    # The kink must land on a panel EDGE. Nudging it off by a hair is the
    # failure the whole rewrite is for, and it is invisible to a mutant that
    # deletes the split outright.
    "X02_kink_off_panel_edge": (
        "    t_kink = -dev / s                  # where d = 0 lands in sigma units",
        "    t_kink = -dev / s + 1e-3           # where d = 0 lands in sigma units",
    ),

    # Panel width stops adapting to a sharp logistic. `_PANEL_SIGMAS` alone is
    # right whenever the Gaussian is the sharp factor, so this only shows up in
    # the large-beta corner.
    "X03_panel_width_ignores_beta": (
        "        width = min(_PANEL_SIGMAS, 1.0 / beta)",
        "        width = _PANEL_SIGMAS",
    ),

    # The two failure modes the new exclusion vocabulary separates. If nothing
    # distinguishes them, the new constant bought nothing.
    "X04_pricing_error_is_no_upfront": (
        "                           flags=tuple(flags), exclusion=EXCL_PRICING_ERROR)",
        "                           flags=tuple(flags), exclusion=EXCL_NO_UPFRONT)",
    ),

    # Guard boundaries, not guard removal.
    "X05_negative_fee_guard_slack": (
        "    if upfront < 0.0:",
        "    if upfront < -1e-6:",
    ),
    "X06_fragile_strict_inequality": (
        "    elif min(abs(dev), abs(z)) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
        "    elif min(abs(dev), abs(z)) < FRAGILE_SIGMA_MULT * float(mid_sigma_bps):",
    ),

    # `_edge_from_dev`'s zero branch: a print exactly at mid must be a tie, not
    # a side. v1's M32 pinned the same branch in `orientation`, which classify
    # no longer calls.
    "X07_edge_from_dev_no_zero": (
        "    s = (1 if dev_bps > 0 else -1 if dev_bps < 0 else 0)\n"
        "    e = s * (abs(float(dev_bps)) - float(upfront_bps) - float(bias_bps))",
        "    s = (1 if dev_bps > 0 else -1)\n"
        "    e = s * (abs(float(dev_bps)) - float(upfront_bps) - float(bias_bps))",
    ),

    # `_num` returns 0.0 for a NaN. Returning the NaN instead re-creates the
    # poisoned sum the fix was for, one layer down.
    "X08_num_passes_nan_through": (
        "    return 0.0 if f != f else f",
        "    return f",
    ),

    # `_normal_mass`'s middle branch (lo < 0 < hi) -- untouched by M46.
    "X09_normal_mass_middle_branch": (
        "    return 1.0 - 0.5 * (math.erfc(-lo / _SQRT2) + math.erfc(hi / _SQRT2))",
        "    return 1.0 - 0.5 * (math.erfc(-lo / _SQRT2) - math.erfc(hi / _SQRT2))",
    ),

    # The empty-interval guard. Without it a reversed interval returns negative
    # mass and p leaves [0, 1].
    "X10_normal_mass_empty_guard": (
        "def _normal_mass(lo: float, hi: float) -> float:",
        "def _normal_mass(lo: float, hi: float) -> float:\n    pass",
    ),

    # `mid_bias_bps` recorded on the call. M35 deletes it from ONE return; this
    # changes the value that is recorded, which a test asserting mere presence
    # would miss.
    "X11_mid_bias_recorded_as_zero": (
        "        bias_bps=bias, mid_bias_bps=float(mid_bias_bps), flags=tuple(flags),",
        "        bias_bps=bias, mid_bias_bps=0.0, flags=tuple(flags),",
    ),
}
