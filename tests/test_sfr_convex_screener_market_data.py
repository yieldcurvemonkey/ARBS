import datetime
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
