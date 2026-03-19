import datetime
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from TB.BaseTimeseriesTB import BaseTimeseriesTB


class _TestTB(BaseTimeseriesTB):
    pass


class _RecordingMDP(MarketDataProvider):
    def __init__(self):
        super().__init__(source="TEST")
        self.requests: List[Dict[str, Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        req = dict(request)
        self.requests.append(req)
        return {"request": req}


@dataclass(frozen=True)
class _FakeQuery(BaseQuery):
    product_name: str = "FAKE"
    symbol: str = "AAA"
    resolved_symbol: Optional[str] = None
    fake_col: str = "fake_col"
    fake_value_result: float = 1.0
    value: str = "PRICE"
    value_kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "product", self.product_name)
        object.__setattr__(self, "structure_id", "OUTRIGHT")
        object.__setattr__(self, "value_id", self.value)

    def return_query(self) -> List[BaseQuery]:
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        return self.fake_col

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        return self.fake_col

    def build_mdp_request(self, now: datetime.datetime) -> Dict[str, Any]:
        req = dict(self.market_request or {})
        req.setdefault("timestamp", now.date())
        req.setdefault("symbol", self.symbol)
        return req

    def resolve_query(self, timestamp, pricer_or_curve):
        _ = timestamp, pricer_or_curve
        if self.resolved_symbol and self.resolved_symbol != self.symbol:
            return replace(self, symbol=self.resolved_symbol, market_request={"symbol": self.resolved_symbol})
        return self

    def resolve_package(
        self,
        *,
        pricer_or_curve: Any,
        **hints: Any,
    ) -> Tuple[List[Any], List[float]]:
        _ = pricer_or_curve, hints
        return ([], [1.0])

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[Any],
        risk_weights: List[float],
    ) -> Any:
        _ = pricer_or_curve, package, risk_weights
        result = float(self.fake_value_result)

        class _VM:
            def apply(self, value: Any, **kwargs: Any) -> float:
                _ = value, kwargs
                return result

        return _VM()


def test_reference_points_prioritize_explicit_timestamps():
    tb = _TestTB(mdp=_RecordingMDP(), date_col="Date", show_tqdm=False)
    t0 = datetime.datetime(2025, 1, 6, 10, 0)
    t1 = datetime.datetime(2025, 1, 6, 9, 0)
    refs = tb._build_reference_points(
        start=datetime.date(2025, 1, 1),
        end=datetime.date(2025, 1, 10),
        freq="1H",
        timestamps=[t0, t1],
    )
    assert refs == [t1, t0]


def test_reference_points_intraday_datetime_freq():
    tb = _TestTB(mdp=_RecordingMDP(), date_col="Date", show_tqdm=False)
    start = datetime.datetime(2025, 1, 6, 9, 0, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2025, 1, 6, 10, 0, tzinfo=datetime.timezone.utc)
    refs = tb._build_reference_points(
        start=start,
        end=end,
        freq="30min",
        timestamps=None,
    )
    assert len(refs) == 3
    assert refs[0].hour == 9
    assert refs[-1].hour == 10


def test_reference_points_business_date_range():
    tb = _TestTB(mdp=_RecordingMDP(), date_col="Date", show_tqdm=False)
    refs = tb._build_reference_points(
        start=datetime.date(2025, 1, 3),  # Friday
        end=datetime.date(2025, 1, 7),  # Tuesday
        freq=None,
        timestamps=None,
    )
    assert refs == [
        datetime.date(2025, 1, 3),
        datetime.date(2025, 1, 6),
        datetime.date(2025, 1, 7),
    ]


def test_reference_points_eod_aliases_resolve_to_business_close_instants():
    tb = _TestTB(mdp=_RecordingMDP(), date_col="Date", show_tqdm=False)
    nyc = ZoneInfo("America/New_York")
    start = datetime.datetime(2025, 7, 28, 0, 1, tzinfo=nyc)
    end = datetime.datetime(2025, 7, 30, 17, 0, tzinfo=nyc)
    expected_nyc = [
        datetime.datetime(2025, 7, 28, 17, 0, tzinfo=nyc),
        datetime.datetime(2025, 7, 29, 17, 0, tzinfo=nyc),
        datetime.datetime(2025, 7, 30, 17, 0, tzinfo=nyc),
    ]
    expected_ldn = [
        datetime.datetime(2025, 7, 28, 12, 0, tzinfo=nyc),
        datetime.datetime(2025, 7, 29, 12, 0, tzinfo=nyc),
        datetime.datetime(2025, 7, 30, 12, 0, tzinfo=nyc),
    ]

    assert tb._build_reference_points(start=start, end=end, freq="eod", timestamps=None) == expected_nyc
    assert tb._build_reference_points(start=start, end=end, freq="nyc_eod", timestamps=None) == expected_nyc
    assert tb._build_reference_points(start=start, end=end, freq="chi_eod", timestamps=None) == expected_nyc
    assert tb._build_reference_points(start=start, end=end, freq="ldn_eod", timestamps=None) == expected_ldn


def test_generic_row_evaluation_pipeline_refetches_when_request_changes():
    mdp = _RecordingMDP()
    tb = _TestTB(mdp=mdp, date_col="Date", show_tqdm=False)
    q = _FakeQuery(
        symbol="AAA",
        resolved_symbol="BBB",
        fake_col="my_col",
        fake_value_result=12.5,
    )

    out = tb.get_timeseries(
        start=datetime.date(2025, 1, 6),
        end=datetime.date(2025, 1, 6),
        queries=[q],
    )

    assert list(out.columns) == ["my_col"]
    assert out.iloc[0, 0] == 12.5
    assert len(mdp.requests) == 2
    assert mdp.requests[0]["symbol"] == "AAA"
    assert mdp.requests[1]["symbol"] == "BBB"


def test_output_pivot_and_index_shape_uses_last_value_for_duplicate_column():
    tb = _TestTB(mdp=_RecordingMDP(), date_col="Date", show_tqdm=False)
    q1 = _FakeQuery(symbol="A1", fake_col="dup", fake_value_result=1.0)
    q2 = _FakeQuery(symbol="A2", fake_col="dup", fake_value_result=2.0)

    out = tb.get_timeseries(
        start=datetime.date(2025, 1, 6),
        end=datetime.date(2025, 1, 6),
        queries=[q1, [q2]],
    )

    assert out.index.name == "Date"
    assert out.loc[datetime.date(2025, 1, 6), "dup"] == 2.0
