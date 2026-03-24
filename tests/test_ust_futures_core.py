import datetime

import pandas as pd
import pytest
import pytz

from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

CHI = pytz.timezone("America/Chicago")


class _FakeStore:
    def __init__(self):
        self.snapshot_rows = {}
        self.basis_rows = {}
        self.snapshot_reads = []
        self.snapshot_writes = []
        self.basis_reads = []
        self.basis_writes = []

    def read_snapshot_day(self, symbol, trading_date):
        self.snapshot_reads.append((symbol, trading_date))
        return self.snapshot_rows.get((symbol, trading_date), pd.DataFrame()).copy()

    def write_snapshot_day(self, symbol, trading_date, df, overwrite=False):
        self.snapshot_writes.append((symbol, trading_date, df.copy(), overwrite))
        self.snapshot_rows[(symbol, trading_date)] = df.copy()

    def has_snapshot_day(self, symbol, trading_date):
        return (symbol, trading_date) in self.snapshot_rows

    def read_basis_report_day(self, symbol, trading_date):
        self.basis_reads.append((symbol, trading_date))
        return self.basis_rows.get((symbol, trading_date), pd.DataFrame()).copy()

    def write_basis_report_day(self, symbol, trading_date, df, overwrite=False):
        self.basis_writes.append((symbol, trading_date, df.copy(), overwrite))
        self.basis_rows[(symbol, trading_date)] = df.copy()

    def has_basis_report_day(self, symbol, trading_date):
        return (symbol, trading_date) in self.basis_rows


class _FakeBondPricer:
    def __init__(self, cusip, label, clean_price, ytm, settlement_date):
        self._meta = {"cusip": cusip, "label": label}
        self._clean_price = clean_price
        self._ytm = ytm
        self._settlement_date = settlement_date

    def meta(self):
        return self._meta

    def clean_price(self):
        return self._clean_price

    def ytm(self):
        return self._ytm

    def settlement_date(self):
        return self._settlement_date


class _FakeFuturePricer:
    def __init__(self, basket_pricers):
        self._price = 112.25
        self._basket_pricers = basket_pricers
        self._meta_data = {"timestamp": "2026-03-24T19:00:00+00:00"}

    def meta(self):
        return self._meta_data

    def build_pricable(self):
        return object()

    def price(self, fut):  # noqa: ARG002
        return self._price

    def yield_to_maturity(self, fut):  # noqa: ARG002
        return 4.95

    def ctd(self):
        return self._basket_pricers[1]

    def gross_basis(self):
        return (0.55, 0.40)

    def bnoc(self, repo_rate=None, settlement=None, delivery=None):  # noqa: ARG002
        return (0.30, 0.20)

    def implied_repo(self, settlement=None, delivery=None):  # noqa: ARG002
        return (5.10, 5.20)

    def _resolve_repo_rate(self, repo_rate=None, curve_name=None):  # noqa: ARG002
        return 4.33 if repo_rate is None else repo_rate

    def _resolve_settlement(self, settlement=None):  # noqa: ARG002
        return datetime.datetime(2026, 3, 26)

    def _resolve_delivery(self, delivery=None):  # noqa: ARG002
        return datetime.datetime(2026, 6, 17)


def _fake_fetch_frame(symbol, ts_dt):
    idx = pd.DatetimeIndex([pd.Timestamp(ts_dt if ts_dt.tzinfo is not None else CHI.localize(ts_dt))])
    return pd.DataFrame({symbol: [112.25]}, index=idx)


def test_get_pricer_uses_core_snapshot_for_canonical_date(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    store.snapshot_rows[("TYM26", datetime.date(2026, 3, 24))] = pd.DataFrame(
        [
            {
                "symbol": "TYM26",
                "timestamp_utc": pd.Timestamp("2026-03-24T19:00:00Z"),
                "trading_date": datetime.date(2026, 3, 24),
                "session_minute": 840,
                "price": 111.75,
            }
        ]
    )
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fetch not expected")))

    out = mdp.get_pricer({"symbols": ["TYM26"], "timestamp": datetime.date(2026, 3, 24), "include_basket": False})

    assert store.snapshot_reads == [("TYM26", datetime.date(2026, 3, 24))]
    assert out["TYM26"]._price == pytest.approx(111.75)


def test_get_pricer_canonical_miss_persists_core_snapshot(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: None)
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda tickers, ts_dt, **kwargs: _fake_fetch_frame(tickers[0], ts_dt))

    out = mdp.get_pricer({"symbols": ["TYM26"], "timestamp": datetime.date(2026, 3, 24), "include_basket": False})

    assert out["TYM26"]._price == pytest.approx(112.25)
    assert store.snapshot_writes
    assert store.snapshot_writes[0][0:2] == ("TYM26", datetime.date(2026, 3, 24))


def test_get_pricer_live_bypasses_core(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: None)
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda tickers, ts_dt, **kwargs: _fake_fetch_frame(tickers[0], ts_dt))

    mdp.get_pricer({"symbols": ["TYM26"], "timestamp": "live", "include_basket": False})

    assert store.snapshot_reads == []
    assert store.snapshot_writes == []


