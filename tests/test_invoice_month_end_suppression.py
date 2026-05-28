"""Tests for end-of-month invoice swap false-match suppression.

Near month-end the spot date (T+2) can coincide with a CBOT Treasury
futures delivery date.  Combined with ±1 day tolerance on CTD maturity,
plain benchmark-tenor spot swaps get falsely labeled as TREASURY INVOICE.

The fix in _apply_invoice_swap_lookup suppresses invoice labeling when:
  1. The trade is spot-starting (forward_start_years <= 0.02)
  2. The tenor is a clean benchmark year (1,2,3,4,5,7,10,15,20,25,30)

Real invoice swaps have non-standard tenors (~1yr 9mo, ~4yr 3mo, etc.)
and are NOT suppressed.
"""
import pandas as pd
import pytest

from SDRUtils.products.usd.usd_swaps import _apply_invoice_swap_lookup


@pytest.fixture
def delivery_date():
    return pd.Timestamp("2026-06-01")


@pytest.fixture
def lookup_all_tenors(delivery_date):
    """Lookup with CTD maturities covering the false-match scenario for
    every standard benchmark tenor.  In production these come from the
    live CTD basket; here we manufacture rows so the ±1 day merge hits."""
    rows = []
    for years, ticker in [
        (1, "TVA"), (2, "TVA"), (3, "FYA"), (4, "FYA"),
        (5, "FYA"), (7, "TYA"), (10, "TYA"), (15, "UTA"),
        (20, "UTA"), (25, "UBA"), (30, "UBA"),
    ]:
        mat = delivery_date + pd.DateOffset(years=years)
        rows.append({
            "invoice_swap_delivery_date": delivery_date,
            "invoice_swap_ctd_maturity": mat,
            "invoice_swap_ticker": ticker,
        })
    return pd.DataFrame(rows)


def _make_row(effective, expiration, tenor_years, forward_start_years=0.0):
    return {
        "trade_id": f"T_{tenor_years}",
        "execution_timestamp": pd.Timestamp("2026-05-28 14:00:00", tz="UTC"),
        "effective_date": effective,
        "expiration_date": expiration,
        "tenor_years": tenor_years,
        "forward_start_years": forward_start_years,
        "matched_ust_maturity": False,
        "matched_ust_maturity_trade_confidence": "low",
        "package_type": "OUTRIGHT",
        "trade_type": "OUTRIGHT",
    }


def _run_lookup(df, lookup):
    return _apply_invoice_swap_lookup(
        df,
        lookup,
        effective_col="effective_date",
        maturity_col="expiration_date",
        confidence_col="matched_ust_maturity_trade_confidence",
        require_high_confidence=True,
        output_col="invoice_swap_ticker",
    )


# ---- Spot-starting benchmark tenors: ALL should be suppressed ----

@pytest.mark.parametrize("years", [1, 2, 3, 5, 7, 10, 15, 20, 25, 30])
def test_spot_benchmark_tenor_suppressed(lookup_all_tenors, delivery_date, years):
    """A spot-starting swap with a clean benchmark tenor should NOT get
    an invoice ticker, even if the (eff, mat) pair happens to hit the
    lookup."""
    eff = delivery_date
    mat = eff + pd.DateOffset(years=years)
    row = _make_row(eff, mat, tenor_years=float(years), forward_start_years=0.0)
    df = pd.DataFrame([row])
    out = _run_lookup(df, lookup_all_tenors)
    assert pd.isna(out.loc[0, "invoice_swap_ticker"]), (
        f"Spot {years}Y should be suppressed but got ticker "
        f"{out.loc[0, 'invoice_swap_ticker']}"
    )


# ---- Real invoice swap tenors: should NOT be suppressed ----

@pytest.mark.parametrize("tenor_years,ticker", [
    (1.75, "TVA"),    # 2-Year Invoice (~1yr 9mo)
    (4.25, "FYA"),    # 5-Year Invoice (~4yr 3mo)
    (6.5, "TYA"),     # 10-Year Invoice (~6yr 6mo)
    (9.42, "TYA"),    # Ultra 10-Year Invoice (~9yr 5mo)
])
def test_real_invoice_tenor_not_suppressed(delivery_date, tenor_years, ticker):
    """A trade with a non-benchmark tenor matching the CME approximate
    IRS tenor should still get the invoice ticker."""
    eff = delivery_date
    mat = eff + pd.DateOffset(days=int(tenor_years * 365.25))
    lookup = pd.DataFrame([{
        "invoice_swap_delivery_date": delivery_date,
        "invoice_swap_ctd_maturity": mat,
        "invoice_swap_ticker": ticker,
    }])
    row = _make_row(eff, mat, tenor_years=tenor_years, forward_start_years=0.0)
    df = pd.DataFrame([row])
    out = _run_lookup(df, lookup)
    assert out.loc[0, "invoice_swap_ticker"] == ticker, (
        f"Real invoice with tenor {tenor_years}Y should get ticker {ticker}"
    )


