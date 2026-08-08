import pytest

from RVUtils.StrikelessVol.costs import FREE, MAKER, TAKER, CostSchedule


def test_initiation_cost_at_the_reference_clip():
    s = CostSchedule()
    # 0.875bp on a $100k DV01 package = $87,500
    assert s.cost_usd("initiate", 100_000.0) == pytest.approx(87_500.0)


def test_hedge_and_roll_are_charged_separately():
    # Use a schedule with different rates so we can actually distinguish the kinds
    s = CostSchedule(hedge_bp=0.30, roll_bp=0.40)
    hedge_cost = s.cost_usd("hedge", 100_000.0)
    roll_cost = s.cost_usd("roll", 100_000.0)
    assert hedge_cost == pytest.approx(0.30 * 100_000.0)
    assert roll_cost == pytest.approx(0.40 * 100_000.0)
    assert hedge_cost != roll_cost  # Confirm they are genuinely different


def test_unknown_cost_kind_raises():
    with pytest.raises(KeyError):
        CostSchedule().cost_usd("vibes", 1.0)


def test_multiplier_scales_everything():
    assert CostSchedule(multiplier=2.0).cost_usd("hedge", 100_000.0) == pytest.approx(
        2.0 * CostSchedule().cost_usd("hedge", 100_000.0)
    )
    # FREE zeroes all kinds, not just initiate (guard against future kind-specific carve-out)
    assert FREE.cost_usd("initiate", 100_000.0) == 0.0
    assert FREE.cost_usd("hedge", 100_000.0) == 0.0
    assert FREE.cost_usd("roll", 100_000.0) == 0.0


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
    # Presets bracket the research prior: initiate within 0.75–1.0bp, hedge/roll within 0.30–0.40bp
    # MAKER should be tighter (lower), TAKER wider (higher) on all three fields.

    # Initiate rates: 0.75–1.0bp range
    assert 0.75 <= MAKER.initiate_bp < TAKER.initiate_bp <= 1.00

    # Hedge rates: 0.30–0.40bp range
    assert 0.30 <= MAKER.hedge_bp < TAKER.hedge_bp <= 0.40

    # Roll rates: 0.30–0.40bp range
    assert 0.30 <= MAKER.roll_bp < TAKER.roll_bp <= 0.40
