"""Tests for OBI event contract strategy."""
import numpy as np
import pandas as pd
import pytest

from OBI.config import BacktestConfig, ExecutionConfig, POLYMARKET_5M_BTC, KALSHI_15M_BTC, build_config
from OBI.signals import raw_obi, multi_level_obi, weighted_obi, compute_obi, simulate_contract_book, generate_signals
from OBI.backtest import run_backtest, generate_contract_windows, compute_metrics, select_best_configs


class TestOBISignals:
    def test_raw_obi_balanced(self):
        assert raw_obi(100, 100) == 0.0

    def test_raw_obi_bid_heavy(self):
        assert raw_obi(200, 100) == pytest.approx(1 / 3)

    def test_raw_obi_ask_heavy(self):
        assert raw_obi(100, 200) == pytest.approx(-1 / 3)

    def test_raw_obi_zero(self):
        assert raw_obi(0, 0) == 0.0

    def test_multi_level_obi(self):
        bids = pd.DataFrame({"price": [0.50, 0.49, 0.48], "quantity": [100, 50, 30]})
        asks = pd.DataFrame({"price": [0.52, 0.53, 0.54], "quantity": [80, 40, 20]})
        obi = multi_level_obi(bids, asks, levels=3)
        assert obi > 0  # bid-heavy

    def test_weighted_obi(self):
        bids = pd.DataFrame({"price": [0.48, 0.46], "quantity": [100, 50]})
        asks = pd.DataFrame({"price": [0.52, 0.54], "quantity": [80, 40]})
        obi = weighted_obi(bids, asks, mid_price=0.50, depth_pct=0.05)
        assert -1 <= obi <= 1

    def test_simulate_contract_book(self):
        bids, asks, mid = simulate_contract_book(0.6, depth_contracts=500)
        assert len(bids) == 10
        assert len(asks) == 10
        assert 0.0 < mid < 1.0
        assert all(bids["quantity"] > 0)

    def test_generate_signals_follow(self):
        obi = pd.Series([0.3, -0.3, 0.05, 0.5, -0.5])
        sig = generate_signals(obi, threshold=0.2, mode="follow")
        assert sig.iloc[0] == 1
        assert sig.iloc[1] == -1
        assert sig.iloc[2] == 0

    def test_generate_signals_fade(self):
        obi = pd.Series([0.3, -0.3])
        sig = generate_signals(obi, threshold=0.2, mode="fade")
        assert sig.iloc[0] == -1
        assert sig.iloc[1] == 1


class TestBacktest:
    @pytest.fixture
    def synthetic_btc(self):
        idx = pd.date_range("2025-05-01", "2025-05-02", freq="1min", tz="UTC")
        rng = np.random.default_rng(42)
        prices = 100000 * np.exp(np.cumsum(rng.normal(0, 0.0003, len(idx))))
        return pd.DataFrame({
            "open": prices,
            "high": prices * 1.001,
            "low": prices * 0.999,
            "close": prices,
            "volume": rng.lognormal(10, 1, len(idx)),
        }, index=idx)

    def test_generate_contract_windows(self, synthetic_btc):
        contracts = generate_contract_windows(synthetic_btc, duration_minutes=5)
        assert len(contracts) > 0
        assert "outcome" in contracts.columns
        assert set(contracts["outcome"].unique()).issubset({0, 1})

    def test_run_backtest_basic(self, synthetic_btc):
        cfg = BacktestConfig(
            start_date="2025-05-01",
            end_date="2025-05-02",
            contract_duration_minutes=5,
        )
        result = run_backtest(cfg, btc_prices=synthetic_btc)
        assert result.metrics["n_trades"] > 0
        assert "sharpe" in result.metrics
        assert "win_rate" in result.metrics

    def test_run_backtest_fade_mode(self, synthetic_btc):
        cfg = BacktestConfig(
            start_date="2025-05-01",
            end_date="2025-05-02",
            signal_mode="fade",
        )
        result = run_backtest(cfg, btc_prices=synthetic_btc)
        assert result.metrics["n_trades"] > 0

    def test_run_backtest_kalshi(self, synthetic_btc):
        cfg = BacktestConfig(
            start_date="2025-05-01",
            end_date="2025-05-02",
            venue="kalshi",
            contract_duration_minutes=15,
        )
        result = run_backtest(cfg, btc_prices=synthetic_btc)
        assert result.metrics["n_trades"] > 0

    def test_run_backtest_scaled_sizing(self, synthetic_btc):
        cfg = BacktestConfig(
            start_date="2025-05-01",
            end_date="2025-05-02",
            sizing_mode="scaled",
        )
        result = run_backtest(cfg, btc_prices=synthetic_btc)
        assert result.metrics["n_trades"] > 0

    def test_metrics_consistency(self, synthetic_btc):
        cfg = BacktestConfig(start_date="2025-05-01", end_date="2025-05-02")
        result = run_backtest(cfg, btc_prices=synthetic_btc)
        m = result.metrics
        assert m["n_trades"] == m["n_wins"] + m["n_losses"]
        if m["n_trades"] > 0:
            assert 0 <= m["win_rate"] <= 1


class TestConfig:
    def test_polymarket_preset(self):
        assert POLYMARKET_5M_BTC.venue == "polymarket"
        assert POLYMARKET_5M_BTC.contract_duration_minutes == 5

    def test_kalshi_preset(self):
        assert KALSHI_15M_BTC.venue == "kalshi"
        assert KALSHI_15M_BTC.contract_duration_minutes == 15

    def test_build_config(self):
        cfg = build_config(POLYMARKET_5M_BTC, {"entry_threshold": 0.5})
        assert cfg.entry_threshold == 0.5
        assert cfg.venue == "polymarket"

    def test_config_roundtrip(self):
        cfg = BacktestConfig(entry_threshold=0.42)
        d = cfg.to_dict()
        cfg2 = BacktestConfig.from_dict(d)
        assert cfg2.entry_threshold == 0.42


class TestSelectBest:
    def test_select_best_configs(self):
        df = pd.DataFrame({
            "entry_threshold": [0.1, 0.2, 0.3],
            "sharpe": [1.5, 2.0, 0.5],
            "win_rate": [0.55, 0.60, 0.70],
            "total_pnl": [100, 200, 50],
            "max_drawdown_pct": [5.0, 3.0, 2.0],
            "expectancy": [0.05, 0.08, 0.02],
        })
        best = select_best_configs(df)
        assert "best_sharpe" in best
        assert best["best_sharpe"]["sharpe"] == 2.0
