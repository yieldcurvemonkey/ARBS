r"""The Excel memory guard, and the two ways it used to be useless.

Both failures this pins were real, found by adversarial review of code written in
this same session:

1. **The guard ran after the connection.** Both the calibration script and the
   warm read Excel's size off ``CitiVelocityExcelClient.excel_memory_mb`` — a
   method on a *connected* client. Connecting is the act the ceiling exists to
   prevent, so the check happened after the damage.
2. **It failed open.** A probe that could not be read returned the same value as
   "no Excel is running", and the gate treated that as "proceed".

Hermetic: the probe is stubbed everywhere except one test that is explicitly
about the real probe's shape, and even that one does not connect to anything.
"""

from __future__ import annotations

import pytest

from MDP.CitiVelocityExcel import memory_guard as MG


# ── the two facts that must stay distinct ────────────────────────────────

def test_no_excel_is_zero_not_none(monkeypatch):
    """A machine with no EXCEL.EXE is the safest state there is, and must proceed."""
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 0.0)
    assert MG.is_safe_to_connect(3800.0) is True
    assert MG.assert_safe_to_connect(3800.0) == 0.0


def test_unreadable_probe_is_none_and_refuses(monkeypatch):
    """A probe that did not complete says nothing about what is running."""
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: None)
    assert MG.is_safe_to_connect(3800.0) is False
    with pytest.raises(MG.ExcelTooLargeError, match="could not read"):
        MG.assert_safe_to_connect(3800.0)


def test_the_two_messages_prescribe_different_fixes(monkeypatch):
    """One needs a human to restart Excel; the other needs the probe repaired."""
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: None)
    with pytest.raises(MG.ExcelTooLargeError) as unreadable:
        MG.assert_safe_to_connect(3800.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 13884.0)
    with pytest.raises(MG.ExcelTooLargeError) as too_big:
        MG.assert_safe_to_connect(3800.0)
    assert "Get-Process" in str(unreadable.value)
    assert "HUMAN restart" in str(too_big.value)
    assert str(unreadable.value) != str(too_big.value)


# ── the ceiling itself ───────────────────────────────────────────────────

@pytest.mark.parametrize("mb,safe", [
    (0.0, True), (500.0, True), (3799.0, True),
    (3800.0, False),        # at the ceiling is NOT below it
    (5249.0, False),        # the size that wedged it on 2026-08-07
    (13884.0, False),       # measured on this machine, 2026-08-08
])
def test_ceiling_is_inclusive_and_refuses_above_it(monkeypatch, mb, safe):
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: mb)
    assert MG.is_safe_to_connect(3800.0) is safe


@pytest.mark.parametrize("mb,limit,raises", [
    (3800.0, 3800.0, True),     # AT the ceiling must refuse: `>=`, not `>`
    (3799.9, 3800.0, False),
    (5249.0, 5249.0, True),     # the exact recorded wedge size, at its own ceiling
])
def test_assert_treats_the_ceiling_as_inclusive(monkeypatch, mb, limit, raises):
    """`>` instead of `>=` lets a process sitting exactly on the limit through.

    Pinned separately from `is_safe_to_connect` because that function has its own
    comparison — a mutation of one is invisible to a test of the other.
    """
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: mb)
    if raises:
        with pytest.raises(MG.ExcelTooLargeError):
            MG.assert_safe_to_connect(limit)
    else:
        assert MG.assert_safe_to_connect(limit) == mb


def test_the_recorded_wedge_size_is_refused_by_the_default_ceiling(monkeypatch):
    """A default that would have permitted the known incident is not a ceiling."""
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 5249.0)
    assert MG.DEFAULT_CEILING_MB < 5249.0
    assert MG.is_safe_to_connect() is False


def test_the_error_reports_the_measured_size(monkeypatch):
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 13884.0)
    with pytest.raises(MG.ExcelTooLargeError, match="13884 MB"):
        MG.assert_safe_to_connect(3800.0, what="a warm")


def test_what_names_the_caller_in_the_message(monkeypatch):
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 99999.0)
    with pytest.raises(MG.ExcelTooLargeError, match="the nightly bond warm"):
        MG.assert_safe_to_connect(3800.0, what="the nightly bond warm")


