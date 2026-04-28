"""Tests for BacktestSignal and snapshot → signal-table flattening."""
import datetime

from RVUtils.SFRConvexScreener import Leg, StructureDef, StructureType
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal


def test_backtest_signal_holds_screener_fields():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    sig = BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=sd,
        direction="PAY SFRZ26",
        flip=False,
        asymmetry_ratio=2.92,
        composite_score=0.64,
        mean_bp=45.6,
        std_bp=155.3,
        rolldown_bp=0.51,
        carry_3m_bp=365.0,
        is_stale=False,
    )
    assert sig.structure_def.structure_id == "SFRZ26_OUTRIGHT"
    assert sig.flip is False
