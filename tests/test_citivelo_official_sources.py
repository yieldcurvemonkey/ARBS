"""Publisher-direct overnight fixings for the currencies Citi does not carry.

The parsing is what these tests guard, because every one of these endpoints has
a way of returning something plausible that is not the rate:

* Norges Bank's ``SHORT_RATES`` serves NOWA under two UNIT_MEASURE codes. ``R``
  is the rate; ``T`` is the daily transaction COUNT - small integers like 9, 15,
  13, which pass every sanity check a rate would and are off by two orders of
  magnitude.
* The Bank of Israel's public endpoint returns the POLICY rate where a caller
  reaching for SHIR would expect the fixing.
* SARB's undated endpoint silently truncates to the last ~25 observations.

Network tests are marked and excluded from the fast gate; the parsing tests run
against recorded payloads and always run.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.IRSwaps.CITIVELO_EXCEL import official_sources as OS

START = datetime.date(2026, 8, 1)
END = datetime.date(2026, 8, 7)


class _Response:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


# -- NY Fed EFFR --------------------------------------------------------


_EFFR_PAYLOAD = {
    "refRates": [
        {"effectiveDate": "2026-08-06", "type": "EFFR", "percentRate": 3.63},
        {"effectiveDate": "2026-08-05", "type": "EFFR", "percentRate": 3.62},
        # The endpoint carries other rate types in the same envelope.
        {"effectiveDate": "2026-08-06", "type": "OBFR", "percentRate": 3.61},
    ]
}


def test_effr_parses_percent_ascending_and_ignores_other_rate_types(monkeypatch):
    monkeypatch.setattr(OS, "_get", lambda url, **kw: _Response(payload=_EFFR_PAYLOAD))
    series = OS.effr_nyfed(START, END)
    assert list(series.index.date) == [datetime.date(2026, 8, 5), datetime.date(2026, 8, 6)]
    assert series.iloc[-1] == pytest.approx(3.63)
    assert series.index.is_monotonic_increasing


def test_effr_returns_percent_not_decimal(monkeypatch):
    """A decimal here would price every Fed Funds swap 100x too low."""
    monkeypatch.setattr(OS, "_get", lambda url, **kw: _Response(payload=_EFFR_PAYLOAD))
    assert OS.effr_nyfed(START, END).max() > 1.0


# -- Norges Bank NOWA ---------------------------------------------------


_NOWA_RATE_CSV = (
    "FREQ;Frequency;INSTRUMENT_TYPE;Instrument Type;TENOR;Tenor;UNIT_MEASURE;"
    "Unit of Measure;COLLECTION;DECIMALS;TIME_PERIOD;OBS_VALUE;CALC_METHOD;Calculation Method\n"
    "B;Business;NOWA;NOWA;ON;Overnight;R;Rate;;2;2026-08-05;4.25;N;Normal\n"
    "B;Business;NOWA;NOWA;ON;Overnight;R;Rate;;2;2026-08-06;4.26;N;Normal\n"
)


def test_nowa_parses_the_rate_series(monkeypatch):
    monkeypatch.setattr(OS, "_get", lambda url, **kw: _Response(text=_NOWA_RATE_CSV))
    series = OS.nowa_norges_bank(START, END)
    assert len(series) == 2
    assert series.iloc[-1] == pytest.approx(4.26)


def test_nowa_asks_for_the_rate_not_the_transaction_count(monkeypatch):
    """``B.NOWA.ON.T`` returns a plausible small integer that is NOT a rate."""
    seen = {}

    def _capture(url, **kw):
        seen["url"] = url
        return _Response(text=_NOWA_RATE_CSV)

    monkeypatch.setattr(OS, "_get", _capture)
    OS.nowa_norges_bank(START, END)
    assert "SHORT_RATES/B.NOWA.ON.R" in seen["url"]
    # The IR dataflow carries only the key policy rate - NOWA is not in it.
    assert "/data/IR" not in seen["url"]


# -- SARB ZARONIA -------------------------------------------------------


_ZARONIA_PAYLOAD = [
    {"Period": "2026-08-06T00:00:00", "Value": 6.8500},
    {"Period": "2026-08-05T00:00:00", "Value": 6.8400},
]


def test_zaronia_parses_and_sorts_ascending(monkeypatch):
    monkeypatch.setattr(OS, "_get", lambda url, **kw: _Response(payload=_ZARONIA_PAYLOAD))
    series = OS.zaronia_sarb(START, END)
    assert series.index.is_monotonic_increasing
    assert series.iloc[-1] == pytest.approx(6.85)


def test_zaronia_uses_the_dated_endpoint(monkeypatch):
    """The undated form truncates to ~25 observations without saying so."""
    seen = {}

    def _capture(url, **kw):
        seen["url"] = url
        return _Response(payload=_ZARONIA_PAYLOAD)

    monkeypatch.setattr(OS, "_get", _capture)
    OS.zaronia_sarb(datetime.date(2024, 1, 1), END)
    assert seen["url"].endswith("MMRD855A/2024-01-01/2026-08-07")


# -- Banxico, which needs a token --------------------------------------


def test_mxn_without_a_token_says_so_instead_of_returning_empty(monkeypatch):
    monkeypatch.delenv("BANXICO_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="BANXICO_TOKEN"):
        OS.fondeo_banxico(START, END)


# -- the dispatch map ---------------------------------------------------


def test_a_currency_with_no_source_raises_with_the_measured_reason():
    fetcher = OS.OfficialFixingsFetcher()
    assert not fetcher.available_for("THB_THOR")
    with pytest.raises(KeyError, match="client key"):
        fetcher.fetch("THB_THOR", START, END)


def test_every_unavailable_currency_records_why():
    for index, reason in OS.UNAVAILABLE.items():
        assert len(reason) > 40, f"{index} needs a real reason, not a shrug"
        assert index not in OS.OFFICIAL_SOURCES or index == "MXN_T_FONDEO"


def test_status_covers_every_currency_this_module_knows_about():
    rows = OS.official_source_status()
    names = {r.citi_index for r in rows}
    assert set(OS.OFFICIAL_SOURCES) <= names
    assert set(OS.UNAVAILABLE) <= names


def test_results_are_cached_so_a_backfill_does_not_refetch_per_day(monkeypatch):
    calls = []
    monkeypatch.setattr(
        OS, "_get", lambda url, **kw: (calls.append(url), _Response(payload=_EFFR_PAYLOAD))[1]
    )
    fetcher = OS.OfficialFixingsFetcher()
    fetcher.fetch("USD_FEDFUND", START, END)
    fetcher.fetch("USD_FEDFUND", START, END)
    assert len(calls) == 1


# -- live ---------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize(
    "index, low, high",
    [("USD_FEDFUND", 0.0, 12.0), ("NOK_NOWA", 0.0, 12.0), ("ZAR_ZARONIA", 0.0, 20.0)],
)
def test_live_each_working_source_returns_a_plausible_percent_rate(index, low, high):
    fetcher = OS.OfficialFixingsFetcher()
    end = datetime.date.today()
    series = fetcher.fetch(index, end - datetime.timedelta(days=60), end)
    assert not series.empty, f"{index} served nothing"
    assert series.index.is_monotonic_increasing
    # A decimal-vs-percent slip is the failure mode a range check actually catches.
    assert low < float(series.iloc[-1]) < high
    assert (end - series.index[-1].date()).days <= 10, "the tail is stale"
