"""De-conflation of execution-vs-event timestamps in the swaption and
cap/floor classifiers (2026-07-17 spec).

Historically both products stored the *Event* timestamp (#30) into
``execution_timestamp``. ``classify_trade`` now reads the true *Execution
Timestamp* (#96) where present and only falls back to the Event timestamp
(flagged via ``original_execution_source == "fallback"``) when it is absent.

These tests exercise ``classify_trade`` directly on each product handler.
``classify_trade`` is pure date/label math (no curves, pricers, or network —
those live in ``build_classification_dataframe``), so no external deps are
required.
"""

import pandas as pd

from SDRUtils.products.usd.usd_swaptions import USD_Swaptions
from SDRUtils.products.usd.usd_capfloors import USD_CapFloors

EXECUTION_TS = "2026-03-09T14:00:00Z"
EVENT_TS = "2026-03-09T15:30:00Z"


def _to_naive_utc(value: object) -> pd.Timestamp:
    """Normalize any tz-aware/naive timestamp to tz-naive UTC for robust ==."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _swaption_row(**overrides: object) -> pd.Series:
    row: dict[str, object] = {
        "Dissemination Identifier": "SW-001",
        "Execution Timestamp": EXECUTION_TS,
        "Event timestamp": EVENT_TS,
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Effective Date": "2026-03-09",
        "Expiration Date": "2026-06-09",
        "Maturity date of the underlier": "2027-06-11",
        "UPI FISN": "NA/O Call Epn Fxd Flt USD",
        "UPI Underlier Name": "USD-SOFR-OIS Compound",
        "Notional amount-Leg 1": "100000000",
        "Notional currency-Leg 1": "USD",
        "Strike Price": 3.5,
        "Option Premium Amount": "125000",
        "description": "USD 3Mx1Y",
    }
    row.update(overrides)
    return pd.Series(row)


def _capfloor_row(**overrides: object) -> pd.Series:
    row: dict[str, object] = {
        "Dissemination Identifier": "CF-001",
        "Execution Timestamp": EXECUTION_TS,
        "Event timestamp": EVENT_TS,
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Effective Date": "2026-03-01",
        "Expiration Date": "2027-03-01",
        "UPI FISN": "NA/O Call Epn USD",
        "UPI Underlier Name": "USD-SOFR-CME TERM",
        "Notional amount-Leg 1": "78000000",
        "Notional currency-Leg 1": "USD",
        "Strike Price": 4.5,
        "Strike price notation": 3.0,
        "Option Premium Amount": 3700.0,
        "Floating rate reset frequency period multiplier-leg 1": 1,
        "Floating rate reset frequency period-leg 1": "MNTH",
        "Package indicator": False,
        "Unique Product Identifier": "QZQJWDQ4V0VJ",
    }
    row.update(overrides)
    return pd.Series(row)


# --------------------------------------------------------------------------
# Swaptions
# --------------------------------------------------------------------------
def test_swaption_execution_and_event_deconflated_when_both_present():
    product = USD_Swaptions()
    c = product.classify_trade(_swaption_row(), trade_id="SW-001")

    assert _to_naive_utc(c.execution_timestamp) == _to_naive_utc(EXECUTION_TS)
    assert _to_naive_utc(c.event_timestamp) == _to_naive_utc(EVENT_TS)
    # The whole point of the de-conflation: the two timestamps must differ.
    assert _to_naive_utc(c.execution_timestamp) != _to_naive_utc(c.event_timestamp)
    assert c.original_execution_source is None


def test_swaption_falls_back_to_event_when_execution_missing():
    # Drop the Execution Timestamp key entirely -> row.get returns None ->
    # pd.to_datetime(None) is NaT -> fallback path.
    row = _swaption_row()
    row = row.drop(labels=["Execution Timestamp"])
    product = USD_Swaptions()
    c = product.classify_trade(row, trade_id="SW-001")

    assert _to_naive_utc(c.execution_timestamp) == _to_naive_utc(EVENT_TS)
    assert _to_naive_utc(c.event_timestamp) == _to_naive_utc(EVENT_TS)
    assert _to_naive_utc(c.execution_timestamp) == _to_naive_utc(c.event_timestamp)
    assert c.original_execution_source == "fallback"


# --------------------------------------------------------------------------
# Cap/Floors
# --------------------------------------------------------------------------
def test_capfloor_execution_and_event_deconflated_when_both_present():
    product = USD_CapFloors()
    c = product.classify_trade(_capfloor_row(), trade_id="CF-001")

    assert _to_naive_utc(c.execution_timestamp) == _to_naive_utc(EXECUTION_TS)
    assert _to_naive_utc(c.event_timestamp) == _to_naive_utc(EVENT_TS)
    assert _to_naive_utc(c.execution_timestamp) != _to_naive_utc(c.event_timestamp)
    assert c.original_execution_source is None


def test_capfloor_falls_back_to_event_when_execution_missing():
    row = _capfloor_row()
    row = row.drop(labels=["Execution Timestamp"])
    product = USD_CapFloors()
    c = product.classify_trade(row, trade_id="CF-001")

    assert _to_naive_utc(c.execution_timestamp) == _to_naive_utc(EVENT_TS)
    assert _to_naive_utc(c.event_timestamp) == _to_naive_utc(EVENT_TS)
    assert _to_naive_utc(c.execution_timestamp) == _to_naive_utc(c.event_timestamp)
    assert c.original_execution_source == "fallback"
