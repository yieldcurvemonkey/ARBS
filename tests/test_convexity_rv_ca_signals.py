r"""The enrichment layer: lagging, provenance, and Citi's Figure 4.

Properties of the code, on synthetic inputs where the answer is known by
construction. The live measurement lives in the notebook.

The two failures being designed against are both ones this package has already
been bitten by:

* **A signal that reads a number published after the date it is indexed on.**
  Found twice now — a ``bfill`` in the SR3 price panel, and an unlagged CFTC
  report date worth three business days.
* **Two different quantities under one column name.** "Open interest" served
  per contract and "open interest" served as a weekly whole-strip aggregate are
  not the same measurement, and a caller who cannot tell them apart will report
  whichever arrived as though it were the other. Hence the provenance dict.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import ca_signals as S


def _raw_cftc(n_weeks=120, market="SOFR-3M - CHICAGO MERCANTILE EXCHANGE",
              seed=0) -> pd.DataFrame:
    """Weekly TFF rows on Tuesdays, with the columns the builder reads."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-05", periods=n_weeks, freq="7D")
    dealer = np.cumsum(rng.normal(0, 50_000, n_weeks)) + 500_000
    return pd.DataFrame({
        "Market_and_Exchange_Names": [market] * n_weeks,
        "Report_Date_as_YYYY-MM-DD": [d.strftime("%Y-%m-%d") for d in dates],
        "Dealer_Positions_Long_All": dealer + 100_000,
        "Dealer_Positions_Short_All": np.full(n_weeks, 100_000.0),
        "Lev_Money_Positions_Long_All": np.full(n_weeks, 50_000.0),
        "Lev_Money_Positions_Short_All": -dealer + 50_000,
        "Asset_Mgr_Positions_Long_All": np.full(n_weeks, 20_000.0),
        "Asset_Mgr_Positions_Short_All": np.full(n_weeks, 10_000.0),
        "Open_Interest_All": np.abs(dealer) * 3 + 1_000_000,
    })


CFG = S.EnrichmentConfig(start=dt.date(2021, 1, 1), end=dt.date(2023, 6, 30))


# ---------------------------------------------------------------------------
# 1. Lagging
# ---------------------------------------------------------------------------
def test_positioning_is_not_readable_on_its_own_report_date():
    """The Tuesday reading must not be visible on the Tuesday."""
    raw = _raw_cftc()
    panel, prov = S.build_enrichment_panel(CFG, raw_cftc=raw)
    assert "dealer_net" in panel, prov

    first_report = pd.Timestamp("2021-01-05")          # a Tuesday
    visible = panel.loc[panel.index <= first_report, "dealer_net"].dropna()
    assert visible.empty, (
        f"the {first_report.date()} report is readable on or before its own "
        f"report date: {visible.to_dict()}"
    )


def test_the_lag_is_recorded_in_the_provenance():
    """A lag nobody can see is a lag nobody will check."""
    _, prov = S.build_enrichment_panel(CFG, raw_cftc=_raw_cftc())
    assert "lagged" in prov["dealer_net"], prov["dealer_net"]
    assert "publication" in prov["dealer_net"]


def test_extra_lag_moves_the_series_further_and_is_not_applied_twice():
    a, _ = S.build_enrichment_panel(CFG, raw_cftc=_raw_cftc())
    b, _ = S.build_enrichment_panel(
        S.EnrichmentConfig(start=CFG.start, end=CFG.end, extra_lag_bdays=5),
        raw_cftc=_raw_cftc())
    fa = a["dealer_net"].first_valid_index()
    fb = b["dealer_net"].first_valid_index()
    assert fb > fa, "extra_lag_bdays did nothing"
    assert int(np.busday_count(fa.date(), fb.date())) == 5, (
        f"extra lag moved the series by {np.busday_count(fa.date(), fb.date())} "
        "business days, not 5 — it is being applied more than once, or the base "
        "lag changed"
    )


def test_market_series_are_lagged_too():
    """The basis and OI are market observables, but still not same-day."""
    idx = pd.bdate_range("2021-01-01", "2021-03-01")
    basis = pd.DataFrame({"10y": np.arange(len(idx), dtype=float)}, index=idx)
    panel, prov = S.build_enrichment_panel(CFG, raw_cftc=None, basis=basis)
    col = "ccp_basis_10y_bp"
    assert col in panel, prov
    # value 0.0 belongs to 2021-01-01 and must appear one bday later
    served = panel[col].dropna()
    assert served.index[0] > idx[0]
    assert "lagged" in prov[col]


