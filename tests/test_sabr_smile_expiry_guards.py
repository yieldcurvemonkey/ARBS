"""Guards around expired / stale SOFR option chains in the SABR smile fetcher.

Regression cover for the failure mode where ``fetch_sabr_smile`` was asked for an
``as_of`` after the option chain had terminated trading.  The underlying future keeps
trading for another quarter, so the forward resolved fine and the request only blew up
deep inside leg selection with an unactionable 34-symbol "Missing SABR smile strike
legs" dump that never mentioned expiry.

Empirically verified termination rule (Barchart last-quote date vs. rule):

    SFRZ25  3rd Wed 2025-12-17   rule 2025-12-12   last quote 2025-12-12
    SFRH26  3rd Wed 2026-03-18   rule 2026-03-13   last quote 2026-03-13
    SFRJ26  3rd Wed 2026-04-15   rule 2026-04-10   last quote 2026-04-10
    SFRM26  3rd Wed 2026-06-17   rule 2026-06-12   last quote 2026-06-12
    SFRN26  3rd Wed 2026-07-15   rule 2026-07-10   last quote 2026-07-10
"""

import datetime

import pytest

from MDP.STIRFutures import _sofr_option_contracts as soc
from MDP.STIRFutures.STIRFutureOptionMDP import _NY_TZ, STIRFutureOptionMDP


def _ts(day: datetime.date) -> datetime.datetime:
    return _NY_TZ.localize(datetime.datetime.combine(day, datetime.time(17, 0)))


class _StubPricer:
    def __init__(self, day: datetime.date):
        self._ts = _ts(day)

    def quote_timestamp(self) -> datetime.datetime:
        return self._ts


@pytest.fixture(scope="module")
def mdp() -> STIRFutureOptionMDP:
    return STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")


def _spec(symbol: str, *, offset_bps: float | None = 0.0) -> dict:
    strike4 = symbol.split("|", 1)[1][:-1]
    return {
        "right": symbol[-1],
        "label": symbol,
        "canonical_symbol": symbol,
        "requested_atm_offset_bps": offset_bps,
        "strike_price": float(int(strike4)) / 100.0,
    }


# --------------------------------------------------------------------------------------
# termination-date rule
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contract,expected",
    [
        ("SFRZ25", datetime.date(2025, 12, 12)),
        ("SFRH26", datetime.date(2026, 3, 13)),
        ("SFRJ26", datetime.date(2026, 4, 10)),
        ("SFRM26", datetime.date(2026, 6, 12)),
        ("SFRN26", datetime.date(2026, 7, 10)),
        ("SFRU26", datetime.date(2026, 9, 11)),
        ("0QZ26", datetime.date(2026, 12, 11)),
    ],
)
def test_sofr_option_last_trade_date(contract, expected):
    assert soc.sofr_option_last_trade_date(contract) == expected


@pytest.mark.parametrize(
    "contract,expected,why",
    [
        # 460A01.J.1 holiday roll-back. These are the only three cases in 2018-2040 where
        # the SIFMA/government-bond calendar and the NYSE calendar disagree on a
        # Friday-preceding-the-third-Wednesday, so they pin the calendar choice.
        ("SFRJ22", datetime.date(2022, 4, 14), "Good Friday 2022-04-15 -> roll back"),
        ("SFRX22", datetime.date(2022, 11, 10), "Veterans Day 2022-11-11 -> roll back"),
        ("SFRX23", datetime.date(2023, 11, 10), "Veterans Day observed Fri -> no roll"),
    ],
)
def test_sofr_option_last_trade_date_holiday_rollback(contract, expected, why):
    """Barchart last-quote dates confirm each of these: SQJ22 2022-04-14,
    SQX22 2022-11-10, SQX23 2023-11-10."""
    assert soc.sofr_option_last_trade_date(contract) == expected, why


def test_sofr_option_last_trade_date_unknown_for_weekly_roots():
    # Weeklies expire on a specified Friday of the month, not the pre-IMM Friday.
    assert soc.sofr_option_last_trade_date("S01Z26") is None


def test_sofr_option_last_trade_date_unknown_for_non_sofr():
    assert soc.sofr_option_last_trade_date("FFZ26") is None


# --------------------------------------------------------------------------------------
# expired-chain guard
# --------------------------------------------------------------------------------------


def test_expired_chain_raises_actionable_error(mdp):
    with pytest.raises(ValueError) as exc:
        mdp._assert_sabr_smile_chain_tradable(contract="SFRM26", as_of=datetime.date(2026, 7, 24))
    msg = str(exc.value)
    assert "SFRM26" in msg
    assert "2026-06-12" in msg  # termination date
    assert "2026-07-24" in msg  # what was requested
    # must point at a chain that is actually still listed on the requested date
    assert "SFRU26" in msg or "SFRQ26" in msg


def test_live_chain_passes_guard(mdp):
    mdp._assert_sabr_smile_chain_tradable(contract="SFRU26", as_of=datetime.date(2026, 7, 24))
    # last trading day itself is still tradable
    mdp._assert_sabr_smile_chain_tradable(contract="SFRM26", as_of=datetime.date(2026, 6, 12))


def test_guard_is_silent_when_rule_is_unknown(mdp):
    mdp._assert_sabr_smile_chain_tradable(contract="S01Z26", as_of=datetime.date(2030, 1, 1))


# --------------------------------------------------------------------------------------
# per-leg as-of resolution must not mix quote days or silently go stale
# --------------------------------------------------------------------------------------


