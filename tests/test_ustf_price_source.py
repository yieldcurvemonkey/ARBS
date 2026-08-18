"""A settlement price and a one-minute bar must not be mistaken for each other.

Repairing the BarChart EOD endpoint made ``interval=None`` -- the exchange's daily settlement --
reachable for the first time. It is *not* the same number as the one-minute bar nearest 14:00
Chicago that every stored UST futures price is today: measured over 59 sampled days across six
contracts and three eras, the two agree with median 0.0/32 but mean absolute 0.79/32 and a maximum
of 4.0/32 (October 2020). Against a net basis whose healthy range is +-11/32, that is small but not
nothing.

Neither the layered price cache key nor the snapshot partition recorded which convention it held,
so an EOD backfill would have been served in place of minute-derived prices, and vice versa, with
nothing to say so. These pin the separation -- and pin that the *default* key is unchanged, so the
existing warm cache is not thrown away.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.USTFutures.USTFuturesMDP import (
    _PRICE_SOURCE_EOD_SETTLE,
    _PRICE_SOURCE_LEGACY,
    USTFuturesMDP,
    _price_cache_suffix,
    _price_source_tag,
)


def test_price_source_tags():
    assert _price_source_tag(1) == _PRICE_SOURCE_LEGACY
    assert _price_source_tag(None) == _PRICE_SOURCE_EOD_SETTLE
    assert _price_source_tag(5) == "barchart_5m"


def test_default_interval_keeps_the_existing_cache_key():
    """The one-minute default must produce the *same* key as before the tag existed.

    Otherwise this change silently discards every warm price in the layered cache and forces a
    full refetch of history for no gain.
    """
    assert _price_cache_suffix(1) == ""
    assert _price_cache_suffix(None) == "-barchart_eod_settle"
    assert _price_cache_suffix(5) == "-barchart_5m"


class _StubStore:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def read_snapshot_day(self, symbol: str, trading_date: datetime.date) -> pd.DataFrame:
        return self._frame.copy()


def _mdp_with_snapshot(monkeypatch, frame: pd.DataFrame) -> USTFuturesMDP:
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    monkeypatch.setattr(USTFuturesMDP, "_get_ust_future_store", lambda self: _StubStore(frame))
    return mdp


_DAY = datetime.date(2026, 8, 13)
_TS = pd.Timestamp("2026-08-13T19:00:00Z")


def _row(price: float, source=None) -> dict:
    row = {
        "symbol": "USU26",
        "timestamp_utc": _TS,
        "trading_date": _DAY,
        "session_minute": 840,
        "price": price,
        "schema_version": 2,
    }
    if source is not None:
        row["price_source"] = source
    return row


def test_settle_and_minute_rows_in_one_partition_are_selected_not_ordered(monkeypatch):
    """Both conventions can land in the same partition, carrying the same timestamp.

    ``_read_partition`` concatenates every parquet in the directory, so taking the last row would
    make the answer depend on file ordering -- the same trap already documented for quarantined
    roots. The row must be *selected* by provenance.
    """
    frame = pd.DataFrame([_row(109.6875, _PRICE_SOURCE_LEGACY), _row(109.65625, _PRICE_SOURCE_EOD_SETTLE)])
    mdp = _mdp_with_snapshot(monkeypatch, frame)

    minute = mdp._read_core_snapshot_row(symbol="USU26", trading_date=_DAY, price_source=_PRICE_SOURCE_LEGACY)
    settle = mdp._read_core_snapshot_row(symbol="USU26", trading_date=_DAY, price_source=_PRICE_SOURCE_EOD_SETTLE)

    assert minute["price"] == pytest.approx(109.6875)
    assert settle["price"] == pytest.approx(109.65625)

    # ... and the reverse file order must give the same answer.
    reversed_frame = frame.iloc[::-1].reset_index(drop=True)
    mdp2 = _mdp_with_snapshot(monkeypatch, reversed_frame)
    assert mdp2._read_core_snapshot_row(symbol="USU26", trading_date=_DAY, price_source=_PRICE_SOURCE_LEGACY)["price"] == pytest.approx(109.6875)


def test_untagged_rows_are_minute_bars(monkeypatch):
    """Every price written before the tag existed is a one-minute bar. Legacy rows must still serve."""
    mdp = _mdp_with_snapshot(monkeypatch, pd.DataFrame([_row(109.6875)]))

    assert mdp._read_core_snapshot_row(symbol="USU26", trading_date=_DAY)["price"] == pytest.approx(109.6875)
    assert (
        mdp._read_core_snapshot_row(symbol="USU26", trading_date=_DAY, price_source=_PRICE_SOURCE_LEGACY)["price"]
        == pytest.approx(109.6875)
    )


def test_a_settle_request_does_not_get_served_an_untagged_minute_price(monkeypatch):
    """The failure this exists to stop: asking for settlement and silently getting a minute bar."""
    mdp = _mdp_with_snapshot(monkeypatch, pd.DataFrame([_row(109.6875)]))
    assert mdp._read_core_snapshot_row(symbol="USU26", trading_date=_DAY, price_source=_PRICE_SOURCE_EOD_SETTLE) is None
