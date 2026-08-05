import pytest

from RVUtils.StrikelessVol.costs import FREE, MAKER, TAKER, CostSchedule


def test_initiation_cost_at_the_reference_clip():
    s = CostSchedule()
    # 0.875bp on a $100k DV01 package = $87,500
    assert s.cost_usd("initiate", 100_000.0) == pytest.approx(87_500.0)


def test_hedge_and_roll_are_charged_separately():
    s = CostSchedule()
    assert s.cost_usd("hedge", 20_000.0) == pytest.approx(0.35 * 20_000.0)
    assert s.cost_usd("roll", 100_000.0) == pytest.approx(0.35 * 100_000.0)


def test_unknown_cost_kind_raises():
    with pytest.raises(KeyError):
        CostSchedule().cost_usd("vibes", 1.0)


def test_multiplier_scales_everything():
    assert CostSchedule(multiplier=2.0).cost_usd("hedge", 100_000.0) == pytest.approx(
        2.0 * CostSchedule().cost_usd("hedge", 100_000.0)
    )
    assert FREE.cost_usd("initiate", 100_000.0) == 0.0


def test_clip_exponent_makes_size_expensive():
    size_blind = CostSchedule(clip_exponent=0.0)
    size_aware = CostSchedule(clip_exponent=0.3)
    big = 1_000_000.0
    assert size_aware.cost_usd("hedge", big) > size_blind.cost_usd("hedge", big)
    # and is neutral at the reference clip
    assert size_aware.cost_usd("hedge", 100_000.0) == pytest.approx(
        size_blind.cost_usd("hedge", 100_000.0)
    )


def test_presets_bracket_the_prior():
    assert MAKER.initiate_bp < TAKER.initiate_bp
