"""Synthetic tests for the FF-vs-SR3 ICS conventions (no network)."""
import datetime

import numpy as np
import pytest

from RVUtils.MeetingProb.ics import (
    compounding_wedge_bp,
    ff_conditional_atoms,
    ics_blend_contracts,
    ics_spread_bp,
    proxy_wedge_bp,
    window_level_weights,
)
from RVUtils.MeetingProb.ladder import MeetingLattice


def _mtg(eff, jump, support, q, label="x"):
    return MeetingLattice(
        effective=eff, decision=eff - datetime.timedelta(days=1),
        jump_bp=jump, support=support, q=q, contract=label,
    )


class TestBlendAndSpread:
    def test_blend_is_the_next_two_ff_months(self):
        # CME worked example: June SR3 vs July + August FF
        assert ics_blend_contracts("SFRM26") == ("ZQN26", "ZQQ26")
        # the user's case, crossing a year boundary
        assert ics_blend_contracts("SFRZ26") == ("ZQF27", "ZQG27")

    def test_spread_reproduces_the_cme_worked_example(self):
        # (94.890 + 94.735)/2 - 94.7775 = 3.5bp (June 20, 2024 settles)
        assert ics_spread_bp(94.7775, [94.890, 94.735]) == pytest.approx(3.5)

    def test_compounding_wedge_magnitude(self):
        # r^2 (D-1)/720 approximation: 4% over 91 days ~ 2bp
        w = compounding_wedge_bp(4.0, 91)
        assert w == pytest.approx(0.04 ** 2 * 90 / 720 * 1e4, rel=0.02)
        assert compounding_wedge_bp(0.0, 91) == 0.0


class TestWindowWeights:
    def test_single_meeting_split(self):
        w = window_level_weights(
            [datetime.date(2027, 1, 27)],
            datetime.date(2026, 12, 16), datetime.date(2027, 3, 17),
        )
        assert w == pytest.approx([42 / 91, 49 / 91])
        assert w.sum() == pytest.approx(1.0)

    def test_meeting_outside_window_gets_full_base_weight(self):
        w = window_level_weights(
            [datetime.date(2027, 6, 1)],
            datetime.date(2026, 12, 16), datetime.date(2027, 3, 17),
        )
        assert w == pytest.approx([1.0, 0.0])


class TestProxyWedge:
    def test_flat_path_has_no_wedge(self):
        lad = [_mtg(datetime.date(2027, 1, 27), 0.0, (0, 0), 0.0)]
        assert proxy_wedge_bp(lad, "SFRZ26") == pytest.approx(0.0)

    def test_single_january_meeting_hand_computed(self):
        # window Dec16->Mar17 weights (42/91, 49/91); Jan month (26/31, 5/31);
        # Feb month (0, 1); blend post-meeting weight = 0.5*(5/31) + 0.5
        lad = [_mtg(datetime.date(2027, 1, 27), 7.0, (0, 1), 0.28)]
        expect = (0.5 * (5 / 31) + 0.5 - 49 / 91) * 7.0
        assert proxy_wedge_bp(lad, "SFRZ26") == pytest.approx(expect)
        assert expect > 0          # a priced hike makes the blend sit ABOVE

    def test_pre_window_meeting_cancels(self):
        # a meeting before the window and both blend months affects neither
        lad = [_mtg(datetime.date(2026, 9, 16), 20.0, (0, 1), 0.8)]
        assert proxy_wedge_bp(lad, "SFRZ26") == pytest.approx(0.0)


class TestFFConditionalAtoms:
    def test_absolute_anchoring_and_mean(self):
        as_of = datetime.date(2026, 11, 1)
        lad = [
            _mtg(datetime.date(2026, 12, 10), 10.0, (0, 1), 0.4),   # pre-window
            _mtg(datetime.date(2027, 1, 27), 7.0, (0, 1), 0.28),    # in-window
        ]
        out = ff_conditional_atoms(as_of, "SFRZ26", lad, 3.63)
        assert out is not None
        rates, probs, smear, mean, cm = out
        # mean = base + w_dec*10 + w_jan*7 with w_dec = 1, w_jan = 49/91
        assert mean == pytest.approx(3.63 + (10.0 + 49 / 91 * 7.0) / 100.0)
        assert float(np.dot(probs, rates)) == pytest.approx(mean)
        # Dec resolved by expiry -> two atoms 25bp apart; Jan is smear
        assert len(rates) == 2
        assert rates[1] - rates[0] == pytest.approx(0.25)
        assert probs == pytest.approx([0.6, 0.4])
        assert cm.n_resolved == 1
        assert smear == pytest.approx(
            np.sqrt((49 / 91 * 25.0) ** 2 * 0.28 * 0.72))
