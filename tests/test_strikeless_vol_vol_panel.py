import datetime as dt

import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import VolQuote
from RVUtils.StrikelessVol.panels import implied_quote, vol_panel


def test_asset_map_covers_all_four_markets():
    from definitions.IRSwaptions import ASSET_IDS_MAP

    for curve in ("USD-SOFR-1D", "EUR-ESTR", "GBP-SONIA", "JPY-TONAR"):
        assert curve in ASSET_IDS_MAP, f"missing swaption coverage for {curve}"
        assert "2y 10y" in set(ASSET_IDS_MAP[curve].values())
        assert "10y 10y" in set(ASSET_IDS_MAP[curve].values())


def test_implied_quote_is_labelled_and_in_bp_per_day():
    panel = pd.DataFrame(
        {"2y10y": [5.329]}, index=pd.DatetimeIndex(["2026-08-03"])
    )
    q = implied_quote(panel, "2y10y", pd.Timestamp("2026-08-03"), market="USD")
    assert isinstance(q, VolQuote)
    assert q.measure == "implied"
    assert "USD" in q.underlying and "2y10y" in q.underlying
    assert q.value_bp_day == pytest.approx(5.329)
    assert q.annual_normals == pytest.approx(84.6, abs=0.05)


@pytest.mark.network
@pytest.mark.slow
def test_usd_vol_panel_history_starts_2017_and_matches_the_desk_level():
    panel = vol_panel(
        "USD-SOFR-1D",
        ["2y 10y", "10y 10y"],
        dt.date(2016, 1, 1),
        dt.date(2026, 8, 3),
    )
    assert panel.index.min() >= pd.Timestamp("2017-01-01")
    assert panel.index.min() <= pd.Timestamp("2017-01-31")
    assert panel.loc["2026-08-03", "2y10y"] == pytest.approx(5.329, abs=0.05)
    assert len(panel) > 2000
