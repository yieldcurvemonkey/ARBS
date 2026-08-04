"""Synthetic tests for the family-B carry harness (no data files, no network)."""
import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "notebooks" / "backtests"))

from famb_common import (            # noqa: E402
    OPT_HALF_TICK_BP,
    Holding,
    attribution,
    book_daily_pnl,
    build_book,
    intra_quarter_backtest,
    intrinsic_bp,
    ou_half_life,
    premium_surface,
    rank_symbol,
    richness_frame,
    structure_legs,
)

DATES = pd.bdate_range("2026-06-01", "2026-06-12")


class TestParitySurface:
    def _quotes(self):
        # one OTM call and one OTM put around forward price 96.00
        return pd.DataFrame({
            "as_of": [DATES[0]] * 2, "symbol": ["SFRU26"] * 2,
            "right": ["C", "P"], "strike_price": [96.25, 95.75],
            "strike_rate": [3.75, 4.25], "premium_bp": [8.0, 6.0],
            "oi": [1, 1], "volume": [0, 0],
        })

    def _fwd(self):
        return pd.DataFrame({"as_of": [DATES[0]], "symbol": ["SFRU26"],
                             "fwd_rate": [4.00]})

    def test_synthesized_rights_obey_parity(self):
        s = premium_surface(self._quotes(), self._fwd())
        # synthetic put at 96.25: P = C - DF*(F-K)*100 with F=96.00 < K
        c, p = s.loc[("C", "SFRU26", 96.25, DATES[0])], \
            s.loc[("P", "SFRU26", 96.25, DATES[0])]
        assert p > c                      # ITM put above OTM call premium
        # DF < 1 so |P - C| slightly below the full 25bp forward gap
        assert p - c == pytest.approx(25.0, abs=0.5)
        # synthetic call at 95.75: C = P + DF*(F-K)*100, F above K
        c2 = s.loc[("C", "SFRU26", 95.75, DATES[0])]
        assert c2 - 6.0 == pytest.approx(25.0, abs=0.5)

    def test_listed_beats_synthetic(self):
        q = self._quotes()
        extra = q.iloc[[0]].assign(right="P", premium_bp=99.0)  # listed put
        s = premium_surface(pd.concat([q, extra], ignore_index=True),
                            self._fwd())
        assert s.loc[("P", "SFRU26", 96.25, DATES[0])] == 99.0


class TestStructures:
    def test_fly_intrinsic_peaks_at_center(self):
        legs = structure_legs("FLY25", 96.00)
        assert intrinsic_bp(legs, 96.00) == pytest.approx(25.0)
        assert intrinsic_bp(legs, 95.75) == pytest.approx(0.0)
        assert intrinsic_bp(legs, 96.25) == pytest.approx(0.0)
        assert intrinsic_bp(legs, 96.125) == pytest.approx(12.5)

    def test_dfly_is_fly_minus_next_fly(self):
        d = structure_legs("DFLY", 96.00)
        f1 = structure_legs("FLY25", 96.00)
        f2 = structure_legs("FLY25", 96.25)
        for px in (95.80, 96.0, 96.10, 96.25, 96.40, 96.60):
            assert intrinsic_bp(d, px) == pytest.approx(
                intrinsic_bp(f1, px) - intrinsic_bp(f2, px))

    def test_strangle_has_no_forward_leg(self):
        legs = structure_legs("STRG50", 96.00)
        assert [r for r, _, _ in legs] == ["P", "C"]
        # symmetric payoff: equal moves either side pay the same
        up = intrinsic_bp(legs, 96.75)
        dn = intrinsic_bp(legs, 95.25)
        assert up == pytest.approx(dn) == pytest.approx(25.0)
        assert intrinsic_bp(legs, 96.10) == 0.0


