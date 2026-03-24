import datetime as dt
from dataclasses import dataclass

import pandas as pd

from Query.Base.query_resolution import resolve_query
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure


@dataclass
class _BondInstrument:
    cusip: str
    issue_date: dt.date
    maturity_date: dt.date
    cpn: float
    notional: float


class _FakeBondPricer:
    def __init__(self, cusip: str):
        self._cusip = cusip

    def issue_date(self) -> dt.date:
        return dt.date(2025, 1, 15)

    def maturity_date(self) -> dt.date:
        return dt.date(2035, 2, 15)

    def coupon(self) -> float:
        return 4.0

    def pv01(self, notional: float) -> float:
        return float(notional) * 0.0001

    def build_pricable(
        self,
        *,
        cusip: str,
        issue_date: dt.date,
        maturity_date: dt.date,
        cpn: float,
        notional: float | None = None,
        bpv: float | None = None,
    ) -> _BondInstrument:
        resolved_notional = notional
        if resolved_notional is None:
            if bpv is not None:
                resolved_notional = float(bpv) / self.pv01(1.0)
            else:
                resolved_notional = 1_000_000.0

        return _BondInstrument(
            cusip=cusip,
            issue_date=issue_date,
            maturity_date=maturity_date,
            cpn=float(cpn),
            notional=float(resolved_notional),
        )

    def notional(self, instrument: _BondInstrument) -> float:
        return float(instrument.notional)


def _make_pricer_map(*cusips: str) -> dict[str, _FakeBondPricer]:
    return {cusip: _FakeBondPricer(cusip) for cusip in cusips}


def test_curve_query_with_slash_cusip_resolves_package() -> None:
    pricers = _make_pricer_map("AAA", "BBB")
    query = FixedRateBondQuery(cusip="AAA/BBB")

    resolved = resolve_query(
        query,
        timestamp=dt.datetime(2026, 3, 10, 12, 0),
        pricer_or_curve=pricers,
    )
    package, risk_weights = resolved.resolve_package(
        pricer_or_curve=pricers,
        is_for_timeseries=True,
    )

    assert resolved.structure == FixedRateBondStructure.CURVE
    assert [bond.cusip for bond in package] == ["AAA", "BBB"]
    assert risk_weights == [-1.0, 1.0]


def test_fly_query_with_slash_cusip_resolves_package() -> None:
    pricers = _make_pricer_map("AAA", "BBB", "CCC")
    query = FixedRateBondQuery(cusip="AAA/BBB/CCC")

    resolved = resolve_query(
        query,
        timestamp=dt.datetime(2026, 3, 10, 12, 0),
        pricer_or_curve=pricers,
    )
    package, risk_weights = resolved.resolve_package(
        pricer_or_curve=pricers,
        is_for_timeseries=True,
    )

    assert resolved.structure == FixedRateBondStructure.FLY
    assert [bond.cusip for bond in package] == ["AAA", "BBB", "CCC"]
    assert risk_weights == [-1.0, 2.0, -1.0]


def test_build_mdp_request_accepts_live_literal() -> None:
    query = FixedRateBondQuery(cusip="CT10")

    request = query.build_mdp_request("live")

    assert request["timestamp"] == "live"
    assert request["cusips"] == ["CT10"]


def test_resolve_query_with_live_timestamp_resolves_constant_maturity_alias(monkeypatch) -> None:
    from MDP.FixedRateBonds.reference_data_cache import ust_reference_data

    today = dt.date.today()
    ref_df = pd.DataFrame(
        [
            {
                "cusip": "91282CPZ8",
                "oi": "10-Year",
                "issue_date": today - dt.timedelta(days=365),
                "maturity_date": today + dt.timedelta(days=3650),
            }
        ]
    )

    monkeypatch.setattr(ust_reference_data, "update_reference_data", lambda *args, **kwargs: ref_df)

    query = FixedRateBondQuery(cusip="CT10")
    resolved = resolve_query(query, timestamp="live", pricer_or_curve={})

    assert resolved.cusip == "91282CPZ8"
