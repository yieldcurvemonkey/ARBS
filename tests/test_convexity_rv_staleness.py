"""Known-answer tests for the stale-settle detector.

The planted answer is a synthetic price panel with a deliberately constructed
defect: one deferred contract holds its price flat for three days while the
front contract moves every day, then catches up in a single print. That is the
exact pattern that manufactures Sharpe in a ``-dCA * DV01`` panel simulation --
three days of artificially zero P&L followed by one fabricated jump -- so the
detector is tested against a case whose correct answer is known by construction
rather than only against live data where it cannot be graded.
"""

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.ca_staleness import (
    flag_stale_prices,
    pack_staleness,
    staleness_summary,
)

DATES = pd.bdate_range("2023-01-02", periods=8)


def _panel() -> pd.DataFrame:
    """Front moves every day. SR3Z5 goes stale on days 3-5 then catches up.

    Prices are futures points; 0.01 point = 1bp of rate.
    """
    front = [95.00, 95.05, 95.12, 95.20, 95.31, 95.40, 95.44, 95.50]
    #                          |---- flat ----|  catch-up (+0.30 = 30bp)
    stale = [94.00, 94.06, 94.10, 94.10, 94.10, 94.40, 94.44, 94.50]
    clean = [93.00, 93.04, 93.09, 93.16, 93.26, 93.34, 93.39, 93.45]
    return pd.DataFrame({"SR3H4": front, "SR3Z5": stale, "SR3M5": clean}, index=DATES)


def test_reference_defaults_to_the_most_active_contract():
    f = flag_stale_prices(_panel())
    # The front never repeats, so it must carry no flags at all.
    front = f[f.contract == "SR3H4"]
    assert not front["any_flag"].any()


def test_planted_stale_run_is_detected_on_the_right_days():
    f = flag_stale_prices(_panel(), reference="SR3H4", min_run=2)
    s = f[f.contract == "SR3Z5"].set_index("date")
    # Price is unchanged on days index 3 and 4 (2023-01-05, 2023-01-06).
    flat_days = [DATES[3], DATES[4]]
    assert s.loc[flat_days, "repeat_price"].all()
    # A run of >=2 unchanged prints: the second flat day qualifies.
    assert s.loc[DATES[4], "stale_run"]


def test_catch_up_jump_is_flagged():
    """The fabricated-P&L day: the first print after the stale run."""
    f = flag_stale_prices(_panel(), reference="SR3H4", min_run=2, jump_bp=3.0)
    s = f[f.contract == "SR3Z5"].set_index("date")
    assert s.loc[DATES[5], "jump_after_stale"], "the 30bp catch-up must be flagged"
    # and it is the ONLY such day for this contract
    assert int(s["jump_after_stale"].sum()) == 1


def test_clean_contract_is_not_flagged():
    f = flag_stale_prices(_panel(), reference="SR3H4")
    clean = f[f.contract == "SR3M5"]
    assert not clean["any_flag"].any(), "a contract that moves daily must stay clean"


def test_detector_is_not_vacuous_when_the_market_is_quiet():
    """If the reference did NOT move, an unchanged deferred print is legitimate
    and must NOT be flagged -- otherwise every holiday-thin day is condemned."""
    quiet = _panel().copy()
    quiet["SR3H4"] = 95.00  # front flat too
    f = flag_stale_prices(quiet, reference="SR3H4")
    assert not f["repeat_price"].any()
    assert not f["stale_run"].any()


def test_pack_inherits_a_flag_from_any_leg():
    """The pack rate is a mean, so one stale leg contaminates the adjustment."""
    f = flag_stale_prices(_panel(), reference="SR3H4", min_run=2)
    packs = pack_staleness(f, {"P1": ["SR3H4", "SR3M5"], "P2": ["SR3H4", "SR3Z5"]})
    p1 = packs[packs["pack"] == "P1"].set_index("date")
    p2 = packs[packs["pack"] == "P2"].set_index("date")
    assert not p1["any_flag"].any(), "pack of two clean legs must be clean"
    assert p2.loc[DATES[4], "stale_run"], "pack containing the stale leg must inherit it"
    assert int(p2.loc[DATES[4], "n_stale_legs"]) == 1


def test_summary_ranks_the_dirtiest_contract_first():
    f = flag_stale_prices(_panel(), reference="SR3H4")
    s = staleness_summary(f)
    assert s.index[0] == "SR3Z5"
    assert s.loc["SR3M5", "any_flag"] == 0.0


def test_empty_panel_is_handled():
    out = flag_stale_prices(pd.DataFrame())
    assert out.empty
    assert list(out.columns)[:2] == ["date", "contract"]


@pytest.mark.parametrize("min_run", [2, 3])
def test_min_run_threshold_is_respected(min_run):
    f = flag_stale_prices(_panel(), reference="SR3H4", min_run=min_run)
    s = f[f.contract == "SR3Z5"]
    n = int(s["stale_run"].sum())
    # Two consecutive unchanged prints: 1 qualifying day at min_run=2, none at 3.
    assert n == (1 if min_run == 2 else 0)
