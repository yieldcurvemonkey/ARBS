"""Tests for entry/exit triggers wrapping FlowSignalTriggerRequirements."""
import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from BT.query_actions import AddQueryAction, UnwindPositionsAction

from RVUtils.SFRConvexScreener import Leg, StructureDef, StructureType
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._backtest_triggers import (
    SFRScreenerBacktestConfig,
    build_entry_trigger,
    build_exit_trigger,
)


def _signal(sid: str, *, asym: float = 2.0, score: float = 0.6, flip: bool = False,
            structure_type: StructureType = StructureType.OUTRIGHT) -> BacktestSignal:
    sd = StructureDef(
        structure_id=sid,
        structure_type=structure_type,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    return BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=sd, direction="PAY SFRZ26", flip=flip,
        asymmetry_ratio=asym, composite_score=score,
        mean_bp=10.0, std_bp=20.0, rolldown_bp=0.5, carry_3m_bp=350.0,
        is_stale=False,
    )


def test_entry_trigger_fires_when_top_signal_passes_filters():
    table = {datetime.date(2026, 4, 28): [_signal("X", asym=3.0, score=1.0)]}
    cfg = SFRScreenerBacktestConfig(
        entry_min_asymmetry=1.5,
        entry_min_composite_score=0.0,
        max_concurrent=10,
    )
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True


def test_entry_trigger_filters_below_asymmetry_threshold():
    table = {datetime.date(2026, 4, 28): [_signal("X", asym=1.05)]}
    cfg = SFRScreenerBacktestConfig(entry_min_asymmetry=1.5)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is False


def test_entry_trigger_caps_at_max_concurrent():
    sigs = [_signal(f"X{i}", asym=2.0, score=1.0 - i * 0.01) for i in range(10)]
    table = {datetime.date(2026, 4, 28): sigs}
    cfg = SFRScreenerBacktestConfig(max_concurrent=2)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True
    actions = info.info
    assert any(len(orders) == 2 for orders in actions.values())


def test_entry_trigger_skips_stale_when_configured():
    s_fresh = _signal("Fresh", asym=2.0)
    s_stale = _signal("Stale", asym=2.0)
    s_stale = BacktestSignal(**{**s_stale.__dict__, "is_stale": True})
    table = {datetime.date(2026, 4, 28): [s_fresh, s_stale]}
    cfg = SFRScreenerBacktestConfig(skip_stale=True, max_concurrent=10)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True
    orders = next(iter(info.info.values()))
    ids = [(o.query.tags or [None])[0] for o in orders]
    assert "sfr_screener_Fresh" in ids
    assert "sfr_screener_Stale" not in ids


def test_entry_trigger_filters_by_structure_types():
    s_outright = _signal("OUT", asym=2.0, structure_type=StructureType.OUTRIGHT)
    s_cal_legs = (Leg("SFRM27", 1.0, 96.5, 25), Leg("SFRU27", -1.0, 96.6, 25))
    s_cal = BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=StructureDef(
            structure_id="CAL", structure_type=StructureType.CALENDAR, legs=s_cal_legs,
        ),
        direction="PAY M / RECEIVE U", flip=False, asymmetry_ratio=2.0,
        composite_score=0.7, mean_bp=10.0, std_bp=20.0,
        rolldown_bp=0.5, carry_3m_bp=350.0, is_stale=False,
    )
    table = {datetime.date(2026, 4, 28): [s_outright, s_cal]}
    cfg = SFRScreenerBacktestConfig(structure_types=("calendar",), max_concurrent=10)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True
    orders = next(iter(info.info.values()))
    ids = [(o.query.tags or [None])[0] for o in orders]
    assert ids == ["sfr_screener_CAL"]


def test_entry_trigger_respects_rebalance_dow():
    table = {datetime.date(2026, 4, 28): [_signal("X", asym=3.0)]}
    cfg = SFRScreenerBacktestConfig(rebalance_dow=4, max_concurrent=10)  # Friday
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    # 2026-04-28 is a Tuesday
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is False


def test_entry_trigger_no_duplicates_for_open_positions():
    table = {datetime.date(2026, 4, 28): [_signal("Open", asym=3.0)]}
    cfg = SFRScreenerBacktestConfig(max_concurrent=10)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    pos = MagicMock()
    pos.meta = {"tags": ["sfr_screener_Open"]}
    bt.portfolio.positions = [pos]
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is False


