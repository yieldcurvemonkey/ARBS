"""Tests for BacktestSignal and snapshot → signal-table flattening."""
import datetime

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._backtest_signals import (
    BacktestSignal,
    build_signal_table_from_snapshots,
)
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


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


def test_build_signal_table_from_snapshots():
    metrics = PayoffMetrics(
        mean_bp=45.6, std_bp=155.0, skew=1.47, excess_kurtosis=2.0,
        p_profit=0.518, ev_given_profit_bp=70.0, ev_given_loss_bp=-30.0,
        asymmetry_ratio=2.92,
        percentiles_bp={"p5": -200, "p25": -50, "p50": 5, "p75": 80, "p95": 250},
        tail_ratio=5.88,
    )
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=365.0, rolldown_bp=0.51,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.64, rank=1,
    )
    snap = SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,),
        config_summary={"universe_size": 4},
    )
    table = build_signal_table_from_snapshots([snap])
    assert datetime.date(2026, 4, 28) in table
    sigs = table[datetime.date(2026, 4, 28)]
    assert len(sigs) == 1
    assert sigs[0].direction == "PAY SFRZ26"
    assert sigs[0].asymmetry_ratio == 2.92
    assert sigs[0].flip is False


def test_build_signal_table_marks_stale_warnings():
    metrics = PayoffMetrics(
        mean_bp=0.0, std_bp=10.0, skew=0.0, excess_kurtosis=0.0,
        p_profit=0.5, ev_given_profit_bp=1.0, ev_given_loss_bp=-1.0,
        asymmetry_ratio=1.0,
        percentiles_bp={"p5": -5, "p25": -2, "p50": 0, "p75": 2, "p95": 5},
        tail_ratio=1.0,
    )
    sd = StructureDef(
        structure_id="X", structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None,
        warnings=("SFRZ26::stale_smile_asof=2026-04-25",),
        composite_score=0.0, rank=1,
    )
    snap = SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,), config_summary={"universe_size": 4},
    )
    table = build_signal_table_from_snapshots([snap])
    sig = table[datetime.date(2026, 4, 28)][0]
    assert sig.is_stale is True


def test_build_signal_table_flip_when_asymmetry_below_one():
    metrics = PayoffMetrics(
        mean_bp=0.0, std_bp=10.0, skew=-1.0, excess_kurtosis=0.0,
        p_profit=0.45, ev_given_profit_bp=1.0, ev_given_loss_bp=-2.5,
        asymmetry_ratio=0.4,
        percentiles_bp={"p5": -10, "p25": -3, "p50": -1, "p75": 1, "p95": 3},
        tail_ratio=0.4,
    )
    sd = StructureDef(
        structure_id="Y", structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRH27", 1.0, 96.7, 25),),
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.0, rank=1,
    )
    snap = SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,), config_summary={"universe_size": 4},
    )
    sig = build_signal_table_from_snapshots([snap])[datetime.date(2026, 4, 28)][0]
    assert sig.flip is True
    assert sig.direction == "RECEIVE SFRH27"
