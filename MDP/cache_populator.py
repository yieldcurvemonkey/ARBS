from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib
import json
import os
import sys
import tempfile
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

PERSISTENT_SCOPE = "persistent"
EPHEMERAL_SCOPE = "ephemeral"
BOTH_SCOPE = "both"
SCOPE_CHOICES = (PERSISTENT_SCOPE, EPHEMERAL_SCOPE, BOTH_SCOPE)

STATUS_DRY_RUN = "dry_run"
STATUS_EXECUTED = "executed"
STATUS_SKIPPED_EXISTING = "skipped_existing"
STATUS_SKIPPED_CLAIMED = "skipped_claimed"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED_SCOPE = "unsupported_scope"

DEFAULT_JOB_PRIORITY = 100
DEFAULT_LOCK_TIMEOUT_SECONDS = 120.0
_CHICAGO_TZ = ZoneInfo("America/Chicago")
_UTC_TZ = ZoneInfo("UTC")


@dataclass
class ProbeResult:
    state: Literal["hit", "miss", "unknown"]
    detail: Optional[str] = None


@dataclass
class WarmJobInput:
    job_id: str
    target: str
    source: Optional[str]
    preset: Optional[str]
    params: dict[str, Any]
    request: Optional[dict[str, Any]]
    cache_scope: str = PERSISTENT_SCOPE
    include_dependencies: bool = True
    force_refresh: bool = False
    priority: int = DEFAULT_JOB_PRIORITY


@dataclass
class WarmUnit:
    target: str
    source: str
    request: dict[str, Any]
    identity_request: dict[str, Any]
    requested_scopes: frozenset[str]
    job_ids: tuple[str, ...]
    user_priority: int
    base_priority: int
    force_refresh: bool
    description: str
    batch_key: str
    unit_key: str
    file_lock_scopes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (int(self.user_priority), int(self.base_priority), self.unit_key)


@dataclass
class WarmResult:
    target: str
    source: str
    unit_key: str
    scope: str
    status: str
    description: str
    attempts: int = 0
    duration_seconds: float = 0.0
    detail: Optional[str] = None
    error: Optional[str] = None
    job_ids: tuple[str, ...] = ()
    request: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["job_ids"] = list(self.job_ids)
        return payload


@dataclass
class WarmTargetSpec:
    target: str
    default_source: str
    allowed_sources: tuple[str, ...]
    supported_scopes: frozenset[str]
    request_schema: dict[str, Any]
    preset_docs: dict[str, str]
    param_docs: dict[str, str]
    dependency_doc: str
    examples: tuple[dict[str, Any], ...]
    base_priority: int
    build_units_from_preset: Callable[["WarmTargetSpec", str, str, Mapping[str, Any], WarmJobInput], list[WarmUnit]]
    build_units_from_request: Callable[["WarmTargetSpec", str, Mapping[str, Any], WarmJobInput], list[WarmUnit]]
    expand_dependencies: Callable[["WarmTargetSpec", WarmUnit], list[WarmUnit]]
    probe_persistent: Callable[["WarmTargetSpec", WarmUnit, "RunContext"], ProbeResult]
    execute_persistent: Callable[["WarmTargetSpec", list[WarmUnit], "RunOptions", "RunContext"], list[WarmResult]]
    execute_ephemeral: Optional[Callable[["WarmTargetSpec", list[WarmUnit], "RunOptions", "RunContext"], list[WarmResult]]] = None


@dataclass
class RunOptions:
    dry_run: bool = False
    skip_existing: bool = True
    continue_on_error: bool = True
    max_retries: int = 0
    report_json: Optional[Path] = None
    shard_count: int = 1
    shard_index: int = 0


@dataclass
class _ClaimHandle:
    path: Path
    fd: int

    def release(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


@dataclass
class RunContext:
    resource_cache: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    repo_root: Path = field(default_factory=lambda: Path.cwd().resolve())

    def __post_init__(self) -> None:
        repo_token = hashlib.sha1(str(self.repo_root).encode("utf-8")).hexdigest()[:12]
        base = Path(tempfile.gettempdir()) / "arbs_mdp_cache_populator" / repo_token
        self.claim_root = base / "claims"
        self.file_lock_root = base / "locks"
        self.claim_root.mkdir(parents=True, exist_ok=True)
        self.file_lock_root.mkdir(parents=True, exist_ok=True)

    def cached(self, key: tuple[Any, ...], factory: Callable[[], Any]) -> Any:
        if key not in self.resource_cache:
            self.resource_cache[key] = factory()
        return self.resource_cache[key]


def _json_primitive(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, dt.date):
        return {"__date__": value.isoformat()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json_primitive(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_primitive(v) for v in value]
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(_json_primitive(value), sort_keys=True, separators=(",", ":"))


def _sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _scope_set(cache_scope: str) -> frozenset[str]:
    if cache_scope == PERSISTENT_SCOPE:
        return frozenset({PERSISTENT_SCOPE})
    if cache_scope == EPHEMERAL_SCOPE:
        return frozenset({EPHEMERAL_SCOPE})
    if cache_scope == BOTH_SCOPE:
        return frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE})
    raise ValueError(f"Unsupported cache scope: {cache_scope}")


def _pretty_json(value: Any) -> str:
    return json.dumps(_json_primitive(value), indent=2, sort_keys=True)


