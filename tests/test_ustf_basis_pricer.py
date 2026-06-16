"""Validate the USTFutureBasis analytics pricer.

Uses a shared MDP and force_refresh on the basis report so both the pricer and the
report see the same basket state (including WI-filtered deliverables).
"""
import datetime

import pytest

from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

SYMBOL = "TYZ25"
ASOF = datetime.date(2025, 11, 14)


@pytest.fixture(scope="module")
def mdp():
    return USTFuturesMDP(source="BARCHART_USTF-RL")


@pytest.fixture(scope="module")
def future_pricer(mdp):
    out = mdp.get_pricer({"symbols": [SYMBOL], "timestamp": ASOF, "include_basket": True})
    return out[SYMBOL]


@pytest.fixture(scope="module")
def report(mdp):
    return mdp.get_basis_report(symbol=SYMBOL, timestamp=ASOF, force_refresh=True)


@pytest.fixture(scope="module")
def ctd_row(report):
    return report[report.is_ctd].iloc[0]


def test_ctd_cusip_matches_report(future_pricer, ctd_row):
    from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

    bp = RLUSTFutureBasisPricer(future_pricer)
    assert bp.ctd_cusip() == str(ctd_row["cusip"])


def test_gross_basis_matches_report(future_pricer, ctd_row):
    from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

    bp = RLUSTFutureBasisPricer(future_pricer)
    assert bp.gross_basis() == pytest.approx(float(ctd_row["gross_basis"]), abs=0.01)


def test_net_basis_bnoc_matches_report(future_pricer, ctd_row):
    from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

    bp = RLUSTFutureBasisPricer(future_pricer)
    assert bp.bnoc() == pytest.approx(float(ctd_row["bnoc"]), abs=0.01)
    assert bp.net_basis() == pytest.approx(float(ctd_row["bnoc"]), abs=0.01)


def test_conversion_factor_matches_report(future_pricer, ctd_row):
    from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

    bp = RLUSTFutureBasisPricer(future_pricer)
    assert bp.conversion_factor() == pytest.approx(float(ctd_row["invoice_cf"]), abs=1e-3)


def test_implied_repo_is_sane(future_pricer):
    from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

    bp = RLUSTFutureBasisPricer(future_pricer)
    irr = bp.implied_repo()
    assert -5.0 < irr < 30.0


def test_dv01_hedge_ratio_equals_cf_for_ctd(future_pricer):
    from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

    bp = RLUSTFutureBasisPricer(future_pricer)
    assert bp.dv01_hedge_ratio() == pytest.approx(bp.conversion_factor(), rel=1e-6)


def test_query_path_value_map(mdp):
    """Full Query product path: build request -> MDP -> resolve_package -> value map."""
    from Query.USTFutureBasis.USTFutureBasisQuery import USTFutureBasisQuery
    from Query.USTFutureBasis.USTFutureBasisValue import USTFutureBasisValue

    q = USTFutureBasisQuery(symbol=SYMBOL, value=USTFutureBasisValue.NET_BASIS)
    req = q.build_mdp_request(datetime.datetime(ASOF.year, ASOF.month, ASOF.day))
    assert req.get("include_basket") is True
    assert req.get("symbols") == [SYMBOL]

    pr = mdp.get_pricer(req)
    pkg, weights = q.resolve_package(pricer_or_curve=pr)
    assert len(pkg) == 1 and len(weights) == 1

    vmap = q.build_value_map(pricer_or_curve=pr, package=pkg, risk_weights=weights)
    nb = vmap.apply(value=USTFutureBasisValue.NET_BASIS)
    gb = vmap.apply(value=USTFutureBasisValue.GROSS_BASIS)
    assert isinstance(nb, float) and isinstance(gb, float)


def test_query_default_mtm_value_id_is_set():
    from Query.USTFutureBasis.USTFutureBasisQuery import USTFutureBasisQuery

    q = USTFutureBasisQuery(symbol=SYMBOL)
    assert q.product == "USTFUTUREBASIS"
    assert q.default_mtm_value_id() is not None
