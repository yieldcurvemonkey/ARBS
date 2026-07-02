"""Live-source integration tests (network) for the SERFF data layer."""

import datetime

import pandas as pd
import pytest

pytestmark = [pytest.mark.network, pytest.mark.integration]


class TestLiveSources:
    def test_h41_series(self):
        from MDP.USMoneyMarkets import fetch_h41_series

        res = fetch_h41_series("reserves")
        assert res.values.index.is_monotonic_increasing
        assert res.values.iloc[-1] > 1000  # $bn scale
        rrp = fetch_h41_series("rrp")
        assert rrp.values.min() >= 0
        tga = fetch_h41_series("tga")
        assert (tga.published > tga.values.index).all()  # release after reference

    def test_gdp(self):
        from MDP.USMoneyMarkets import fetch_nominal_gdp

        gdp = fetch_nominal_gdp()
        assert gdp["gdp"].iloc[-1] > 20000  # $bn SAAR
        assert (gdp["published"] > gdp.index).all()

    def test_panel_matches_fixture_head(self, serff_panel):
        from BT.serff.config import SerffDataConfig
        from BT.serff.data import build_panel

        cfg = SerffDataConfig(start=datetime.date(2018, 4, 2), end=datetime.date(2019, 12, 31))
        live = build_panel(cfg)
        fixture = serff_panel.loc[: pd.Timestamp("2019-12-31")]
        joined = live[["spread"]].join(fixture[["spread"]], rsuffix="_fix").dropna()
        assert len(joined) > 400
        # fixings are unrevised: spreads must agree exactly
        assert (joined["spread"] - joined["spread_fix"]).abs().max() < 1e-9

    def test_published_alignment_lags_weeklies(self):
        from BT.serff.config import SerffDataConfig
        from BT.serff.data import build_panel

        cfg_c = SerffDataConfig(start=datetime.date(2024, 1, 2), end=datetime.date(2024, 6, 28), alignment="contemporaneous")
        cfg_p = SerffDataConfig(start=datetime.date(2024, 1, 2), end=datetime.date(2024, 6, 28), alignment="published")
        contemp = build_panel(cfg_c)
        published = build_panel(cfg_p)
        both = contemp[["res"]].join(published[["res"]], rsuffix="_pub").dropna()
        # published mode must never see a Wednesday level before contemporaneous does
        # (values equal or older -> on Wed/Thu rows they differ)
        assert (both["res"] != both["res_pub"]).mean() > 0.2
