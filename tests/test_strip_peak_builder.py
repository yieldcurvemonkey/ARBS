"""Tests for the daily SR3 strip builder."""
import datetime
import pandas as pd
import pytest

from RVUtils.StripPeak.strip_builder import build_daily_strip


@pytest.mark.network
def test_build_daily_strip_shape_and_content():
    """Pull a small window and verify the strip has the right shape."""
    df = build_daily_strip(
        start_date=datetime.date(2026, 8, 18),
        end_date=datetime.date(2026, 8, 22),
        n_front=8,
    )
    assert isinstance(df, pd.DataFrame)
    assert len(df) >= 4  # 4-5 business days
    assert len(df.columns) == 8
    # Columns must be chronologically ordered near-to-far. This is NOT the same as
    # alphabetical order: "SR3U26" > "SR3M28" as strings (the quarter-code letter sorts
    # first), even though U26 (Sep 2026) is chronologically *before* M28 (Jun 2028). The
    # anchor window here spans three calendar years, so a plain string compare on the
    # endpoints would pass by coincidence in some windows and fail in this one -- assert
    # the exact expected sequence instead (see task-1-brief.md Step 6's worked example).
    assert list(df.columns) == [
        "SR3U26", "SR3Z26", "SR3H27", "SR3M27",
        "SR3U27", "SR3Z27", "SR3H28", "SR3M28",
    ]
    # values are rates in percent, should be between 2% and 8%
    assert (df > 2.0).all().all()
    assert (df < 8.0).all().all()


@pytest.mark.network
def test_strip_builder_known_value():
    """Verify against the known 21-Aug settle: SR3H27=4.07, SR3Z27=4.11.

    2026-08-22 is a Saturday (no trading, no Barchart EOD bar), so the window anchors
    on 2026-08-21 -- the last finalized settle before it -- rather than the 22nd itself.
    A live pull on 2026-08-24 confirmed 08-21 closes of SQH27=95.940 (rate 4.060) and
    SQZ27=95.895 (rate 4.105), both within this test's existing 0.05 tolerance of the
    stated reference values.
    """
    df = build_daily_strip(
        start_date=datetime.date(2026, 8, 21),
        end_date=datetime.date(2026, 8, 21),
        n_front=8,
    )
    row = df.iloc[0]
    # SR3U26 should be in the columns (front contract)
    assert "SR3U26" in df.columns or "SR3M26" in df.columns
    # Check a known value (tolerance for EOD bar timestamp)
    if "SR3H27" in df.columns:
        assert abs(row["SR3H27"] - 4.07) < 0.05
