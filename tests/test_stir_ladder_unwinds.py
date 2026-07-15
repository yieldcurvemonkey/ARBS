import pandas as pd
from SDRUtils.stir_flow.unwinds import _match_unwinds_frame


def test_match_unwinds_direct_lineage():
    unwind_rows = pd.DataFrame([
        dict(trade_id="U1", lineage_ref="T1", execution_timestamp=pd.Timestamp("2026-07-11 14:00:00+00:00"), is_block=False),
        dict(trade_id="U2", lineage_ref="NOT_CLASSIFIED", execution_timestamp=pd.Timestamp("2026-07-11 15:00:00+00:00"), is_block=False),
    ])
    out = _match_unwinds_frame(unwind_rows, {"T1", "T9"}, lineage_col="lineage_ref")
    assert list(out["unit_key"]) == ["T1"]
    assert out.iloc[0]["unwind_visibility_ts"] == pd.Timestamp("2026-07-11 14:01:00+00:00")


def test_match_unwinds_block_delay_and_empty():
    unwind_rows = pd.DataFrame([
        dict(trade_id="U1", lineage_ref="T1", execution_timestamp=pd.Timestamp("2026-07-11 14:00:00+00:00"), is_block=True),
    ])
    out = _match_unwinds_frame(unwind_rows, {"T1"}, lineage_col="lineage_ref")
    assert out.iloc[0]["unwind_visibility_ts"] == pd.Timestamp("2026-07-11 14:15:00+00:00")
    empty = _match_unwinds_frame(unwind_rows.head(0), {"T1"}, lineage_col="lineage_ref")
    assert list(empty.columns) == ["unit_key", "unwind_visibility_ts"] and empty.empty
