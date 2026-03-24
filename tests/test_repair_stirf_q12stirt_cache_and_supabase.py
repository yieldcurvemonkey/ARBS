import datetime as dt
from pathlib import Path

import pandas as pd

from scripts.repair_stirf_q12stirt_cache_and_supabase import (
    IMM_TENORS,
    LocalChunk,
    RepairConfig,
    SupabaseMismatchSummary,
    _build_local_backfill_command,
    _chunked,
    _compute_supabase_mismatches,
    _extract_last_row_from_day_frame,
)


def _config(tmp_path) -> RepairConfig:
    return RepairConfig(
        curve_name="USD-SOFR-1D-Q12STIRT",
        source="BARCHART_STIRF-RL",
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2026, 3, 20),
        tenors=tuple(IMM_TENORS),
        n_jobs=12,
        local_chunk_business_days=5,
        row_batch_days=25,
        max_retries=3,
        retry_sleep_seconds=1.0,
        verification_rounds=3,
        state_path=tmp_path / "state.json",
        report_path=tmp_path / "report.json",
        log_path=tmp_path / "run.log",
        ts_base_dir=tmp_path / "ts",
        sync_curve_blocks=True,
        skip_local=False,
        skip_supabase=False,
        reset_state=False,
    )


def test_chunked_splits_sequence_in_order():
    assert _chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_build_local_backfill_command_includes_required_flags(tmp_path):
    config = _config(tmp_path)
    chunk = LocalChunk(start_date=dt.date(2025, 4, 1), end_date=dt.date(2025, 4, 7))
    perf_log = tmp_path / "perf.jsonl"

    cmd = _build_local_backfill_command(
        python_executable="python",
        config=config,
        chunk=chunk,
        perf_log_path=perf_log,
    )

    assert cmd[:3] == ["python", str(Path.cwd() / "scripts" / "stirf_curve_service.py"), "backfill"]
    assert "--skip-curve-warm" in cmd
    assert "--no-backfill-local-cache" in cmd
    assert "--disable-l2" in cmd
    assert "--cme-session" in cmd
    assert cmd.count("--tenor") == 12


def test_extract_last_row_from_day_frame_prefers_last_valid_value():
    index = pd.DatetimeIndex(
        [
            dt.datetime(2026, 3, 20, 20, 58),
            dt.datetime(2026, 3, 20, 20, 59),
            dt.datetime(2026, 3, 20, 21, 0),
        ]
    )
    day_df = pd.DataFrame(
        {
            "value": [3.50, None, 3.75],
            "_column_name": ["RATE", "RATE", "RATE"],
        },
        index=index,
    )

    assert _extract_last_row_from_day_frame(day_df, dt.date(2026, 3, 20)) == (
        dt.date(2026, 3, 20),
        "RATE",
        3.75,
    )


def test_compute_supabase_mismatches_detects_missing_and_stale_items():
    local_curve = {dt.date(2025, 1, 2): "abc", dt.date(2025, 1, 3): "def"}
    remote_curve = {dt.date(2025, 1, 2): "abc", dt.date(2025, 1, 3): "stale"}

    local_ts = {
        "SYM1": {dt.date(2025, 1, 2): "sha1", dt.date(2025, 1, 3): "sha2"},
        "SYM2": {dt.date(2025, 1, 2): "sha3"},
    }
    remote_ts = {
        "SYM1": {dt.date(2025, 1, 2): "sha1"},
        "SYM2": {dt.date(2025, 1, 2): "bad"},
    }

    local_rows = {
        "SYM1": {
            dt.date(2025, 1, 2): ("RATE", 1.0),
            dt.date(2025, 1, 3): ("RATE", 2.0),
        },
        "SYM2": {dt.date(2025, 1, 2): ("RATE", 3.0)},
    }
    remote_rows = {
        "SYM1": {dt.date(2025, 1, 2): ("RATE", 1.0)},
        "SYM2": {dt.date(2025, 1, 2): ("RATE", 2.5)},
    }

    mismatch = _compute_supabase_mismatches(
        local_curve_shas=local_curve,
        remote_curve_shas=remote_curve,
        local_ts_shas=local_ts,
        remote_ts_shas=remote_ts,
        local_row_targets=local_rows,
        remote_row_targets=remote_rows,
    )

    assert mismatch == SupabaseMismatchSummary(
        curve_block_days=[dt.date(2025, 1, 3)],
        ts_block_days_by_symbol={
            "SYM1": [dt.date(2025, 1, 3)],
            "SYM2": [dt.date(2025, 1, 2)],
        },
        row_days_by_symbol={
            "SYM1": [dt.date(2025, 1, 3)],
            "SYM2": [dt.date(2025, 1, 2)],
        },
    )