# ---- Forward-starting trades: suppression should NOT apply ----

@pytest.mark.parametrize("years", [2, 5, 10])
def test_forward_starting_benchmark_not_suppressed(lookup_all_tenors, delivery_date, years):
    """A forward-starting trade should never be suppressed, even with a
    benchmark tenor — the forward start means the effective date is
    intentionally chosen (e.g., an IMM delivery date)."""
    eff = delivery_date
    mat = eff + pd.DateOffset(years=years)
    row = _make_row(eff, mat, tenor_years=float(years), forward_start_years=0.25)
    df = pd.DataFrame([row])
    out = _run_lookup(df, lookup_all_tenors)
    assert out.loc[0, "invoice_swap_ticker"] is not None and not pd.isna(
        out.loc[0, "invoice_swap_ticker"]
    ), f"Forward-starting {years}Y should NOT be suppressed"


# ---- Near-benchmark but not exact: should NOT be suppressed ----

@pytest.mark.parametrize("tenor_years", [4.9, 5.1, 9.8, 10.2])
def test_near_benchmark_not_exact_not_suppressed(delivery_date, tenor_years):
    """Tenors that are close to but not exactly a benchmark year should
    not be suppressed — the 0.05yr tolerance is tight enough to avoid
    this."""
    eff = delivery_date
    mat = eff + pd.DateOffset(days=int(tenor_years * 365.25))
    lookup = pd.DataFrame([{
        "invoice_swap_delivery_date": delivery_date,
        "invoice_swap_ctd_maturity": mat,
        "invoice_swap_ticker": "FYA",
    }])
    row = _make_row(eff, mat, tenor_years=tenor_years, forward_start_years=0.0)
    df = pd.DataFrame([row])
    out = _run_lookup(df, lookup)
    assert out.loc[0, "invoice_swap_ticker"] == "FYA", (
        f"Tenor {tenor_years}Y is not exactly benchmark — should get ticker"
    )


# ---- Edge: tenor_years / forward_start_years missing ----

def test_missing_tenor_years_column(lookup_all_tenors, delivery_date):
    """If tenor_years column is missing, suppression is skipped and the
    invoice ticker resolves normally (backward compat)."""
    eff = delivery_date
    mat = eff + pd.DateOffset(years=5)
    row = _make_row(eff, mat, tenor_years=5.0, forward_start_years=0.0)
    del row["tenor_years"]
    df = pd.DataFrame([row])
    out = _run_lookup(df, lookup_all_tenors)
    # Without tenor_years, suppression can't fire — ticker resolves.
    assert out.loc[0, "invoice_swap_ticker"] is not None


# ---- Mixed batch: only spot-benchmark rows suppressed ----

def test_mixed_batch_selective_suppression(lookup_all_tenors, delivery_date):
    """In a batch with spot benchmark, real invoice, and forward trades,
    only the spot benchmark row is suppressed."""
    rows = [
        _make_row(delivery_date, delivery_date + pd.DateOffset(years=5),
                  tenor_years=5.0, forward_start_years=0.0),
        _make_row(delivery_date,
                  delivery_date + pd.DateOffset(days=int(4.25 * 365.25)),
                  tenor_years=4.25, forward_start_years=0.0),
        _make_row(delivery_date, delivery_date + pd.DateOffset(years=5),
                  tenor_years=5.0, forward_start_years=0.25),
    ]
    rows[0]["trade_id"] = "spot_5Y"
    rows[1]["trade_id"] = "real_invoice"
    rows[2]["trade_id"] = "fwd_5Y"
    df = pd.DataFrame(rows)
    out = _run_lookup(df, lookup_all_tenors)
    assert pd.isna(out.loc[0, "invoice_swap_ticker"]), "spot 5Y should be suppressed"
    # Row 1 (real invoice 4.25Y) has its own lookup hit; construct one:
    lookup_with_425 = pd.concat([
        lookup_all_tenors,
        pd.DataFrame([{
            "invoice_swap_delivery_date": delivery_date,
            "invoice_swap_ctd_maturity": delivery_date + pd.DateOffset(days=int(4.25 * 365.25)),
            "invoice_swap_ticker": "FYA",
        }])
    ], ignore_index=True)
    out2 = _run_lookup(df, lookup_with_425)
    assert out2.loc[1, "invoice_swap_ticker"] == "FYA", "real invoice should not be suppressed"
    assert not pd.isna(out2.loc[2, "invoice_swap_ticker"]), "forward 5Y should not be suppressed"
