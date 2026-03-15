import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import pytz

pytest.importorskip("rateslib")
pytest.importorskip("QuantLib")
import QuantLib as ql

from Caching.curve_store import CurveSnapshot, CurveStore
from scripts import export_eris_cache


def _sample_eris_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": [
                "2024-06-14",
                "2024-06-15",
                "2024-07-15",
                "2025-06-14",
            ],
            "DiscountFactor": [1.0, 0.9998, 0.995, 0.95],
        }
    )


def test_curve_snapshot_from_eris_df_roundtrips_rl_and_ql(tmp_path):
    trading_date = datetime.date(2024, 6, 14)
    snap = CurveSnapshot.from_eris_df(_sample_eris_df(), trading_date=trading_date)

    assert snap.source_variant == "ERIS_RL_BASIC"
    assert snap.reference_key == "USD-SOFR-1D"
    assert snap.session_minute == 480
    assert snap.timestamp_utc == pytz.UTC.localize(datetime.datetime(2024, 6, 14, 19, 0))

    store = CurveStore(base_dir=tmp_path)
    store.write_day("USD-SOFR-1D", trading_date, [snap])
    df = store.read_raw_day("USD-SOFR-1D", trading_date)

    assert "source_variant" in df.columns
    assert df.loc[0, "source_variant"] == "ERIS_RL_BASIC"

    rl_curves = store.reconstruct_curves_batch(df, cfg=None)
    assert len(rl_curves) == 1
    rl_curve = next(iter(rl_curves.values()))
    raw_nodes = rl_curve.nodes._nodes if hasattr(rl_curve.nodes, "_nodes") else dict(rl_curve.nodes)
    assert len(raw_nodes) == 4
    assert pytest.approx(float(list(raw_nodes.values())[-1])) == 0.95

    ql_curves = store.reconstruct_ql_curves_batch(df)
    assert len(ql_curves) == 1
    ql_curve = ql_curves[trading_date]
    assert pytest.approx(ql_curve.discount(ql.Date(14, ql.June, 2025))) == 0.95


def test_curve_store_reads_old_and_new_raw_schema_together(tmp_path):
    store = CurveStore(base_dir=tmp_path)
    curve_name = "USD-SOFR-1D"
    old_date = datetime.date(2024, 1, 2)
    new_date = datetime.date(2024, 1, 3)

    old_part_dir = tmp_path / "raw" / f"asset={curve_name}" / f"date={old_date.isoformat()}"
    old_part_dir.mkdir(parents=True)
    old_table = pa.table(
        {
            "timestamp_utc": pa.array(
                [pytz.UTC.localize(datetime.datetime(2024, 1, 2, 20, 0))],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "timestamp_local": pa.array(
                [datetime.datetime(2024, 1, 2, 14, 0)],
                type=pa.timestamp("us"),
            ),
            "trading_date": pa.array([old_date], type=pa.date32()),
            "session_minute": pa.array([480], type=pa.int16()),
            "curve_name": pa.array([curve_name]).dictionary_encode(),
            "cfg_hash": pa.array([""]).dictionary_encode(),
            "reference_key": pa.array([curve_name]).dictionary_encode(),
            "interpolation": pa.array(["log_linear"]).dictionary_encode(),
            "node_dates": pa.array(
                [[old_date, old_date + datetime.timedelta(days=1)]],
                type=pa.list_(pa.date32()),
            ),
            "discount_factors": pa.array([[1.0, 0.999]], type=pa.list_(pa.float64())),
        }
    )
    pq.write_table(old_table, old_part_dir / "legacy.parquet")

    new_snap = CurveSnapshot.from_eris_df(
        _sample_eris_df(),
        trading_date=new_date,
        source_variant="ERIS_RL_BASIC",
    )
    store.write_day(curve_name, new_date, [new_snap])

    old_df = store.read_raw_day(curve_name, old_date)
    assert "source_variant" in old_df.columns
    assert pd.isna(old_df.loc[0, "source_variant"])

    mixed_df = store.read_raw_nodes(curve_name, start=old_date, end=new_date)
    assert [ts.date() for ts in mixed_df["trading_date"]] == [old_date, new_date]
    assert pd.isna(mixed_df.loc[0, "source_variant"])
    assert mixed_df.loc[1, "source_variant"] == "ERIS_RL_BASIC"


def test_export_eris_cache_writes_curve_store(tmp_path, monkeypatch):
    csv_bytes = b"Date,DiscountFactor\n2024-06-14,1.0\n2024-06-15,0.9998\n"
    fake_cache = {
        "EOD_DiscountFactors_SOFR::2024-06-14": {"content": csv_bytes},
        "IGNORED::2024-06-14": {"content": b""},
    }

    monkeypatch.setattr(export_eris_cache, "_open_eris_cache", lambda: fake_cache)

    store = CurveStore(base_dir=tmp_path)
    stats = export_eris_cache.export(store=store)

    assert stats["curves_scanned"] == 1
    assert stats["days_written"] == 1

    df = store.read_raw_day("USD-SOFR-1D", datetime.date(2024, 6, 14))
    assert len(df) == 1
    assert df.loc[0, "source_variant"] == "ERIS_RL_BASIC"