# ---------------------------------------------------------------------------
# 2. Provenance — the two open interests are not the same thing
# ---------------------------------------------------------------------------
def test_whole_strip_open_interest_says_so():
    _, prov = S.build_enrichment_panel(CFG, raw_cftc=_raw_cftc())
    assert "open_interest" in prov
    p = prov["open_interest"]
    assert "WHOLE" in p.upper(), p
    assert "per-contract" in p, (
        "the provenance does not warn that this is not per-contract OI, which "
        "is the distinction the whole column turns on"
    )


def test_caller_supplied_open_interest_is_labelled_differently():
    idx = pd.bdate_range("2021-01-01", "2021-06-01")
    oi = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    _, prov = S.build_enrichment_panel(CFG, raw_cftc=None, open_interest=oi)
    assert "caller-supplied" in prov["open_interest"]


# ---------------------------------------------------------------------------
# 3. Citi's Figure 4
# ---------------------------------------------------------------------------
def test_the_regression_recovers_a_planted_slope():
    """Verify the checker against a known answer before trusting it."""
    idx = pd.bdate_range("2021-01-01", "2025-12-31")
    rng = np.random.default_rng(7)
    pos = pd.Series(np.cumsum(rng.normal(0, 40_000, len(idx))), index=idx)
    slope = 3e-06
    resid = pos * slope + pd.Series(rng.normal(0, 0.02, len(idx)), index=idx)

    fit = S.positioning_regression(resid, pos)
    assert fit.n > 40
    assert fit.slope == pytest.approx(slope, rel=0.35), (
        f"planted slope {slope:.2e}, recovered {fit.slope:.2e}"
    )
    assert fit.r2 > 0.5


def test_the_regression_is_on_changes_not_levels():
    """Two independent random walks must NOT produce a large R2.

    A levels-on-levels regression of two trending series reports a big number
    that is about the trends. Citi's Figure 4 is monthly CHANGES; running it any
    other way is not running it.
    """
    idx = pd.bdate_range("2021-01-01", "2025-12-31")
    rng = np.random.default_rng(11)
    a = pd.Series(np.cumsum(rng.normal(0, 1.0, len(idx))), index=idx)
    b = pd.Series(np.cumsum(rng.normal(0, 40_000, len(idx))), index=idx)

    fit = S.positioning_regression(a, b)
    assert fit.r2 < 0.35, (
        f"R2 {fit.r2:.3f} between two independent random walks — the regression "
        "is being run in levels, or the differencing is not happening"
    )


def test_the_published_target_is_carried_with_its_provenance():
    c = S.CITI_FIG4_BLUES
    assert c["r2"] == pytest.approx(0.2724)
    assert c["slope"] == pytest.approx(2e-06)
    assert c["market"] == "Eurodollars", (
        "the target is a EURODOLLAR number; a SOFR run reproduces the method, "
        "not the result, and the label is what keeps that visible"
    )
    assert c["freq"] == "M"


def test_a_short_sample_returns_nan_rather_than_a_number():
    idx = pd.bdate_range("2021-01-01", periods=20)
    s = pd.Series(np.arange(20, dtype=float), index=idx)
    fit = S.positioning_regression(s, s)
    assert not np.isfinite(fit.slope), "a 1-observation fit reported a slope"


# ---------------------------------------------------------------------------
# 4. Broadcasting onto the screen
# ---------------------------------------------------------------------------
def test_enrichment_columns_are_prefixed_so_they_cannot_be_read_as_per_pack():
    screen = pd.DataFrame({"pack": ["A", "B"], "ca_bp": [1.0, 2.0]})
    idx = pd.bdate_range("2021-01-01", "2021-02-01")
    enr = pd.DataFrame({"dealer_net": np.arange(len(idx), dtype=float)}, index=idx)
    out = S.enrich_screen(screen, enr, dt.date(2021, 1, 15))
    assert "enr_dealer_net" in out.columns
    assert out["enr_dealer_net"].nunique() == 1, (
        "a per-DATE quantity varies by pack; it has been joined wrongly"
    )
