import datetime as dt
import math

import pandas as pd
import pytest

from SDRUtils._swappulse_scripts.ingest_usdcapfloors import (
    build_legs_dataframe,
    normalize_dataframe,
)
from SDRUtils._swappulse_scripts.ingest_usdswaptions import upsert_dataframe
from SDRUtils.products._capfloors.pricing import (
    bachelier_caplet,
    build_caplet_schedule,
    strip_cap_vol,
)
from SDRUtils.products.usd import usd_capfloors as capfloors_mod
from SDRUtils.products.usd.usd_capfloors import USD_CapFloors


def _coerce_datetime(value: object) -> dt.datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts.to_pydatetime()


class StubCapFloorCurve:
    def __init__(
        self,
        reference_date: dt.datetime,
        forwards_by_start: dict[str, float],
        discount_rate: float = 0.04,
    ) -> None:
        self.reference_date = reference_date
        self.forwards_by_start = forwards_by_start
        self.discount_rate = discount_rate

    def rate(self, start: object, end: object) -> float:
        start_key = _coerce_datetime(start).date().isoformat()
        return self.forwards_by_start[start_key]

    def __getitem__(self, when: object) -> float:
        dt_value = _coerce_datetime(when)
        years = max((dt_value - self.reference_date).days / 365.0, 0.0)
        return math.exp(-self.discount_rate * years)


def _sample_trade_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Dissemination Identifier": "CF-001",
        "Event timestamp": "2026-02-27 15:00:00+00:00",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Effective Date": "2026-03-01",
        "Expiration Date": "2027-03-01",
        "UPI FISN": "NA/O Call Epn USD",
        "UPI Underlier Name": "USD-SOFR-CME TERM",
        "Notional amount-Leg 1": "78000000",
        "Notional currency-Leg 1": "USD",
        "Strike Price": 4.5,
        "Strike price notation": 3.0,
        "Option Premium Amount": 3700.0,
        "Floating rate reset frequency period multiplier-leg 1": 1,
        "Floating rate reset frequency period-leg 1": "MNTH",
        "Package indicator": False,
        "Unique Product Identifier": "QZQJWDQ4V0VJ",
    }
    row.update(overrides)
    return row


def test_strip_cap_vol_round_trips_flat_normal_vol():
    valuation_date = dt.datetime(2026, 2, 27)
    effective = dt.datetime(2026, 3, 1)
    expiration = dt.datetime(2027, 3, 1)
    sigma = 0.008281
    notional = 78_000_000
    strike = 0.045
    forward_path = [
        3.684,
        3.655,
        3.603,
        3.563,
        3.508,
        3.413,
        3.355,
        3.284,
        3.191,
        3.125,
        3.091,
        3.034,
    ]
    schedule = build_caplet_schedule(effective, expiration, freq_months=1)
    forwards_by_start = {
        start.date().isoformat(): forward_path[index]
        for index, (start, _) in enumerate(schedule)
    }
    curve = StubCapFloorCurve(valuation_date, forwards_by_start)

    market_premium = 0.0
    for accrual_start, accrual_end in schedule:
        forward = curve.rate(accrual_start, accrual_end) / 100.0
        tau = (accrual_end - accrual_start).days / 360.0
        t_fix = max((accrual_start - valuation_date).days / 365.0, 0.0)
        discount_factor = curve[accrual_end] / curve[valuation_date]
        market_premium += bachelier_caplet(
            forward,
            strike,
            sigma,
            t_fix,
            tau,
            discount_factor,
            notional,
        )

    trade = _sample_trade_row(
        **{
            "Option Premium Amount": market_premium,
            "Effective Date": effective,
            "Expiration Date": expiration,
        }
    )
    result = strip_cap_vol(trade, curve, valuation_date=valuation_date)

    assert result["implied_vol_bps"] == pytest.approx(82.81, abs=0.05)
    assert result["model_premium"] == pytest.approx(market_premium, abs=1e-6)
    assert result["num_caplets"] == 12
    assert len(result["caplet_details"]) == 12
    assert result["caplet_details"][0]["moneyness_bps"] == pytest.approx(-81.6, abs=0.2)


