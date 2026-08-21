r"""Restarting Excel is destructive, so the tests are about what it refuses to do.

``supervisor.restart_excel`` terminates the user's Excel. Every failure mode that
matters here loses somebody's unsaved work, and none of them raise on their own -
a workbook silently discarded looks exactly like one that was never open. So the
assertions below are about **refusal and rescue**, not about the happy path:

* a dirty workbook is saved before anything is terminated;
* an unsaved, unnamed one goes to a recovery file whose path is returned;
* a scratch workbook this package created is skipped, because it is ours;
* a rescue that FAILS aborts the restart rather than proceeding;
* an Excel whose contents cannot be read is not silently killed.

The COM objects are fakes. Nothing here starts Excel, and nothing here needs it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from MDP.CitiVelocityExcel import supervisor
from MDP.CitiVelocityExcel.com_client import WORKBOOK_MARKER_PREFIX
from MDP.CitiVelocityExcel.errors import AddInNotSignedInError, ExcelNotRunningError


# ------------------------------------------------------------------ #
#                            COM fakes                               #
# ------------------------------------------------------------------ #


class _Cell:
    def __init__(self, value):
        self.Value = value


class _Sheet:
    def __init__(self, a1):
        self._a1 = _Cell(a1)

    def Range(self, ref):
        if ref != "A1":
            raise KeyError(ref)
        return self._a1


class _Sheets:
    def __init__(self, sheet):
        self._sheet = sheet

    def __call__(self, index):
        return self._sheet


class _Workbook:
    def __init__(self, name, *, saved=True, path="", a1=None, save_raises=False):
        self.Name = name
        self.Saved = saved
        self.Path = path
        self.Worksheets = _Sheets(_Sheet(a1))
        self._save_raises = save_raises
        self.saved_in_place = False
        self.saved_as = None

    def Save(self):
        if self._save_raises:
            raise RuntimeError("Excel refused the save")
        self.saved_in_place = True
        self.Saved = True

    def SaveAs(self, target):
        if self._save_raises:
            raise RuntimeError("Excel refused the save")
        Path(target).write_text("fake workbook", encoding="utf-8")
        self.saved_as = Path(target)
        self.Saved = True


class _Workbooks:
    def __init__(self, books):
        self._books = list(books)

    @property
    def Count(self):
        return len(self._books)

    def __call__(self, index):
        return self._books[index - 1]


class _App:
    def __init__(self, books):
        self.Workbooks = _Workbooks(books)
        self.DisplayAlerts = True
        self.quit_calls = 0

    def Quit(self):
        self.quit_calls += 1


class _BrokenApp:
    @property
    def Workbooks(self):
        raise RuntimeError("call was rejected by callee")


# ------------------------------------------------------------------ #
#                    rescuing the user's own work                    #
# ------------------------------------------------------------------ #


def test_a_dirty_workbook_with_a_path_is_saved_in_place(tmp_path: Path):
    book = _Workbook("model.xlsx", saved=False, path=str(tmp_path))
    saved = supervisor.rescue_unsaved_workbooks(_App([book]), recovery_dir=tmp_path / "rec")
    assert book.saved_in_place is True
    assert saved == [tmp_path / "model.xlsx"]


def test_an_unsaved_unnamed_workbook_is_written_to_the_recovery_dir(tmp_path: Path):
    """``Book5`` with something typed in it is the case this exists for."""
    book = _Workbook("Book5", saved=False, path="")
    recovery = tmp_path / "rec"
    saved = supervisor.rescue_unsaved_workbooks(_App([book]), recovery_dir=recovery)
    assert len(saved) == 1
    assert saved[0].parent == recovery
    assert saved[0].exists()
    assert saved[0].name.startswith("Book5-")
    assert book.saved_as == saved[0]


def test_our_own_scratch_workbook_is_skipped_even_when_dirty(tmp_path: Path):
    ours = _Workbook("Book9", saved=False, path="", a1=f"{WORKBOOK_MARKER_PREFIX}TSWARM")
    saved = supervisor.rescue_unsaved_workbooks(_App([ours]), recovery_dir=tmp_path)
    assert saved == []
    assert ours.saved_as is None


def test_a_clean_workbook_is_left_alone(tmp_path: Path):
    book = _Workbook("model.xlsx", saved=True, path=str(tmp_path))
    assert supervisor.rescue_unsaved_workbooks(_App([book]), recovery_dir=tmp_path) == []
    assert book.saved_in_place is False


def test_a_failed_rescue_aborts_the_restart(tmp_path: Path):
    """The whole point: do not terminate a process holding work you could not save."""
    book = _Workbook("Book5", saved=False, path="", save_raises=True)
    with pytest.raises(supervisor.ExcelRestartError, match="unsaved changes"):
        supervisor.rescue_unsaved_workbooks(_App([book]), recovery_dir=tmp_path)


def test_an_unreadable_excel_is_not_silently_killed(tmp_path: Path):
    with pytest.raises(supervisor.ExcelRestartError, match="unreachable"):
        supervisor.rescue_unsaved_workbooks(_BrokenApp(), recovery_dir=tmp_path)


def test_every_workbook_is_inspected_not_just_the_first(tmp_path: Path):
    books = [
        _Workbook("a.xlsx", saved=True, path=str(tmp_path)),
        _Workbook("Book7", saved=False, path=""),
        _Workbook("c.xlsx", saved=False, path=str(tmp_path)),
    ]
    saved = supervisor.rescue_unsaved_workbooks(_App(books), recovery_dir=tmp_path / "rec")
    assert len(saved) == 2
    assert books[1].saved_as is not None
    assert books[2].saved_in_place is True


# ------------------------------------------------------------------ #
#                       finding the executable                       #
# ------------------------------------------------------------------ #


def test_the_env_override_wins(tmp_path: Path, monkeypatch):
    exe = tmp_path / "EXCEL.EXE"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv(supervisor.EXE_ENV_VAR, str(exe))
    assert supervisor.excel_executable() == exe


def test_a_bad_env_override_is_an_error_not_a_fallback(tmp_path: Path, monkeypatch):
    """Falling back would start the WRONG Office build without saying so."""
    monkeypatch.setenv(supervisor.EXE_ENV_VAR, str(tmp_path / "nope.exe"))
    with pytest.raises(supervisor.ExcelRestartError, match="is not a file"):
        supervisor.excel_executable()


# ------------------------------------------------------------------ #
#                 waiting through the sign-in silence                #
# ------------------------------------------------------------------ #


def test_not_signed_in_means_keep_waiting(monkeypatch):
    """~13 minutes of ``#NAME?`` is the NORMAL path, not a failure."""
    from MDP.CitiVelocityExcel import com_client

    sentinel = object()
    calls = {"n": 0}

    def fake_connect(**kwargs):
        calls["n"] += 1
        if calls["n"] < 4:
            raise AddInNotSignedInError()
        return sentinel

    monkeypatch.setattr(com_client.CitiVelocityExcelClient, "connect", staticmethod(fake_connect))
    monkeypatch.setattr(supervisor.time, "sleep", lambda _s: None)
    # THE ONE LINE THAT KEPT HANGING THE GATE. wait_for_addin presses the add-in's
    # Login button the first time it sees AddInNotSignedInError, and the mock above
    # raises it three times on purpose. Unstubbed, press_addin_login reaches pywinauto's
    # UIA element walk against whatever Excel the machine has -- or against none, where
    # it takes an access violation and STALLS rather than failing. Two whole-suite runs
    # were abandoned to this. conftest now rails it as well; this keeps the test honest
    # about what it is exercising, which is the WAITING, not the clicking.
    presses = []
    monkeypatch.setattr(supervisor, "press_addin_login", lambda **kw: presses.append(kw) or True)
    assert supervisor.wait_for_addin(timeout=300, poll=0.0) is sentinel
    assert calls["n"] == 4
    # Once per not-signed-in poll, which is three here, and that is CORRECT rather
    # than tolerated: the add-in's Login handler is inert for the first minutes after
    # launch, so a single early press is a silent no-op. The source says as much --
    # "a press that arrives too early is a silent no-op, and that is the failure worth
    # designing against". I asserted 1 first and the code was right, not the test.
    assert len(presses) == 3, "the pane is pressed on every not-signed-in poll"