def _parse_json_file(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def _parse_json_inline(text: str) -> Any:
    return json.loads(text)


def _parse_iso_datetime(value: str) -> dt.datetime:
    cleaned = value.strip().replace("Z", "+00:00")
    return dt.datetime.fromisoformat(cleaned)


def _coerce_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return _parse_iso_datetime(text).date()
    raise TypeError(f"Unable to coerce date from {value!r}")


def _coerce_datetime(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(0, 0))
    if isinstance(value, str):
        text = value.strip()
        try:
            return _parse_iso_datetime(text)
        except ValueError:
            return dt.datetime.combine(dt.date.fromisoformat(text), dt.time(0, 0))
    raise TypeError(f"Unable to coerce datetime from {value!r}")


def _coerce_timestamp(value: Any) -> dt.date | dt.datetime | Literal["live"]:
    if value == "live":
        return "live"
    if isinstance(value, str) and value.strip().lower() == "live":
        return "live"
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return _parse_iso_datetime(text)
    raise TypeError(f"Unable to coerce timestamp from {value!r}")


def _as_date_for_dependency(value: Any) -> dt.date:
    if value == "live":
        return dt.date.today()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return _coerce_date(value)


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe_strs(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _date_range_business_days(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        raise ValueError(f"Invalid date window: {start} > {end}")
    out: list[dt.date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            out.append(current)
        current += dt.timedelta(days=1)
    return out


def _last_weekday(value: Optional[dt.date] = None) -> dt.date:
    current = value or dt.date.today()
    while current.weekday() >= 5:
        current -= dt.timedelta(days=1)
    return current


def _ensure_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return dict(value)


def _extract_timestamp_list(request: Mapping[str, Any], *, required: bool = True) -> list[dt.date | dt.datetime | Literal["live"]]:
    if "timestamps" in request:
        raw = request["timestamps"]
    elif "timestamp" in request:
        raw = request["timestamp"]
    elif required:
        raise ValueError("Request must include 'timestamp' or 'timestamps'.")
    else:
        return []
    values = [_coerce_timestamp(v) for v in _listify(raw)]
    if not values:
        raise ValueError("Timestamp list is empty.")
    return values


def _extract_date_list(
    request: Mapping[str, Any],
    *,
    singular: str,
    plural: str,
    required: bool = True,
) -> list[dt.date]:
    if plural in request:
        raw = request[plural]
    elif singular in request:
        raw = request[singular]
    elif required:
        raise ValueError(f"Request must include '{singular}' or '{plural}'.")
    else:
        return []
    values = [_coerce_date(v) for v in _listify(raw)]
    if not values:
        raise ValueError(f"{plural} is empty.")
    return values


def _resolve_source(spec: WarmTargetSpec, source: Optional[str]) -> str:
    if source is None:
        return spec.default_source
    lookup = {allowed.upper(): allowed for allowed in spec.allowed_sources}
    candidate = str(source).strip()
    if candidate.upper() not in lookup:
        allowed = ", ".join(spec.allowed_sources)
        raise ValueError(f"Unsupported source '{candidate}' for target '{spec.target}'. Allowed: {allowed}")
    return lookup[candidate.upper()]


def _param_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parse_param_pairs(items: Optional[Sequence[str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"Invalid --param '{item}'. Expected key=value.")
        key, raw_value = item.split("=", 1)
        out[key.strip()] = _param_value(raw_value)
    return out


def _report_summary(results: Sequence[WarmResult]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for result in results:
        counts[result.status] += 1
    return dict(sorted(counts.items()))


def _unit_scope_request(unit: WarmUnit, scope: str) -> bool:
    return scope in unit.requested_scopes


def _claim_filename(scope: str, unit_key: str) -> str:
    return f"{_sha1_text(scope + '|' + unit_key)}.lock"


def _try_claim(root: Path, scope: str, unit_key: str) -> Optional[_ClaimHandle]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / _claim_filename(scope, unit_key)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags)
    except FileExistsError:
        return None
    payload = {"pid": os.getpid(), "scope": scope, "unit_key": unit_key, "created_at": dt.datetime.now(tz=_UTC_TZ).isoformat()}
    os.write(fd, _pretty_json(payload).encode("utf-8"))
    return _ClaimHandle(path=path, fd=fd)


def _wait_for_file_lock(root: Path, scope: str, timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS) -> _ClaimHandle:
    start = time.monotonic()
    while True:
        handle = _try_claim(root, "file-lock", scope)
        if handle is not None:
            return handle
        if time.monotonic() - start > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for file lock '{scope}'.")
        time.sleep(0.25)


@contextlib.contextmanager
def _acquire_file_locks(context: RunContext, scopes: Iterable[str]):
    handles: list[_ClaimHandle] = []
    normalized = sorted({scope for scope in scopes if scope})
    try:
        for scope in normalized:
            handles.append(_wait_for_file_lock(context.file_lock_root, scope))
        yield
    finally:
        for handle in reversed(handles):
            handle.release()


def _load_attr(module_name: str, attr_name: str) -> Any:
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _cache_unit(
    *,
    spec: WarmTargetSpec,
    source: str,
    request: Mapping[str, Any],
    job: WarmJobInput,
    description: str,
    batch_identity: Mapping[str, Any],
    identity_request: Optional[Mapping[str, Any]] = None,
    file_lock_scopes: Optional[Sequence[str]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> WarmUnit:
    identity_payload = {"target": spec.target, "source": source, "request": dict(identity_request or request)}
    batch_payload = {"target": spec.target, "source": source, "batch": dict(batch_identity)}
    unit_key = f"{spec.target}|{_sha1_text(_stable_json(identity_payload))}"
    batch_key = f"{spec.target}|{_sha1_text(_stable_json(batch_payload))}"
    return WarmUnit(
        target=spec.target,
        source=source,
        request=dict(request),
        identity_request=dict(identity_request or request),
        requested_scopes=_scope_set(job.cache_scope),
        job_ids=(job.job_id,),
        user_priority=int(job.priority),
        base_priority=int(spec.base_priority),
        force_refresh=bool(job.force_refresh),
        description=description,
        batch_key=batch_key,
        unit_key=unit_key,
        file_lock_scopes=tuple(file_lock_scopes or ()),
        metadata=dict(metadata or {}),
    )


def _merge_units(existing: WarmUnit, new: WarmUnit) -> WarmUnit:
    existing.requested_scopes = frozenset(set(existing.requested_scopes) | set(new.requested_scopes))
    existing.job_ids = tuple(sorted(set(existing.job_ids) | set(new.job_ids)))
    existing.user_priority = min(existing.user_priority, new.user_priority)
    existing.base_priority = min(existing.base_priority, new.base_priority)
    existing.force_refresh = existing.force_refresh or new.force_refresh
    existing.file_lock_scopes = tuple(sorted(set(existing.file_lock_scopes) | set(new.file_lock_scopes)))
    return existing


def _normalize_requested_units(jobs: Sequence[WarmJobInput], registry: Mapping[str, WarmTargetSpec]) -> list[WarmUnit]:
    seed_units: list[WarmUnit] = []
    for job in jobs:
        if job.target not in registry:
            raise ValueError(f"Unknown target '{job.target}'.")
        spec = registry[job.target]
        source = _resolve_source(spec, job.source)
        if job.preset:
            units = spec.build_units_from_preset(spec, source, job.preset, job.params, job)
        else:
            if job.request is None:
                raise ValueError(f"Job '{job.job_id}' must provide a preset or request.")
            units = spec.build_units_from_request(spec, source, job.request, job)
        seed_units.extend(units)

    merged: OrderedDict[str, WarmUnit] = OrderedDict()
    dependency_queue: deque[tuple[WarmUnit, bool]] = deque()
    include_by_job = {job.job_id: bool(job.include_dependencies) for job in jobs}
    for unit in seed_units:
        should_expand = any(include_by_job.get(job_id, True) for job_id in unit.job_ids)
        dependency_queue.append((unit, should_expand))

    seen_for_deps: set[str] = set()
    while dependency_queue:
        unit, allow_deps = dependency_queue.popleft()
        if unit.unit_key in merged:
            merged[unit.unit_key] = _merge_units(merged[unit.unit_key], unit)
        else:
            merged[unit.unit_key] = unit

        if not allow_deps or PERSISTENT_SCOPE not in unit.requested_scopes:
            continue
        if unit.unit_key in seen_for_deps:
            continue
        seen_for_deps.add(unit.unit_key)
        spec = registry[unit.target]
        for dep in spec.expand_dependencies(spec, unit):
            dependency_queue.append((dep, False))

    return list(merged.values())


def _apply_shard(units: Sequence[WarmUnit], shard_count: int, shard_index: int) -> list[WarmUnit]:
    if shard_count < 1:
        raise ValueError("--shard-count must be >= 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("--shard-index must satisfy 0 <= shard-index < shard-count")
    ordered = sorted(units, key=lambda unit: unit.unit_key)
    return [unit for idx, unit in enumerate(ordered) if idx % shard_count == shard_index]


def _group_by_target_and_batch(units: Sequence[WarmUnit]) -> OrderedDict[str, list[list[WarmUnit]]]:
    grouped: OrderedDict[str, OrderedDict[str, list[WarmUnit]]] = OrderedDict()
    for unit in sorted(units, key=lambda item: item.sort_key):
        grouped.setdefault(unit.target, OrderedDict()).setdefault(unit.batch_key, []).append(unit)
    return OrderedDict((target, list(batch_map.values())) for target, batch_map in grouped.items())


def _result_for_unit(unit: WarmUnit, *, scope: str, status: str, detail: Optional[str] = None, error: Optional[str] = None, attempts: int = 0, duration_seconds: float = 0.0) -> WarmResult:
    return WarmResult(
        target=unit.target,
        source=unit.source,
        unit_key=unit.unit_key,
        scope=scope,
        status=status,
        description=unit.description,
        detail=detail,
        error=error,
        attempts=attempts,
        duration_seconds=duration_seconds,
        job_ids=unit.job_ids,
        request=dict(unit.request),
    )


def _run_executor_with_retries(
    spec: WarmTargetSpec,
    units: list[WarmUnit],
    options: RunOptions,
    context: RunContext,
    *,
    scope: str,
    executor: Callable[[WarmTargetSpec, list[WarmUnit], RunOptions, RunContext], list[WarmResult]],
) -> list[WarmResult]:
    attempts = 0
    start = time.monotonic()
    while True:
        attempts += 1
        try:
            results = executor(spec, units, options, context)
            elapsed = time.monotonic() - start
            for result in results:
                result.scope = scope
                result.attempts = attempts
                result.duration_seconds = elapsed
            return results
        except Exception as exc:  # pragma: no cover
            if attempts > max(0, int(options.max_retries)):
                elapsed = time.monotonic() - start
                return [
                    _result_for_unit(
                        unit,
                        scope=scope,
                        status=STATUS_FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                        attempts=attempts,
                        duration_seconds=elapsed,
                    )
                    for unit in units
                ]


def _execute_scope(
    *,
    scope: str,
    units: Sequence[WarmUnit],
    registry: Mapping[str, WarmTargetSpec],
    options: RunOptions,
    context: RunContext,
) -> list[WarmResult]:
    results: list[WarmResult] = []
    grouped = _group_by_target_and_batch([unit for unit in units if _unit_scope_request(unit, scope)])
    for target, batches in grouped.items():
        spec = registry[target]
        if scope == EPHEMERAL_SCOPE and spec.execute_ephemeral is None:
            results.extend(
                _result_for_unit(unit, scope=scope, status=STATUS_UNSUPPORTED_SCOPE, detail="Target has no ephemeral warm hook.")
                for batch in batches
                for unit in batch
            )
            continue
        for batch_units in batches:
            pending: list[WarmUnit] = []
            claims: list[_ClaimHandle] = []
            try:
                for unit in batch_units:
                    if scope == PERSISTENT_SCOPE and options.skip_existing and not unit.force_refresh:
                        probe = spec.probe_persistent(spec, unit, context)
                        if probe.state == "hit":
                            results.append(_result_for_unit(unit, scope=scope, status=STATUS_SKIPPED_EXISTING, detail=probe.detail))
                            continue
                    claim = _try_claim(context.claim_root, f"{scope}|{unit.target}", unit.unit_key)
                    if claim is None:
                        results.append(_result_for_unit(unit, scope=scope, status=STATUS_SKIPPED_CLAIMED, detail="Another process already claimed this unit."))
                        continue
                    claims.append(claim)
                    pending.append(unit)

                if not pending:
                    continue

                if options.dry_run:
                    results.extend(_result_for_unit(unit, scope=scope, status=STATUS_DRY_RUN) for unit in pending)
                    continue

                executor = spec.execute_persistent if scope == PERSISTENT_SCOPE else spec.execute_ephemeral
                if executor is None:
                    results.extend(
                        _result_for_unit(unit, scope=scope, status=STATUS_UNSUPPORTED_SCOPE, detail="No executor registered for scope.")
                        for unit in pending
                    )
                    continue

                with _acquire_file_locks(context, (lock for unit in pending for lock in unit.file_lock_scopes)):
                    batch_results = _run_executor_with_retries(spec, pending, options, context, scope=scope, executor=executor)
                results.extend(batch_results)

                if not options.continue_on_error and any(result.status == STATUS_FAILED for result in batch_results):
                    return results
            finally:
                for claim in reversed(claims):
                    claim.release()
    return results


def _write_report(path: Path, units: Sequence[WarmUnit], results: Sequence[WarmResult], options: RunOptions) -> None:
    payload = {
        "generated_at": dt.datetime.now(tz=_UTC_TZ).isoformat(),
        "options": {
            "dry_run": options.dry_run,
            "skip_existing": options.skip_existing,
            "continue_on_error": options.continue_on_error,
            "max_retries": options.max_retries,
            "shard_count": options.shard_count,
            "shard_index": options.shard_index,
        },
        "unit_count": len(units),
        "summary": _report_summary(results),
        "results": [result.to_dict() for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pretty_json(payload))


def _run_jobs(jobs: Sequence[WarmJobInput], options: RunOptions, registry: Mapping[str, WarmTargetSpec]) -> list[WarmResult]:
    context = RunContext()
    all_units = _normalize_requested_units(jobs, registry)
    sharded_units = _apply_shard(all_units, options.shard_count, options.shard_index)
    persistent_results = _execute_scope(scope=PERSISTENT_SCOPE, units=sharded_units, registry=registry, options=options, context=context)
    ephemeral_results = _execute_scope(scope=EPHEMERAL_SCOPE, units=sharded_units, registry=registry, options=options, context=context)
    results = persistent_results + ephemeral_results
    if options.report_json:
        _write_report(options.report_json, sharded_units, results, options)
    return results


def _manifest_jobs(payload: Mapping[str, Any]) -> list[WarmJobInput]:
    data = dict(payload)
    version = data.get("version", 1)
    if version not in (1, "1"):
        raise ValueError(f"Unsupported manifest version '{version}'.")
    defaults = _ensure_mapping(data.get("defaults", {}), name="defaults")
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("Manifest must contain a non-empty 'jobs' array.")
    out: list[WarmJobInput] = []
    for index, raw_job in enumerate(jobs):
        job_obj = _ensure_mapping(raw_job, name=f"jobs[{index}]")
        merged = dict(defaults)
        merged.update(job_obj)
        if "target" not in merged:
            raise ValueError(f"Manifest job {index} is missing 'target'.")
        preset = merged.get("preset")
        request = merged.get("request")
        if preset is None and request is None:
            raise ValueError(f"Manifest job '{merged.get('id', index)}' must provide 'preset' or 'request'.")
        if preset is not None and request is not None:
            raise ValueError(f"Manifest job '{merged.get('id', index)}' cannot provide both 'preset' and 'request'.")
        out.append(
            WarmJobInput(
                job_id=str(merged.get("id") or f"job-{index}"),
                target=str(merged["target"]),
                source=merged.get("source"),
                preset=str(preset) if preset is not None else None,
                params=_ensure_mapping(merged.get("params", {}), name=f"jobs[{index}].params"),
                request=_ensure_mapping(request, name=f"jobs[{index}].request") if request is not None else None,
                cache_scope=str(merged.get("cache_scope", PERSISTENT_SCOPE)),
                include_dependencies=bool(merged.get("include_dependencies", True)),
                force_refresh=bool(merged.get("force_refresh", False)),
                priority=int(merged.get("priority", DEFAULT_JOB_PRIORITY)),
            )
        )
    return out


def _quarter_month_code(month: int) -> str:
    if month in (1, 2, 3):
        return "H"
    if month in (4, 5, 6):
        return "M"
    if month in (7, 8, 9):
        return "U"
    return "Z"


def _current_quarter_contract(root: str, as_of: dt.date) -> str:
    code = _quarter_month_code(as_of.month)
    return f"{root.upper()}{code}{as_of.strftime('%y')}"


def _fixedratebonds_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    raw_symbols = req.pop("cusips", None) or req.pop("symbols", None)
    symbols = _dedupe_strs(_listify(raw_symbols))
    if not symbols:
        raise ValueError("Request must include 'cusips' or 'symbols'.")
    timestamps = _extract_timestamp_list(req)
    allowed_keys = {"max_workers"}
    extra = {k: req[k] for k in list(req.keys()) if k in allowed_keys}
    unknown = sorted(set(req.keys()) - allowed_keys - {"timestamp", "timestamps"})
    if unknown:
        raise ValueError(f"Unsupported fixedratebonds.pricer request keys: {', '.join(unknown)}")
    units: list[WarmUnit] = []
    for timestamp in timestamps:
        for symbol in symbols:
            scalar_request = {"cusips": [symbol], "timestamp": timestamp, **extra}
            units.append(
                _cache_unit(
                    spec=spec,
                    source=source,
                    request=scalar_request,
                    job=job,
                    description=f"{spec.target} {symbol} @ {_json_primitive(timestamp)}",
                    batch_identity={"timestamp": timestamp},
                )
            )
    return units


def _fixedratebonds_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    as_of = _last_weekday()
    if preset_key == "smoke":
        request = {"symbols": params.get("symbols") or ["CT2", "CT10"], "timestamp": params.get("timestamp", as_of)}
        return _fixedratebonds_units_from_request(spec, source, request, job)
    if preset_key == "front":
        request = {
            "symbols": params.get("symbols") or ["CT2", "CT3", "CT5", "CT7", "CT10", "CT20", "CT30"],
            "timestamp": params.get("timestamp", as_of),
        }
        return _fixedratebonds_units_from_request(spec, source, request, job)
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _looks_like_cusip(symbol: str) -> bool:
    cleaned = str(symbol).strip().upper()
    return len(cleaned) == 9 and cleaned.isalnum()


def _fixedratebonds_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    symbol = str((unit.request.get("cusips") or [""])[0]).strip()
    timestamp = unit.request["timestamp"]
    ts = _coerce_timestamp(timestamp)
    ts_key = "live" if ts == "live" else ts.isoformat()
    mdp = context.cached(("mdp", "FixedRateBondsMDP", unit.source), lambda: _load_attr("MDP.FixedRateBonds.FixedRateBondsMDP", "FixedRateBondsMDP")(source=unit.source))
    key = f"{ts_key}-{symbol}-{unit.source.upper()}"
    hit = mdp._threadsafe_cache_get(key)
    if hit is not None:
        return ProbeResult("hit", "Diskcache entry already present.")
    if not _looks_like_cusip(symbol):
        return ProbeResult("unknown", "Alias symbols are not deterministically resolved during probing.")
    return ProbeResult("miss")


def _fixedratebonds_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "FixedRateBondsMDP", units[0].source), lambda: _load_attr("MDP.FixedRateBonds.FixedRateBondsMDP", "FixedRateBondsMDP")(source=units[0].source))
    timestamps: OrderedDict[str, tuple[dt.date | dt.datetime | Literal["live"], list[str], dict[str, Any]]] = OrderedDict()
    for unit in units:
        timestamp = unit.request["timestamp"]
        key = _stable_json({"timestamp": timestamp, "extra": {k: v for k, v in unit.request.items() if k not in {"cusips", "timestamp"}}})
        bucket = timestamps.setdefault(key, (timestamp, [], {k: v for k, v in unit.request.items() if k not in {"cusips", "timestamp"}}))
        bucket[1].extend(_dedupe_strs(unit.request.get("cusips") or []))
    for timestamp, symbols, extra in timestamps.values():
        mdp.bulk_get_data(
            timestamps=[timestamp],
            cusips=_dedupe_strs(symbols),
            show_tqdm=False,
            force_refresh=any(unit.force_refresh for unit in units),
            max_workers=int(extra.get("max_workers", 8)),
        )
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _irswap_curve_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    curve_name = str(req.pop("curve_name", "")).strip()
    if not curve_name:
        raise ValueError("Request must include 'curve_name'.")
    timestamps = _extract_timestamp_list(req)
    allowed_keys = {"ignore_cache", "n_jobs"}
    extra = {k: req[k] for k in list(req.keys()) if k in allowed_keys}
    unknown = sorted(set(req.keys()) - allowed_keys - {"timestamp", "timestamps"})
    if unknown:
        raise ValueError(f"Unsupported irswaps.curve request keys: {', '.join(unknown)}")
    units: list[WarmUnit] = []
    for timestamp in timestamps:
        scalar_request = {"curve_name": curve_name, "timestamp": timestamp, **extra}
        units.append(
            _cache_unit(
                spec=spec,
                source=source,
                request=scalar_request,
                job=job,
                description=f"{spec.target} {curve_name} @ {_json_primitive(timestamp)}",
                batch_identity={"curve_name": curve_name, **extra},
            )
        )
    return units


def _irswap_curve_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    curve_names = _dedupe_strs(params.get("curve_names") or ["USD-SOFR-1D"])
    as_of = _last_weekday()
    if preset_key == "smoke":
        return _irswap_curve_units_from_request(spec, source, {"curve_name": curve_names[0], "timestamp": params.get("timestamp", as_of)}, job)
    if preset_key == "front":
        dates = _extract_date_list({"as_ofs": params.get("as_ofs") or [as_of - dt.timedelta(days=offset) for offset in range(5)]}, singular="as_of", plural="as_ofs")
        out: list[WarmUnit] = []
        for curve_name in curve_names:
            out.extend(_irswap_curve_units_from_request(spec, source, {"curve_name": curve_name, "timestamps": dates}, job))
        return out
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _irswap_curve_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    _ = unit
    _ = context
    return ProbeResult("unknown", "Curve caches are source-specific and are not probed reliably.")


def _irswap_curve_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    mdp = context.cached(("mdp", "IRSwapsMDP", units[0].source), lambda: _load_attr("MDP.IRSwaps.IRSwapsMDP", "IRSwapsMDP")(source=units[0].source))
    curve_name = str(units[0].request["curve_name"])
    ignore_cache = bool(units[0].request.get("ignore_cache", False) or any(unit.force_refresh for unit in units))
    n_jobs = int(units[0].request.get("n_jobs", 1))
    timestamps = [unit.request["timestamp"] for unit in units]
    mdp.bulk_get_data({"curve_name": curve_name, "timestamps": timestamps, "ignore_cache": ignore_cache, "n_jobs": n_jobs})
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _irswap_fixings_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    _ = source
    req = dict(request)
    curve_name = str(req.pop("curve_name", "")).strip()
    if not curve_name:
        raise ValueError("Request must include 'curve_name'.")
    as_ofs = _extract_date_list(req, singular="as_of", plural="as_ofs")
    units: list[WarmUnit] = []
    resolve_dir = _load_attr("MDP.IRSwaps.fixings_cache.fixings_cache", "_resolve_fixings_cache_dir")
    for as_of in as_ofs:
        cache_dir = resolve_dir(curve_name)
        units.append(
            _cache_unit(
                spec=spec,
                source=spec.default_source,
                request={"curve_name": curve_name, "as_of": as_of},
                job=job,
                description=f"{spec.target} {curve_name} @ {as_of.isoformat()}",
                batch_identity={"curve_name": curve_name},
                file_lock_scopes=[str(cache_dir / f"{as_of.isoformat()}.csv")],
            )
        )
    return units


def _irswap_fixings_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    _ = source
    preset_key = str(preset).strip().lower()
    curve_names = _dedupe_strs(params.get("curve_names") or ["USD-SOFR-1D"])
    as_of = _last_weekday()
    if preset_key == "smoke":
        return _irswap_fixings_units_from_request(spec, spec.default_source, {"curve_name": curve_names[0], "as_of": params.get("as_of", as_of)}, job)
    if preset_key == "front":
        dates = params.get("as_ofs") or [as_of - dt.timedelta(days=offset) for offset in range(5)]
        out: list[WarmUnit] = []
        for curve_name in curve_names:
            out.extend(_irswap_fixings_units_from_request(spec, spec.default_source, {"curve_name": curve_name, "as_ofs": dates}, job))
        return out
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _irswap_fixings_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    _ = context
    resolve_dir = _load_attr("MDP.IRSwaps.fixings_cache.fixings_cache", "_resolve_fixings_cache_dir")
    last_usbd = _load_attr("MDP.IRSwaps.fixings_cache.fixings_cache", "_last_usbd_before")
    read_cached = _load_attr("MDP.IRSwaps.fixings_cache.fixings_cache", "_read_cached_if_valid")
    curve_name = str(unit.request["curve_name"])
    as_of = _coerce_date(unit.request["as_of"])
    root = resolve_dir(curve_name)
    expected_dt = last_usbd(as_of)
    hit = read_cached(root, curve_name, expected_dt)
    return ProbeResult("hit", "Fixings series already cached.") if hit is not None else ProbeResult("miss")


def _irswap_fixings_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    _ = context
    fetch_fixings = _load_attr("MDP.IRSwaps.fixings_cache.fixings_cache", "_fetch_fixings")
    for unit in units:
        fetch_fixings(unit.request["as_of"], unit.request["curve_name"], force_refresh=bool(unit.force_refresh))
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _swaption_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    curve_name = str(req.pop("curve_name", "")).strip()
    if not curve_name:
        raise ValueError("Request must include 'curve_name'.")
    timestamps = _extract_timestamp_list(req)
    surface_type = str(req.pop("surface_type", "atmf_normal"))
    curve_source = str(req.pop("curve_source", "ERIS_EOD_LIVE-QL_BASIC"))
    extra = dict(req)
    units: list[WarmUnit] = []
    for timestamp in timestamps:
        as_of = _as_date_for_dependency(timestamp)
        scalar_request = {"endpoint": "swaption_snapshot", "curve_name": curve_name, "timestamp": as_of, "surface_type": surface_type, **extra}
        units.append(
            _cache_unit(
                spec=spec,
                source=source,
                request=scalar_request,
                job=job,
                description=f"{spec.target} {curve_name} {surface_type} @ {as_of.isoformat()}",
                batch_identity={"curve_name": curve_name, "surface_type": surface_type, "curve_source": curve_source, **extra},
                metadata={"curve_source": curve_source, "curve_name": curve_name, "surface_type": surface_type},
            )
        )
    return units


def _swaption_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    curve_name = str(params.get("curve_name", "USD-SOFR-1D"))
    as_of = _last_weekday()
    if preset_key == "smoke":
        return _swaption_units_from_request(spec, source, {"curve_name": curve_name, "timestamp": params.get("timestamp", as_of)}, job)
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _swaption_dependency_units(spec: WarmTargetSpec, unit: WarmUnit) -> list[WarmUnit]:
    _ = spec
    if PERSISTENT_SCOPE not in unit.requested_scopes:
        return []
    registry = build_registry()
    curve_spec = registry["irswaps.curve"]
    dep_job = WarmJobInput(
        job_id=unit.job_ids[0],
        target=curve_spec.target,
        source=unit.metadata.get("curve_source"),
        preset=None,
        params={},
        request=None,
        cache_scope=PERSISTENT_SCOPE,
        include_dependencies=False,
        force_refresh=unit.force_refresh,
        priority=unit.user_priority,
    )
    request = {"curve_name": unit.metadata["curve_name"], "timestamp": _coerce_date(unit.request["timestamp"])}
    dep_units = curve_spec.build_units_from_request(curve_spec, _resolve_source(curve_spec, dep_job.source), request, dep_job)
    for dep in dep_units:
        dep.description = f"dependency of {unit.target}: {dep.description}"
    return dep_units


def _swaption_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    curve_source = str(unit.metadata["curve_source"])
    mdp = context.cached(
        ("mdp", "IRSwaptionMDP", unit.source, curve_source),
        lambda: _load_attr("MDP.IRSwaptions.IRSwaptionMDP", "IRSwaptionMDP")(source=unit.source, curve_source=curve_source),
    )
    key = mdp._cache_key(
        curve_name=unit.metadata["curve_name"],
        d=_coerce_date(unit.request["timestamp"]),
        provider=str(unit.source).split("-")[0],
        engine=str(unit.source).split("-")[-1],
        surface_type=str(unit.metadata["surface_type"]),
    )
    mapping = getattr(mdp, mdp._CACHE_ATTR)
    return ProbeResult("hit", "Diskcache entry already present.") if mapping.get(key) is not None else ProbeResult("miss")


def _swaption_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    curve_source = str(units[0].metadata["curve_source"])
    mdp = context.cached(
        ("mdp", "IRSwaptionMDP", units[0].source, curve_source),
        lambda: _load_attr("MDP.IRSwaptions.IRSwaptionMDP", "IRSwaptionMDP")(source=units[0].source, curve_source=curve_source),
    )
    curve_name = str(units[0].metadata["curve_name"])
    surface_type = str(units[0].metadata["surface_type"])
    timestamps = [_coerce_date(unit.request["timestamp"]) for unit in units]
    request = {"endpoint": "swaption_snapshot", "curve_name": curve_name, "timestamps": timestamps, "surface_type": surface_type}
    if any(unit.force_refresh for unit in units):
        request["ignore_cache"] = True
    mdp.get_bulk_data(request)
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _reference_data_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    resolve_cache_dir = _load_attr("MDP.FixedRateBonds.reference_data_cache.ust_reference_data", "_resolve_ust_cache_dir")
    last_govt_day = _load_attr("MDP.FixedRateBonds.reference_data_cache.ust_reference_data", "_last_ust_govt_business_day")
    if source == "fiscaldata":
        as_ofs = [last_govt_day(dt.date.today())]
    else:
        as_ofs = _extract_date_list(req, singular="as_of", plural="as_ofs", required=False) or [_last_weekday()]
    units: list[WarmUnit] = []
    cache_dir = resolve_cache_dir(source)
    for as_of in as_ofs:
        file_path = cache_dir / as_of.strftime("%Y-%m-%d") / f"{as_of.strftime('%Y-%m-%d')}.parquet"
        units.append(
            _cache_unit(
                spec=spec,
                source=source,
                request={"as_of": as_of},
                job=job,
                description=f"{spec.target} @ {as_of.isoformat()}",
                batch_identity={"as_of": as_of},
                file_lock_scopes=[str(file_path)],
            )
        )
    return units


def _reference_data_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    if preset_key != "smoke":
        raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")
    request: dict[str, Any] = {}
    if source == "treasurydirect" and "as_of" in params:
        request["as_of"] = params["as_of"]
    return _reference_data_units_from_request(spec, source, request, job)


def _reference_data_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    _ = context
    resolve_cache_dir = _load_attr("MDP.FixedRateBonds.reference_data_cache.ust_reference_data", "_resolve_ust_cache_dir")
    cache_dir = resolve_cache_dir(unit.source)
    as_of = _coerce_date(unit.request["as_of"])
    file_path = cache_dir / as_of.strftime("%Y-%m-%d") / f"{as_of.strftime('%Y-%m-%d')}.parquet"
    return ProbeResult("hit", "Parquet file already present.") if file_path.exists() else ProbeResult("miss")


def _reference_data_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    _ = context
    update_reference_data = _load_attr("MDP.FixedRateBonds.reference_data_cache.ust_reference_data", "update_reference_data")
    for unit in units:
        source_kwargs = {"as_of": unit.request["as_of"]} if unit.source == "treasurydirect" else {}
        update_reference_data(unit.source, source_kwargs=source_kwargs, force_refresh=bool(unit.force_refresh))
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _stir_futures_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    symbols = _dedupe_strs(req.pop("symbols", None) or req.pop("tickers", None) or [])
    if not symbols:
        raise ValueError("Request must include 'symbols' or 'tickers'.")
    timestamps = _extract_timestamp_list(req)
    allowed_keys = {"cache_full_intraday_fetch", "max_workers"}
    extra = {k: req[k] for k in list(req.keys()) if k in allowed_keys}
    unknown = sorted(set(req.keys()) - allowed_keys - {"timestamp", "timestamps"})
    if unknown:
        raise ValueError(f"Unsupported {spec.target} request keys: {', '.join(unknown)}")
    units: list[WarmUnit] = []
    for timestamp in timestamps:
        for symbol in symbols:
            scalar_request = {"symbols": [symbol], "timestamp": timestamp, **extra}
            units.append(
                _cache_unit(
                    spec=spec,
                    source=source,
                    request=scalar_request,
                    job=job,
                    description=f"{spec.target} {symbol} @ {_json_primitive(timestamp)}",
                    batch_identity={"timestamp": timestamp, "cache_full_intraday_fetch": bool(extra.get('cache_full_intraday_fetch', False))},
                )
            )
    return units


def _stir_futures_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    as_of = _last_weekday()
    if preset_key == "smoke":
        request = {"symbols": params.get("symbols") or ["SR3"], "timestamp": params.get("timestamp", as_of)}
        return _stir_futures_units_from_request(spec, source, request, job)
    if preset_key == "front":
        request = {"symbols": params.get("symbols") or ["SR3", "ZQ"], "timestamps": params.get("timestamps") or [as_of - dt.timedelta(days=offset) for offset in range(3)]}
        return _stir_futures_units_from_request(spec, source, request, job)
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _fxforward_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    symbols = _dedupe_strs(req.pop("symbols", None) or req.pop("tickers", None) or [])
    if not symbols:
        raise ValueError("Request must include 'symbols' or 'tickers'.")
    timestamps = _extract_timestamp_list(req)
    allowed_keys = {"cache_full_intraday_fetch", "curve_profile_key", "window_minutes", "max_workers"}
    extra = {k: req[k] for k in list(req.keys()) if k in allowed_keys}
    unknown = sorted(set(req.keys()) - allowed_keys - {"timestamp", "timestamps"})
    if unknown:
        raise ValueError(f"Unsupported {spec.target} request keys: {', '.join(unknown)}")
    units: list[WarmUnit] = []
    for timestamp in timestamps:
        for symbol in symbols:
            scalar_request = {"symbols": [symbol], "timestamp": timestamp, **extra}
            units.append(
                _cache_unit(
                    spec=spec,
                    source=source,
                    request=scalar_request,
                    job=job,
                    description=f"{spec.target} {symbol} @ {_json_primitive(timestamp)}",
                    batch_identity={"timestamp": timestamp, **extra},
                )
            )
    return units


def _fxforward_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    as_of = _last_weekday()
    if preset_key == "smoke":
        request = {"symbols": params.get("symbols") or ["EURUSD"], "timestamp": params.get("timestamp", as_of)}
        return _fxforward_units_from_request(spec, source, request, job)
    if preset_key == "front":
        request = {"symbols": params.get("symbols") or ["EURUSD", "USDJPY"], "timestamps": params.get("timestamps") or [as_of - dt.timedelta(days=offset) for offset in range(3)]}
        return _fxforward_units_from_request(spec, source, request, job)
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _candidate_stir_cache_keys(source: str, timestamp: Any, symbol: str, *, cache_full_intraday_fetch: bool) -> Optional[list[str]]:
    ts = _coerce_timestamp(timestamp)
    if ts == "live":
        return None
    src = str(source).upper()
    want_eod = isinstance(ts, dt.date) and not isinstance(ts, dt.datetime)
    use_barchart_intraday = src != "WEBULL_STIRF-RL" and not want_eod
    floor_req_to_minute = bool(cache_full_intraday_fetch) and use_barchart_intraday
    ts_dt = pd.Timestamp(ts)
    req_keys: list[str] = []

    def _push(key: str) -> None:
        if key not in req_keys:
            req_keys.append(key)

    def _cache_ts_iso(ts_like: Any, *, floor_minute: bool) -> str:
        ts_obj = pd.Timestamp(ts_like)
        if use_barchart_intraday and ts_obj.tzinfo is not None:
            ts_obj = ts_obj.tz_convert("UTC")
        if floor_minute:
            ts_obj = ts_obj.floor("min")
        return ts_obj.isoformat()

    _push(_cache_ts_iso(ts_dt, floor_minute=floor_req_to_minute))
    if use_barchart_intraday:
        _push(_cache_ts_iso(ts_dt, floor_minute=True))
        _push(_cache_ts_iso(ts_dt, floor_minute=False))
    _push(pd.Timestamp(ts_dt).isoformat())
    _push(pd.Timestamp(ts_dt).floor("min").isoformat())
    return [f"{ts_key}-{symbol}-{src}" for ts_key in req_keys]


def _candidate_fx_cache_keys(source: str, timestamp: Any, symbol: str, *, cache_full_intraday_fetch: bool) -> Optional[list[str]]:
    ts = _coerce_timestamp(timestamp)
    if ts == "live":
        return None
    base_dt = _coerce_datetime(ts)
    if base_dt.tzinfo is not None:
        base_dt = base_dt.astimezone(_UTC_TZ)
    ts_dt = pd.Timestamp(base_dt)
    req_keys: list[str] = []

    def _push(key: str) -> None:
        if key not in req_keys:
            req_keys.append(key)

    def _cache_ts_iso(ts_like: Any, *, floor_minute: bool) -> str:
        ts_obj = pd.Timestamp(ts_like)
        if floor_minute:
            ts_obj = ts_obj.floor("min")
        return ts_obj.isoformat()

    _push(_cache_ts_iso(ts_dt, floor_minute=bool(cache_full_intraday_fetch)))
    _push(_cache_ts_iso(ts_dt, floor_minute=True))
    _push(_cache_ts_iso(ts_dt, floor_minute=False))
    _push(pd.Timestamp(ts_dt).isoformat())
    _push(pd.Timestamp(ts_dt).floor("min").isoformat())
    return [f"{ts_key}-{symbol}-{str(source).upper()}" for ts_key in req_keys]


def _stir_futures_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    symbol = str((unit.request.get("symbols") or [""])[0]).strip().upper()
    keys = _candidate_stir_cache_keys(unit.source, unit.request["timestamp"], symbol, cache_full_intraday_fetch=bool(unit.request.get("cache_full_intraday_fetch", False)))
    if not keys:
        return ProbeResult("unknown", "Live requests are not persistently cached.")
    mdp = context.cached(("mdp", "STIRFutureMDP", unit.source), lambda: _load_attr("MDP.STIRFutures.STIRFutureMDP", "STIRFutureMDP")(source=unit.source))
    for key in keys:
        if mdp._threadsafe_cache_get(key) is not None:
            return ProbeResult("hit", "Diskcache entry already present.")
    return ProbeResult("miss")


def _stir_futures_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "STIRFutureMDP", units[0].source), lambda: _load_attr("MDP.STIRFutures.STIRFutureMDP", "STIRFutureMDP")(source=units[0].source))
    timestamps: OrderedDict[str, tuple[Any, list[str], dict[str, Any]]] = OrderedDict()
    for unit in units:
        timestamp = unit.request["timestamp"]
        extra = {k: v for k, v in unit.request.items() if k not in {"symbols", "tickers", "timestamp"}}
        key = _stable_json({"timestamp": timestamp, "extra": extra})
        bucket = timestamps.setdefault(key, (timestamp, [], extra))
        bucket[1].extend(_dedupe_strs(unit.request.get("symbols") or unit.request.get("tickers") or []))
    for timestamp, symbols, extra in timestamps.values():
        mdp.get_bulk_data(
            {
                "symbols": _dedupe_strs(symbols),
                "timestamps": [timestamp],
                "show_tqdm": False,
                "force_refresh": any(unit.force_refresh for unit in units),
                "cache_full_intraday_fetch": bool(extra.get("cache_full_intraday_fetch", False) or isinstance(timestamp, dt.datetime)),
                "max_workers": int(extra.get("max_workers", 8)),
            }
        )
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _stir_futures_ephemeral(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "STIRFutureMDP", units[0].source), lambda: _load_attr("MDP.STIRFutures.STIRFutureMDP", "STIRFutureMDP")(source=units[0].source))
    if hasattr(mdp, "_get_barchart_fetcher") and "BARCHART" in str(units[0].source).upper():
        mdp._get_barchart_fetcher()
        return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_EXECUTED, detail="Barchart session state warmed.") for unit in units]
    return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_UNSUPPORTED_SCOPE, detail="No ephemeral hook for this source.") for unit in units]


def _fxforward_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    symbol = str((unit.request.get("symbols") or [""])[0]).strip().upper()
    keys = _candidate_fx_cache_keys(unit.source, unit.request["timestamp"], symbol, cache_full_intraday_fetch=bool(unit.request.get("cache_full_intraday_fetch", False)))
    if not keys:
        return ProbeResult("unknown", "Live requests are not persistently cached.")
    mdp = context.cached(("mdp", "FXForwardMDP", unit.source), lambda: _load_attr("MDP.STIRFutures.FXForwardMDP", "FXForwardMDP")(source=unit.source))
    for key in keys:
        if mdp._threadsafe_cache_get(key) is not None:
            return ProbeResult("hit", "Diskcache entry already present.")
    return ProbeResult("miss")


def _fxforward_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "FXForwardMDP", units[0].source), lambda: _load_attr("MDP.STIRFutures.FXForwardMDP", "FXForwardMDP")(source=units[0].source))
    groups: OrderedDict[str, tuple[Any, list[str], dict[str, Any]]] = OrderedDict()
    for unit in units:
        extra = {k: v for k, v in unit.request.items() if k not in {"symbols", "tickers", "timestamp"}}
        timestamp = unit.request["timestamp"]
        key = _stable_json({"timestamp": timestamp, "extra": extra})
        bucket = groups.setdefault(key, (timestamp, [], extra))
        bucket[1].extend(_dedupe_strs(unit.request.get("symbols") or unit.request.get("tickers") or []))
    for timestamp, symbols, extra in groups.values():
        mdp.get_bulk_data(
            {
                "symbols": _dedupe_strs(symbols),
                "timestamps": [timestamp],
                "show_tqdm": False,
                "force_refresh": any(unit.force_refresh for unit in units),
                "cache_full_intraday_fetch": bool(extra.get("cache_full_intraday_fetch", False) or isinstance(timestamp, dt.datetime)),
                "curve_profile_key": extra.get("curve_profile_key"),
                "window_minutes": int(extra.get("window_minutes", 2)),
                "max_workers": int(extra.get("max_workers", 8)),
            }
        )
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _fxforward_ephemeral(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "FXForwardMDP", units[0].source), lambda: _load_attr("MDP.STIRFutures.FXForwardMDP", "FXForwardMDP")(source=units[0].source))
    if hasattr(mdp, "_get_barchart_fetcher"):
        mdp._get_barchart_fetcher()
        return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_EXECUTED, detail="Barchart session state warmed.") for unit in units]
    return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_UNSUPPORTED_SCOPE, detail="No ephemeral hook for this source.") for unit in units]


