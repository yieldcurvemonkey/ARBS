from __future__ import annotations

import datetime
import json
from collections import OrderedDict

import pytest

import MDP.cache_populator as cp


EXPECTED_TARGETS = {
    "fixedratebonds.pricer",
    "fixedratebonds.reference_data.fiscaldata",
    "fixedratebonds.reference_data.treasurydirect",
    "irswaps.curve",
    "irswaps.fixings",
    "irswaptions.swaption_snapshot",
    "stirfutures.pricer",
    "stirfutureoptions.option_snapshot",
    "stirfutureoptions.option_timeseries",
    "stirfutureoptions.sabr_smile",
    "ustfutures.pricer",
    "ustfutures.delivery_basket",
    "ustfutures.basis_report",
    "ustfutureoptions.option_snapshot",
    "ustfutureoptions.option_timeseries",
    "ustfutureoptions.sabr_smile",
    "fxforward.pricer",
}


def _dummy_spec(*, fail: bool = False) -> cp.WarmTargetSpec:
    def _from_request(spec, source, request, job):
        return [
            cp._cache_unit(
                spec=spec,
                source=source,
                request=request,
                job=job,
                description="dummy-unit",
                batch_identity=request,
            )
        ]

    def _execute(spec, units, options, context):
        _ = spec
        _ = options
        _ = context
        if fail:
            raise RuntimeError("boom")
        return [cp._result_for_unit(unit, scope=cp.PERSISTENT_SCOPE, status=cp.STATUS_EXECUTED) for unit in units]

    return cp.WarmTargetSpec(
        target="dummy.target",
        default_source="DUMMY",
        allowed_sources=("DUMMY",),
        supported_scopes=frozenset({cp.PERSISTENT_SCOPE}),
        request_schema={"required": ["value"], "optional": []},
        preset_docs={"smoke": "dummy"},
        param_docs={},
        dependency_doc="None.",
        examples=({"value": 1},),
        base_priority=10,
        build_units_from_preset=lambda spec, source, preset, params, job: _from_request(spec, source, {"value": params.get("value", 1)}, job),
        build_units_from_request=_from_request,
        expand_dependencies=lambda spec, unit: [],
        probe_persistent=lambda spec, unit, context: cp.ProbeResult("miss"),
        execute_persistent=_execute,
    )


def test_registry_contains_expected_targets():
    registry = cp.build_registry()
    assert set(registry) == EXPECTED_TARGETS


def test_describe_target_mentions_dependencies_and_examples():
    described = cp.describe_target("irswaptions.swaption_snapshot")
    assert "Depends on irswaps.curve" in described
    assert "surface_type" in described
    assert "examples" in described


def test_dependency_expansion_for_swaption_adds_curve():
    registry = cp.build_registry()
    job = cp.WarmJobInput(
        job_id="swaption",
        target="irswaptions.swaption_snapshot",
        source=None,
        preset=None,
        params={},
        request={"curve_name": "USD-SOFR-1D", "timestamp": "2026-03-05"},
        cache_scope=cp.PERSISTENT_SCOPE,
        include_dependencies=True,
        force_refresh=False,
        priority=100,
    )
    units = cp._normalize_requested_units([job], registry)
    targets = {unit.target for unit in units}
    assert "irswaptions.swaption_snapshot" in targets
    assert "irswaps.curve" in targets


def test_dependency_expansion_for_ust_basis_report_adds_pricer_and_basket():
    registry = cp.build_registry()
    job = cp.WarmJobInput(
        job_id="ust-basis",
        target="ustfutures.basis_report",
        source=None,
        preset=None,
        params={},
        request={"symbol": "TY", "as_of": "2026-03-05"},
        cache_scope=cp.PERSISTENT_SCOPE,
        include_dependencies=True,
        force_refresh=False,
        priority=100,
    )
    units = cp._normalize_requested_units([job], registry)
    targets = {unit.target for unit in units}
    assert "ustfutures.basis_report" in targets
    assert "ustfutures.pricer" in targets
    assert "ustfutures.delivery_basket" in targets