def test_get_pricer_intraday_datetime_bypasses_core(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    ts = CHI.localize(datetime.datetime(2026, 3, 24, 13, 30))
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: None)
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda tickers, ts_dt, **kwargs: _fake_fetch_frame(tickers[0], ts_dt))

    mdp.get_pricer({"symbols": ["TYM26"], "timestamp": ts, "include_basket": False})

    assert store.snapshot_reads == []
    assert store.snapshot_writes == []


def test_get_pricer_force_refresh_bypasses_core_and_overwrites(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    store.snapshot_rows[("TYM26", datetime.date(2026, 3, 24))] = pd.DataFrame([{"symbol": "TYM26", "price": 111.0}])
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: None)
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda tickers, ts_dt, **kwargs: _fake_fetch_frame(tickers[0], ts_dt))

    mdp.get_pricer({"symbols": ["TYM26"], "timestamp": datetime.date(2026, 3, 24), "include_basket": False, "force_refresh": True})

    assert store.snapshot_reads == []
    assert store.snapshot_writes[-1][3] is True


def test_get_basis_report_builds_sorted_dataframe_and_persists(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    settlement_dt = datetime.datetime(2026, 3, 26)
    bonds = [
        _FakeBondPricer("A", "Bond A", 90.0, 4.90, settlement_dt),
        _FakeBondPricer("B", "Bond B", 91.0, 4.80, settlement_dt),
    ]
    future_pricer = _FakeFuturePricer(bonds)

    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "get_pricer", lambda request: {"USM26": future_pricer})
    monkeypatch.setattr(
        mdp,
        "get_delivery_basket",
        lambda **kwargs: {
            "delivery": (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)),
            "basket_pricers": bonds,
            "conversion_factors": [0.80, 0.81],
            "contract_coupon": 6.0,
            "calc_mode": "ust_long",
        },
    )

    df = mdp.get_basis_report(symbol="USM26", timestamp=datetime.date(2026, 3, 24))

    assert list(df.columns) == mdp._basis_report_columns()
    assert df["cusip"].tolist() == ["B", "A"]
    assert df["is_ctd"].tolist() == [True, False]
    assert store.basis_writes


def test_get_basis_report_reuses_core_snapshot(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    cached = pd.DataFrame(
        [
            {
                "cusip": "A",
                "label": "Bond A",
                "clean_price": 90.0,
                "ytm": 4.90,
                "invoice_cf": 0.80,
                "gross_basis": 0.10,
                "bnoc": 0.05,
                "irr": 5.10,
                "is_ctd": True,
                "symbol": "USM26",
                "timestamp_utc": pd.Timestamp("2026-03-24T19:00:00Z"),
                "trading_date": datetime.date(2026, 3, 24),
                "session_minute": 840,
                "futures_price": 112.25,
                "futures_ytm": 4.95,
                "repo_rate": 4.33,
                "settlement_date": datetime.date(2026, 3, 26),
                "delivery_date": datetime.date(2026, 6, 17),
            }
        ]
    )
    store.basis_rows[("USM26", datetime.date(2026, 3, 24))] = cached
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_build_basis_report_frame", lambda **kwargs: (_ for _ in ()).throw(AssertionError("builder not expected")))

    out = mdp.get_basis_report(symbol="USM26", timestamp=datetime.date(2026, 3, 24))

    assert not out.empty
    assert store.basis_reads == [("USM26", datetime.date(2026, 3, 24))]


def test_get_basis_report_custom_repo_bypasses_core(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_build_basis_report_frame", lambda **kwargs: pd.DataFrame(columns=mdp._basis_report_columns()))

    mdp.get_basis_report(symbol="USM26", timestamp=datetime.date(2026, 3, 24), repo_rate=5.0)

    assert store.basis_reads == []
    assert store.basis_writes == []


def test_get_basis_report_non_default_sources_bypass_core(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    store = _FakeStore()
    monkeypatch.setattr(mdp, "_get_ust_future_store", lambda: store)
    monkeypatch.setattr(mdp, "_build_basis_report_frame", lambda **kwargs: pd.DataFrame(columns=mdp._basis_report_columns()))

    mdp.get_basis_report(
        symbol="USM26",
        timestamp=datetime.date(2026, 3, 24),
        basket_source="INTERNAL_CF",
        usts_mdp_source="ALT_SOURCE",
    )

    assert store.basis_reads == []
    assert store.basis_writes == []


def test_get_ctd_reuses_basis_report_frame(monkeypatch):
    mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    basis_df = pd.DataFrame(
        [
            {"cusip": "A", "label": "A", "clean_price": 90.0, "ytm": 4.9, "invoice_cf": 0.80, "gross_basis": 0.20, "bnoc": 0.10, "irr": 5.0, "is_ctd": False},
            {"cusip": "B", "label": "B", "clean_price": 91.0, "ytm": 4.8, "invoice_cf": 0.81, "gross_basis": 0.10, "bnoc": 0.05, "irr": 5.2, "is_ctd": True},
        ]
    )
    monkeypatch.setattr(mdp, "_build_basis_report_frame", lambda **kwargs: basis_df.copy())

    out = mdp.get_ctd(as_of=datetime.date(2026, 3, 24), symbol="USM26")

    assert out["cusip"].tolist() == ["B", "A"]
    assert "invoice_conversion_factor" in out.columns
    assert "gross_basis_rl" in out.columns
    assert out.loc[0, "gross_basis_rl"] == pytest.approx(out.loc[0, "gross_basis"])
