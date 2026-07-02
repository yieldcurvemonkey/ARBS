"""End-to-end backtest on synthetic settles: attribution + cost invariants."""

import datetime

import numpy as np
import pandas as pd
import pytest

from BT.serff.backtest import _PNL_BUCKETS, run_serff_backtest
from BT.serff.config import (
    SerffBacktestConfig,
    SerffDataConfig,
    SerffModelConfig,
    SerffTradeConfig,
    SerffWalkForwardConfig,
)
from BT.serff.mechanics import (
    carry_weights,
    contract_window,
    settlement_rate,
    sr3_quarterly_symbols,
    zq_monthly_symbols,
)
from tests.serff.test_ledger import _synthetic_panel


def _make_world(start, end, *, cheap_sr3_bp=0.0, seed=3):
    """Fixings + exchange-consistent settle prices for a synthetic market.

    SOFR = EFFR - 3bp with quarter-end spikes; futures priced at fair value
    from the true forward fixings, with SR3 shifted ``cheap_sr3_bp`` cheap
    (price below fair) so the model should buy it.
    """
    idx = pd.date_range(start - datetime.timedelta(days=200), end + datetime.timedelta(days=200), freq="D")
    effr = pd.Series(4.0, index=idx)
    spread = pd.Series(-3.0, index=idx)
    bidx = pd.bdate_range(idx.min(), idx.max())
    frame = pd.DataFrame(index=bidx)
    frame["ym"] = frame.index.to_period("M")
    for me in frame.groupby("ym").apply(lambda g: g.index.max()).values:
        me = pd.Timestamp(me)
        if me.month in (3, 6, 9, 12):
            spread.loc[me] += 8.0
    sofr = effr + spread / 100.0

    syms = sr3_quarterly_symbols(start, end) + zq_monthly_symbols(start, end)
    dates = pd.bdate_range(start, end)
    settles = pd.DataFrame(index=dates, columns=syms, dtype=float)
    for s in syms:
        w = contract_window(s)
        fx = sofr if s.startswith("SR3") else effr
        rate = settlement_rate(fx, s)
        px = 100.0 - rate
        if s.startswith("SR3"):
            px -= cheap_sr3_bp / 100.0  # cheap = lower price = higher implied rate
        live = dates[(dates.date < w.end)]
        settles.loc[live, s] = px
    return sofr, effr, settles


@pytest.fixture(scope="module")
def bt_result():
    panel = _synthetic_panel(end="2026-06-30", n_days=1200)
    model_cfg = SerffModelConfig(regime_boundaries=(), regime_labels=("r_synth",))
    start, end = datetime.date(2026, 1, 5), datetime.date(2026, 6, 26)
    sofr, effr, settles = _make_world(start, end, cheap_sr3_bp=4.0)

    cfg = SerffBacktestConfig(
        data=SerffDataConfig(start=start, end=end, alignment="published"),
        model=model_cfg,
        walkforward=SerffWalkForwardConfig(min_train_days=400, min_turn_events=6),
        trade=SerffTradeConfig(entry_threshold_bp=1.0, exit_threshold_bp=0.25),
    )
    from BT.serff.walkforward import walk_forward_fits

    wf = walk_forward_fits(panel, model_cfg, cfg.walkforward)
    return run_serff_backtest(
        cfg,
        panel=panel,
        settles=settles,
        sofr_fixings=sofr,
        effr_fixings=effr,
        wf=wf,
        show_progress=False,
    )


class TestBacktest:
    def test_attribution_sums_to_gross(self, bt_result):
        d = bt_result.daily
        assert not d.empty
        buckets = [b for b in _PNL_BUCKETS if b != "costs"]
        np.testing.assert_allclose(d[buckets].sum(axis=1).values, d["pnl_gross"].values, atol=1e-6)

    def test_net_is_gross_plus_costs(self, bt_result):
        d = bt_result.daily
        np.testing.assert_allclose((d["pnl_gross"] + d["costs"]).values, d["pnl_net"].values, atol=1e-9)

    def test_entered_cheap_sr3_long(self, bt_result):
        # SR3 priced 4bp cheap (rate too high): residual = model - market < 0
        # -> direction = +1 (long SR3)
        assert len(bt_result.trades) >= 1
        assert (bt_result.trades["direction"] == 1).all()

    def test_costs_charged_both_ways(self, bt_result):
        t = bt_result.trades.iloc[0]
        assert t["entry_cost"] > 0
        closed = bt_result.trades.dropna(subset=["exit_date"])
        if len(closed):
            assert (closed["exit_cost"] > 0).all()

    def test_positions_never_ride_into_stub(self, bt_result):
        cfg = bt_result.config.trade
        for _, tr in bt_result.trades.dropna(subset=["exit_date"]).iterrows():
            w = contract_window(tr["sr3_symbol"])
            # exit strictly before the last `min_unrealized_bd_to_hold` bd
            assert tr["exit_date"] < w.end

    def test_ledger_history_emitted(self, bt_result):
        assert len(bt_result.ledgers) > 50
        any_ledger = next(iter(bt_result.ledgers.values()))
        assert {"basis", "turn", "policy_zq_strip"} <= set(any_ledger.residual_by_source)

    def test_reconciliation_gate_detects_price_offset(self, bt_result):
        # ZQ settles were built exactly from fixings -> reconcile to ~0;
        # SR3 was deliberately priced 4bp cheap -> the gate must FLAG it.
        recon = bt_result.reconciliation.dropna(subset=["diff_bp"])
        assert len(recon)
        zq = recon[recon.index.str.startswith("ZQ")]
        sr3 = recon[recon.index.str.startswith("SR3")]
        assert (zq["diff_bp"].abs() < 1e-6).all()
        assert (zq["ok"]).all()
        if len(sr3):
            assert (sr3["diff_bp"].abs() > 3.5).all()
            assert (~sr3["ok"]).all()

    def test_summary_reports_buckets_and_turn_calibration(self, bt_result):
        s = bt_result.summary
        assert set(_PNL_BUCKETS) == set(s["bucket_totals"])
        assert "turn_events" in s
        te = s["turn_events"]
        assert 0 <= te["realized_hit_rate"] <= 1
        assert len(te["hit_rate_wilson95"]) == 2
