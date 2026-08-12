"""The local reference provider must reproduce the fetched path exactly.

`FixedRateBondsMDP.get_bond_reference_data` calls `_fetch_fiscaldata` directly and bypasses the
reference cache, so a 350-day panel made 350 HTTP round-trips for one static universe file. A bond's
identity is fixed at auction; only *which bonds are alive* and *how they rank* vary by date, and
both are local computations over the universe.

Replacing a fetch with a computation is only safe if the computation gives the same answer, and
that was **measured against 48 reference frames built by the fetched path**, not assumed. The
boundary that reproduces all 48 is `issue_date <= as_of < maturity_date` — a bond is tradeable on
its issue day and not on the day it matures. Neither boundary matches `_filter_and_rank_ref_df`,
whose strict `issue_date < as_of` moved 181 ranks on 2024-09-03 and whose `maturity_date >= as_of`
keeps a bond on its maturity date.

These tests pin the rule on synthetic issues whose answer is known by construction, so they run
without network. The 48-day tie-out against live fetched data is recorded in PLAN.md.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from BT.gss_fly.data import LocalReferenceProvider


def _universe() -> pd.DataFrame:
    """Three 5-year issues in one on-the-run bucket, plus one that matures mid-sample."""
    rows = [
        # cusip,      auction,      issue,        maturity,     oi
        ("OLD5Y", "2023-02-22", "2023-02-28", "2028-02-28", "5-Year"),
        ("MID5Y", "2023-05-24", "2023-05-31", "2028-05-31", "5-Year"),
        ("NEW5Y", "2023-08-23", "2023-08-31", "2028-08-31", "5-Year"),
        ("EXPIRE", "2021-02-22", "2021-02-28", "2023-06-30", "2-Year"),
    ]
    return pd.DataFrame(
        {
            "cusip": [r[0] for r in rows],
            "auction_date": [pd.Timestamp(r[1]).date() for r in rows],
            "issue_date": [pd.Timestamp(r[2]).date() for r in rows],
            "maturity_date": [pd.Timestamp(r[3]).date() for r in rows],
            "oi": [r[4] for r in rows],
        }
    )


@pytest.fixture
def provider(monkeypatch):
    """A provider over the synthetic universe, with no network and no MDP roll helper."""
    p = LocalReferenceProvider.__new__(LocalReferenceProvider)
    p.universe = _universe()
    # The roll takes effect the business day after auction. Computed here rather than imported so
    # the test needs no MDP; using issue_date as the roll instead would make the issue-day boundary
    # untestable by construction, since `roll < as_of` would then exclude the very bond under test.
    p._roll = pd.Series(
        [(pd.Timestamp(a) + pd.tseries.offsets.BDay(1)).date() for a in p.universe["auction_date"]],
        index=p.universe.index,
    )
    return p


def test_a_bond_is_tradeable_on_its_issue_day(provider):
    """The boundary that cost 181 ranks: the fetched path INCLUDES a bond issued on as_of."""
    out = provider(datetime.date(2023, 8, 31))
    assert "NEW5Y" in set(out["cusip"])


def test_a_bond_is_not_tradeable_on_its_maturity_day(provider):
    out = provider(datetime.date(2023, 6, 30))
    assert "EXPIRE" not in set(out["cusip"])
    # ...but it was the day before
    assert "EXPIRE" in set(provider(datetime.date(2023, 6, 29))["cusip"])


def test_the_new_issue_demotes_the_previous_on_the_run(provider):
    """Why the issue boundary is not cosmetic for this book.

    With `exclude_ranks=(0,)` the GSS universe drops rank 0. Whether NEW5Y is present therefore
    decides whether MID5Y is rank 0 and dropped, or rank 1 and traded.
    """
    before = provider(datetime.date(2023, 8, 30)).set_index("cusip")["rank"]
    after = provider(datetime.date(2023, 8, 31)).set_index("cusip")["rank"]
    assert before["MID5Y"] == 0        # MID5Y is the on-the-run the day before
    assert after["NEW5Y"] == 0         # the new issue takes rank 0 on its issue day
    assert after["MID5Y"] == 1         # and MID5Y becomes tradeable for this book
    assert after["OLD5Y"] == 2


def test_rank_is_per_on_the_run_bucket(provider):
    out = provider(datetime.date(2023, 6, 29)).set_index("cusip")["rank"]
    assert out["EXPIRE"] == 0          # only issue in the 2-Year bucket
    assert sorted(out.loc[["OLD5Y", "MID5Y"]].tolist()) == [0, 1]


def test_a_bond_issued_after_as_of_is_absent(provider):
    assert "NEW5Y" not in set(provider(datetime.date(2023, 8, 30))["cusip"])


# ---------------------------------------------------- the silent-universe guard
def test_local_provider_supplies_ttm(provider):
    """The column whose absence emptied the universe on 284 of 332 dates."""
    out = provider(datetime.date(2023, 8, 31))
    assert "ttm" in out.columns
    assert out["ttm"].notna().all()
    # OLD5Y matures 2028-02-28, so ~4.5y out from 2023-08-31
    assert out.set_index("cusip").loc["OLD5Y", "ttm"] == pytest.approx(4.5, abs=0.02)


def test_ttm_uses_actualactual_isda_not_365_25():
    """`days/365.25` is off by ~half a day, and `min_ttm` is a hard cutoff at exactly 3.0."""
    import QuantLib as ql

    from BT.gss_fly.data import LocalReferenceProvider as P

    as_of, mat = datetime.date(2024, 9, 25), datetime.date(2027, 9, 30)
    got = P._ttm_years(mat, as_of)
    want = ql.ActualActual(ql.ActualActual.ISDA).yearFraction(ql.Date(25, 9, 2024), ql.Date(30, 9, 2027))
    assert got == pytest.approx(want, abs=1e-12)
    naive = (pd.Timestamp(mat) - pd.Timestamp(as_of)).days / 365.25
    assert abs(got - naive) > 1e-4, "if these agreed the convention would not matter"


def test_a_null_gating_column_is_refused_not_ignored():
    """A present-but-null gate excludes every bond. Refuse the panel rather than trade nothing."""
    from BT.gss_fly.data import CurvePanel, _assert_reference_is_usable

    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    ref = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "cusip": ["A", "A", "B", "B"],
            "ttm": [5.0, np.nan, 7.0, np.nan],   # second date never populated
            "cpn": [4.0, 4.0, 4.0, 4.0],
            "rank": [1, 1, 2, 2],
        }
    )
    panel = CurvePanel(
        s2c=pd.DataFrame(index=dates), ytm=pd.DataFrame(index=dates),
        ttm=pd.DataFrame(index=dates), reference=ref, rmse=pd.Series(index=dates, dtype=float),
    )
    with pytest.raises(RuntimeError, match="ttm"):
        _assert_reference_is_usable(panel)


def test_a_fully_populated_reference_passes_the_guard():
    from BT.gss_fly.data import CurvePanel, _assert_reference_is_usable

    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    ref = pd.DataFrame(
        {"date": list(dates) * 2, "cusip": ["A", "A", "B", "B"],
         "ttm": [5.0, 5.0, 7.0, 7.0], "cpn": [4.0] * 4, "rank": [1, 1, 2, 2]}
    )
    panel = CurvePanel(
        s2c=pd.DataFrame(index=dates), ytm=pd.DataFrame(index=dates),
        ttm=pd.DataFrame(index=dates), reference=ref, rmse=pd.Series(index=dates, dtype=float),
    )
    _assert_reference_is_usable(panel)  # must not raise