class TestCalendarAndBook:
    def test_rank_symbols_on_a_known_date(self):
        d = datetime.date(2026, 7, 28)
        assert rank_symbol(d, 1) == "SFRU26"
        assert rank_symbol(d, 2) == "SFRZ26"
        assert rank_symbol(d, 3) == "SFRH27"

    class _StubTree:
        def modal_center_px(self, d, sym, fwd_rate):
            return 96.00

        def fair_package_bp(self, d, sym, fwd_rate, legs):
            return 10.0

    def _surface(self, marks):
        rows = []
        for right, k, _ in structure_legs("FLY25", 96.00):
            for i, ts in enumerate(DATES):
                rows.append({"right": right, "symbol": "SFRU26",
                             "strike_price": k, "as_of": ts,
                             "premium_bp": marks[i] if k == 96.00 else 0.0})
        s = pd.DataFrame(rows).set_index(
            ["right", "symbol", "strike_price", "as_of"])["premium_bp"]
        return s.sort_index()

    def test_book_marks_and_costs(self):
        # center leg premium falls 10 -> 8; wings zero => package = -2*center.
        # Rank 1 is SFRM26 (no surface -> segment skipped) until its roll on
        # 06-09, then SFRU26: the holding starts mid-window by design.
        marks = np.linspace(10.0, 8.0, len(DATES))
        fwd = pd.DataFrame({"as_of": DATES, "symbol": "SFRU26",
                            "fwd_rate": 4.0}).set_index(
            ["as_of", "symbol"])["fwd_rate"]
        hs = build_book("FLY25", 1, DATES, self._surface(marks), fwd,
                        self._StubTree())
        assert len(hs) == 1
        h = hs[0]
        assert h.symbol == "SFRU26"
        i0 = list(DATES).index(h.marks.index[0])
        assert h.marks.iloc[0] == pytest.approx(-2 * marks[i0])
        assert h.marks.iloc[-1] == pytest.approx(-16.0)
        pnl = book_daily_pnl([h], cost_mult=1.0, n_legs=4)
        expected_gross = -16.0 - (-2 * marks[i0])
        assert pnl["pnl_bp"].sum() == pytest.approx(
            expected_gross - 2 * 4 * OPT_HALF_TICK_BP)

    def test_attribution_partitions_total(self):
        marks = np.linspace(10.0, 8.0, len(DATES))
        fwd = pd.DataFrame({"as_of": DATES, "symbol": "SFRU26",
                            "fwd_rate": 4.0}).set_index(
            ["as_of", "symbol"])["fwd_rate"]
        hs = build_book("FLY25", 1, DATES, self._surface(marks), fwd,
                        self._StubTree())
        pnl = book_daily_pnl(hs, cost_mult=1.0, n_legs=4)
        att = attribution(pnl, [DATES[7].date()])   # inside the holding
        assert att["sum"].sum() == pytest.approx(pnl["pnl_bp"].sum())
        assert "decision_window" in att.index


class TestMeanReversion:
    def _holding(self, rich_path):
        marks = pd.Series(20.0 + np.asarray(rich_path), index=DATES[:len(
            rich_path)])
        fair = pd.Series(20.0, index=marks.index)
        return Holding(symbol="S", start=marks.index[0], end=marks.index[-1],
                       legs=structure_legs("FLY25", 96.0), marks=marks,
                       fair=fair, terminal_bp=None)

    def test_ou_half_life_recovers_phi(self):
        rng = np.random.default_rng(7)
        x = [5.0]
        for _ in range(400):
            x.append(0.8 * x[-1] + rng.normal(0, 0.3))
        idx = pd.bdate_range("2024-01-01", periods=len(x))
        rich = pd.DataFrame({"as_of": idx, "symbol": "S", "rich_bp": x})
        hl, phi, n = ou_half_life(rich)
        assert phi == pytest.approx(0.8, abs=0.06)
        assert 2.0 < hl < 5.0

    def test_intra_quarter_fade_trade(self):
        # rich starts at +4, decays to ~0: fade = SHORT the structure,
        # entry lag-1, exit when |rich| < 2
        path = [4.0, 4.0, 3.5, 2.5, 1.5, 0.5, 0.2, 0.1, 0.0, 0.0]
        h = self._holding(path)
        trades = intra_quarter_backtest([h], thr_bp=3.0, exit_frac=0.5,
                                        direction="fade", cost_mult=1.0)
        assert len(trades) == 1
        t = trades[0]
        assert t["entry"] == DATES[1]                 # lag-1
        # short from 4.0 down to 1.5 (first |rich| < 2.0) = +2.5 gross
        assert t["gross_bp"] == pytest.approx(2.5)
        assert t["net_bp"] == pytest.approx(2.5 - 2 * 4 * OPT_HALF_TICK_BP)

    def test_richness_frame_roundtrip(self):
        h = self._holding([1.0, 2.0, 3.0])
        rf = richness_frame([h])
        assert rf["rich_bp"].tolist() == pytest.approx([1.0, 2.0, 3.0])
