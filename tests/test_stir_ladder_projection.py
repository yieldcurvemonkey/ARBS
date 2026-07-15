import pandas as pd
import pytest
from SDRUtils.stir_flow.ladder import extract_bucket_deltas


def _fake_delta_df(rows):
    """Mimic rl.Portfolio.delta(solver) shape: MultiIndex (type, solver_id, label)."""
    idx = pd.MultiIndex.from_tuples(
        [("instruments", "RISK", label) for label, _ in rows],
        names=["type", "solver", "label"],
    )
    return pd.DataFrame({("usd", "usd"): [v for _, v in rows]}, index=idx)


def test_extract_bucket_deltas_maps_and_sums():
    df = _fake_delta_df([("SR3U26", 100.0), ("SR3Z26", -40.0), ("SR3H27", 0.5)])
    label_map = {"SR3U26": "SR3U26", "SR3Z26": "SR3Z26", "SR3H27": "SR3H27"}
    out = extract_bucket_deltas(df, label_map)
    assert out == {"SR3U26": 100.0, "SR3Z26": -40.0, "SR3H27": 0.5}


def test_extract_bucket_deltas_meeting_labels():
    df = _fake_delta_df([("fomc_1", 80.0), ("fomc_2", -20.0), ("ignored", 5.0)])
    label_map = {"fomc_1": "2026-07-29", "fomc_2": "2026-09-16"}
    out = extract_bucket_deltas(df, label_map)
    assert out == {"2026-07-29": 80.0, "2026-09-16": -20.0}


def test_extract_bucket_deltas_basis_prefix():
    df = _fake_delta_df([("SR1V26", 30.0), ("cvx_SR1V26", -7.0)])
    pure = extract_bucket_deltas(df, {"SR1V26": "2026-10"})
    basis = extract_bucket_deltas(df, {"SR1V26": "2026-10"}, basis_prefix="cvx_")
    assert pure == {"2026-10": 30.0}
    assert basis == {"2026-10": -7.0}


def test_extract_bucket_deltas_collapses_duplicate_buckets():
    df = _fake_delta_df([("a", 10.0), ("b", 15.0)])
    out = extract_bucket_deltas(df, {"a": "2026-10-28", "b": "2026-10-28"})
    assert out == {"2026-10-28": 25.0}


@pytest.mark.network
@pytest.mark.slow
def test_build_risk_models_golden():
    import datetime
    import pytz
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from SDRUtils.stir_flow.ladder import build_risk_models

    NY = pytz.timezone("America/New_York")
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirf = STIRFutureMDP(source="BARCHART_STIRF-RL")
    h = mdp._get_curve(curve_name="USD-OIS-Q12xM12STIRT-SERFFX-MIX23", timestamp=ts)
    models = build_risk_models("USD-OIS-Q12xM12STIRT-SERFFX-MIX23", h, ts, stirf, include_basis=True)
    spaces = {m.space for m in models}
    assert spaces == {"MEETING", "FUTURES", "SERFF_BASIS"}
    meeting = next(m for m in models if m.space == "MEETING")
    assert len(meeting.label_to_bucket) >= 10          # ~12 upcoming meetings resolved
    assert meeting.label_to_bucket["fomc_1"] == "2026-07-29"
    futures = next(m for m in models if m.space == "FUTURES")
    assert len(futures.label_to_bucket) == 12
    serff = next(m for m in models if m.space == "SERFF_BASIS")
    assert len(serff.label_to_bucket) >= 10  # ~12 SER months
