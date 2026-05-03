import datetime
import json
from pathlib import Path

import pandas as pd

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._export import write_snapshot
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


def _trivial_snapshot() -> SFRConvexScreenerSnapshot:
    sd = StructureDef(
        structure_id="A_B_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("A", 1, 96.5, 25), Leg("B", -1, 96.6, 25)),
    )
    metrics = PayoffMetrics(
        mean_bp=1.0, std_bp=5.0, skew=0.5, excess_kurtosis=1.0,
        p_profit=0.55, ev_given_profit_bp=4.0, ev_given_loss_bp=-3.0,
        asymmetry_ratio=1.5,
        percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )
    r = StructureResult(
        structure_def=sd,
        metrics_by_method={"common_state": metrics},
        primary_method="common_state",
        carry_3m_bp=1.0,
        rolldown_bp=0.5,
        iv_rv_diagnostics=(),
        historical=None,
        warnings=(),
        composite_score=0.7,
        rank=1,
    )
    return SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,),
        config_summary={"universe_size": 4},
    )


def test_write_snapshot_emits_csv_and_json(tmp_path: Path):
    snap = _trivial_snapshot()
    paths = write_snapshot(snap, root_dir=tmp_path)
    assert paths["csv"].exists()
    assert paths["json"].exists()

    df = pd.read_csv(paths["csv"])
    assert "structure_id" in df.columns
    payload = json.loads(paths["json"].read_text())
    assert payload["as_of"] == "2026-04-28"
    assert payload["results"][0]["structure_id"] == "A_B_CAL_1"
