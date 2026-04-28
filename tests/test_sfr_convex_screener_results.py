import datetime

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


def _trivial_metrics() -> PayoffMetrics:
    return PayoffMetrics(
        mean_bp=1.0,
        std_bp=5.0,
        skew=0.5,
        excess_kurtosis=1.0,
        p_profit=0.55,
        ev_given_profit_bp=4.0,
        ev_given_loss_bp=-3.0,
        asymmetry_ratio=1.5,
        percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )


def test_structure_result_to_dict_roundtrip():
    sd = StructureDef(
        structure_id="A_B_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("A", 1, 96.5, 25), Leg("B", -1, 96.6, 25)),
    )
    r = StructureResult(
        structure_def=sd,
        metrics_by_method={"common_state": _trivial_metrics()},
        primary_method="common_state",
        carry_3m_bp=1.0,
        rolldown_bp=0.5,
        iv_rv_diagnostics=(),
        historical=None,
        warnings=("liquidity flag",),
        composite_score=0.7,
        rank=3,
    )
    d = r.to_dict()
    assert d["structure_id"] == "A_B_CAL_1"
    assert d["composite_score"] == 0.7
    assert "common_state" in d["metrics_by_method"]


def test_direction_outright_pay_when_asymmetry_above_one():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1, 96.5, 25),),
    )
    metrics = _trivial_metrics()  # asymmetry_ratio = 1.5
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.0, rank=1,
    )
    assert r.direction() == "PAY SFRZ26"


def test_direction_outright_receive_when_asymmetry_below_one():
    sd = StructureDef(
        structure_id="SFRH29_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRH29", 1, 96.5, 25),),
    )
    metrics_low = PayoffMetrics(
        mean_bp=-1.0, std_bp=5.0, skew=-0.5, excess_kurtosis=1.0,
        p_profit=0.45, ev_given_profit_bp=3.0, ev_given_loss_bp=-4.5,
        asymmetry_ratio=0.6,
        percentiles_bp={"p5": -11, "p25": -5, "p50": -1, "p75": 2, "p95": 7},
        tail_ratio=0.7,
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics_low},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.0, rank=1,
    )
    assert r.direction() == "RECEIVE SFRH29"


def test_direction_calendar_pay_front_receive_back():
    sd = StructureDef(
        structure_id="SFRM27_SFRU27_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("SFRM27", 1, 96.5, 25), Leg("SFRU27", -1, 96.6, 25)),
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"common_state": _trivial_metrics()},
        primary_method="common_state", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.0, rank=1,
    )
    assert r.direction() == "PAY SFRM27 / RECEIVE SFRU27"


def test_direction_butterfly_long_rate_when_asymmetry_above_one():
    sd = StructureDef(
        structure_id="SFRM27_SFRU27_SFRZ27_FLY_1_-2_1",
        structure_type=StructureType.BUTTERFLY,
        legs=(
            Leg("SFRM27", 1, 96.5, 25),
            Leg("SFRU27", -2, 96.6, 25),
            Leg("SFRZ27", 1, 96.7, 25),
        ),
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"common_state": _trivial_metrics()},
        primary_method="common_state", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.0, rank=1,
    )
    assert r.direction() == (
        "PAY SFRM27+SFRZ27 / RECEIVE 2x SFRU27 (long-rate fly)"
    )


def test_snapshot_to_dataframe():
    sd = StructureDef(
        structure_id="A_B_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("A", 1, 96.5, 25), Leg("B", -1, 96.6, 25)),
    )
    r = StructureResult(
        structure_def=sd,
        metrics_by_method={"common_state": _trivial_metrics()},
        primary_method="common_state",
        carry_3m_bp=1.0,
        rolldown_bp=0.5,
        iv_rv_diagnostics=(),
        historical=None,
        warnings=(),
        composite_score=0.7,
        rank=1,
    )
    snap = SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,),
        config_summary={"universe_size": 12},
    )
    df = snap.to_dataframe()
    assert df.shape[0] == 1
    assert "structure_id" in df.columns
    assert "asymmetry_ratio" in df.columns
