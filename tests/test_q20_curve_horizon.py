"""The Q20 curve's horizon must reach past its own terminal instrument.

``_build_stirf_nodes`` (``MDP/IRSwaps/BARCHART_STIRF/rl.py``) sizes the node
grid from ``max_tenor_from_timestamp_months`` **alone** -- it takes central-bank
period ends in ``(base_date, horizon]``, then pricer maturities in the same
window, and filters both by ``d <= horizon_date``. The instrument count never
enters. So an instrument whose maturity falls past the horizon supplies a
solver *target* but receives no *node*, and its accrual period is priced by
``log_linear`` extrapolation off the last segment's slope.

``SFRCM{k}`` references the quarter ``[IMM_k, IMM_{k+1}]``, so the terminal
instrument of an N-instrument config matures at ``IMM_1 + 3N`` months. Because
``IMM_1 > as_of`` always, that is strictly later than ``as_of + 3N`` months --
and the shipped Q20 config set the horizon to exactly ``3N = 60``. The terminal
instrument therefore lost its node on **every** date, and when the gap runs a
full quarter its whole accrual period sits in the extrapolated region, leaving
it with no independent degree of freedom at all: contracts 19 and 20 come back
with *identical* model rates while the market prices them 3.5bp apart. The
solver splits that unrepresentable slope and bleeds it backwards, which is what
put rank 17 (Golds, contracts 17..20) at a median 3.7bp against a 2.0bp gate.

Measured 2026-08-19, offline, ``network_calls_blocked`` delta 0. The defect was
present on every date probed across 2020-2026; ``2026-06-15`` is the extreme
case and is the date these tests pin.

These tests are about the NODE GRID, not about the gate threshold. They assert
the structural property -- the terminal instrument owns a node, and the two
deferred contracts can be told apart -- rather than a basis-point level on a
borderline date, so they stay meaningful as the panel grows.
"""
from __future__ import annotations

import datetime
import glob
import os
import time

import pytest

from RVUtils.ConvexityRV import strat2_q20 as Q
from RVUtils.ConvexityRV.listed_cache_guard import network_calls_blocked
from RVUtils.ConvexityRV.packs import imm_date, quarterly_imm_sequence


def _have_stir_cache() -> bool:
    return bool(glob.glob(os.path.join(Q._default_cache_root(), "*", "cache.db")))


needs_cache = pytest.mark.skipif(not _have_stir_cache(),
                                 reason="local SR3 diskcache not present")


def _retry(fn, n: int = 4, sleep: float = 0.7):
    """Serial retry.

    Three sibling workflows and a live warm share the same 8-shard diskcache,
    and a concurrent reader surfaces as a MISS -- which ``cache_only()`` turns
    into an exception. A single failed read is not evidence the data is absent.
    """
    last: Exception | None = None
    for i in range(n):
        try:
            return fn()
        except Exception as exc:                               # noqa: BLE001
            last = exc
            time.sleep(sleep * (i + 1))
    raise AssertionError(f"cache read failed {n}x serially: {last!r}")


def _q20_curve_cfg() -> dict:
    from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE

    return dict(BARCHART_STIRF_CURVE()._STIRF_CURVE_CONFIGS[Q.Q20_CURVE])


def _terminal_maturity(as_of: datetime.date, depth: int) -> datetime.date:
    """Maturity of the deepest contract in a strip of *depth* contracts."""
    from RVUtils.ConvexityRV.ca_diagnostics import next_quarterly

    y, m = quarterly_imm_sequence(as_of, depth)[-1]
    return imm_date(*next_quarterly(y, m))


# ===========================================================================
# Config arithmetic -- no market data
# ===========================================================================
def test_q20_horizon_reaches_past_its_terminal_instrument():
    """The invariant, stated on the shipped config alone.

    ``SFRCM{N}`` matures at ``IMM_1 + 3N`` months and ``IMM_1 > as_of``, so a
    horizon of exactly ``3N`` months can never admit it. ``IMM_1 - as_of`` runs
    up to a full quarter, so ``3N + 3`` is the bare minimum and ``3N + 6`` is
    the smallest value that holds with a quarter of slack on every day of the
    roll cycle.
    """
    cfg = _q20_curve_cfg()
    n = len(cfg["instruments"])
    h = int(cfg["max_tenor_from_timestamp_months"])

    assert h > 3 * n, (
        f"{Q.Q20_CURVE}: horizon {h}m cannot reach SFRCM{n}, which matures at "
        f"IMM_1 + {3 * n}m and IMM_1 > as_of on every date -- the terminal "
        f"calibration instrument gets no node and is priced by extrapolation")
    assert h >= 3 * n + 6, (
        f"{Q.Q20_CURVE}: horizon {h}m leaves under one quarter of slack over "
        f"the {3 * n}m terminal maturity; IMM_1 - as_of reaches a full quarter")