def test_build_classification_dataframe_overwrites_pricing_columns_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
):
    raw_df = pd.DataFrame([_sample_trade_row()])

    class StubBuilder:
        def __init__(self, cache_path: str, show_tqdm: bool = False) -> None:
            self.cache_path = cache_path
            self.show_tqdm = show_tqdm

        def grab_sdr_trades(self, **kwargs: object) -> pd.DataFrame:
            return raw_df.copy()

    monkeypatch.setattr(capfloors_mod, "SDRDataBuilder", StubBuilder)
    monkeypatch.setattr(capfloors_mod, "_resolve_curve_handle", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        capfloors_mod,
        "strip_cap_vol",
        lambda trade, curve, valuation_date=None: {
            "implied_vol_bps": 82.81,
            "bpvol": 82.81,
            "num_caplets": 12,
            "moneyness_bps": -81.6,
            "caplet_details": [
                {
                    "accrual_start": dt.datetime(2026, 3, 1),
                    "accrual_end": dt.datetime(2026, 4, 1),
                    "forward": 0.03684,
                    "moneyness_bps": -81.6,
                    "T_fix": 0.005,
                    "caplet_price": 0.0,
                }
            ],
            "model_premium": 3700.0,
            "market_premium": 3700.0,
            "warnings": [],
        },
    )

    product = USD_CapFloors()
    result = product.build_classification_dataframe(
        start=pd.Timestamp("2026-02-27 00:00:00+00:00"),
        end=pd.Timestamp("2026-02-27 23:59:59+00:00"),
        cache_path="unused",
        only_newt=True,
    )

    assert len(result) == 1
    assert result.columns.is_unique
    assert result.loc[result.index[0], "product_type"] == "CAP"
    assert result.loc[result.index[0], "bpvol"] == pytest.approx(82.81)
    assert result.loc[result.index[0], "implied_vol_bps"] == pytest.approx(82.81)
    assert result.loc[result.index[0], "package_id"] == "OUTRIGHT-CF-001"
    assert "USD-SOFR-CME-TERM 1M" in result.loc[result.index[0], "trade_label"]
    assert result.loc[result.index[0], "caplet_details"][0]["moneyness_bps"] == pytest.approx(-81.6)


def test_build_legs_dataframe_preserves_caplet_metrics_as_jsonable_payload():
    raw_df = pd.DataFrame(
        [
            {
                "trade_id": "CF-001",
                "package_id": "OUTRIGHT-CF-001",
                "execution_timestamp": "2026-02-27 15:00:00+00:00",
                "effective_date": "2026-03-01",
                "expiration_date": "2027-03-01",
                "product_type": "CAP",
                "trade_label": "USD-SOFR-CME-TERM 1M 1Y CAP 4.50%",
                "tenor_years": 1.0,
                "tenor_label": "1Y",
                "forward_start_years": 0.0,
                "forward_label": "0D",
                "notional": 78_000_000,
                "notional_currency": "USD",
                "is_notional_capped": False,
                "strike": 0.045,
                "premium": 3700.0,
                "exercise_style": "EUROPEAN",
                "package_type": "OUTRIGHT",
                "bpvol": 82.81,
                "implied_vol_bps": 82.81,
                "num_caplets": 12,
                "reset_frequency": "1M",
                "moneyness_bps": -81.6,
                "cap_floor_type": "CAP",
                "caplet_details": [
                    {
                        "accrual_start": dt.datetime(2026, 3, 1),
                        "accrual_end": dt.datetime(2026, 4, 1),
                        "forward": 0.03684,
                        "moneyness_bps": -81.6,
                        "T_fix": 0.005,
                        "caplet_price": 0.0,
                    }
                ],
                "model_premium": 3700.0,
                "market_premium": 3700.0,
                "warnings": ["premium_outside_nominal_band"],
                "outright_bpvol_yr": 82.81,
            }
        ]
    )

    cleaned = normalize_dataframe(raw_df)
    legs_df = build_legs_dataframe(cleaned)

    assert len(legs_df) == 1
    leg_metrics = legs_df.loc[legs_df.index[0], "leg_metrics"]
    assert leg_metrics["cap_floor_type"] == "CAP"
    assert leg_metrics["bpvol"] == pytest.approx(82.81)
    assert leg_metrics["caplet_details"][0]["accrual_start"] == "2026-03-01T00:00:00"
    assert leg_metrics["caplet_details"][0]["accrual_end"] == "2026-04-01T00:00:00"
    assert leg_metrics["warnings"] == ["premium_outside_nominal_band"]


def test_upsert_dataframe_converts_nat_dates_to_none_for_db_params():
    class DummyConn:
        def __init__(self) -> None:
            self.batches: list[list[dict[str, object]]] = []

        def execute(self, sql, batch):
            self.batches.append(batch)

    class DummyBegin:
        def __init__(self, conn: DummyConn) -> None:
            self.conn = conn

        def __enter__(self) -> DummyConn:
            return self.conn

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    class DummyEngine:
        def __init__(self) -> None:
            self.conn = DummyConn()

        def begin(self) -> DummyBegin:
            return DummyBegin(self.conn)

    engine = DummyEngine()
    df = pd.DataFrame(
        [
            {
                "trade_id": "CF-001",
                "package_id": "OUTRIGHT-CF-001",
                "leg_order": 0,
                "execution_timestamp": pd.Timestamp("2026-03-09T12:54:22Z"),
                "effective_date": dt.date(2026, 3, 9),
                "expiration_date": dt.date(2028, 3, 15),
                "underlying_expiration_date": pd.NaT,
                "package_transaction_price": float("nan"),
                "leg_metrics": {"bpvol": 90.0},
            }
        ]
    )

    written = upsert_dataframe(
        df,
        engine,
        "arbs_capfloor_legs_v1",
        conflict_cols=["trade_id"],
        update_cols=["package_id"],
        json_cols=["leg_metrics"],
        batch_size=1000,
        progress_desc="test",
    )

    assert written == 1
    assert len(engine.conn.batches) == 1
    params = engine.conn.batches[0][0]
    assert params["underlying_expiration_date"] is None
    assert params["package_transaction_price"] is None