def _exit_pos(structure_id: str, *, opened: pd.Timestamp, flip: bool = False,
              entry_asym: float = 3.0):
    pos = MagicMock()
    pos.meta = {
        "tags": [f"sfr_screener_{structure_id}"],
        "structure_id": structure_id,
        "entry_asymmetry": entry_asym,
        "flip": flip,
    }
    pos.opened = opened
    return pos


def test_exit_trigger_fires_on_asymmetry_decay():
    sd = StructureDef(
        structure_id="X",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    table = {
        datetime.date(2026, 5, 5): [BacktestSignal(
            as_of=datetime.date(2026, 5, 5), structure_def=sd, direction="PAY",
            flip=False, asymmetry_ratio=1.05, composite_score=0.0,
            mean_bp=0.0, std_bp=10.0, rolldown_bp=0.0, carry_3m_bp=350.0,
            is_stale=False,
        )]
    }
    cfg = SFRScreenerBacktestConfig(exit_asymmetry_threshold=1.10)
    trig = build_exit_trigger(table, cfg)

    bt = MagicMock()
    bt.portfolio.positions = [_exit_pos("X", opened=pd.Timestamp("2026-04-28"))]
    bt.mtm_history = {}
    info = trig.has_triggered(datetime.datetime(2026, 5, 5, 17, 0), backtest=bt)
    assert bool(info) is True
    unwinds = info.info[UnwindPositionsAction]
    assert len(unwinds) == 1
    assert unwinds[0].meta["reason"] == "asymmetry_decay"


def test_exit_trigger_max_holding_days():
    sd = StructureDef(
        structure_id="X",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    table = {
        datetime.date(2026, 5, 30): [BacktestSignal(
            as_of=datetime.date(2026, 5, 30), structure_def=sd, direction="PAY",
            flip=False, asymmetry_ratio=3.0, composite_score=0.0,
            mean_bp=0.0, std_bp=10.0, rolldown_bp=0.0, carry_3m_bp=350.0,
            is_stale=False,
        )]
    }
    cfg = SFRScreenerBacktestConfig(exit_max_holding_days=22)
    trig = build_exit_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = [_exit_pos("X", opened=pd.Timestamp("2026-04-28"))]
    bt.mtm_history = {}
    info = trig.has_triggered(datetime.datetime(2026, 5, 30, 17, 0), backtest=bt)
    assert bool(info) is True
    assert info.info[UnwindPositionsAction][0].meta["reason"] == "max_holding"


def test_exit_trigger_no_signal_keeps_position_until_max_hold():
    """Empty table on a given date -> no asymmetry decay check; max-hold only."""
    cfg = SFRScreenerBacktestConfig(exit_max_holding_days=22, exit_asymmetry_threshold=1.10)
    trig = build_exit_trigger({}, cfg)
    bt = MagicMock()
    bt.portfolio.positions = [_exit_pos("X", opened=pd.Timestamp("2026-04-28"))]
    bt.mtm_history = {}
    info = trig.has_triggered(datetime.datetime(2026, 5, 1, 17, 0), backtest=bt)
    assert bool(info) is False


def test_exit_trigger_flip_inverts_decay_direction():
    """Position entered with flip=True (long-price) - decay = (1/A) below threshold."""
    sd = StructureDef(
        structure_id="Y", structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRH27", 1.0, 96.7, 25),),
    )
    table = {
        datetime.date(2026, 5, 5): [BacktestSignal(
            as_of=datetime.date(2026, 5, 5), structure_def=sd, direction="RECEIVE",
            flip=True, asymmetry_ratio=0.95, composite_score=0.0,
            mean_bp=0.0, std_bp=10.0, rolldown_bp=0.0, carry_3m_bp=350.0,
            is_stale=False,
        )]
    }
    cfg = SFRScreenerBacktestConfig(exit_asymmetry_threshold=1.10)
    trig = build_exit_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = [_exit_pos("Y", opened=pd.Timestamp("2026-04-28"), flip=True)]
    bt.mtm_history = {}
    info = trig.has_triggered(datetime.datetime(2026, 5, 5, 17, 0), backtest=bt)
    # 1/0.95 = 1.05 < 1.10 -> decay
    assert bool(info) is True
    assert info.info[UnwindPositionsAction][0].meta["reason"] == "asymmetry_decay"


def test_exit_trigger_no_open_positions_returns_false():
    cfg = SFRScreenerBacktestConfig()
    trig = build_exit_trigger({}, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 5, 5, 17, 0), backtest=bt)
    assert bool(info) is False
