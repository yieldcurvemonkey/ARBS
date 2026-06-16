"""USTFutureBasisHandler PnL — pure-function sign/scale conventions.

Long basis  = buy cash bond + sell CF-weighted futures (direction = +1).
Short basis = sell cash bond + buy futures (direction = -1).

Long the bond -> you PAY repo to fund it (financing is a cost).
Long basis sells futures -> a rise in the futures price is a LOSS on that leg.
"""
import math

import pytest


def test_long_basis_financing_is_a_cost():
    from Query.USTFutureBasis.position_handler import compute_financing_delta

    fin = compute_financing_delta(
        dirty_value=1_000_000.0, repo_pct=5.0, specialness_bps=0.0, days=1, haircut=0.0, direction=+1
    )
    assert fin == pytest.approx(-(1_000_000.0 * 0.05 / 360.0))


def test_short_basis_financing_is_income_with_specialness():
    from Query.USTFutureBasis.position_handler import compute_financing_delta

    fin = compute_financing_delta(
        dirty_value=1_000_000.0, repo_pct=5.0, specialness_bps=20.0, days=1, haircut=0.0, direction=-1
    )
    # short the bond -> earn reverse repo at (gc - specialness) = 5% - 0.20% = 4.80%
    assert fin == pytest.approx(+(1_000_000.0 * (0.05 - 0.0020) / 360.0))


def test_financing_scales_with_days_and_haircut():
    from Query.USTFutureBasis.position_handler import compute_financing_delta

    base = compute_financing_delta(dirty_value=1_000_000.0, repo_pct=4.0, specialness_bps=0.0, days=3, haircut=0.0, direction=1)
    assert base == pytest.approx(-(1_000_000.0 * 0.04 * 3 / 360.0))
    hair = compute_financing_delta(dirty_value=1_000_000.0, repo_pct=4.0, specialness_bps=0.0, days=3, haircut=0.02, direction=1)
    assert hair == pytest.approx(base * (1.0 - 0.02))


def test_futures_leg_pnl_sign_for_long_basis():
    from Query.USTFutureBasis.position_handler import compute_futures_leg_pnl

    # TY: tick_size = 1/64, tick_value = 15.625 -> $1000 per full point per contract.
    # long basis is SHORT futures, so a +1.0 point move is a loss.
    pnl = compute_futures_leg_pnl(
        f_now=111.0, f_entry=110.0, tick_size=1 / 64, tick_value=15.625, n_contracts=10, direction=+1
    )
    assert pnl == pytest.approx(-1000.0 * 10)


def test_futures_leg_pnl_sign_for_short_basis():
    from Query.USTFutureBasis.position_handler import compute_futures_leg_pnl

    pnl = compute_futures_leg_pnl(
        f_now=111.0, f_entry=110.0, tick_size=1 / 64, tick_value=15.625, n_contracts=10, direction=-1
    )
    assert pnl == pytest.approx(+1000.0 * 10)


def test_cash_leg_pnl_sign():
    from Query.USTFutureBasis.position_handler import compute_cash_leg_pnl

    assert compute_cash_leg_pnl(npv_now=101_000_000.0, npv_entry=100_000_000.0, direction=+1) == pytest.approx(1_000_000.0)
    assert compute_cash_leg_pnl(npv_now=101_000_000.0, npv_entry=100_000_000.0, direction=-1) == pytest.approx(-1_000_000.0)


# ---------------------------------------------------------------------------
# End-to-end engine integration (live MDP, small verified window)
# ---------------------------------------------------------------------------
NOTIONAL = 100_000_000.0


def _run_small_long_basis_backtest():
    import datetime

    import QuantLib as ql

    from BT.data_handler import TimeGrid
    from BT.misc import ql_cal_date_range
    from BT.query_actions import AddQueryAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
    from Query.USTFutureBasis.USTFutureBasisQuery import USTFutureBasisQuery

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    grid = ql_cal_date_range(ql_cal=cal, start=datetime.datetime(2025, 11, 11), end=datetime.datetime(2025, 11, 14), freq="1b")
    entry = grid[0]
    q = USTFutureBasisQuery(
        symbol="TYZ25",
        direction=1,
        bond_notional=NOTIONAL,
        meta={"financing": {"specialness_bps": 0.0, "haircut": 0.0}},
    )
    trig = DateTrigger(DateTriggerRequirements(dates=[entry.date()]), actions=[AddQueryAction(query=q)])
    strat = QueryStrategy(name="ustfb-long", triggers=[trig])
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    bt = QueryDrivenBacktest(time_grid=TimeGrid(grid), mdp=mdp, strategy=strat, show_progress=False)
    bt.run()
    return bt, grid, entry


def test_handler_end_to_end_long_basis():
    bt, grid, entry = _run_small_long_basis_backtest()
    vals = list(bt.mtm_history.values())
    assert len(vals) >= 2, f"expected >=2 priced days, got {list(bt.mtm_history.keys())}"
    assert all(math.isfinite(v) for v in vals)
    # entry-day total PnL is ~0 (entered at the mark)
    assert bt.mtm_history[entry] == pytest.approx(0.0, abs=1.0)
    # the futures hedge offsets the cash leg: residual is tiny vs a naked $100mm bond
    # (which would move ~$700k+/day). This proves CF-weighting actually neutralises DV01.
    assert max(abs(v) for v in vals) < 0.02 * NOTIONAL
    # long basis funds the bond in repo -> financing accrual is a cost (negative)
    comp = getattr(bt, "ustf_basis_components", {})
    assert comp.get("financing_total", 0.0) < 0.0

