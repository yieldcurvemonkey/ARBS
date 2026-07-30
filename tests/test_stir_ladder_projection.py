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


def test_contract_grid_sr3_quarterly_imm():
    """SR3 grid = quarterly IMM contracts whose period has not yet STARTED.

    Pinned against the bucket keys the vendor SFRCM1..12 fetch produced at this
    as-of date, so the curve-implied path stays bucket-compatible with the rows
    already persisted by the fetch path.
    """
    import datetime as _dt

    from SDRUtils.stir_flow.ladder import contract_grid

    grid = contract_grid(_dt.date(2026, 7, 10), "SR3")
    assert [g[0] for g in grid] == [
        "SFRU26", "SFRZ26", "SFRH27", "SFRM27", "SFRU27", "SFRZ27",
        "SFRH28", "SFRM28", "SFRU28", "SFRZ28", "SFRH29", "SFRM29",
    ]
    # front contract runs 3rd-Wed Sep 26 -> 3rd-Wed Dec 26; JUN26 already started
    assert grid[0][1] == _dt.datetime(2026, 9, 16)
    assert grid[0][2] == _dt.datetime(2026, 12, 16)
    # rateslib 2.x rejects datetime.date -- these must be datetimes
    assert all(type(d) is _dt.datetime for _b, e, m in grid for d in (e, m))


def test_contract_grid_zq_monthly_includes_current_month():
    """ZQ grid = calendar months starting with the CURRENT one (mid-period front)."""
    import datetime as _dt

    from SDRUtils.stir_flow.ladder import contract_grid

    grid = contract_grid(_dt.date(2026, 7, 10), "ZQ")
    assert [g[0] for g in grid] == [
        "FFN26", "FFQ26", "FFU26", "FFV26", "FFX26", "FFZ26",
        "FFF27", "FFG27", "FFH27", "FFJ27", "FFK27", "FFM27",
    ]
    assert grid[0][1] == _dt.datetime(2026, 7, 1)      # first business day of July
    assert grid[0][2] == _dt.datetime(2026, 8, 3)      # first business day of August


def test_contract_grid_rolls_with_as_of():
    """The grid is as-of dependent: past the Sep IMM, SFRU26 drops out."""
    import datetime as _dt

    from SDRUtils.stir_flow.ladder import contract_grid

    before = [g[0] for g in contract_grid(_dt.date(2026, 9, 15), "SR3")]
    after = [g[0] for g in contract_grid(_dt.date(2026, 9, 17), "SR3")]
    assert before[0] == "SFRU26"
    assert after[0] == "SFRZ26"


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
    # FUTURES and FED_FUNDS are curve-implied now: both must ALWAYS be present
    # when the curve exists -- their absence used to be silently tolerated.
    assert spaces == {"MEETING", "FUTURES", "FED_FUNDS", "SERFF_BASIS"}
    meeting = next(m for m in models if m.space == "MEETING")
    assert len(meeting.label_to_bucket) >= 10          # ~12 upcoming meetings resolved
    assert meeting.label_to_bucket["fomc_1"] == "2026-07-29"
    futures = next(m for m in models if m.space == "FUTURES")
    assert len(futures.label_to_bucket) == 12
    assert futures.label_to_bucket["SFRU26"] == "SFRU26"
    ff = next(m for m in models if m.space == "FED_FUNDS")
    assert len(ff.label_to_bucket) == 12
    assert ff.label_to_bucket["FFN26"] == "FFN26"
    serff = next(m for m in models if m.space == "SERFF_BASIS")
    assert len(serff.label_to_bucket) >= 10  # ~12 SER months


