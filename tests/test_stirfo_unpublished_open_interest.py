"""The vendor's newest bar carries no open interest, and a fabricated zero must not
silently demote an observed-premium density to a SABR model one.

Barchart's ``queryeod`` feed reports ``Open Interest = 0`` on the last bar of every frame
-- for a deep OTM strike and for a 1.7-million-lot front future alike -- because the
exchange disseminates a session's open interest the following morning. Read literally,
that zero makes the default ``raw_market_open_interest_min=100.0`` screen reject an entire
75-strike chain, and the ``min_strikes`` fallback then returns a SABR density. A SABR
density is unimodal by construction, so the substitution does not merely lose precision:
it manufactures the answer to a bimodality question.
"""
import datetime

import numpy as np
import pandas as pd
import pytest

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionSABRParams,
    STIRFutureOptionSABRSmile,
    STIRFutureOptionSmilePoint,
)
from RVUtils.ImpliedDistribution._data_prep import smile_to_rnd_input


# --------------------------------------------------------------------------------------
# BarchartFetcher.blank_unpublished_open_interest
# --------------------------------------------------------------------------------------

def _frame(open_interest, column="Open Interest"):
    n = len(open_interest)
    idx = pd.date_range("2026-08-03", periods=n, freq="B", name="Date")
    return pd.DataFrame(
        {
            "Open": np.linspace(96.0, 96.1, n),
            "High": np.linspace(96.0, 96.1, n),
            "Low": np.linspace(96.0, 96.1, n),
            "Close": np.linspace(96.0, 96.1, n),
            "Volume": np.arange(n, dtype=float),
            column: open_interest,
        },
        index=idx,
    )


def test_unpublished_last_bar_becomes_nan_not_zero():
    out = BarchartFetcher.blank_unpublished_open_interest(_frame([6362, 6362, 6362, 0]))
    values = out["Open Interest"].tolist()
    assert values[:3] == [6362.0, 6362.0, 6362.0]
    assert np.isnan(values[-1]), "an unpublished last bar must read as unknown, not zero"


def test_genuinely_empty_strike_is_left_alone():
    """A strike nobody holds reports zero on every bar. Blanking that would invent
    liquidity where the vendor is telling the truth."""
    out = BarchartFetcher.blank_unpublished_open_interest(_frame([0, 0, 0, 0]))
    assert out["Open Interest"].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_published_last_bar_is_untouched():
    frame = _frame([6362, 6362, 6362, 6400])
    out = BarchartFetcher.blank_unpublished_open_interest(frame)
    assert out["Open Interest"].tolist() == [6362.0, 6362.0, 6362.0, 6400.0]


def test_interior_zero_is_untouched():
    """Only the newest bar is ever unpublished; an interior zero is data."""
    out = BarchartFetcher.blank_unpublished_open_interest(_frame([6362, 0, 6362, 0]))
    values = out["Open Interest"].tolist()
    assert values[1] == 0.0
    assert np.isnan(values[-1])


def test_single_bar_frame_is_untouched():
    frame = _frame([0])
    assert BarchartFetcher.blank_unpublished_open_interest(frame)["Open Interest"].tolist() == [0.0]


def test_frame_without_open_interest_column_survives():
    frame = _frame([1, 2, 3, 0]).drop(columns=["Open Interest"])
    out = BarchartFetcher.blank_unpublished_open_interest(frame)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]


@pytest.mark.parametrize("column", ["Open Interest", "openinterest", "openInterest"])
def test_every_vendor_spelling_is_recognised(column):
    out = BarchartFetcher.blank_unpublished_open_interest(_frame([6362, 6362, 0], column=column))
    assert np.isnan(out[column].tolist()[-1])


def test_blanking_is_idempotent():
    once = BarchartFetcher.blank_unpublished_open_interest(_frame([6362, 6362, 0]))
    twice = BarchartFetcher.blank_unpublished_open_interest(once)
    assert np.isnan(twice["Open Interest"].tolist()[-1])
    assert twice["Open Interest"].tolist()[:2] == [6362.0, 6362.0]


