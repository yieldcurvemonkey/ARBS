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