def _ust_future_pricer_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    symbols = _dedupe_strs(req.pop("symbols", None) or req.pop("tickers", None) or [])
    if not symbols:
        raise ValueError("Request must include 'symbols' or 'tickers'.")
    timestamps = _extract_timestamp_list(req)
    allowed_keys = {"show_tqdm"}
    unknown = sorted(set(req.keys()) - allowed_keys - {"timestamp", "timestamps"})
    if unknown:
        raise ValueError(f"Unsupported {spec.target} request keys: {', '.join(unknown)}")
    units: list[WarmUnit] = []
    for timestamp in timestamps:
        for symbol in symbols:
            scalar_request = {"symbols": [symbol], "timestamp": timestamp, "include_basket": False}
            units.append(
                _cache_unit(
                    spec=spec,
                    source=source,
                    request=scalar_request,
                    job=job,
                    description=f"{spec.target} {symbol} @ {_json_primitive(timestamp)}",
                    batch_identity={"timestamp": timestamp},
                )
            )
    return units


def _ust_future_pricer_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    as_of = _last_weekday()
    if preset_key == "smoke":
        request = {"symbols": params.get("symbols") or ["TY"], "timestamp": params.get("timestamp", as_of)}
        return _ust_future_pricer_units_from_request(spec, source, request, job)
    if preset_key == "front":
        request = {"symbols": params.get("symbols") or ["TU", "FV", "TY", "US"], "timestamps": params.get("timestamps") or [as_of - dt.timedelta(days=offset) for offset in range(3)]}
        return _ust_future_pricer_units_from_request(spec, source, request, job)
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _ust_future_pricer_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    symbol = str((unit.request.get("symbols") or [""])[0]).strip().upper()
    if len(symbol) <= 3:
        return ProbeResult("unknown", "Short root symbols are expanded internally before caching.")
    mdp = context.cached(("mdp", "USTFuturesMDP", unit.source), lambda: _load_attr("MDP.USTFutures.USTFuturesMDP", "USTFuturesMDP")(source=unit.source))
    as_datetime = _load_attr("MDP.USTFutures.USTFuturesMDP", "_as_datetime")
    ts_iso = as_datetime(unit.request["timestamp"]).isoformat()
    key = f"{ts_iso}-{symbol}-{unit.source}"
    return ProbeResult("hit", "Diskcache entry already present.") if mdp._threadsafe_cache_get(key) is not None else ProbeResult("miss")


