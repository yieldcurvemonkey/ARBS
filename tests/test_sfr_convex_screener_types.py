import pytest

from RVUtils.SFRConvexScreener import (
    JointMethod,
    Leg,
    SFRConvexScreenerConfig,
    StructureDef,
    StructureType,
)


def test_leg_is_frozen():
    leg = Leg(contract="SFRZ26", weight=1.0, price=96.5, dv01=25.0)
    with pytest.raises(Exception):
        leg.weight = 2.0  # frozen dataclass should reject


def test_structure_type_enum_values():
    assert StructureType.CALENDAR.value == "calendar"
    assert StructureType.BUTTERFLY.value == "butterfly"


def test_joint_method_enum_values():
    assert JointMethod.COMMON_STATE.value == "common_state"
    assert JointMethod.HISTORICAL_GAUSSIAN_COPULA.value == "historical_gaussian_copula"


def test_config_defaults():
    cfg = SFRConvexScreenerConfig()
    assert cfg.universe_size == 12
    assert cfg.calendar_gaps == (1, 2, 4)
    assert cfg.fly_gaps == (1, 2, 4)
    assert cfg.correlation_window == 60
    assert cfg.n_simulations == 100_000
    assert JointMethod.COMMON_STATE in cfg.joint_methods
    assert JointMethod.HISTORICAL_GAUSSIAN_COPULA in cfg.joint_methods
    assert cfg.score_weights == (0.4, 0.2, 0.3, 0.1)


def test_structure_def_id_canonical():
    sd = StructureDef(
        structure_id="SFRZ26_SFRH27_FLY_1_-2_1",
        structure_type=StructureType.BUTTERFLY,
        legs=(
            Leg(contract="SFRZ26", weight=1, price=96.5, dv01=25),
            Leg(contract="SFRH27", weight=-2, price=96.6, dv01=25),
            Leg(contract="SFRM27", weight=1, price=96.7, dv01=25),
        ),
    )
    assert sd.structure_type is StructureType.BUTTERFLY
    assert len(sd.legs) == 3
