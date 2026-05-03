from RVUtils.SFRConvexScreener import (
    JointMethod,
    SFRConvexScreenerConfig,
    StructureType,
)
from RVUtils.SFRConvexScreener._universe import (
    enumerate_butterflies,
    enumerate_calendars,
    enumerate_outrights,
    enumerate_structures,
)


SYMBOLS = ["SFRM26", "SFRU26", "SFRZ26", "SFRH27"]


def test_outrights_one_per_contract():
    outs = enumerate_outrights(SYMBOLS)
    assert len(outs) == len(SYMBOLS)
    for sym, sd in zip(SYMBOLS, outs):
        assert sd.structure_type is StructureType.OUTRIGHT
        assert sd.structure_id == f"{sym}_OUTRIGHT"
        assert len(sd.legs) == 1
        assert sd.legs[0].weight == 1.0


def test_enumerate_structures_includes_outrights_by_default():
    cfg = SFRConvexScreenerConfig(calendar_gaps=(1,), fly_gaps=(1,))
    structures = enumerate_structures(SYMBOLS, cfg)
    n_outrights = sum(1 for s in structures if s.structure_type is StructureType.OUTRIGHT)
    assert n_outrights == len(SYMBOLS)


def test_enumerate_structures_skips_outrights_when_disabled():
    cfg = SFRConvexScreenerConfig(
        calendar_gaps=(1,), fly_gaps=(1,), include_outrights=False,
    )
    structures = enumerate_structures(SYMBOLS, cfg)
    n_outrights = sum(1 for s in structures if s.structure_type is StructureType.OUTRIGHT)
    assert n_outrights == 0


def test_calendars_with_gap_1_produces_three_pairs():
    cals = enumerate_calendars(SYMBOLS, gap=1)
    assert len(cals) == 3
    ids = [s.structure_id for s in cals]
    assert "SFRM26_SFRU26_CAL_1" in ids
    assert "SFRZ26_SFRH27_CAL_1" in ids


def test_calendar_legs_have_pm_one_weights():
    cals = enumerate_calendars(SYMBOLS, gap=1)
    for s in cals:
        weights = [leg.weight for leg in s.legs]
        assert weights == [1.0, -1.0]


def test_calendars_skip_when_gap_too_large():
    cals = enumerate_calendars(SYMBOLS, gap=4)
    assert cals == []


def test_butterflies_with_gap_1_produces_two():
    flies = enumerate_butterflies(SYMBOLS, gap=1)
    assert len(flies) == 2
    weights_set = [tuple(leg.weight for leg in f.legs) for f in flies]
    assert (1.0, -2.0, 1.0) in weights_set


def test_butterfly_id_format():
    flies = enumerate_butterflies(SYMBOLS, gap=1)
    assert all("FLY_1_-2_1" in f.structure_id for f in flies)


def test_enumerate_structures_uses_config_gaps():
    cfg = SFRConvexScreenerConfig(calendar_gaps=(1,), fly_gaps=(1,))
    structures = enumerate_structures(SYMBOLS, cfg)
    n_cals = sum(1 for s in structures if s.structure_type is StructureType.CALENDAR)
    n_flies = sum(1 for s in structures if s.structure_type is StructureType.BUTTERFLY)
    assert n_cals == 3
    assert n_flies == 2