def _ust_future_pricer_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "USTFuturesMDP", units[0].source), lambda: _load_attr("MDP.USTFutures.USTFuturesMDP", "USTFuturesMDP")(source=units[0].source))
    if any(unit.force_refresh for unit in units):
        for unit in units:
            mdp.get_pricer({"symbols": unit.request["symbols"], "timestamp": unit.request["timestamp"], "show_tqdm": False, "force_refresh": True, "include_basket": False})
    else:
        by_timestamp: OrderedDict[str, tuple[Any, list[str]]] = OrderedDict()
        for unit in units:
            timestamp = unit.request["timestamp"]
            key = _stable_json({"timestamp": timestamp})
            bucket = by_timestamp.setdefault(key, (timestamp, []))
            bucket[1].extend(_dedupe_strs(unit.request.get("symbols") or []))
        for timestamp, symbols in by_timestamp.values():
            mdp.bulk_get_data(timestamps=[timestamp], symbols=_dedupe_strs(symbols), show_tqdm=False)
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _ust_future_pricer_ephemeral(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "USTFuturesMDP", units[0].source), lambda: _load_attr("MDP.USTFutures.USTFuturesMDP", "USTFuturesMDP")(source=units[0].source))
    if hasattr(mdp, "_get_barchart_fetcher") and "BARCHART" in str(units[0].source).upper():
        mdp._get_barchart_fetcher()
        return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_EXECUTED, detail="Barchart session state warmed.") for unit in units]
    return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_UNSUPPORTED_SCOPE, detail="No ephemeral hook for this source.") for unit in units]