@pytest.mark.network
@pytest.mark.slow
def test_futures_risk_model_no_vendor_fetch():
    """The curve-implied futures model must build with NO STIRFutureMDP handle at all.

    This is the property that kills the availability fallback: it works at every
    timestamp the dense curve exists, including minutes where the vendor returns
    nothing.
    """
    import datetime
    import pytz
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from SDRUtils.stir_flow.ladder import build_futures_risk_model

    NY = pytz.timezone("America/New_York")
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    h = IRSwapsMDP(source="BARCHART_STIRF-RL")._get_curve(
        curve_name="USD-SOFR-1D-Q12xM12STIRT", timestamp=ts)
    for space, front in (("FUTURES", "SFRU26"), ("FED_FUNDS", "FFN26")):
        m = build_futures_risk_model(space, h, ts)
        assert m.space == space
        assert list(m.label_to_bucket)[0] == front
        assert len(m.label_to_bucket) == 12


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
        # on-facility SEF code: makes visibility_class resolve definitely
        # (ON_FACILITY_NON_BLOCK / SEF_BLOCK depending on is_block) instead
        # of falling back to INDETERMINATE, matching this fixture's original
        # pre-audit +1min/+15min expectations exactly.
        platform_identifier="TWSF",
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


@pytest.mark.network
@pytest.mark.slow
@pytest.mark.parametrize("direction,want_sign", [("PAID", -1.0), ("RECEIVED", +1.0)])
def test_project_unit_sign_and_scale_agree_across_every_space(direction, want_sign):
    """EVERY bucket space must agree on the persisted sign, and scale to ~DV01.

    Regression guard for the defect found in the persisted table on 2026-07-29:
    FED_FUNDS was inverted relative to MEETING and FUTURES was internally mixed,
    with |ladder sum| up to 6.7x structure DV01. A single `RL_DELTA_TO_FUTURES_EQ`
    plus the curve-implied futures models fixes both; this pins them.
    """
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
    models = build_risk_models(curve_name, h, ts, stirf, include_basis=False)
    rows, _ = project_unit(_unit(), _direction_row(dealer_direction=direction), models,
                           CurvePricer(mdp=mdp), curve_name, ts)
    dv01 = 50001.0
    sums = {}
    for r in rows:
        sums[r["bucket_space"]] = sums.get(r["bucket_space"], 0.0) + r["delta_dv01"]
    assert set(sums) == {"MEETING", "FUTURES", "FED_FUNDS"}, sums
    for space, total in sums.items():
        assert total * want_sign > 0, f"{space} sign wrong for {direction}: {total}"
        # futures baskets do not partition swap DV01 exactly (basis/convexity),
        # but they must not be off by more than ~10% -- the plan's Task 9 gate.
        assert abs(abs(total) - dv01) < 0.10 * dv01, f"{space} scale off: {total} vs {dv01}"


@pytest.mark.network
@pytest.mark.slow
def test_dates_path_matches_vendor_fetch_path_sr3():
    """SR3 curve-implied ladder must reproduce the vendor SFRCM ladder it replaces.

    Deferred ZQ buckets agree too, but the FRONT monthly bucket does not: the
    fetched pricer carries one extra same-day fixing that was unpublished at the
    decision timestamp, so it prices a shorter un-fixed window. That is a
    look-ahead in the legacy path, not an error here -- see
    SDRUtils.stir_flow.ladder.build_futures_risk_model.
    """
    import datetime
    import pytz
    from MDP.IRSwaps.BARCHART_STIRF.risk import build_delta_risk_ladder
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from SDRUtils.stir_flow.ladder import RiskModel, build_futures_risk_model, project_unit
    from SDRUtils.stir_flow.pricing import CurvePricer

    NY = pytz.timezone("America/New_York")
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    curve_name = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirf = STIRFutureMDP(source="BARCHART_STIRF-RL")
    h = mdp._get_curve(curve_name=curve_name, timestamp=ts)
    pricer = CurvePricer(mdp=mdp)

    qs = [STIRFutureQuery(symbol=f"SFRCM{i}") for i in range(1, 13)]
    fc, fs = build_delta_risk_ladder(qs, h, stirf_mdp_handle=stirf, timestamp=ts)
    fetch = RiskModel("FUTURES", fc, fs, {l: l for l in fs.instrument_labels})
    dates = build_futures_risk_model("FUTURES", h, ts)

    got = {}
    for name, model in (("fetch", fetch), ("dates", dates)):
        rows, _ = project_unit(_unit(), _direction_row(), [model], pricer, curve_name, ts)
        got[name] = sum(r["delta_dv01"] for r in rows)
    rel = abs(got["dates"] - got["fetch"]) / abs(got["fetch"])
    assert rel < 1e-3, f"SR3 dates vs fetch drifted {rel:.4%}: {got}"
