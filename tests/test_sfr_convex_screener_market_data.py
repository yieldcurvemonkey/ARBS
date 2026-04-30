import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener._market_data import (
    SFRMarketData,
    load_market_data,
    resolve_universe_symbols,
)


@pytest.mark.integration
def test_resolve_universe_symbols_returns_12_sr3():
    cfg = SFRConvexScreenerConfig()
    syms = resolve_universe_symbols(cfg, as_of=datetime.date(2026, 4, 28))
    assert len(syms) == 12
    for s in syms:
        assert s.startswith("SFR")


@pytest.mark.integration
def test_load_market_data_smoke():
    cfg = SFRConvexScreenerConfig()
    md = load_market_data(cfg, as_of=datetime.date(2026, 4, 28))
    assert isinstance(md, SFRMarketData)
    assert len(md.symbols) == cfg.universe_size
    assert md.curve_handle is not None
    assert not md.futures_df.empty
    assert "price" in md.futures_df.columns
    assert "open_interest" in md.futures_df.columns
    assert md.price_panel.shape[0] >= cfg.correlation_window // 2


def test_smile_strike_mode_default_is_delta_sparse():
    """Default config picks the sparse 5-delta grid (≈20 strikes/contract)."""
    cfg = SFRConvexScreenerConfig()
    assert cfg.smile_strike_mode == "delta_sparse"


def test_smile_strike_mode_delta_sparse_omits_strike_offsets():
    """When mode=delta_sparse, fetch_sabr_smile is called WITHOUT
    ``strike_offsets_bps`` so the MDP picks the default 5/10/.../50-delta grid."""
    cfg = SFRConvexScreenerConfig(smile_strike_mode="delta_sparse")
    captured_requests: list = []

    class _StubSmile:
        pass

    with patch("RVUtils.SFRConvexScreener._market_data.IRSwapsMDP") as mock_curve, \
         patch("RVUtils.SFRConvexScreener._market_data.STIRFutureMDP") as mock_fut, \
         patch("RVUtils.SFRConvexScreener._market_data.STIRFutureOptionMDP") as mock_opt:
        mock_curve.return_value.get_pricer.return_value = object()
        mock_fut.return_value.get_data.return_value = {}
        mock_fut.return_value.get_bulk_data.return_value = {}

        def _fake_fetch(req: dict):
            captured_requests.append(dict(req))
            return _StubSmile()

        mock_opt.return_value.fetch_sabr_smile.side_effect = _fake_fetch
        load_market_data(cfg, as_of=datetime.date(2026, 4, 28))

    assert captured_requests, "fetch_sabr_smile was never called"
    for req in captured_requests:
        assert "strike_offsets_bps" not in req, (
            f"delta_sparse must not pass strike_offsets_bps, got {req!r}"
        )
        # ``deltas`` is also omitted so MDP uses its default 10-point grid.
        assert "deltas" not in req


def test_smile_strike_mode_listed_passes_listed_token():
    """When mode=listed, ``strike_offsets_bps='listed'`` is forwarded to MDP."""
    cfg = SFRConvexScreenerConfig(smile_strike_mode="listed")
    captured_requests: list = []

    class _StubSmile:
        pass

    with patch("RVUtils.SFRConvexScreener._market_data.IRSwapsMDP") as mock_curve, \
         patch("RVUtils.SFRConvexScreener._market_data.STIRFutureMDP") as mock_fut, \
         patch("RVUtils.SFRConvexScreener._market_data.STIRFutureOptionMDP") as mock_opt:
        mock_curve.return_value.get_pricer.return_value = object()
        mock_fut.return_value.get_data.return_value = {}
        mock_fut.return_value.get_bulk_data.return_value = {}

        def _fake_fetch(req: dict):
            captured_requests.append(dict(req))
            return _StubSmile()

        mock_opt.return_value.fetch_sabr_smile.side_effect = _fake_fetch
        load_market_data(cfg, as_of=datetime.date(2026, 4, 28))

    assert captured_requests, "fetch_sabr_smile was never called"
    for req in captured_requests:
        assert req.get("strike_offsets_bps") == "listed"


def test_smile_strike_mode_unknown_raises():
    cfg = SFRConvexScreenerConfig(smile_strike_mode="weird_mode")
    with patch("RVUtils.SFRConvexScreener._market_data.IRSwapsMDP") as mock_curve, \
         patch("RVUtils.SFRConvexScreener._market_data.STIRFutureMDP") as mock_fut, \
         patch("RVUtils.SFRConvexScreener._market_data.STIRFutureOptionMDP") as mock_opt:
        mock_curve.return_value.get_pricer.return_value = object()
        mock_fut.return_value.get_data.return_value = {}
        mock_fut.return_value.get_bulk_data.return_value = {}
        with pytest.raises(ValueError, match="smile_strike_mode"):
            load_market_data(cfg, as_of=datetime.date(2026, 4, 28))


def test_config_summary_includes_smile_strike_mode():
    """Cache hash must include smile mode so old listed-mode pickles don't
    silently get reused after the default flips to delta_sparse."""
    from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache

    cfg_a = SFRConvexScreenerConfig(smile_strike_mode="listed")
    cfg_b = SFRConvexScreenerConfig(smile_strike_mode="delta_sparse")
    sum_a = _config_summary_for_cache(cfg_a)
    sum_b = _config_summary_for_cache(cfg_b)
    assert sum_a["smile_strike_mode"] == "listed"
    assert sum_b["smile_strike_mode"] == "delta_sparse"
    assert sum_a != sum_b


def test_config_summary_includes_joint_methods():
    """Cache hash must include joint_methods so a (HGC, PC) prime can't
    silently mix with a (CS, HGC, PC) prime — they produce different
    metrics_by_method dicts even though primary_method matches."""
    from RVUtils.SFRConvexScreener import JointMethod
    from RVUtils.SFRConvexScreener.backtest import _config_summary_for_cache

    cfg_full = SFRConvexScreenerConfig(joint_methods=(
        JointMethod.COMMON_STATE,
        JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        JointMethod.PERFECT_CORRELATION,
    ))
    cfg_lite = SFRConvexScreenerConfig(joint_methods=(
        JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        JointMethod.PERFECT_CORRELATION,
    ))
    sum_full = _config_summary_for_cache(cfg_full)
    sum_lite = _config_summary_for_cache(cfg_lite)
    assert sum_full["joint_methods"] == ["common_state", "historical_gaussian_copula", "perfect_correlation"]
    assert sum_lite["joint_methods"] == ["historical_gaussian_copula", "perfect_correlation"]
    assert sum_full != sum_lite