def _resolve_delivery_basket_root_and_period(symbol: str, as_of: dt.date) -> tuple[str, int]:
    import rateslib as rl

    if len(symbol) > 3:
        root = symbol[:-3]
        contract_imm_date = rl.get_imm(code=symbol[-3:])
    else:
        root = symbol
        contract_imm_date = rl.next_imm(start=dt.datetime(as_of.year, as_of.month, as_of.day))
    return root, int(contract_imm_date.strftime("%Y%m"))


def _delivery_basket_cusips(symbol: str, as_of: dt.date) -> list[str]:
    read_cme_tcf = _load_attr("MDP.FixedRateBonds.reference_data_cache.cme_tcf", "read_cme_tcf_with_headers")
    root, period = _resolve_delivery_basket_root_and_period(symbol, as_of)
    df = read_cme_tcf(as_of=as_of)
    df = df[(df["ticker"] == root) & (df["period"] == period)].copy()
    if df.empty:
        return []
    return [str(value) for value in df["cusip"].tolist()]


def _ust_delivery_basket_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    req = dict(request)
    symbols = _dedupe_strs(req.pop("symbols", None) or req.pop("tickers", None) or req.pop("symbol", None) or [])
    if not symbols:
        raise ValueError("Request must include 'symbols' or 'symbol'.")
    as_ofs = _extract_date_list(req, singular="as_of", plural="as_ofs")
    basket_source = str(req.pop("basket_source", "RL_CME_TCF"))
    usts_source = str(req.pop("usts_mdp_source", "USTS_FEDINVEST_WSJ_LIVE-RL"))
    if req:
        raise ValueError(f"Unsupported {spec.target} request keys: {', '.join(sorted(req.keys()))}")
    units: list[WarmUnit] = []
    for as_of in as_ofs:
        for symbol in symbols:
            scalar_request = {"symbol": symbol, "as_of": as_of, "source": basket_source, "usts_mdp_source": usts_source}
            identity_request = {"symbol": symbol, "as_of": as_of, "source": basket_source}
            units.append(
                _cache_unit(
                    spec=spec,
                    source=source,
                    request=scalar_request,
                    identity_request=identity_request,
                    job=job,
                    description=f"{spec.target} {symbol} @ {as_of.isoformat()}",
                    batch_identity={"as_of": as_of, "source": basket_source, "usts_mdp_source": usts_source},
                    metadata={"basket_source": basket_source, "usts_mdp_source": usts_source},
                )
            )
    return units


def _ust_delivery_basket_units_from_preset(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    as_of = _last_weekday()
    if preset_key == "smoke":
        return _ust_delivery_basket_units_from_request(spec, source, {"symbols": params.get("symbols") or ["TY"], "as_of": params.get("as_of", as_of)}, job)
    if preset_key == "front":
        return _ust_delivery_basket_units_from_request(
            spec,
            source,
            {"symbols": params.get("symbols") or ["TU", "FV", "TY", "US"], "as_ofs": params.get("as_ofs") or [as_of - dt.timedelta(days=offset) for offset in range(3)]},
            job,
        )
    raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")


def _ust_delivery_basket_dependencies(spec: WarmTargetSpec, unit: WarmUnit) -> list[WarmUnit]:
    _ = spec
    if PERSISTENT_SCOPE not in unit.requested_scopes:
        return []
    registry = build_registry()
    frb_spec = registry["fixedratebonds.pricer"]
    dep_job = WarmJobInput(
        job_id=unit.job_ids[0],
        target=frb_spec.target,
        source=unit.metadata.get("usts_mdp_source"),
        preset=None,
        params={},
        request=None,
        cache_scope=PERSISTENT_SCOPE,
        include_dependencies=False,
        force_refresh=unit.force_refresh,
        priority=unit.user_priority,
    )
    as_of = _coerce_date(unit.request["as_of"])
    timestamp = dt.datetime(as_of.year, as_of.month, as_of.day, 14, 0, tzinfo=_CHICAGO_TZ)
    cusips = _delivery_basket_cusips(str(unit.request["symbol"]), as_of)
    if not cusips:
        return []
    dep_request = {"cusips": cusips, "timestamp": timestamp}
    dep_units = frb_spec.build_units_from_request(frb_spec, _resolve_source(frb_spec, dep_job.source), dep_request, dep_job)
    for dep in dep_units:
        dep.description = f"dependency of {unit.target}: {dep.description}"
    return dep_units


def _ust_delivery_basket_probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
    _ = spec
    mdp = context.cached(("mdp", "USTFuturesMDP", unit.source), lambda: _load_attr("MDP.USTFutures.USTFuturesMDP", "USTFuturesMDP")(source=unit.source))
    key = f"{unit.request['source']}|{unit.request['symbol']}|{_coerce_date(unit.request['as_of']).isoformat()}"
    return ProbeResult("hit", "Basket cache entry already present.") if mdp._threadsafe_basket_cache_get(key) is not None else ProbeResult("miss")


def _ust_delivery_basket_execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
    _ = spec
    _ = options
    mdp = context.cached(("mdp", "USTFuturesMDP", units[0].source), lambda: _load_attr("MDP.USTFutures.USTFuturesMDP", "USTFuturesMDP")(source=units[0].source))
    for unit in units:
        mdp.get_delivery_basket(
            as_of=_coerce_date(unit.request["as_of"]),
            symbol=str(unit.request["symbol"]),
            usts_mdp_source=str(unit.request["usts_mdp_source"]),
            source=str(unit.request["source"]),
            ignore_cache=bool(unit.force_refresh),
        )
    return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]


def _option_scalar_units(
    *,
    spec: WarmTargetSpec,
    source: str,
    job: WarmJobInput,
    endpoint: str,
    request: Mapping[str, Any],
) -> list[WarmUnit]:
    req = dict(request)
    req["endpoint"] = endpoint
    if endpoint == "option_snapshot":
        symbols = _dedupe_strs(req.pop("symbols", None) or req.pop("tickers", None) or [])
        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")
        timestamps = _extract_timestamp_list(req)
        units: list[WarmUnit] = []
        for timestamp in timestamps:
            scalar_request = dict(req)
            scalar_request["endpoint"] = endpoint
            scalar_request["symbols"] = list(symbols)
            scalar_request["timestamp"] = timestamp
            units.append(
                _cache_unit(
                    spec=spec,
                    source=source,
                    request=scalar_request,
                    job=job,
                    description=f"{spec.target} {','.join(symbols)} @ {_json_primitive(timestamp)}",
                    batch_identity={k: v for k, v in scalar_request.items() if k != "timestamp"},
                )
            )
        return units
    if endpoint == "option_timeseries":
        symbols = _dedupe_strs(req.pop("symbols", None) or req.pop("tickers", None) or [])
        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")
        start = _coerce_date(req.pop("start"))
        end = _coerce_date(req.pop("end"))
        scalar_request = dict(req)
        scalar_request["endpoint"] = endpoint
        scalar_request["symbols"] = list(symbols)
        scalar_request["start"] = start
        scalar_request["end"] = end
        return [
            _cache_unit(
                spec=spec,
                source=source,
                request=scalar_request,
                job=job,
                description=f"{spec.target} {','.join(symbols)} [{start.isoformat()}..{end.isoformat()}]",
                batch_identity=scalar_request,
            )
        ]
    if endpoint == "sabr_smile":
        symbol_field = None
        raw_symbols = None
        for candidate in ("globex_symbols", "globex_symbol", "symbols", "symbol", "contract"):
            if candidate in req:
                symbol_field = candidate
                raw_symbols = req.pop(candidate)
                break
        symbols = _dedupe_strs(_listify(raw_symbols))
        if not symbols:
            raise ValueError("Request must include symbol(s) for sabr_smile.")
        as_ofs = _extract_date_list(req, singular="as_of", plural="timestamps")
        units = []
        for as_of in as_ofs:
            for symbol in symbols:
                scalar_request = dict(req)
                scalar_request["endpoint"] = endpoint
                scalar_request["as_of"] = as_of
                if symbol_field in {"globex_symbols", "globex_symbol"}:
                    scalar_request["globex_symbol"] = symbol
                    batch_symbol_field = "globex_symbol"
                else:
                    scalar_request["symbol"] = symbol
                    batch_symbol_field = "symbol"
                units.append(
                    _cache_unit(
                        spec=spec,
                        source=source,
                        request=scalar_request,
                        job=job,
                        description=f"{spec.target} {symbol} @ {as_of.isoformat()}",
                        batch_identity={k: v for k, v in scalar_request.items() if k not in {"as_of", "symbol", "globex_symbol"}},
                        metadata={"symbol_field": batch_symbol_field},
                    )
                )
        return units
    raise NotImplementedError(f"Unsupported endpoint '{endpoint}'.")