def test_asof_pricer_respects_staleness_bound(mdp):
    by_day = {datetime.date(2026, 6, 11): _StubPricer(datetime.date(2026, 6, 11))}
    target = datetime.date(2026, 6, 16)
    assert mdp._asof_pricer_for_date(by_day, target) is not None
    assert mdp._asof_pricer_for_date(by_day, target, max_staleness_days=3) is None
    assert mdp._asof_pricer_for_date(by_day, target, max_staleness_days=5) is not None


def test_explicit_legs_do_not_mix_quote_days(mdp):
    """as_of 2026-06-16 used to build a smile from 9631C@06-12 + everything else @06-11."""
    fresh, stale = datetime.date(2026, 6, 12), datetime.date(2026, 6, 11)
    window = {
        "SFRM26|9631C": {stale: _StubPricer(stale), fresh: _StubPricer(fresh)},
        "SFRM26|9637C": {stale: _StubPricer(stale)},
        "SFRM26|9625P": {stale: _StubPricer(stale)},
    }
    legs = mdp._select_sabr_smile_explicit_legs_from_pricer_window(
        requested_legs=[_spec(s) for s in window],
        pricers_window=window,
        target_date=datetime.date(2026, 6, 16),
    )
    days = {leg["pricer"].quote_timestamp().astimezone(_NY_TZ).date() for leg in legs}
    assert len(days) == 1, f"smile mixes quote days: {sorted(days)}"
    assert days == {fresh}


def test_available_legs_do_not_mix_quote_days(mdp):
    fresh, stale = datetime.date(2026, 6, 12), datetime.date(2026, 6, 11)
    window = {
        "SFRM26|9631C": {fresh: _StubPricer(fresh)},
        "SFRM26|9637C": {stale: _StubPricer(stale)},
    }
    legs = mdp._select_sabr_smile_available_legs_from_pricer_window(
        requested_legs=[_spec(s) for s in window],
        pricers_window=window,
        target_date=datetime.date(2026, 6, 12),
    )
    days = {leg["pricer"].quote_timestamp().astimezone(_NY_TZ).date() for leg in legs}
    assert days == {fresh}


def test_explicit_legs_error_names_last_available_quote_date(mdp):
    stale = datetime.date(2026, 6, 11)
    window = {"SFRM26|9625C": {stale: _StubPricer(stale)}}
    with pytest.raises(ValueError) as exc:
        mdp._select_sabr_smile_explicit_legs_from_pricer_window(
            requested_legs=[_spec("SFRM26|9625C")],
            pricers_window=window,
            target_date=datetime.date(2026, 7, 24),
        )
    msg = str(exc.value)
    assert "2026-06-11" in msg, msg
    assert "2026-07-24" in msg, msg


def test_explicit_legs_error_when_window_is_empty(mdp):
    with pytest.raises(ValueError) as exc:
        mdp._select_sabr_smile_explicit_legs_from_pricer_window(
            requested_legs=[_spec("SFRM26|9625C"), _spec("SFRM26|9625P")],
            pricers_window={},
            target_date=datetime.date(2026, 7, 24),
        )
    assert "no quotes" in str(exc.value).lower()


def test_offset_mode_tolerance_is_not_loop_order_dependent(mdp):
    """The 'missing legs are tolerable in offset mode' flag must be derived from the
    request, not from whichever leg happened to resolve last."""
    day = datetime.date(2026, 6, 11)
    window = {"SFRM26|9625C": {day: _StubPricer(day)}}
    requested = [
        _spec("SFRM26|9625C", offset_bps=0.0),
        _spec("SFRM26|9875C", offset_bps=250.0),  # unresolvable wing, offset-specified
    ]
    legs = mdp._select_sabr_smile_explicit_legs_from_pricer_window(
        requested_legs=requested, pricers_window=window, target_date=day
    )
    assert [leg["canonical_symbol"] for leg in legs] == ["SFRM26|9625C"]

    # explicitly-named strikes (no offset) must still be strict about a missing leg
    with pytest.raises(ValueError):
        mdp._select_sabr_smile_explicit_legs_from_pricer_window(
            requested_legs=[
                _spec("SFRM26|9625C", offset_bps=None),
                _spec("SFRM26|9875C", offset_bps=None),
            ],
            pricers_window=window,
            target_date=day,
        )


# --------------------------------------------------------------------------------------
# empty pricer windows must not poison the cache
# --------------------------------------------------------------------------------------


def test_empty_pricer_window_is_not_cached(mdp, monkeypatch):
    legs = ["SFRM26|9625C", "SFRM26|9625P"]
    start = end = datetime.date(2026, 7, 24)
    w_start, w_end = mdp._historical_prefetch_window(start=start, end=end)
    cache_key = mdp._build_barchart_pricer_window_cache_key(
        leg_symbols=legs,
        window_start=w_start,
        window_end=w_end,
        price_mode="mid_then_fallback",
        curve_name=mdp._curve_name_default,
        curve_kwargs={},
        use_ql_calculator=True,
    )
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", lambda **kwargs: {})
    puts: list = []
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, val: puts.append((key, val)))

    out = mdp._get_or_build_barchart_pricer_window(
        leg_symbols=legs,
        cache_symbols=legs,
        request_start=start,
        request_end=end,
        show_tqdm=False,
        price_mode="mid_then_fallback",
        curve_name=mdp._curve_name_default,
        curve_kwargs={},
        use_ql_calculator=True,
        source="BARCHART_EOD_WINDOW",
    )
    assert out == {}
    assert not [p for p in puts if p[0] == cache_key], (
        "an empty pricer window was persisted; a transient Barchart outage would be "
        "cached as 'no data' and never retried"
    )
