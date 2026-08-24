"""The CHBASIS query and its timeseries router.

The basis had an MDP but no query and no router, so every consumer reached past
the query layer. These tests pin the seam that closes it: the sign convention,
the units, one fetch per instrument rather than per date, and the refusal to
forward-fill a date the cache does not carry.

Everything here runs offline against a stub MDP except the last two, which are
skipped when the CCP-basis disk cache is absent.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from Query.IRClearingHouseBasis.IRClearingHouseBasisQuery import (
    PRODUCT,
    IRClearingHouseBasisQuery,
    IRClearingHouseBasisValue,
    value_column,
    value_units,
)
from TB.IRClearingHouseBasisTB import IRClearingHouseBasisTB


# ---------------------------------------------------------------------------
# A stub MDP: deterministic, offline, and it COUNTS its calls.
# ---------------------------------------------------------------------------
class _StubPricer:
    def __init__(self, df, meta):
        self.basis_data = df
        self.meta_data = meta


class _StubMDP:
    """Serves a canned panel and records every request it is handed."""

    def __init__(self, index=None, gap: bool = False, raises: bool = False):
        self.requests = []
        self.raises = raises
        idx = index if index is not None else pd.bdate_range("2026-08-03", periods=10)
        if gap:                       # drop one date to test the no-ffill rule
            idx = idx.delete(4)
        self._idx = pd.DatetimeIndex(idx)

    def get_pricer(self, request):
        self.requests.append(dict(request))
        if self.raises:
            raise RuntimeError("cold cache window")
        n = len(self._idx)
        rate_a = pd.Series(np.linspace(0.0428, 0.0432, n), index=self._idx)
        rate_b = rate_a + 0.0002                     # CME 2bp ABOVE LCH
        df = pd.DataFrame({"rate_a": rate_a, "rate_b": rate_b,
                           "basis_bps": (rate_a - rate_b) * 1e4})
        df.index.name = "date"
        return _StubPricer(df, {"sign_convention": "LCH minus CME",
                                "units": "bp", "rate_units": "decimal"})


def _tb(**kw):
    return IRClearingHouseBasisTB(_StubMDP(**kw), show_tqdm=False)


# ---------------------------------------------------------------------------
# 1. The query
# ---------------------------------------------------------------------------
def test_product_is_the_router_key():
    assert IRClearingHouseBasisQuery().product == PRODUCT == "CHBASIS"


def test_defaults_are_usd_sofr_lch_minus_cme():
    q = IRClearingHouseBasisQuery()
    assert (q.ccy, q.index, q.clearing_house_a, q.clearing_house_b) == \
        ("USD", "SOFR", "LCH", "CME")
    assert q.value is IRClearingHouseBasisValue.BASIS_BPS
    assert q.allow_network is False, "network must be opt-in, never a default"


def test_window_request_carries_everything_the_mdp_needs():
    q = IRClearingHouseBasisQuery(tenor="5y")
    r = q.window_request(datetime.date(2026, 1, 2), datetime.date(2026, 8, 21))
    assert r == {"tenor": "5y", "ccy": "USD", "index": "SOFR",
                 "clearing_house_a": "LCH", "clearing_house_b": "CME",
                 "start": datetime.date(2026, 1, 2),
                 "end": datetime.date(2026, 8, 21), "allow_network": False}


def test_build_mdp_request_is_a_single_day_window():
    q = IRClearingHouseBasisQuery()
    r = q.build_mdp_request(datetime.datetime(2026, 8, 10, 17, 0))
    assert r["start"] == r["end"] == datetime.date(2026, 8, 10)


def test_column_name_states_pair_tenor_and_value():
    assert IRClearingHouseBasisQuery(tenor="10y").col_name() == \
        "USD-SOFR 10Y LCH-CME BASIS_BPS"
    assert IRClearingHouseBasisQuery(tenor="5y",
                                     value=IRClearingHouseBasisValue.RATE_A
                                     ).col_name() == "USD-SOFR 5Y LCH-CME RATE_A"
    assert IRClearingHouseBasisQuery(name="my basis").col_name() == "my basis"


def test_units_are_named_because_bp_and_decimal_both_appear():
    assert value_units(IRClearingHouseBasisValue.BASIS_BPS) == "bp"
    assert value_units(IRClearingHouseBasisValue.RATE_A) == "decimal"
    assert value_units(IRClearingHouseBasisValue.RATE_B) == "decimal"
    assert value_column(IRClearingHouseBasisValue.BASIS_BPS) == "basis_bps"


def test_instrument_key_ignores_the_value_but_not_the_pair():
    a = IRClearingHouseBasisQuery(tenor="10y")
    b = IRClearingHouseBasisQuery(tenor="10y",
                                  value=IRClearingHouseBasisValue.RATE_A)
    c = IRClearingHouseBasisQuery(tenor="10y", clearing_house_b="EUREX")
    d = IRClearingHouseBasisQuery(tenor="5y")
    assert a.instrument_key() == b.instrument_key()
    assert a.instrument_key() != c.instrument_key()
    assert a.instrument_key() != d.instrument_key()


# ---------------------------------------------------------------------------
# 2. The router
# ---------------------------------------------------------------------------
def test_router_returns_a_dated_frame_with_the_query_column():
    tb = _tb()
    df = tb.get_timeseries(datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
                           [IRClearingHouseBasisQuery(tenor="10y")])
    assert not df.empty
    assert list(df.columns) == ["USD-SOFR 10Y LCH-CME BASIS_BPS"]
    assert df.index.name == "Date"


def test_sign_convention_is_house_a_minus_house_b():
    """The stub puts CME 2bp ABOVE LCH, so LCH-minus-CME must be -2bp."""
    tb = _tb()
    df = tb.get_timeseries(datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
                           [IRClearingHouseBasisQuery(tenor="10y")])
    assert np.allclose(df.iloc[:, 0].to_numpy(), -2.0)


def test_leg_rates_come_back_in_decimal_not_bp():
    tb = _tb()
    df = tb.get_timeseries(
        datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
        [IRClearingHouseBasisQuery(tenor="10y",
                                   value=IRClearingHouseBasisValue.RATE_A)])
    v = float(df.iloc[0, 0])
    assert 0.001 < v < 0.5, f"{v} is not a decimal rate"


def test_one_mdp_call_per_instrument_not_per_date():
    """The MDP returns a whole panel; a per-date loop would re-read the same
    cache once per business day."""
    mdp = _StubMDP()
    tb = IRClearingHouseBasisTB(mdp, show_tqdm=False)
    qs = [IRClearingHouseBasisQuery(tenor="5y"),
          IRClearingHouseBasisQuery(tenor="10y"),
          # same instrument, different value -> must NOT add a fetch
          IRClearingHouseBasisQuery(tenor="10y",
                                    value=IRClearingHouseBasisValue.RATE_A)]
    df = tb.get_timeseries(datetime.date(2026, 8, 3),
                           datetime.date(2026, 8, 14), qs)
    assert len(df) >= 8
    assert len(mdp.requests) == 2, mdp.requests
    assert {r["tenor"] for r in mdp.requests} == {"5y", "10y"}


def test_the_window_request_spans_the_whole_range():
    mdp = _StubMDP()
    tb = IRClearingHouseBasisTB(mdp, show_tqdm=False)
    tb.get_timeseries(datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
                      [IRClearingHouseBasisQuery()])
    r = mdp.requests[0]
    assert r["start"] == datetime.date(2026, 8, 3)
    assert r["end"] == datetime.date(2026, 8, 14)


def test_a_missing_date_is_missing_and_is_NOT_forward_filled():
    """A stale basis that looks like a fresh one is the failure mode this
    router exists to avoid."""
    plain = _tb()
    gapped = _tb(gap=True)
    win = (datetime.date(2026, 8, 3), datetime.date(2026, 8, 14))
    q = [IRClearingHouseBasisQuery(tenor="10y")]
    a = plain.get_timeseries(*win, q)
    b = gapped.get_timeseries(*win, q)
    assert len(b) == len(a) - 1, "the gapped date must not be filled in"


def test_a_cold_window_is_recorded_rather_than_silently_empty():
    tb = IRClearingHouseBasisTB(_StubMDP(raises=True), show_tqdm=False)
    df = tb.get_timeseries(datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
                           [IRClearingHouseBasisQuery(tenor="10y")])
    assert df.empty
    assert len(tb.failures) == 1
    assert "cold cache window" in list(tb.failures.values())[0]


def test_multiple_tenors_come_back_as_multiple_columns():
    tb = _tb()
    df = tb.get_timeseries(
        datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
        [IRClearingHouseBasisQuery(tenor=t) for t in ("2y", "5y", "10y", "30y")])
    assert df.shape[1] == 4
    assert all("LCH-CME" in c for c in df.columns)


def test_router_ignores_a_foreign_query_rather_than_mispricing_it():
    class _Other:
        product = "IRS"

    tb = _tb()
    out = tb._price_one(_Other(), ref_point=pd.Timestamp("2026-08-05"),
                        now=datetime.datetime(2026, 8, 5), bulk_data={},
                        n_jobs=1, ignore_cache=False)
    assert out is None


# ---------------------------------------------------------------------------
# 3. Against the real cache, and against the MDP's own pinned reference
# ---------------------------------------------------------------------------
def _real_mdp():
    from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import (
        IRClearingHouseBasisSwapsMDP)
    return IRClearingHouseBasisSwapsMDP()


def _cache_has(start, end, tenor="10y") -> bool:
    try:
        from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import basis_panel
        p = basis_panel(start, end, tenors=[tenor], allow_network=False)
        return not p.empty
    except Exception:                                           # noqa: BLE001
        return False


@pytest.mark.skipif(not _cache_has(datetime.date(2026, 8, 3),
                                   datetime.date(2026, 8, 14)),
                    reason="CCP basis cache not warm for the reference window")
def test_router_reproduces_the_mdps_pinned_reference():
    """The MDP docstring pins USD SOFR 10y on 2026-08-10 at -2.00 bp
    (LCH 0.04288489, CME 0.04308489)."""
    tb = IRClearingHouseBasisTB(_real_mdp(), show_tqdm=False)
    df = tb.get_timeseries(
        datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
        [IRClearingHouseBasisQuery(tenor="10y"),
         IRClearingHouseBasisQuery(tenor="10y",
                                   value=IRClearingHouseBasisValue.RATE_A),
         IRClearingHouseBasisQuery(tenor="10y",
                                   value=IRClearingHouseBasisValue.RATE_B)])
    # The TB layer indexes by datetime.date, not Timestamp -- the same
    # convention IRSwapsTB uses. Pinned here so it cannot drift silently.
    assert all(isinstance(i, datetime.date) and not isinstance(i, datetime.datetime)
               for i in df.index)
    d = datetime.date(2026, 8, 10)
    assert d in list(df.index)
    assert df.loc[d, "USD-SOFR 10Y LCH-CME BASIS_BPS"] == pytest.approx(-2.00, abs=0.01)
    assert df.loc[d, "USD-SOFR 10Y LCH-CME RATE_A"] == pytest.approx(0.04288489, abs=1e-7)
    assert df.loc[d, "USD-SOFR 10Y LCH-CME RATE_B"] == pytest.approx(0.04308489, abs=1e-7)


@pytest.mark.skipif(not _cache_has(datetime.date(2026, 8, 3),
                                   datetime.date(2026, 8, 14)),
                    reason="CCP basis cache not warm for the reference window")
def test_basis_equals_the_two_legs_it_is_built_from():
    tb = IRClearingHouseBasisTB(_real_mdp(), show_tqdm=False)
    df = tb.get_timeseries(
        datetime.date(2026, 8, 3), datetime.date(2026, 8, 14),
        [IRClearingHouseBasisQuery(tenor="10y", value=v)
         for v in IRClearingHouseBasisValue]).dropna()
    lhs = df["USD-SOFR 10Y LCH-CME BASIS_BPS"]
    rhs = (df["USD-SOFR 10Y LCH-CME RATE_A"]
           - df["USD-SOFR 10Y LCH-CME RATE_B"]) * 1e4
    assert len(df) > 3
    assert np.allclose(lhs.to_numpy(), rhs.to_numpy(), atol=1e-8)