def _option_mdp(spec: WarmTargetSpec, context: RunContext, source: str, class_path: str, *, cache_full_intraday_fetch: bool = False):
    _ = spec
    module_name, class_name = class_path.rsplit(".", 1)
    return context.cached(
        ("mdp", class_path, source, bool(cache_full_intraday_fetch)),
        lambda: _load_attr(module_name, class_name)(source=source, cache_full_intraday_fetch=bool(cache_full_intraday_fetch)),
    )


def _option_probe(class_path: str) -> Callable[[WarmTargetSpec, WarmUnit, RunContext], ProbeResult]:
    def _probe(spec: WarmTargetSpec, unit: WarmUnit, context: RunContext) -> ProbeResult:
        mdp = _option_mdp(spec, context, unit.source, class_path, cache_full_intraday_fetch=bool(unit.request.get("cache_full_intraday_fetch", False)))
        cache_key = mdp._build_get_data_cache_key(spec.metadata_endpoint, dict(unit.request))  # type: ignore[attr-defined]
        if not cache_key:
            return ProbeResult("unknown", "Request does not map to a persistent cache key.")
        cached = mdp._threadsafe_cache_get(cache_key)
        return ProbeResult("hit", "Diskcache entry already present.") if cached is not None else ProbeResult("miss")

    return _probe


def _option_execute(class_path: str) -> Callable[[WarmTargetSpec, list[WarmUnit], RunOptions, RunContext], list[WarmResult]]:
    def _execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
        _ = options
        mdp = _option_mdp(spec, context, units[0].source, class_path, cache_full_intraday_fetch=bool(units[0].request.get("cache_full_intraday_fetch", False)))
        endpoint = spec.metadata_endpoint  # type: ignore[attr-defined]
        if endpoint == "option_snapshot":
            timestamps = [unit.request["timestamp"] for unit in units]
            base_request = dict(units[0].request)
            base_request.pop("timestamp", None)
            base_request["timestamps"] = timestamps
            base_request["force_refresh"] = any(unit.force_refresh for unit in units)
            mdp.get_bulk_data(base_request)
        elif endpoint == "option_timeseries":
            for unit in units:
                req = dict(unit.request)
                req["force_refresh"] = bool(unit.force_refresh)
                mdp.get_data(req)
        elif endpoint == "sabr_smile":
            dates = sorted({_coerce_date(unit.request["as_of"]) for unit in units})
            base_request = {k: v for k, v in units[0].request.items() if k not in {"as_of", "symbol", "globex_symbol"}}
            symbol_field = str(units[0].metadata["symbol_field"])
            symbols = [
                str(unit.request["globex_symbol"] if symbol_field == "globex_symbol" else unit.request["symbol"])
                for unit in units
            ]
            if symbol_field == "globex_symbol":
                base_request["globex_symbols"] = _dedupe_strs(symbols)
            else:
                base_request["symbols"] = _dedupe_strs(symbols)
            base_request["timestamps"] = dates
            base_request["force_refresh"] = any(unit.force_refresh for unit in units)
            mdp.get_bulk_data(base_request)
        else:  # pragma: no cover
            raise NotImplementedError(endpoint)
        return [_result_for_unit(unit, scope=PERSISTENT_SCOPE, status=STATUS_EXECUTED) for unit in units]

    return _execute


def _option_ephemeral(class_path: str) -> Callable[[WarmTargetSpec, list[WarmUnit], RunOptions, RunContext], list[WarmResult]]:
    def _execute(spec: WarmTargetSpec, units: list[WarmUnit], options: RunOptions, context: RunContext) -> list[WarmResult]:
        _ = options
        mdp = _option_mdp(spec, context, units[0].source, class_path, cache_full_intraday_fetch=bool(units[0].request.get("cache_full_intraday_fetch", False)))
        if hasattr(mdp, "_get_barchart_fetcher") and "BARCHART" in str(units[0].source).upper():
            required_concurrency = max(1, len(units))
            mdp._get_barchart_fetcher(required_concurrency=required_concurrency)
            return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_EXECUTED, detail="Barchart session state warmed.") for unit in units]
        return [_result_for_unit(unit, scope=EPHEMERAL_SCOPE, status=STATUS_UNSUPPORTED_SCOPE, detail="No ephemeral hook for this source.") for unit in units]

    return _execute


def _stir_option_dependencies(spec: WarmTargetSpec, unit: WarmUnit) -> list[WarmUnit]:
    _ = spec
    if PERSISTENT_SCOPE not in unit.requested_scopes:
        return []
    registry = build_registry()
    curve_spec = registry["irswaps.curve"]
    dep_job = WarmJobInput(
        job_id=unit.job_ids[0],
        target=curve_spec.target,
        source=None,
        preset=None,
        params={},
        request=None,
        cache_scope=PERSISTENT_SCOPE,
        include_dependencies=False,
        force_refresh=unit.force_refresh,
        priority=unit.user_priority,
    )
    curve_name = str(unit.request.get("curve_name", "USD-SOFR-1D-Q12xM12STIRT"))
    endpoint = spec.metadata_endpoint  # type: ignore[attr-defined]
    if endpoint == "option_snapshot":
        dates = [_as_date_for_dependency(unit.request["timestamp"])]
    elif endpoint == "option_timeseries":
        dates = _date_range_business_days(_coerce_date(unit.request["start"]), _coerce_date(unit.request["end"]))
    else:
        dates = [_coerce_date(unit.request["as_of"])]
    dep_units = curve_spec.build_units_from_request(curve_spec, curve_spec.default_source, {"curve_name": curve_name, "timestamps": dates}, dep_job)
    for dep in dep_units:
        dep.description = f"dependency of {unit.target}: {dep.description}"
    return dep_units


