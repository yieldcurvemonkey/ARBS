import pytest
from SDRUtils.analytics.fomc import short_meeting_label


@pytest.mark.parametrize("raw,expected", [
    ("APR26", "APR26"),
    ("FOMC_APR2026", "APR26"),
    ("FOMC APR2026", "APR26"),
    ("FOMC_20260428", "APR26"),   # date-based fallback
    ("", ""),
    (None, ""),
])
def test_short_meeting_label_formats(raw, expected):
    assert short_meeting_label(raw) == expected
