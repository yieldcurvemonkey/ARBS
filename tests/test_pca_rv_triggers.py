import datetime as dt
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

from BT.signals.pca_rv_triggers import PCARVEntryTrigger, PCARVExitTrigger
from BT.signals.pca_rv_scanner import (
    PCARVScannerConfig, FlyCandidate, AnalyzedTrade,
)


def _make_trade(date, tenors=("2Y", "5Y", "10Y"), z=2.0, passes=True):
    cand = FlyCandidate(
        forward_start=None,
        tenors=tenors,
        weights=(-0.9, 1.0, -0.46),
        direction="receive_belly",
        zscore_belly=z,
        zscore_left=-1.0,
        zscore_right=-0.8,
        neutrality_check=(0.0, 0.0),
    )
    return AnalyzedTrade(
        candidate=cand,
        fly_series=pd.Series([1.0, 2.0, 3.0]),
        ou_speed=0.05,
        ou_mean=2.5,
        ou_vol=0.3,
        half_life_days=14,
        investment_horizon_days=42,
        current_level=3.0,
        target_level=2.5,
        stop_loss_level=3.25,
        lifetime_zscore=z,
        adf_pvalue=0.01,
        carry_bps=0.5,
        roll_bps=0.3,
        carry_roll_bps=0.8,
        expected_profit_bps=5.0,
        profit_cost_ratio=3.3,
        passes_filter=passes,
    )


def test_entry_trigger_fires_on_signal():
    d = pd.Timestamp("2023-06-15")
    trade = _make_trade(d)
    signal_table = {d: [trade]}
    cfg = PCARVScannerConfig(min_zscore_entry=1.5)
    trigger = PCARVEntryTrigger(signal_table, cfg)
    info = trigger.has_triggered(d, backtest=None)
    assert info.triggered is True


def test_entry_trigger_silent_when_no_signal():
    d = pd.Timestamp("2023-06-15")
    signal_table = {}
    cfg = PCARVScannerConfig()
    trigger = PCARVEntryTrigger(signal_table, cfg)
    info = trigger.has_triggered(d, backtest=None)
    assert info.triggered is False


def test_entry_trigger_skips_failing_filter():
    d = pd.Timestamp("2023-06-15")
    trade = _make_trade(d, passes=False)
    signal_table = {d: [trade]}
    cfg = PCARVScannerConfig()
    trigger = PCARVEntryTrigger(signal_table, cfg)
    info = trigger.has_triggered(d, backtest=None)
    assert info.triggered is False


def test_exit_trigger_on_target():
    d = pd.Timestamp("2023-06-15")
    trade = _make_trade(d)
    # Current level is at target (ou_mean=2.5)
    trade_at_target = AnalyzedTrade(
        candidate=trade.candidate,
        fly_series=trade.fly_series,
        ou_speed=trade.ou_speed,
        ou_mean=2.5,
        ou_vol=trade.ou_vol,
        half_life_days=trade.half_life_days,
        investment_horizon_days=trade.investment_horizon_days,
        current_level=2.5,  # at target
        target_level=2.5,
        stop_loss_level=trade.stop_loss_level,
        lifetime_zscore=0.0,
        adf_pvalue=trade.adf_pvalue,
        carry_bps=trade.carry_bps,
        roll_bps=trade.roll_bps,
        carry_roll_bps=trade.carry_roll_bps,
        expected_profit_bps=trade.expected_profit_bps,
        profit_cost_ratio=trade.profit_cost_ratio,
        passes_filter=True,
    )
    signal_table = {d: [trade_at_target]}
    cfg = PCARVScannerConfig()
    trigger = PCARVExitTrigger(signal_table, cfg)
    # Mock backtest with open positions
    bt = MagicMock()
    pos = MagicMock()
    pos.meta = {"tags": ["pca_rv_spot_2Y_5Y_10Y"]}
    pos.opened = d - pd.Timedelta(days=5)
    bt.portfolio.positions = [pos]
    info = trigger.has_triggered(d, backtest=bt)
    assert info.triggered is True
