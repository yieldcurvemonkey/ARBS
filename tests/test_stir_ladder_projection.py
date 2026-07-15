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


import datetime

from SDRUtils.stir_flow.ladder import LADDER_COLUMNS, project_unit, RiskModel
from SDRUtils.stir_flow.trade_selection import Unit


def _direction_row(**kw):
    base = dict(
        unit_key="4137861837000000101", trade_type="OUTRIGHT",
        classification_method="NPV_VS_UPFRONT", dealer_direction="PAID",
        rate_index_clean="FED_FUNDS", p_flip=0.2, direction_confidence="LOW",
        curve_suspect_trade=False, structure_dv01=50001.0,
    )
    base.update(kw)
    return base


def _unit():
    legs = pd.DataFrame([dict(
        trade_id="4137861837000000101", package_id=None,
        as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        original_execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        effective_date=datetime.date(2026, 7, 29),
        expiration_date=datetime.date(2026, 9, 16),
        notional=3.7e9, fixed_rate=0.03713, is_block=False, risk=50001.0,
    )])
    return Unit("4137861837000000101", "OUTRIGHT", legs, None, True)


class FakeVmapModel:
    """RiskModel whose solver/curve are ignored by the fake projector below."""


def test_project_unit_rows_and_entry_mark(monkeypatch):
    import SDRUtils.stir_flow.ladder as ladder_mod

    # fake the two pricer-touching internals; test the orchestration + conventions
    monkeypatch.setattr(
        ladder_mod, "_project_onto_model",
        lambda pkgs, model: {"2026-07-29": -50001.0} if model.space == "MEETING"
        else {"SR3U26": -30000.0, "SR3Z26": -20001.0},
    )

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            from SDRUtils.stir_flow.pricing import LegPricing
            return LegPricing(3.717511, 22554.95, 50001.0)

    models = [
        RiskModel("MEETING", None, None, {"fomc_1": "2026-07-29"}),
        RiskModel("FUTURES", None, None, {"SR3U26": "SR3U26", "SR3Z26": "SR3Z26"}),
    ]
    rows, entry = project_unit(
        _unit(), _direction_row(), models, FakePricer(),
        "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        pd.Timestamp("2026-07-10 15:40:00-04:00"),
    )
    by_space = {(r["bucket_space"], r["bucket_key"]): r for r in rows}
    # dealer PAID -> short futures-equivalent -> negative delta
    assert by_space[("MEETING", "2026-07-29")]["delta_dv01"] == -50001.0
    assert set(r["bucket_space"] for r in rows) == {"MEETING", "FUTURES"}
    r0 = rows[0]
    assert r0["visibility_timestamp"] == pd.Timestamp("2026-07-10 19:42:45+00:00")
    assert r0["p_flip"] == 0.2 and r0["is_block"] is False
    assert set(LADDER_COLUMNS) <= set(r0.keys())
    # ENTRY mark: dealer PAID -> dealer npv = +npv_pay = +22,554.95
    assert entry["mark_kind"] == "ENTRY"
    assert abs(entry["npv_usd"] - 22554.95) < 0.01
    assert entry["pnl_since_entry_usd"] == 0.0


def test_project_unit_block_visibility(monkeypatch):
    import SDRUtils.stir_flow.ladder as ladder_mod
    monkeypatch.setattr(ladder_mod, "_project_onto_model", lambda p, m: {"2026-07-29": 1.0})

    class FakePricer:
        def price_leg(self, *a, **k):
            from SDRUtils.stir_flow.pricing import LegPricing
            return LegPricing(3.7, 0.0, 1.0)

    u = _unit()
    u.legs.loc[0, "is_block"] = True
    rows, _ = project_unit(
        u, _direction_row(), [RiskModel("MEETING", None, None, {"fomc_1": "2026-07-29"})],
        FakePricer(), "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        pd.Timestamp("2026-07-10 15:40:00-04:00"),
    )
    assert rows[0]["visibility_timestamp"] == pd.Timestamp("2026-07-10 19:56:45+00:00")


@pytest.mark.network
@pytest.mark.slow
def test_project_unit_golden_sign_and_magnitude():
    """FF FOMC JUL26 outright, dealer PAID, DV01 ~50K (classifier golden print).
    Persisted convention: PAID -> delta_dv01 NEGATIVE, |sum| ~ structure DV01."""
    import datetime
    import pytz
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from SDRUtils.stir_flow.ladder import build_risk_models, project_unit
    from SDRUtils.stir_flow.pricing import CurvePricer

    NY = pytz.timezone("America/New_York")
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    curve_name = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirf = STIRFutureMDP(source="BARCHART_STIRF-RL")
    h = mdp._get_curve(curve_name=curve_name, timestamp=ts)
    models = [m for m in build_risk_models(curve_name, h, ts, stirf, include_basis=False)]
    rows, entry = project_unit(_unit(), _direction_row(), models, CurvePricer(mdp=mdp),
                               curve_name, ts)
    meeting = {r["bucket_key"]: r["delta_dv01"] for r in rows if r["bucket_space"] == "MEETING"}
    total = sum(meeting.values())
    assert total < 0, f"PAID must be negative futures-equivalent, got {total}"
    assert abs(abs(total) - 50001) < 2500          # ~ structure DV01
    assert abs(meeting.get("2026-07-29", 0.0)) > 0.9 * abs(total)  # concentrated in JUL26
    assert abs(entry["npv_usd"] - 22554.95) < 250
    # FUTURES space must also be negative for PAID (same trade, different decomposition)
    futures = {r["bucket_key"]: r["delta_dv01"] for r in rows if r["bucket_space"] == "FUTURES"}
    fut_total = sum(futures.values())
    assert fut_total < 0, f"PAID FUTURES must be negative, got {fut_total}"