# ── the probe must not connect ───────────────────────────────────────────

def test_the_probe_does_not_import_or_touch_com():
    """The whole point: reading the size must not be the thing that opens Excel."""
    import ast
    import inspect

    src = inspect.getsource(MG)
    assert "Get-Process" in src, "the probe should ask Windows, not Excel"

    # Strip every docstring: the prose deliberately NAMES the connected client's
    # method to explain why it is not used, so a plain substring search over the
    # source would flag the explanation as the offence.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    code = ast.unparse(tree)

    for forbidden in ("win32com", "Dispatch", "CitiVelocityExcelClient", "CitiVeloQuotes"):
        assert forbidden not in code, (
            f"{forbidden!r} appears in executable code: the probe must not reach for "
            "anything that connects — that is the act the guard exists to prevent"
        )


def test_probe_returns_none_rather_than_raising_when_powershell_fails(monkeypatch):
    """An exception escaping the probe would crash the caller instead of gating it."""
    def _boom(*a, **k):
        raise OSError("powershell not found")

    monkeypatch.setattr(MG.subprocess, "run", _boom)
    assert MG.excel_memory_mb() is None


def test_probe_returns_none_on_a_nonzero_exit(monkeypatch):
    class _R:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(MG.subprocess, "run", lambda *a, **k: _R())
    assert MG.excel_memory_mb() is None


def test_probe_returns_none_on_unparseable_output(monkeypatch):
    class _R:
        returncode = 0
        stdout = "Access is denied."

    monkeypatch.setattr(MG.subprocess, "run", lambda *a, **k: _R())
    assert MG.excel_memory_mb() is None


def test_probe_maps_the_no_process_sentinel_to_zero(monkeypatch):
    class _R:
        returncode = 0
        stdout = "NONE\n"

    monkeypatch.setattr(MG.subprocess, "run", lambda *a, **k: _R())
    assert MG.excel_memory_mb() == 0.0


def test_probe_converts_bytes_to_decimal_megabytes(monkeypatch):
    class _R:
        returncode = 0
        stdout = "13864734720\n"      # the real reading on 2026-08-08

    monkeypatch.setattr(MG.subprocess, "run", lambda *a, **k: _R())
    assert MG.excel_memory_mb() == pytest.approx(13864.73472)


# ── the callers must gate BEFORE they connect ────────────────────────────

def _first_call_line(tree, name):
    """Line of the first CALL to ``name``. Imports are not calls, which matters:
    matching the bare name would find the `from ... import assert_safe_to_connect`
    line at the top of the file and make the ordering assertion vacuous."""
    import ast

    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) == name
             or getattr(node.func, "attr", None) == name)
    ]
    return min(lines) if lines else None


@pytest.mark.parametrize("path", [
    "scripts/citivelo_bond_calibration.py",
    "scripts/daily_cache_warmer.py",
])
def test_the_guard_precedes_the_connection_in_every_caller(path):
    """Ordering is the whole defect: a check after ``client()`` is not a check.

    Asserted on source order rather than by running the scripts, because running
    them is precisely what must not happen in a test.
    """
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
    )
    gate = _first_call_line(tree, "assert_safe_to_connect")
    connect = _first_call_line(tree, "CitiVeloQuotes")
    assert gate is not None, f"{path} does not CALL the shared guard"
    assert connect is not None, f"{path} no longer constructs CitiVeloQuotes — update this test"
    assert gate < connect, (
        f"{path} constructs CitiVeloQuotes at line {connect} before gating at line "
        f"{gate}: the guard would run after the act it exists to prevent"
    )


def test_client_is_never_reached_before_the_guard(path="scripts/daily_cache_warmer.py"):
    """`quotes.client()` is the actual COM connect, so gate it too."""
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
    )
    gate = _first_call_line(tree, "assert_safe_to_connect")
    client = _first_call_line(tree, "client")
    assert gate is not None and client is not None
    assert gate < client, (
        f"{path} calls client() at line {client} before gating at line {gate}"
    )
