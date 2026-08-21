r"""Every STIRF curve's node horizon must reach its own terminal instrument.

``_build_stirf_nodes`` admits a candidate node only while
``d <= base_ts + max_tenor_from_timestamp_months``. The instrument count never
enters that filter, so an instrument maturing past the horizon supplies the
solver with a target and receives no node of its own: it is priced by
``log_linear`` extrapolation off the last segment, and the solver bleeds the
unrepresentable slope *backwards* into the ranks below it.

``db95871d`` measured this on ``Q20STIRT`` -- rank 17 went from 0.0 % to 100 %
pass on the 2.0 bp settle-agreement gate in 2026 -- fixed that one curve, and
flagged the rest as unfixed. ``tests/test_q20_curve_horizon.py`` then pinned the
rule for ``Q20STIRT`` **only**, which is why the same defect sat undetected in
six sibling curves. This file asserts the rule across the whole config table.

The requirement, per instrument family:

* ``SFRCM_k`` is the quarterly SR3 strip. It references ``[IMM_k, IMM_k+1]`` and
  therefore matures at ``IMM_1 + 3k`` months. ``IMM_1 > as_of`` always, and the
  gap reaches a full quarter, so the horizon must be at least ``3k + 6``.
* ``SERCM_m`` / ``FFCM_m`` / ``RACM_m`` are monthly and mature around ``m + 1``
  months, so they never bind on any curve in this table.

A first pass at this test applied ``3 * n_instruments + 6`` to every curve and
reported nine violations. Seven of those were false: the mixed curves interleave
a monthly ladder with the quarterly one, so ``n_instruments`` is not the
quarterly depth. The binding quantity is the **highest SFRCM index**, not the
instrument count -- which is the whole reason the checker is derived from the
ladder here rather than from a length.
"""

from __future__ import annotations

import re

import pytest


def _configs() -> dict[str, dict]:
    """``{curve_name: {"max_sfrcm": int|None, "horizon": int}}``, parsed from source.

    Parsed rather than imported because building the real config table
    constructs an MDP and its fetchers. The rule is a property of the literal.
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "MDP" / "IRSwaps" / "BARCHART_STIRF" / "rl.py"
    text = src.read_text(encoding="utf-8")

    out: dict[str, dict] = {}
    for name, body in re.findall(r'"(USD-[A-Z0-9\-x]+)":\s*\{(.*?)\n            \},', text, re.S):
        m = re.search(r'"max_tenor_from_timestamp_months":\s*(\d+)', body)
        if not m:
            continue
        sfr = [int(x) for x in re.findall(r'"SFRCM(\d+)"', body)]
        out[name] = {"max_sfrcm": max(sfr) if sfr else None, "horizon": int(m.group(1))}
    return out


def _required(max_sfrcm: int | None) -> int | None:
    return None if max_sfrcm is None else 3 * max_sfrcm + 6


#: Curves knowingly left short, with the shortfall measured at the time of
#: writing. They are NOT fixed here: each interleaves a monthly ladder and feeds
#: the production intraday curve store (``MIX23`` among them), so widening the
#: horizon changes a live series and needs its own before/after measurement
#: rather than a blind edit. The allowlist exists so the defect is recorded in
#: code and cannot grow -- a new curve, or a worse shortfall on one of these,
#: fails the test.
KNOWN_SHORT = {
    "USD-SOFR-1D-Q12x3STIRT": 18,
    "USD-SOFR-1D-Q12xM12STIRT": 6,
    "USD-OIS-Q12xM11STIRT": 18,
    "USD-OIS-Q12xM12STIRT": 6,
    "USD-OIS-Q12xM12STIRT-SERFFX": 6,
    "USD-OIS-Q12xM12STIRT-SERFFX-MIX23": 6,
    "USD-OIS-Q12xM12STIRT-MIX23": 6,
    "USD-OIS-Q12xM12STIRT-SERFFXCONST-MIX23": 6,
}

#: The SOFR-only quarterly curves. These are the convexity-adjustment lineage and
#: they must satisfy the rule outright.
MUST_COMPLY = [
    "USD-SOFR-1D-Q12STIRT",
    "USD-SOFR-1D-Q16STIRT",
    "USD-SOFR-1D-Q20STIRT",
]


def test_the_parser_finds_the_curve_table():
    """Guard the checker before trusting anything it says.

    A regex that silently matched nothing would make every assertion below pass
    vacuously -- the failure mode this codebase names as its most expensive.
    """
    cfgs = _configs()
    assert len(cfgs) >= 11, f"parsed only {len(cfgs)} curve configs: {sorted(cfgs)}"
    for name in MUST_COMPLY:
        assert name in cfgs, f"{name} not parsed out of rl.py"
        assert cfgs[name]["max_sfrcm"] is not None, f"{name} has no SFRCM ladder"


@pytest.mark.parametrize("curve", MUST_COMPLY)
def test_sofr_quarterly_curves_reach_their_terminal_instrument(curve):
    cfg = _configs()[curve]
    need = _required(cfg["max_sfrcm"])
    assert cfg["horizon"] >= need, (
        f"{curve}: horizon {cfg['horizon']}m does not reach SFRCM{cfg['max_sfrcm']}, "
        f"which matures at IMM_1 + {3 * cfg['max_sfrcm']}m and needs {need}m. The "
        f"terminal instrument gets no node and is priced by extrapolation, which "
        f"bleeds backwards into the ranks below it."
    )


@pytest.mark.parametrize("curve", MUST_COMPLY)
def test_sofr_quarterly_curves_are_not_wider_than_they_need_to_be(curve):
    """One quarter of slack, no more -- wider pulls in unconstrained nodes."""
    cfg = _configs()[curve]
    need = _required(cfg["max_sfrcm"])
    assert cfg["horizon"] <= need, (
        f"{curve}: horizon {cfg['horizon']}m is more than one quarter past "
        f"SFRCM{cfg['max_sfrcm']}'s {3 * cfg['max_sfrcm']}m maturity; the extra "
        f"nodes are constrained by no instrument."
    )


def test_no_curve_is_shorter_than_the_allowlist_records():
    """Every remaining violation is known, and none of them has got worse."""
    cfgs = _configs()
    surprises, regressions, stale = [], [], []

    for name, cfg in cfgs.items():
        need = _required(cfg["max_sfrcm"])
        if need is None:
            continue
        short = need - cfg["horizon"]
        if short <= 0:
            if name in KNOWN_SHORT:
                stale.append(name)
            continue
        if name not in KNOWN_SHORT:
            surprises.append(f"{name}: short by {short}m (horizon {cfg['horizon']}, needs {need})")
        elif short > KNOWN_SHORT[name]:
            regressions.append(
                f"{name}: short by {short}m, allowlist records {KNOWN_SHORT[name]}m")

    assert not surprises, (
        "a curve violates the node-horizon rule and is not on the allowlist:\n  "
        + "\n  ".join(surprises))
    assert not regressions, (
        "a known-short curve got shorter:\n  " + "\n  ".join(regressions))
    assert not stale, (
        "these curves now satisfy the rule and should be removed from "
        f"KNOWN_SHORT: {stale}")