def test_excel_not_running_also_means_keep_waiting(monkeypatch):
    from MDP.CitiVelocityExcel import com_client

    sentinel = object()
    calls = {"n": 0}

    def fake_connect(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ExcelNotRunningError()
        return sentinel

    monkeypatch.setattr(com_client.CitiVelocityExcelClient, "connect", staticmethod(fake_connect))
    monkeypatch.setattr(supervisor.time, "sleep", lambda _s: None)
    assert supervisor.wait_for_addin(timeout=300, poll=0.0) is sentinel


def test_the_wait_gives_up_on_the_wall_clock(monkeypatch):
    from MDP.CitiVelocityExcel import com_client

    def fake_connect(**kwargs):
        raise AddInNotSignedInError()

    monkeypatch.setattr(com_client.CitiVelocityExcelClient, "connect", staticmethod(fake_connect))
    monkeypatch.setattr(supervisor.time, "sleep", lambda _s: None)
    with pytest.raises(supervisor.ExcelRestartError, match="did not sign in"):
        supervisor.wait_for_addin(timeout=0.0, poll=0.0)


def test_the_default_wait_outlasts_the_documented_login(monkeypatch):
    """The connect path records ~13 minutes; a 10-minute default would call it dead."""
    assert supervisor.DEFAULT_READY_TIMEOUT >= 15 * 60


# ------------------------------------------------------------------ #
#                        quitting is a no-op                         #
# ------------------------------------------------------------------ #


def test_quit_excel_does_nothing_when_excel_is_not_running(monkeypatch, caplog):
    monkeypatch.setattr(supervisor, "excel_pids", lambda: [])
    with caplog.at_level(logging.INFO):
        assert supervisor.quit_excel() == []
    assert "no EXCEL.EXE is running" in caplog.text
