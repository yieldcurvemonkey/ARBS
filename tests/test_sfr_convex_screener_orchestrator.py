import datetime
import pytest

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig, build_snapshot

pytestmark = pytest.mark.slow


@pytest.mark.integration
def test_build_snapshot_smoke():
    cfg = SFRConvexScreenerConfig(universe_size=4, calendar_gaps=(1,), fly_gaps=(1,))
    snap = build_snapshot(cfg, as_of=datetime.date(2026, 4, 28))
    assert snap.as_of == datetime.date(2026, 4, 28)
    assert len(snap.results) > 0
    df = snap.to_dataframe()
    assert "asymmetry_ratio" in df.columns
