"""One EURIBOR day, fetched parquet in and CurveStore snapshots out.

Hermetic: a real ``CurveStore`` under ``tmp_path``, real rateslib solves, no
Excel and no network. The unit tests either side of this cover the planner and
the single-instant builder; this is the seam between them - the per-day worker
that reads a fetched parquet, resolves a discount curve, solves every minute and
writes a partition. It is the path that has never run end to end, and the one
where a wrong answer looks like a perfectly good curve.

The three discounting regimes are asserted separately, because they are three
different artefacts sharing a name and the only thing that tells them apart
downstream is ``source_variant``.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import citivelo_deep_intraday_warm as D  # noqa: E402
import citivelo_excel_intraday_warm as base  # noqa: E402

DAY = datetime.date(2024, 6, 12)

EURIBOR = {
    "1W": 3.80, "3M": 3.70, "6M": 3.58, "1Y": 3.36, "2Y": 3.05, "3Y": 2.92,
    "5Y": 2.87, "7Y": 2.90, "10Y": 2.98, "15Y": 3.10, "20Y": 3.11, "30Y": 2.99,
}
ESTR = {
    "1W": 3.72, "3M": 3.57, "6M": 3.38, "1Y": 3.09, "2Y": 2.75, "3Y": 2.62,
    "5Y": 2.59, "7Y": 2.63, "10Y": 2.72, "15Y": 2.85, "20Y": 2.86, "30Y": 2.75,
}


def _write_day(path: Path, rates: dict, minutes: int = 6) -> None:
    """A day parquet in the exact shape phase 1 writes: timestamp + tenor columns."""
    stamps = [
        datetime.datetime.combine(DAY, datetime.time(9, 0)) + datetime.timedelta(minutes=i)
        for i in range(minutes)
    ]
    frame = pd.DataFrame(
        {t: [v + 0.0005 * i for i in range(minutes)] for t, v in rates.items()},
        index=pd.DatetimeIndex(stamps),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = [pa.array(frame.index.values.astype("datetime64[us]"))]
    names = ["timestamp"]
    for column in frame.columns:
        arrays.append(pa.array(frame[column].to_numpy(dtype="float64"), type=pa.float64()))
        names.append(str(column))
    pq.write_table(pa.Table.from_arrays(arrays, names=names), path, compression="zstd")


@pytest.fixture
def work_dir(tmp_path):
    _write_day(tmp_path / "EUR-EURIBOR-6M" / f"{DAY.isoformat()}.parquet", EURIBOR)
    _write_day(tmp_path / "EUR-ESTR-1D" / f"{DAY.isoformat()}.parquet", ESTR)
    return tmp_path


@pytest.fixture
def store(tmp_path, monkeypatch):
    from Caching.curve_store import CurveStore

    real = CurveStore(base_dir=tmp_path / "store")
    monkeypatch.setitem(base._WORKER, "store", real)
    return real


def _run(work_dir, disc_name, disc_from, include_short=False):
    par = str(work_dir / "EUR-EURIBOR-6M" / f"{DAY.isoformat()}.parquet")
    disc_path = (
        str(work_dir / disc_name / f"{DAY.isoformat()}.parquet")
        if disc_name and disc_from == "parquet" else ""
    )
    return D._build_ibor_day(
        ("EUR-EURIBOR-6M", DAY, par, disc_name or "", disc_path, disc_from, include_short)
    )


def test_a_dual_curve_day_builds_and_labels_its_discount_curve(work_dir, store):
    out = _run(work_dir, "EUR-ESTR-1D", "parquet")
    assert out["error"] is None, out["error"]
    assert out["n_curves"] == 6 and out["n_skipped"] == 0
    assert out["max_reprice_bp"] < 0.01

    stored = store.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY)
    assert len(stored) == 6
    assert set(stored["source_variant"]) == {f"{base.SOURCE_VARIANT}/EUR-ESTR-1D"}
    assert set(stored["reference_key"]) == {"EUR-EURIBOR-6M"}


def test_a_self_discounted_day_says_so_in_source_variant(work_dir, store):
    """The label is the only thing that separates two artefacts with one name.

    A self-discounted EURIBOR curve and an ESTR-discounted one reproduce the same
    par quotes and differ in their forwards. A reader that cannot tell them apart
    will splice them into one series across the 2017-12 boundary.
    """
    out = _run(work_dir, None, "self")
    assert out["error"] is None and out["n_curves"] == 6
    stored = store.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY)
    assert set(stored["source_variant"]) == {f"{base.SOURCE_VARIANT}/self_discounted"}


def test_the_two_regimes_produce_DIFFERENT_curves(work_dir, store, tmp_path):
    """If these came out identical the discount curve would not be reaching the solve."""
    from Caching.curve_store import CurveStore

    _run(work_dir, "EUR-ESTR-1D", "parquet")
    dual = store.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY).iloc[0].to_dict()

    other = CurveStore(base_dir=tmp_path / "store2")
    base._WORKER["store"] = other
    _run(work_dir, None, "self")
    solo = other.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY).iloc[0].to_dict()

    a = [float(x) for x in dual["discount_factors"]]
    b = [float(x) for x in solo["discount_factors"]]
    assert len(a) == len(b)
    assert max(abs(x - y) for x, y in zip(a, b)) > 1e-9, (
        "the ESTR-discounted and self-discounted projection curves are identical, "
        "so the discount curve is not reaching the solver"
    )


def test_the_sub_1y_quotes_are_excluded_unless_asked_for(work_dir, store, tmp_path):
    """1W/3M/6M are not annual-vs-6M-EURIBOR swaps, whatever eur_irs6 will schedule."""
    from Caching.curve_store import CurveStore

    _run(work_dir, "EUR-ESTR-1D", "parquet")
    without = store.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY).iloc[0].to_dict()

    other = CurveStore(base_dir=tmp_path / "store3")
    base._WORKER["store"] = other
    _run(work_dir, "EUR-ESTR-1D", "parquet", include_short=True)
    with_short = other.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY).iloc[0].to_dict()

    # 12 quotes, 3 of them under a year: 9 nodes plus the curve's own anchor.
    assert len(without["node_dates"]) == 10
    assert len(with_short["node_dates"]) == 13


def test_a_minute_with_too_few_tenors_is_skipped_not_faked(work_dir, store):
    """A thin row must cost its own minute and nothing else."""
    path = work_dir / "EUR-EURIBOR-6M" / f"{DAY.isoformat()}.parquet"
    frame = pd.read_parquet(path).set_index("timestamp")
    frame.iloc[0, 3:] = float("nan")  # leave 1W/3M/6M, which the >=1Y filter drops
    frame = frame.reset_index()
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, compression="zstd")

    out = _run(work_dir, "EUR-ESTR-1D", "parquet")
    assert out["error"] is None
    assert out["n_skipped"] == 1
    assert out["n_curves"] == 5


def test_a_missing_discount_parquet_degrades_rather_than_failing_the_day(work_dir, store):
    """A planned discount curve that was never fetched must not cost the whole day."""
    out = _run(work_dir, "EUR-ESTR-1D", "store")  # no store rows exist for it here
    assert out["error"] is None
    assert out["n_curves"] == 6
    stored = store.read_raw_day(D.asset_name("EUR-EURIBOR-6M"), DAY)
    assert set(stored["source_variant"]) == {f"{base.SOURCE_VARIANT}/self_discounted"}
