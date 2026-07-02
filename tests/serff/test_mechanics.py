"""Deterministic contract-mechanics invariants (fast, offline)."""

import datetime

import numpy as np
import pandas as pd
import pytest

from BT.serff.mechanics import (
    PolicyPath,
    bootstrap_policy_path,
    carry_weights,
    contract_window,
    covering_zq_months,
    fomc_effective_date,
    fomc_window_weight,
    implied_remainder,
    make_symbol,
    parse_symbol,
    settlement_price,
    sr3_settlement_rate,
    sr3_quarterly_symbols,
    zq_settlement_rate,
)


class TestWindows:
    def test_sr3_m26_reference_quarter(self):
        w = contract_window("SR3M26")
        assert w.start == datetime.date(2026, 6, 17)   # 3rd Wed June
        assert w.end == datetime.date(2026, 9, 16)     # 3rd Wed Sept (excl)
        assert w.calendar_days == 91

    def test_zq_calendar_month(self):
        w = contract_window("ZQN26")
        assert w.start == datetime.date(2026, 7, 1)
        assert w.end == datetime.date(2026, 8, 1)
        assert w.calendar_days == 31

    def test_symbol_roundtrip(self):
        assert parse_symbol("SR3Z25") == ("SR3", 2025, 12)
        assert make_symbol("ZQ", 2026, 7) == "ZQN26"

    def test_quarterlies_cover_range(self):
        syms = sr3_quarterly_symbols(datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))
        assert "SR3H25" in syms and "SR3Z25" in syms
        # Z24's window extends into 2025 -> included
        assert "SR3Z24" in syms


class TestCarryWeights:
    def test_friday_counts_three_times(self):
        w = contract_window("ZQN26")  # July 2026
        cw = carry_weights(w)
        # 2026-07-03 is a Friday and July 4 falls Saturday (observed Fri? no:
        # July 3 2026 is the observed holiday Friday) -> use a plain Friday:
        # 2026-07-10 Friday carries Sat 11 + Sun 12
        assert cw.loc[pd.Timestamp("2026-07-10")] == 3.0
        assert cw.sum() == w.calendar_days

    def test_weights_cover_month_start_weekend(self):
        # Aug 1 2026 is a Saturday: the carried fixing date is July 31
        w = contract_window("ZQQ26")
        cw = carry_weights(w)
        assert cw.sum() == 31
        assert pd.Timestamp("2026-07-31") in cw.index  # carry from prior month


class TestFOMCWeights:
    def test_prompt_canonical_weights(self):
        m6, n6 = contract_window("SR3M26"), contract_window("ZQN26")
        eff = datetime.date(2026, 7, 30)  # decision Jul 29 -> effective Jul 30
        assert fomc_window_weight(n6, eff) == pytest.approx(2 / 31)
        assert fomc_window_weight(m6, eff) == pytest.approx(48 / 91)
        assert fomc_window_weight(m6, datetime.date(2026, 9, 17)) == 0.0

    def test_effective_is_next_business_day(self):
        assert fomc_effective_date(datetime.date(2026, 7, 29)) == datetime.date(2026, 7, 30)


class TestSettlement:
    def test_flat_curve_averages(self):
        idx = pd.date_range("2026-05-25", "2026-09-16", freq="D")
        fx = pd.Series(4.0, index=idx)
        assert zq_settlement_rate(fx, contract_window("ZQN26")) == pytest.approx(4.0)

    def test_sr3_compounding_convexity(self):
        idx = pd.date_range("2026-05-25", "2026-09-16", freq="D")
        fx = pd.Series(4.0, index=idx)
        r = sr3_settlement_rate(fx, contract_window("SR3M26"))
        # epsilon ~ r^2 * T / 2 = 16 * (91/360) / 2 ~ 2.02bp
        assert (r - 4.0) * 100 == pytest.approx(2.02, abs=0.15)

    def test_one_day_spike_adds_x_over_d(self):
        idx = pd.date_range("2026-05-25", "2026-09-16", freq="D")
        fx = pd.Series(4.0, index=idx)
        fx.loc["2026-06-30"] = 4.20  # +20bp one-day print (Tuesday)
        w = contract_window("SR3M26")
        base = sr3_settlement_rate(pd.Series(4.0, index=idx), w)
        spiked = sr3_settlement_rate(fx, w)
        # ~ 20bp / 91 days ~ 0.22bp on the compounded setting
        assert (spiked - base) * 100 == pytest.approx(20 / 91, abs=0.02)

    def test_price_boundary(self):
        idx = pd.date_range("2026-06-25", "2026-08-05", freq="D")
        fx = pd.Series(3.5, index=idx)
        assert settlement_price(fx, "ZQN26") == pytest.approx(96.5)