def test_none_frame_passes_through():
    assert BarchartFetcher.blank_unpublished_open_interest(None) is None


# --------------------------------------------------------------------------------------
# smile_to_rnd_input: an inapplicable screen is skipped, not applied
# --------------------------------------------------------------------------------------

_FWD = 96.5


def _point(right, strike, price, open_interest):
    return STIRFutureOptionSmilePoint(
        label=f"SFRZ26|{int(strike * 100):04d}{right}",
        right=right,
        delta_abs=25.0,
        atm_offset_bps=0.0,
        strike_price=strike,
        strike_rate=100.0 - strike,
        iv_normal_price=0.01,
        iv_normal_bps=1.0,
        market_price=price,
        discount_factor=1.0,
        open_interest=open_interest,
    )


def _chain(open_interest):
    """Eight OTM legs bracketing the forward, all sharing one open-interest value."""
    puts = [(96.00, 0.030), (96.125, 0.040), (96.25, 0.055), (96.375, 0.075)]
    calls = [(96.625, 0.070), (96.75, 0.052), (96.875, 0.038), (97.00, 0.027)]
    points = [_point("P", k, px, open_interest) for k, px in puts]
    points += [_point("C", k, px, open_interest) for k, px in calls]
    return STIRFutureOptionSABRSmile(
        source="BARCHART_STIRFO-QL",
        symbol="SFRZ26",
        underlying_contract="SFRZ26",
        quote_timestamp=datetime.datetime(2026, 8, 7, 17, 0),
        params=STIRFutureOptionSABRParams(
            alpha=0.1,
            beta=0.5,
            rho=0.0,
            nu=1.0,
            forward_price=_FWD,
            forward_rate=100.0 - _FWD,
            time_to_expiry=0.35,
            expiry_date=datetime.date(2026, 12, 11),
            as_of=datetime.date(2026, 8, 7),
        ),
        points=tuple(points),
    )


def _rnd(chain):
    return smile_to_rnd_input(
        chain,
        use_sabr_vols=False,
        raw_market_open_interest_min=100.0,
        raw_market_otm_only=True,
    )


def test_published_open_interest_still_screens_normally():
    rnd = _rnd(_chain(5_000.0))
    assert rnd.strike_source == "market_jpm"
    assert len(rnd.strikes_price) == 8


@pytest.mark.parametrize("unavailable", [0.0, None, float("nan")])
def test_chain_wide_unavailable_open_interest_skips_the_screen(unavailable):
    """This is the reported bug: every leg reads zero, so the screen deletes the chain
    rather than filtering it, and the caller silently receives a model density."""
    rnd = _rnd(_chain(unavailable))

    assert not rnd.strike_source.startswith("sabr"), (
        "an inapplicable open-interest screen must not demote the density to a SABR model"
    )
    assert rnd.strike_source == "market_jpm_no_oi_screen"
    assert len(rnd.strikes_price) == 8
    assert any("SKIPPED" in w for w in rnd.warnings), rnd.warnings
    assert any("open interest is unavailable" in w for w in rnd.warnings), rnd.warnings


def test_genuinely_illiquid_chain_still_fails_the_screen():
    """Present-but-tiny open interest is a real liquidity signal and must still bite;
    only a chain with no usable open interest at all disables the screen."""
    rnd = _rnd(_chain(3.0))
    assert rnd.strike_source == "sabr_smile"
    assert any("fell back to SABR" in w for w in rnd.warnings), rnd.warnings
    assert any("dropped by the open-interest screen" in w for w in rnd.warnings), rnd.warnings


def test_fallback_is_still_fatal_when_the_caller_asks():
    with pytest.raises(ValueError, match="dropped by the open-interest screen"):
        smile_to_rnd_input(
            _chain(3.0),
            use_sabr_vols=False,
            raw_market_open_interest_min=100.0,
            raw_market_otm_only=True,
            allow_sabr_fallback=False,
        )
