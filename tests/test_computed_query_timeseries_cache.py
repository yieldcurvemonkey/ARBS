import datetime
import uuid
from typing import Any, Dict

import pandas as pd

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from MDP.MarketDataProvider import MarketDataProvider
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.IRSwapsTB import IRSwapsTB


class _FakeIRSwapsMDP(MarketDataProvider):
    def __init__(self, source: str):
        super().__init__(source=source)
        self.bulk_calls = 0

    def get_pricer(self, request: Dict[str, Any]) -> Any:
        return request

    def bulk_get_data(self, request: Dict[str, Any]) -> Dict[Any, Any]:
        self.bulk_calls += 1
        return {ts: {"curve": ts} for ts in request["timestamps"]}


class _FakeFixedRateBondsMDP(MarketDataProvider):
    def __init__(self, source: str):
        super().__init__(source=source)
        self.bulk_calls = 0

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def bulk_get_data(
        self,
        timestamps,
        cusips,
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
    ) -> Dict[Any, Dict[str, Any]]:
        _ = show_tqdm, force_refresh, max_workers
        self.bulk_calls += 1
        return {ts: {cusip: {"cusip": cusip, "timestamp": ts} for cusip in cusips} for ts in timestamps}


def test_computed_timeseries_store_roundtrip_preserves_intraday_column_names(tmp_path):
    store = ComputedTimeseriesStore(base_dir=tmp_path)
    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)

    store.append_rows(
        symbol="IRS::TEST",
        rows=[
            (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
            (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
        ],
    )

    rows = store.read_rows(
        symbol="IRS::TEST",
        reference_points=[ts1, ts2],
        intraday=True,
        skip_current_eod=False,
        fallback_column_name="fallback",
    )

    assert rows == [
        (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
        (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
    ]


def test_irswaps_tb_uses_shared_computed_store_across_instances(monkeypatch, tmp_path):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(q.curve), 0.05 if ref_dt == ts1 else 0.051),
    )

    source = f"TEST_IRS_{uuid.uuid4().hex}"
    mdp1 = _FakeIRSwapsMDP(source=source)
    tb1 = IRSwapsTB(mdp1, show_tqdm=False, ts_base_dir=str(tmp_path))
    out1 = tb1.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp1.bulk_calls == 1
    assert list(out1.iloc[:, 0]) == [0.05, 0.051]

    mdp2 = _FakeIRSwapsMDP(source=source)
    tb2 = IRSwapsTB(mdp2, show_tqdm=False, ts_base_dir=str(tmp_path))
    out2 = tb2.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp2.bulk_calls == 0
    pd.testing.assert_frame_equal(out1, out2)


def test_fixedratebonds_tb_uses_shared_computed_store_across_instances(monkeypatch, tmp_path):
    import TB.FixedRateBondsTB as frb_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (ref_dt, q.col_name(), 4.25 if ref_dt == ts1 else 4.30),
    )

    source = f"TEST_FRB_{uuid.uuid4().hex}"
    mdp1 = _FakeFixedRateBondsMDP(source=source)
    tb1 = FixedRateBondsTB(mdp1, show_tqdm=False, ts_base_dir=str(tmp_path))
    out1 = tb1.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp1.bulk_calls == 1
    assert list(out1.iloc[:, 0]) == [4.25, 4.30]

    mdp2 = _FakeFixedRateBondsMDP(source=source)
    tb2 = FixedRateBondsTB(mdp2, show_tqdm=False, ts_base_dir=str(tmp_path))
    out2 = tb2.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp2.bulk_calls == 0
    pd.testing.assert_frame_equal(out1, out2)