def _underlying_ust_future_tokens_from_option_request(request: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    raw_symbols = []
    for field in ("symbols", "tickers"):
        raw_symbols.extend(_listify(request.get(field)))
    if "symbol" in request:
        raw_symbols.extend(_listify(request.get("symbol")))
    if "globex_symbol" in request:
        raw_symbols.extend(_listify(request.get("globex_symbol")))
    if "globex_symbols" in request:
        raw_symbols.extend(_listify(request.get("globex_symbols")))
    for raw in raw_symbols:
        token = str(raw).split("|", 1)[0].strip().upper()
        if not token:
            continue
        if "_" in token:
            out.append(token.split("_", 1)[0])
        else:
            out.append(token)
    return _dedupe_strs(out)


def _ust_option_dependencies(spec: WarmTargetSpec, unit: WarmUnit) -> list[WarmUnit]:
    deps = _stir_option_dependencies(spec, unit)
    if PERSISTENT_SCOPE not in unit.requested_scopes:
        return deps
    registry = build_registry()
    fut_spec = registry["ustfutures.pricer"]
    dep_job = WarmJobInput(
        job_id=unit.job_ids[0],
        target=fut_spec.target,
        source="BARCHART_USTF-RL",
        preset=None,
        params={},
        request=None,
        cache_scope=PERSISTENT_SCOPE,
        include_dependencies=False,
        force_refresh=unit.force_refresh,
        priority=unit.user_priority,
    )
    endpoint = spec.metadata_endpoint  # type: ignore[attr-defined]
    if endpoint == "option_snapshot":
        timestamps: list[Any] = [unit.request["timestamp"]]
    elif endpoint == "option_timeseries":
        timestamps = _date_range_business_days(_coerce_date(unit.request["start"]), _coerce_date(unit.request["end"]))
    else:
        timestamps = [_coerce_date(unit.request["as_of"])]
    symbols = _underlying_ust_future_tokens_from_option_request(unit.request)
    if symbols:
        fut_units = fut_spec.build_units_from_request(fut_spec, dep_job.source or fut_spec.default_source, {"symbols": symbols, "timestamps": timestamps}, dep_job)
        for dep in fut_units:
            dep.description = f"dependency of {unit.target}: {dep.description}"
        deps.extend(fut_units)
    return deps


def _option_units_from_preset_stir(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    endpoint = spec.metadata_endpoint  # type: ignore[attr-defined]
    as_of = _last_weekday()
    if preset_key != "smoke":
        raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")
    if endpoint == "option_snapshot":
        symbol = "SR3_60|25DC" if source == "STIRFO_DUAL-QL" else f"{_current_quarter_contract('SFR', as_of)}|25DC"
        return _option_scalar_units(spec=spec, source=source, job=job, endpoint=endpoint, request={"symbols": params.get("symbols") or [symbol], "timestamp": params.get("timestamp", as_of)})
    if endpoint == "option_timeseries":
        symbol = "SR3_60|25DC" if source == "STIRFO_DUAL-QL" else f"{_current_quarter_contract('SFR', as_of)}|25DC"
        return _option_scalar_units(spec=spec, source=source, job=job, endpoint=endpoint, request={"symbols": params.get("symbols") or [symbol], "start": params.get("start", as_of - dt.timedelta(days=1)), "end": params.get("end", as_of)})
    if endpoint == "sabr_smile":
        if source == "STIRFO_DUAL-QL":
            request = {"globex_symbol": params.get("globex_symbol", "SR3_60"), "as_of": params.get("as_of", as_of)}
        else:
            request = {"symbol": params.get("symbol", _current_quarter_contract("SR3", as_of)), "as_of": params.get("as_of", as_of)}
        return _option_scalar_units(spec=spec, source=source, job=job, endpoint=endpoint, request=request)
    raise NotImplementedError(endpoint)


def _option_units_from_preset_ust(spec: WarmTargetSpec, source: str, preset: str, params: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    preset_key = str(preset).strip().lower()
    endpoint = spec.metadata_endpoint  # type: ignore[attr-defined]
    as_of = _last_weekday()
    if preset_key != "smoke":
        raise ValueError(f"Unsupported preset '{preset}' for target '{spec.target}'.")
    if endpoint == "option_snapshot":
        symbol = "TY_03|25DC" if source == "USTFO_DUAL-QL" else f"{_current_quarter_contract('TY', as_of)}|25DC"
        return _option_scalar_units(spec=spec, source=source, job=job, endpoint=endpoint, request={"symbols": params.get("symbols") or [symbol], "timestamp": params.get("timestamp", as_of)})
    if endpoint == "option_timeseries":
        symbol = "TY_03|25DC" if source == "USTFO_DUAL-QL" else f"{_current_quarter_contract('TY', as_of)}|25DC"
        return _option_scalar_units(spec=spec, source=source, job=job, endpoint=endpoint, request={"symbols": params.get("symbols") or [symbol], "start": params.get("start", as_of - dt.timedelta(days=1)), "end": params.get("end", as_of)})
    if endpoint == "sabr_smile":
        if source == "USTFO_DUAL-QL":
            request = {"globex_symbol": params.get("globex_symbol", "TY_03"), "as_of": params.get("as_of", as_of)}
        else:
            request = {"symbol": params.get("symbol", _current_quarter_contract("TY", as_of)), "as_of": params.get("as_of", as_of)}
        return _option_scalar_units(spec=spec, source=source, job=job, endpoint=endpoint, request=request)
    raise NotImplementedError(endpoint)


def _option_units_from_request(spec: WarmTargetSpec, source: str, request: Mapping[str, Any], job: WarmJobInput) -> list[WarmUnit]:
    return _option_scalar_units(spec=spec, source=source, job=job, endpoint=spec.metadata_endpoint, request=request)  # type: ignore[attr-defined]


def _build_registry_impl() -> OrderedDict[str, WarmTargetSpec]:
    registry: OrderedDict[str, WarmTargetSpec] = OrderedDict()

    def add(spec: WarmTargetSpec) -> None:
        registry[spec.target] = spec

    add(
        WarmTargetSpec(
            target="fixedratebonds.reference_data.fiscaldata",
            default_source="fiscaldata",
            allowed_sources=("fiscaldata",),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": [], "optional": [], "notes": ["Fetches the latest FiscalData UST reference parquet for the current government-bond business day."]},
            preset_docs={"smoke": "Warm the current FiscalData parquet cache."},
            param_docs={},
            dependency_doc="None.",
            examples=({},),
            base_priority=5,
            build_units_from_preset=_reference_data_units_from_preset,
            build_units_from_request=_reference_data_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_reference_data_probe,
            execute_persistent=_reference_data_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="fixedratebonds.reference_data.treasurydirect",
            default_source="treasurydirect",
            allowed_sources=("treasurydirect",),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": [], "optional": ["as_of", "as_ofs"], "notes": ["As-of dates should be ISO dates."]},
            preset_docs={"smoke": "Warm one TreasuryDirect parquet cache date."},
            param_docs={"as_of": "Optional ISO date override for the smoke preset."},
            dependency_doc="None.",
            examples=({"as_of": "2026-03-05"},),
            base_priority=5,
            build_units_from_preset=_reference_data_units_from_preset,
            build_units_from_request=_reference_data_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_reference_data_probe,
            execute_persistent=_reference_data_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="irswaps.fixings",
            default_source="fixings_cache",
            allowed_sources=("fixings_cache",),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": ["curve_name", "as_of|as_ofs"], "optional": [], "notes": ["Backfills CSV fixings caches by curve and as-of date."]},
            preset_docs={"smoke": "Warm one fixings date for one curve.", "front": "Warm recent fixings dates for one or more curves."},
            param_docs={"curve_names": "JSON array of curve names for the front preset.", "as_ofs": "Optional JSON array of ISO dates."},
            dependency_doc="None.",
            examples=({"curve_name": "USD-SOFR-1D", "as_ofs": ["2026-03-02", "2026-03-03"]},),
            base_priority=5,
            build_units_from_preset=_irswap_fixings_units_from_preset,
            build_units_from_request=_irswap_fixings_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_irswap_fixings_probe,
            execute_persistent=_irswap_fixings_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="irswaps.curve",
            default_source="CME_NY_EOD_LIVE-ql_basic",
            allowed_sources=(
                "CME_NY_EOD_LIVE-ql_basic",
                "CME_NY_EOD_LIVE-QL_BASIC",
                "CME_NY_EOD_LIVE-RL_BASIC",
                "ERIS_EOD_LIVE-QL_BASIC",
                "ERIS_EOD_LIVE-QL_BASIC-NOJUMPS",
                "ERIS_EOD_LIVE-RL_BASIC",
                "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS",
                "BARCHART_STIRF-RL",
                "GSQUANT-RL",
                "SDR_INTRADAY-RL",
                "SDR_3PM_EOD-RL",
            ),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": ["curve_name", "timestamp|timestamps"], "optional": ["ignore_cache", "n_jobs"], "notes": ["Timestamps accept ISO dates, ISO datetimes, or 'live'."]},
            preset_docs={"smoke": "Warm one curve/date pair.", "front": "Warm recent dates for one or more curve names."},
            param_docs={"curve_names": "JSON array of curve names.", "as_ofs": "Optional JSON array of ISO dates for the front preset."},
            dependency_doc="None.",
            examples=({"curve_name": "USD-SOFR-1D", "timestamps": ["2026-03-05", "2026-03-06"]},),
            base_priority=10,
            build_units_from_preset=_irswap_curve_units_from_preset,
            build_units_from_request=_irswap_curve_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_irswap_curve_probe,
            execute_persistent=_irswap_curve_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="fixedratebonds.pricer",
            default_source="USTS_FEDINVEST_WSJ_LIVE-QL",
            allowed_sources=(
                "USTS_FEDINVEST_WSJ_LIVE-QL",
                "USTS_FEDINVEST_WSJ_LIVE-RL",
                "USTS_PUBLICDOTCOM_WSJ_LIVE-QL",
                "USTS_TRADINGVIEW_LIVE-RL",
                "USTS_WEBULL_WSJ_LIVE-RL",
            ),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": ["cusips|symbols", "timestamp|timestamps"], "optional": ["max_workers"], "notes": ["Symbols may be raw CUSIPs or supported aliases such as CT2/CT10."]},
            preset_docs={"smoke": "Warm a small on-the-run alias set for one date.", "front": "Warm a broader Treasury alias set for one date."},
            param_docs={"symbols": "JSON array override for preset symbols.", "timestamp": "Optional ISO date/datetime override."},
            dependency_doc="None.",
            examples=({"symbols": ["CT2", "CT10"], "timestamp": "2026-03-05"},),
            base_priority=10,
            build_units_from_preset=_fixedratebonds_units_from_preset,
            build_units_from_request=_fixedratebonds_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_fixedratebonds_probe,
            execute_persistent=_fixedratebonds_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="irswaptions.swaption_snapshot",
            default_source="GSQUANT-QL",
            allowed_sources=("GSQUANT-QL",),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": ["curve_name", "timestamp|timestamps"], "optional": ["surface_type", "curve_source"], "notes": ["Timestamp values are normalized to dates before caching."]},
            preset_docs={"smoke": "Warm one swaption market-context date."},
            param_docs={"curve_name": "Optional curve-name override.", "timestamp": "Optional ISO date override."},
            dependency_doc="Depends on irswaps.curve for the same curve/date pairs.",
            examples=({"curve_name": "USD-SOFR-1D", "timestamp": "2026-03-05", "surface_type": "atmf_normal"},),
            base_priority=30,
            build_units_from_preset=_swaption_units_from_preset,
            build_units_from_request=_swaption_units_from_request,
            expand_dependencies=_swaption_dependency_units,
            probe_persistent=_swaption_probe,
            execute_persistent=_swaption_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="stirfutures.pricer",
            default_source="WEBULL_STIRF-RL",
            allowed_sources=("WEBULL_STIRF-RL", "BARCHART_STIRF-RL", "BARCHART_TOS_LIVE_STIRF-RL", "SCHWAB_APP_STIRF-RL"),
            supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
            request_schema={"required": ["symbols|tickers", "timestamp|timestamps"], "optional": ["cache_full_intraday_fetch", "max_workers"], "notes": ["Use cache_full_intraday_fetch for dense intraday persistence."]},
            preset_docs={"smoke": "Warm a small STIR future set.", "front": "Warm a broader STIR future set across recent dates."},
            param_docs={"symbols": "JSON array override for preset symbols.", "timestamps": "Optional JSON array of ISO dates."},
            dependency_doc="None.",
            examples=({"symbols": ["SR3", "ZQ"], "timestamps": ["2026-03-05", "2026-03-06"]},),
            base_priority=10,
            build_units_from_preset=_stir_futures_units_from_preset,
            build_units_from_request=_stir_futures_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_stir_futures_probe,
            execute_persistent=_stir_futures_execute,
            execute_ephemeral=_stir_futures_ephemeral,
        )
    )
    add(
        WarmTargetSpec(
            target="ustfutures.pricer",
            default_source="BARCHART_USTF-RL",
            allowed_sources=("BARCHART_USTF-RL",),
            supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
            request_schema={"required": ["symbols|tickers", "timestamp|timestamps"], "optional": [], "notes": ["The populator warms the quote cache with include_basket disabled; basket caching is handled by ustfutures.delivery_basket."]},
            preset_docs={"smoke": "Warm one front-root UST future quote cache.", "front": "Warm a standard front-root basket of UST future quotes."},
            param_docs={"symbols": "JSON array override for preset symbols.", "timestamps": "Optional JSON array of ISO dates."},
            dependency_doc="None.",
            examples=({"symbols": ["TY", "US"], "timestamps": ["2026-03-05", "2026-03-06"]},),
            base_priority=10,
            build_units_from_preset=_ust_future_pricer_units_from_preset,
            build_units_from_request=_ust_future_pricer_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_ust_future_pricer_probe,
            execute_persistent=_ust_future_pricer_execute,
            execute_ephemeral=_ust_future_pricer_ephemeral,
        )
    )
    add(
        WarmTargetSpec(
            target="ustfutures.delivery_basket",
            default_source="BARCHART_USTF-RL",
            allowed_sources=("BARCHART_USTF-RL",),
            supported_scopes=frozenset({PERSISTENT_SCOPE}),
            request_schema={"required": ["symbols|symbol", "as_of|as_ofs"], "optional": ["basket_source", "usts_mdp_source"], "notes": ["Backfills the delivery-basket reference cache and hydrates the related bond pricer cache."]},
            preset_docs={"smoke": "Warm one delivery basket.", "front": "Warm recent delivery baskets across standard roots."},
            param_docs={"symbols": "JSON array override for preset futures roots.", "as_ofs": "Optional JSON array of ISO dates."},
            dependency_doc="Depends on fixedratebonds.pricer when basket constituents must be resolved.",
            examples=({"symbols": ["TY"], "as_ofs": ["2026-03-05", "2026-03-06"]},),
            base_priority=10,
            build_units_from_preset=_ust_delivery_basket_units_from_preset,
            build_units_from_request=_ust_delivery_basket_units_from_request,
            expand_dependencies=_ust_delivery_basket_dependencies,
            probe_persistent=_ust_delivery_basket_probe,
            execute_persistent=_ust_delivery_basket_execute,
        )
    )
    add(
        WarmTargetSpec(
            target="fxforward.pricer",
            default_source="BARCHART_FXFWD-RL",
            allowed_sources=("BARCHART_FXFWD-RL", "BARCHART_STIRF-RL"),
            supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
            request_schema={"required": ["symbols|tickers", "timestamp|timestamps"], "optional": ["curve_profile_key", "window_minutes", "cache_full_intraday_fetch", "max_workers"], "notes": ["The persistent cache is keyed by timestamp and symbol."]},
            preset_docs={"smoke": "Warm one FX forward symbol.", "front": "Warm a small FX forward symbol set across recent dates."},
            param_docs={"symbols": "JSON array override for preset symbols.", "timestamps": "Optional JSON array of ISO dates."},
            dependency_doc="None.",
            examples=({"symbols": ["EURUSD", "USDJPY"], "timestamps": ["2026-03-05", "2026-03-06"]},),
            base_priority=10,
            build_units_from_preset=_fxforward_units_from_preset,
            build_units_from_request=_fxforward_units_from_request,
            expand_dependencies=lambda spec, unit: [],
            probe_persistent=_fxforward_probe,
            execute_persistent=_fxforward_execute,
            execute_ephemeral=_fxforward_ephemeral,
        )
    )

    stir_snapshot = WarmTargetSpec(
        target="stirfutureoptions.option_snapshot",
        default_source="STIRFO_DUAL-QL",
        allowed_sources=("STIRFO_DUAL-QL", "BARCHART_STIRFO-QL"),
        supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
        request_schema={"required": ["symbols|tickers", "timestamp|timestamps"], "optional": ["curve_name", "curve_kwargs", "use_ql_calculator", "cache_full_intraday_fetch"], "notes": ["The cache key follows STIRFutureOptionMDP._build_get_data_cache_key('option_snapshot', request)."]},
        preset_docs={"smoke": "Warm one STIR option snapshot cache entry."},
        param_docs={"symbols": "JSON array override for preset symbols.", "timestamp": "Optional ISO date override."},
        dependency_doc="Depends on irswaps.curve for the same effective dates.",
        examples=({"symbols": ["SR3_60|25DC"], "timestamp": "2026-03-05"},),
        base_priority=30,
        build_units_from_preset=_option_units_from_preset_stir,
        build_units_from_request=_option_units_from_request,
        expand_dependencies=_stir_option_dependencies,
        probe_persistent=_option_probe("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
        execute_persistent=_option_execute("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
        execute_ephemeral=_option_ephemeral("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
    )
    stir_snapshot.metadata_endpoint = "option_snapshot"  # type: ignore[attr-defined]
    add(stir_snapshot)

    stir_timeseries = WarmTargetSpec(
        target="stirfutureoptions.option_timeseries",
        default_source="STIRFO_DUAL-QL",
        allowed_sources=("STIRFO_DUAL-QL", "BARCHART_STIRFO-QL"),
        supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
        request_schema={"required": ["symbols|tickers", "start", "end"], "optional": ["curve_name", "curve_kwargs", "use_ql_calculator"], "notes": ["The exact request window is the cache identity."]},
        preset_docs={"smoke": "Warm one short STIR option timeseries window."},
        param_docs={"symbols": "JSON array override for preset symbols.", "start": "Optional ISO date override.", "end": "Optional ISO date override."},
        dependency_doc="Depends on irswaps.curve for all business days in the requested window.",
        examples=({"symbols": ["SR3_60|25DC"], "start": "2026-03-04", "end": "2026-03-05"},),
        base_priority=20,
        build_units_from_preset=_option_units_from_preset_stir,
        build_units_from_request=_option_units_from_request,
        expand_dependencies=_stir_option_dependencies,
        probe_persistent=_option_probe("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
        execute_persistent=_option_execute("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
        execute_ephemeral=_option_ephemeral("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
    )
    stir_timeseries.metadata_endpoint = "option_timeseries"  # type: ignore[attr-defined]
    add(stir_timeseries)

    stir_sabr = WarmTargetSpec(
        target="stirfutureoptions.sabr_smile",
        default_source="STIRFO_DUAL-QL",
        allowed_sources=("STIRFO_DUAL-QL", "BARCHART_STIRFO-QL"),
        supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
        request_schema={"required": ["symbol|symbols|globex_symbol|globex_symbols", "as_of|timestamps"], "optional": ["curve_name", "curve_kwargs", "use_ql_calculator"], "notes": ["Batched execution prefers fetch_bulk_sabr_smile semantics."]},
        preset_docs={"smoke": "Warm one STIR SABR smile cache entry."},
        param_docs={"symbol": "Optional underlying-symbol override.", "globex_symbol": "Optional dual-source override.", "as_of": "Optional ISO date override."},
        dependency_doc="Depends on irswaps.curve for the same SABR as-of dates.",
        examples=({"globex_symbol": "SR3_60", "as_of": "2026-03-05"},),
        base_priority=25,
        build_units_from_preset=_option_units_from_preset_stir,
        build_units_from_request=_option_units_from_request,
        expand_dependencies=_stir_option_dependencies,
        probe_persistent=_option_probe("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
        execute_persistent=_option_execute("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
        execute_ephemeral=_option_ephemeral("MDP.STIRFutures.STIRFutureOptionMDP.STIRFutureOptionMDP"),
    )
    stir_sabr.metadata_endpoint = "sabr_smile"  # type: ignore[attr-defined]
    add(stir_sabr)

    ust_snapshot = WarmTargetSpec(
        target="ustfutureoptions.option_snapshot",
        default_source="BARCHART_USTFO-QL",
        allowed_sources=("USTFO_DUAL-QL", "BARCHART_USTFO-QL"),
        supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
        request_schema={"required": ["symbols|tickers", "timestamp|timestamps"], "optional": ["curve_name", "curve_kwargs", "use_ql_calculator", "cache_full_intraday_fetch"], "notes": ["The cache key follows USTFutureOptionMDP._build_get_data_cache_key('option_snapshot', request)."]},
        preset_docs={"smoke": "Warm one UST option snapshot cache entry."},
        param_docs={"symbols": "JSON array override for preset symbols.", "timestamp": "Optional ISO date override."},
        dependency_doc="Depends on ustfutures.pricer and irswaps.curve for the same effective dates.",
        examples=({"symbols": ["TYM26|25DC"], "timestamp": "2026-03-05"},),
        base_priority=30,
        build_units_from_preset=_option_units_from_preset_ust,
        build_units_from_request=_option_units_from_request,
        expand_dependencies=_ust_option_dependencies,
        probe_persistent=_option_probe("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
        execute_persistent=_option_execute("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
        execute_ephemeral=_option_ephemeral("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
    )
    ust_snapshot.metadata_endpoint = "option_snapshot"  # type: ignore[attr-defined]
    add(ust_snapshot)

    ust_timeseries = WarmTargetSpec(
        target="ustfutureoptions.option_timeseries",
        default_source="BARCHART_USTFO-QL",
        allowed_sources=("USTFO_DUAL-QL", "BARCHART_USTFO-QL"),
        supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
        request_schema={"required": ["symbols|tickers", "start", "end"], "optional": ["curve_name", "curve_kwargs", "use_ql_calculator"], "notes": ["The exact request window is the cache identity."]},
        preset_docs={"smoke": "Warm one short UST option timeseries window."},
        param_docs={"symbols": "JSON array override for preset symbols.", "start": "Optional ISO date override.", "end": "Optional ISO date override."},
        dependency_doc="Depends on ustfutures.pricer and irswaps.curve for all business days in the requested window.",
        examples=({"symbols": ["TYM26|25DC"], "start": "2026-03-04", "end": "2026-03-05"},),
        base_priority=20,
        build_units_from_preset=_option_units_from_preset_ust,
        build_units_from_request=_option_units_from_request,
        expand_dependencies=_ust_option_dependencies,
        probe_persistent=_option_probe("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
        execute_persistent=_option_execute("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
        execute_ephemeral=_option_ephemeral("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
    )
    ust_timeseries.metadata_endpoint = "option_timeseries"  # type: ignore[attr-defined]
    add(ust_timeseries)

    ust_sabr = WarmTargetSpec(
        target="ustfutureoptions.sabr_smile",
        default_source="BARCHART_USTFO-QL",
        allowed_sources=("USTFO_DUAL-QL", "BARCHART_USTFO-QL"),
        supported_scopes=frozenset({PERSISTENT_SCOPE, EPHEMERAL_SCOPE}),
        request_schema={"required": ["symbol|symbols|globex_symbol|globex_symbols", "as_of|timestamps"], "optional": ["curve_name", "curve_kwargs", "use_ql_calculator"], "notes": ["Batched execution prefers fetch_bulk_sabr_smile semantics."]},
        preset_docs={"smoke": "Warm one UST SABR smile cache entry."},
        param_docs={"symbol": "Optional listed-contract override.", "globex_symbol": "Optional dual-source override.", "as_of": "Optional ISO date override."},
        dependency_doc="Depends on ustfutures.pricer and irswaps.curve for the same SABR as-of dates.",
        examples=({"symbol": "TYM26", "as_of": "2026-03-05"},),
        base_priority=25,
        build_units_from_preset=_option_units_from_preset_ust,
        build_units_from_request=_option_units_from_request,
        expand_dependencies=_ust_option_dependencies,
        probe_persistent=_option_probe("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
        execute_persistent=_option_execute("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
        execute_ephemeral=_option_ephemeral("MDP.USTFutures.USTFutureOptionMDP.USTFutureOptionMDP"),
    )
    ust_sabr.metadata_endpoint = "sabr_smile"  # type: ignore[attr-defined]
    add(ust_sabr)

    return registry


_REGISTRY_CACHE: Optional[OrderedDict[str, WarmTargetSpec]] = None


def build_registry() -> OrderedDict[str, WarmTargetSpec]:
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        _REGISTRY_CACHE = _build_registry_impl()
    return _REGISTRY_CACHE


def list_targets(registry: Optional[Mapping[str, WarmTargetSpec]] = None) -> str:
    reg = registry or build_registry()
    lines: list[str] = []
    for target, spec in reg.items():
        scopes = ",".join(sorted(spec.supported_scopes))
        presets = ", ".join(sorted(spec.preset_docs)) or "-"
        allowed = ", ".join(spec.allowed_sources)
        lines.append(f"{target}")
        lines.append(f"  default_source: {spec.default_source}")
        lines.append(f"  allowed_sources: {allowed}")
        lines.append(f"  cache_scopes: {scopes}")
        lines.append(f"  presets: {presets}")
    return "\n".join(lines)


def describe_target(target: str, registry: Optional[Mapping[str, WarmTargetSpec]] = None) -> str:
    reg = registry or build_registry()
    if target not in reg:
        raise ValueError(f"Unknown target '{target}'.")
    spec = reg[target]
    lines = [
        target,
        f"default_source: {spec.default_source}",
        f"allowed_sources: {', '.join(spec.allowed_sources)}",
        f"cache_scopes: {', '.join(sorted(spec.supported_scopes))}",
        "request_schema:",
        _pretty_json(spec.request_schema),
        "presets:",
        _pretty_json(spec.preset_docs),
        "preset_params:",
        _pretty_json(spec.param_docs),
        f"dependencies: {spec.dependency_doc}",
        "examples:",
        _pretty_json(spec.examples),
    ]
    return "\n".join(lines)


def _direct_run_job(args: argparse.Namespace) -> list[WarmJobInput]:
    if not args.target:
        raise ValueError("--target is required unless --manifest is used.")
    selection_flags = [bool(args.preset), bool(args.request_json), bool(args.request_file)]
    if sum(selection_flags) != 1:
        raise ValueError("Exactly one of --preset, --request-json, or --request-file is required for direct runs.")
    request_payload = None
    if args.request_json:
        request_payload = _ensure_mapping(_parse_json_inline(args.request_json), name="request-json")
    elif args.request_file:
        request_payload = _ensure_mapping(_parse_json_file(args.request_file), name="request-file")
    return [
        WarmJobInput(
            job_id="direct",
            target=args.target,
            source=args.source,
            preset=args.preset,
            params=_parse_param_pairs(args.param),
            request=request_payload,
            cache_scope=args.cache_scope,
            include_dependencies=bool(args.include_dependencies),
            force_refresh=bool(args.force_refresh),
            priority=DEFAULT_JOB_PRIORITY,
        )
    ]


def _jobs_from_args(args: argparse.Namespace) -> list[WarmJobInput]:
    if args.manifest:
        payload = _ensure_mapping(_parse_json_file(args.manifest), name="manifest")
        return _manifest_jobs(payload)
    return _direct_run_job(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m MDP.cache_populator", description="Populate persistent and ephemeral MDP caches.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-targets", help="List available cache targets.")

    describe = subparsers.add_parser("describe-target", help="Describe one cache target.")
    describe.add_argument("target")

    run = subparsers.add_parser("run", help="Execute cache warming jobs.")
    run.add_argument("--manifest")
    run.add_argument("--target")
    run.add_argument("--source")
    run.add_argument("--preset")
    run.add_argument("--param", action="append", default=[])
    run.add_argument("--request-json")
    run.add_argument("--request-file")
    run.add_argument("--cache-scope", choices=SCOPE_CHOICES, default=PERSISTENT_SCOPE)
    run.add_argument("--include-dependencies", dest="include_dependencies", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--skip-existing", dest="skip_existing", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--force-refresh", dest="force_refresh", action=argparse.BooleanOptionalAction, default=False)
    run.add_argument("--continue-on-error", dest="continue_on_error", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--max-retries", type=int, default=0)
    run.add_argument("--shard-count", type=int, default=1)
    run.add_argument("--shard-index", type=int, default=0)
    run.add_argument("--report-json")
    run.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    registry = build_registry()

    if args.command == "list-targets":
        print(list_targets(registry))
        return 0

    if args.command == "describe-target":
        print(describe_target(args.target, registry))
        return 0

    jobs = _jobs_from_args(args)
    options = RunOptions(
        dry_run=bool(args.dry_run),
        skip_existing=bool(args.skip_existing),
        continue_on_error=bool(args.continue_on_error),
        max_retries=int(args.max_retries),
        report_json=Path(args.report_json) if args.report_json else None,
        shard_count=int(args.shard_count),
        shard_index=int(args.shard_index),
    )
    results = _run_jobs(jobs, options, registry)
    print(_pretty_json({"summary": _report_summary(results), "results": [result.to_dict() for result in results]}))
    return 1 if any(result.status == STATUS_FAILED for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