def test_basis_report_execute_invokes_mdp():
    class _FakeUSTMDP:
        def __init__(self):
            self.calls = []

        def get_basis_report(self, **kwargs):
            self.calls.append(kwargs)
            return None

    mdp = _FakeUSTMDP()

    class _Ctx:
        def cached(self, key, factory):
            return mdp

    unit = cp._cache_unit(
        spec=cp.build_registry()["ustfutures.basis_report"],
        source="BARCHART_USTF-RL",
        request={"symbol": "TY", "as_of": datetime.date(2026, 3, 5), "basket_source": "RL_CME_TCF", "usts_mdp_source": "USTS_FEDINVEST_WSJ_LIVE-RL"},
        job=cp.WarmJobInput(
            job_id="basis-exec",
            target="ustfutures.basis_report",
            source="BARCHART_USTF-RL",
            preset=None,
            params={},
            request=None,
            cache_scope=cp.PERSISTENT_SCOPE,
            include_dependencies=False,
            force_refresh=False,
            priority=10,
        ),
        description="basis-report",
        batch_identity={"as_of": datetime.date(2026, 3, 5)},
    )

    results = cp._ust_basis_report_execute(cp.build_registry()["ustfutures.basis_report"], [unit], cp.RunOptions(), _Ctx())

    assert len(results) == 1
    assert mdp.calls[0]["symbol"] == "TY"


def test_shard_is_deterministic_after_dedupe():
    registry = cp.build_registry()
    job_a = cp.WarmJobInput(
        job_id="a",
        target="fixedratebonds.pricer",
        source=None,
        preset=None,
        params={},
        request={"symbols": ["CT2", "CT10"], "timestamp": "2026-03-05"},
        cache_scope=cp.PERSISTENT_SCOPE,
        include_dependencies=True,
        force_refresh=False,
        priority=100,
    )
    job_b = cp.WarmJobInput(
        job_id="b",
        target="fixedratebonds.pricer",
        source=None,
        preset=None,
        params={},
        request={"symbols": ["CT2", "CT10"], "timestamp": "2026-03-05"},
        cache_scope=cp.PERSISTENT_SCOPE,
        include_dependencies=True,
        force_refresh=False,
        priority=100,
    )
    units = cp._normalize_requested_units([job_a, job_b], registry)
    assert len(units) == 2
    shard0 = [unit.unit_key for unit in cp._apply_shard(units, 2, 0)]
    shard1 = [unit.unit_key for unit in cp._apply_shard(units, 2, 1)]
    assert set(shard0).isdisjoint(shard1)
    assert set(shard0) | set(shard1) == {unit.unit_key for unit in units}


def test_claim_file_skips_duplicate_unit(tmp_path):
    first = cp._try_claim(tmp_path, "scope", "unit")
    assert first is not None
    second = cp._try_claim(tmp_path, "scope", "unit")
    assert second is None
    first.release()
    third = cp._try_claim(tmp_path, "scope", "unit")
    assert third is not None
    third.release()


def test_run_dry_run_writes_report(tmp_path):
    report = tmp_path / "report.json"
    exit_code = cp.main(
        [
            "run",
            "--target",
            "fixedratebonds.pricer",
            "--request-json",
            '{"symbols":["CT2"],"timestamp":"2026-03-05"}',
            "--dry-run",
            "--no-skip-existing",
            "--report-json",
            str(report),
        ]
    )
    assert exit_code == 0
    payload = json.loads(report.read_text())
    assert payload["summary"][cp.STATUS_DRY_RUN] == 1
    assert payload["unit_count"] == 1


def test_failure_report_returns_nonzero(tmp_path, monkeypatch):
    report = tmp_path / "failed.json"
    registry = OrderedDict({"dummy.target": _dummy_spec(fail=True)})
    monkeypatch.setattr(cp, "build_registry", lambda: registry)
    exit_code = cp.main(
        [
            "run",
            "--target",
            "dummy.target",
            "--request-json",
            '{"value":1}',
            "--no-skip-existing",
            "--report-json",
            str(report),
        ]
    )
    assert exit_code == 1
    payload = json.loads(report.read_text())
    assert payload["summary"][cp.STATUS_FAILED] == 1