def test_q20_horizon_is_not_wider_than_it_needs_to_be():
    """Negative control on the value above.

    The fix is one quarter of slack, not an open-ended extension. A horizon
    materially past ``3N + 6`` would pull in central-bank nodes no instrument
    constrains, which is a different defect from the one being fixed.
    """
    cfg = _q20_curve_cfg()
    n = len(cfg["instruments"])
    h = int(cfg["max_tenor_from_timestamp_months"])
    assert h <= 3 * n + 6, (
        f"{Q.Q20_CURVE}: horizon {h}m is more than one quarter past the {3 * n}m "
        f"terminal maturity; nodes beyond it are unconstrained by any instrument")


# ===========================================================================
# The node grid on real dates
# ===========================================================================
@needs_cache
@pytest.mark.parametrize("iso", ["2026-06-15", "2023-06-09", "2021-03-10", "2020-07-15"])
def test_terminal_instrument_is_not_priced_by_extrapolation(iso: str):
    """The mechanism, asserted directly: the deepest contract is inside the grid.

    ``mat(SFRCM20) <= max(nodes)`` is the invariant that matters, and it is the
    one that generalises. ``_build_stirf_nodes`` has two regimes and only the
    first is the defect:

    * **pricer-maturity regime** -- the central-bank schedule stops short of the
      horizon, so contract maturities are appended as nodes. Here the terminal
      instrument owns its own node, and the 60m horizon excluded it.
    * **central-bank regime** -- the CB schedule already runs past the horizon,
      so pricer maturities are never appended at all and the grid is pure CB
      period ends. The terminal maturity is then interpolated between dense CB
      nodes rather than owning one, which is fine: it is not extrapolated.

    Asserting "is a node" would be true on these four dates but false in the CB
    regime, where nothing is wrong. Measured across 12 sampled dates per year
    2018-2026 at strip depth 20 (108 dates, offline, network delta 0), the
    non-extrapolation invariant held on **1/108** dates under the old 60m
    horizon and **108/108** under 66m.
    """
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from RVUtils.ConvexityRV.ca_diagnostics import curve_nodes

    d = datetime.date.fromisoformat(iso)
    cfg = Q.Q20Config()
    before = network_calls_blocked()
    b = Q.Q20Builder(cfg)
    pricer = _retry(lambda: b.pricer(d, 20))
    assert network_calls_blocked() == before, "the build reached for the network"

    nodes = curve_nodes(pricer)
    mat = _terminal_maturity(d, 20)
    assert mat <= max(nodes), (
        f"{d}: SFRCM20 matures {mat} but the last curve node is {max(nodes)} -- "
        f"the terminal calibration instrument is priced by extrapolation off the "
        f"last segment's slope and carries no degree of freedom of its own")

    # These four dates are all in the pricer-maturity regime, where the terminal
    # instrument should own its node outright rather than merely be covered.
    assert mat in nodes, (
        f"{d}: SFRCM20's maturity {mat} is covered by the grid but is not itself "
        f"a node; this date was measured in the pricer-maturity regime, so a "
        f"missing node means contract maturities stopped being appended")


@needs_cache
def test_deferred_contracts_are_not_rank_deficient():
    """Contracts 19 and 20 must be distinguishable when the market separates them.

    2026-06-15 is the extreme case: SFRCM20 matures 91 days past the 60m
    horizon, so its entire accrual period lay in the extrapolated region and it
    had no degree of freedom of its own. Measured on the shipped config the two
    contracts came back with *bit-identical* model rates (3.996287 both) while
    their settles are 3.5bp apart. That unrepresentable slope is what the solver
    redistributes backwards into contracts 17 and 18.

    Asserted as a fraction of the observed settle slope rather than an absolute
    level, so the test measures representational capacity and not the size of
    that day's move.
    """
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from RVUtils.ConvexityRV.ca_diagnostics import next_quarterly
    from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

    d = datetime.date(2026, 6, 15)
    cfg = Q.Q20Config()
    before = network_calls_blocked()
    b = Q.Q20Builder(cfg)
    pricer = _retry(lambda: b.pricer(d, 20))
    settles = _retry(lambda: b.settles(d, 20))
    assert network_calls_blocked() == before, "the build reached for the network"

    seq = quarterly_imm_sequence(d, 20)
    model = [matched_forward_swap_rate(pricer, imm_date(*seq[k]),
                                       imm_date(*next_quarterly(*seq[k])))
             for k in (18, 19)]
    settle_slope_bp = (settles[seq[19]] - settles[seq[18]]) * 100.0
    model_slope_bp = (model[1] - model[0]) * 100.0

    assert abs(settle_slope_bp) > 2.0, (
        f"{d}: settles 19/20 differ by only {settle_slope_bp:.3f}bp -- this date "
        f"no longer discriminates and the test needs a new one")
    assert abs(model_slope_bp) > 0.5 * abs(settle_slope_bp), (
        f"{d}: the curve carries {model_slope_bp:.3f}bp between contracts 19 and "
        f"20 against a settle slope of {settle_slope_bp:.3f}bp -- the deferred "
        f"end is rank deficient, not merely mis-fitted")