class TestImpliedRemainder:
    def test_zq_roundtrip(self):
        idx = pd.date_range("2026-06-25", "2026-08-05", freq="D")
        fx = pd.Series(np.linspace(3.9, 4.1, len(idx)), index=idx)
        price = settlement_price(fx, "ZQN26")
        ir = implied_remainder("ZQN26", price, fx.loc[:"2026-07-15"])
        # remaining true fixings average ~ implied flat
        w = carry_weights(contract_window("ZQN26"))
        rem = w[w.index > "2026-07-15"]
        truth = float((fx.reindex(rem.index) * rem).sum() / rem.sum())
        assert ir.flat_rate == pytest.approx(truth, abs=1e-9)

    def test_sr3_roundtrip_flat(self):
        idx = pd.date_range("2026-05-25", "2026-09-16", freq="D")
        fx = pd.Series(4.0, index=idx)
        price = 100 - sr3_settlement_rate(fx, contract_window("SR3M26"))
        ir = implied_remainder("SR3M26", price, fx.loc[:"2026-06-30"])
        assert ir.flat_rate == pytest.approx(4.0, abs=1e-8)
        assert ir.realized_days == 14.0  # Jun 17..Jun 30 inclusive

    def test_sr3_addon_over_shape(self):
        idx = pd.date_range("2026-05-25", "2026-09-16", freq="D")
        fx = pd.Series(4.0, index=idx)
        w = carry_weights(contract_window("SR3M26"))
        price = 100 - sr3_settlement_rate(fx, contract_window("SR3M26"))
        shape = pd.Series(4.0, index=w.index)
        ir = implied_remainder("SR3M26", price, fx.loc[:"2026-06-30"], shape=shape)
        assert ir.flat_addon == pytest.approx(0.0, abs=1e-8)
        # shift the shape down 10bp: addon must be ~ +10bp
        ir2 = implied_remainder("SR3M26", price, fx.loc[:"2026-06-30"], shape=shape - 0.10)
        assert ir2.flat_addon == pytest.approx(0.10, abs=1e-6)


class TestPolicyBootstrap:
    def test_recovers_known_step(self):
        # EFFR 4.00, one -25bp cut effective 2026-07-30
        idx = pd.date_range("2026-05-01", "2026-06-30", freq="B")
        effr = pd.Series(4.0, index=idx)
        cut_eff = datetime.date(2026, 7, 30)

        path_true = PolicyPath(anchor=datetime.date(2026, 6, 30), base_rate=4.0, steps=((cut_eff, 3.75),))
        prices = {}
        for sym in ("ZQN26", "ZQQ26", "ZQU26"):
            w = carry_weights(contract_window(sym))
            daily = path_true.daily(w.index)
            prices[sym] = 100.0 - float((daily * w).sum() / w.sum())

        path = bootstrap_policy_path(
            datetime.date(2026, 6, 30),
            prices,
            effr,
            meeting_decisions=[datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)],
        )
        # July meeting: -25bp recovered exactly; September meeting (inside
        # ZQU26's month) solves to "no further move" at the same level.
        assert [eff for eff, _ in path.steps] == [cut_eff, datetime.date(2026, 9, 17)]
        assert path.steps[0][1] == pytest.approx(3.75, abs=1e-9)
        assert path.steps[1][1] == pytest.approx(3.75, abs=1e-6)
        assert path.rate_on(datetime.date(2026, 7, 15)) == pytest.approx(4.0)
        assert path.rate_on(datetime.date(2026, 8, 15)) == pytest.approx(3.75)


class TestCoveringMonths:
    def test_stub_weights_and_aggregate(self):
        legs = dict(covering_zq_months(contract_window("SR3M26")))
        assert legs["ZQM26"] == pytest.approx(14 / 30)  # Jun 17..30
        assert legs["ZQN26"] == 1.0
        assert legs["ZQQ26"] == 1.0
        assert legs["ZQU26"] == pytest.approx(15 / 30)  # Sep 1..15
        # aggregate DV01 neutrality ~ 5 SR3 : 3 ZQ
        assert sum(legs.values()) == pytest.approx(3.0, abs=0.05)
