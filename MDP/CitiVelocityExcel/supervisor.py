r"""Restart Excel and wait for the Citi Velocity add-in to sign itself back in.

The add-in's memory only ever grows and **only a restart clears it**. Measured
2026-08-07 a 528-window fetch left ``EXCEL.EXE`` at 5,249 MB and wedged it - no
modal dialog, no cell-edit mode, unresponsive to a 15 s window ping, and it did
not recover when the COM client was released. On 2026-08-08 the same process was
seen climbing through 7,639 MB and then 13,884 MB with nothing in this repo
connected to it. ``memory_guard`` exists to *refuse* in that state; this module
exists to *fix* it, so an unattended multi-hour backfill does not stop dead at
the ceiling waiting for a human.

Restarting Excel is destructive and this module treats it that way
--------------------------------------------------------------------
``EXCEL.EXE`` is the user's application, not this repo's. It routinely holds
unsaved work - a ``Book5`` with something typed in it - and a backfill that
discards that to save itself twenty minutes has made a bad trade on someone
else's behalf. So :func:`restart_excel` **rescues before it quits**:

* a dirty workbook with a path is saved in place;
* a dirty workbook with no path is saved into ``recovery_dir`` under its own
  window name, and the path is returned AND logged;
* a scratch workbook this package created (identified by the ``A1`` marker, the
  same way :func:`~MDP.CitiVelocityExcel.com_client.find_marked_workbook` finds
  it) is skipped - it is ours and it is disposable.

If a rescue fails, the default is to **abort the restart** and leave Excel alone.
``force=True`` overrides that; nothing in this repo passes it by default.

Signing back in takes minutes, and silence is not failure
---------------------------------------------------------
After a restart the Velocity add-in re-authenticates from saved credentials with
no progress output of any kind, and ``=CVTODAY()`` answers ``#NAME?`` -
``AddInNotSignedInError`` - for the whole of it. The connect path's own docstring
records ~13 minutes. :func:`wait_for_addin` therefore treats both
``AddInNotSignedInError`` and ``ExcelNotRunningError`` as *keep waiting* and only
gives up on the wall clock, defaulting to 25 minutes.

This module never types a password. It relies on the credentials already being
saved in the add-in - which is what makes the restart unattended, and also what
makes it useless on a machine where they are not.
"""

from __future__ import annotations

import ctypes
import datetime
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional

from MDP.CitiVelocityExcel.errors import AddInNotSignedInError, ExcelNotRunningError

__all__ = [
    "DEFAULT_READY_TIMEOUT",
    "ExcelRestartError",
    "excel_executable",
    "excel_pids",
    "launch_excel",
    "quit_excel",
    "rescue_unsaved_workbooks",
    "press_addin_login",
    "restart_excel",
    "signin_anchor_workbook",
    "wait_for_addin",
]

_logger = logging.getLogger(__name__)

#: How long to wait for ``=CVTODAY()`` to answer after a restart. The login is
#: ~13 minutes and logs nothing, so a timeout under ~20 minutes reports a healthy
#: Excel as dead.
DEFAULT_READY_TIMEOUT = 25 * 60.0

#: Override the executable when Office lives somewhere the registry does not say.
EXE_ENV_VAR = "ARBS_EXCEL_EXE"

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")

#: The ribbon tab the add-in installs, and the button on it that opens the login
#: task pane. Both are UI Automation ``Name`` values, read off the live ribbon on
#: 2026-08-09 rather than guessed.
RIBBON_TAB = "Citi Velocity"
LOGIN_BUTTON = "Login"


class ExcelRestartError(RuntimeError):
    """The restart could not be completed safely."""


# ------------------------------------------------------------------ #
#                        finding and counting                        #
# ------------------------------------------------------------------ #


def excel_executable() -> Path:
    """Where ``EXCEL.EXE`` is, from the env var, the registry, then the usual paths."""
    override = os.environ.get(EXE_ENV_VAR, "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise ExcelRestartError(f"{EXE_ENV_VAR}={override!r} is not a file.")
        return path

    try:
        import winreg  # type: ignore

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                    root,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
                ) as key:
                    value, _kind = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            candidate = Path(str(value).strip('"'))
            if candidate.is_file():
                return candidate
    except ImportError:  # pragma: no cover - non-Windows
        pass

    for candidate in (
        Path(r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"),
        Path(r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"),
        Path(r"C:\Program Files\Microsoft Office\Office16\EXCEL.EXE"),
    ):
        if candidate.is_file():
            return candidate

    raise ExcelRestartError(
        "Could not locate EXCEL.EXE. Set "
        f"{EXE_ENV_VAR} to its full path (registry App Paths had no usable entry)."
    )


def excel_pids() -> List[int]:
    """Every running ``EXCEL.EXE`` pid. Empty when Excel is not running."""
    try:
        import psutil  # type: ignore
    except ImportError:  # pragma: no cover - psutil is a hard dep of this repo
        return []
    out: List[int] = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if str(proc.info.get("name") or "").upper() == "EXCEL.EXE":
                out.append(int(proc.info["pid"]))
        except Exception:  # noqa: BLE001 - a process that died mid-iteration
            continue
    return out


# ------------------------------------------------------------------ #
#                    rescuing the user's own work                    #
# ------------------------------------------------------------------ #


def _is_ours(workbook: Any) -> bool:
    """True for a scratch workbook this package stamped, which is disposable."""
    from MDP.CitiVelocityExcel.com_client import WORKBOOK_MARKER_PREFIX, com_retry

    try:
        value = com_retry(
            lambda: workbook.Worksheets(1).Range("A1").Value, attempts=2, delay=0.1
        )
    except Exception:  # noqa: BLE001 - unreadable means not ours
        return False
    return isinstance(value, str) and value.strip().startswith(WORKBOOK_MARKER_PREFIX)


def rescue_unsaved_workbooks(app: Any, *, recovery_dir: Path) -> List[Path]:
    """Save every dirty workbook that is not one of ours. Returns what was written.

    Raises
    ------
    ExcelRestartError
        When a workbook is dirty and could not be saved. Deliberately fatal:
        the caller's next move is to terminate the process holding it.
    """
    from MDP.CitiVelocityExcel.com_client import com_retry

    saved: List[Path] = []
    try:
        count = int(com_retry(lambda: app.Workbooks.Count, attempts=4, delay=0.25))
    except Exception as exc:  # noqa: BLE001
        raise ExcelRestartError(
            f"Excel is running but its Workbooks collection is unreachable ({exc}); "
            "refusing to terminate a process whose contents cannot be checked."
        ) from exc

    for index in range(count, 0, -1):
        try:
            workbook = com_retry(lambda: app.Workbooks(index), attempts=2, delay=0.1)
            name = str(com_retry(lambda: workbook.Name, attempts=2, delay=0.1))
            dirty = not bool(com_retry(lambda: workbook.Saved, attempts=2, delay=0.1))
            path = str(com_retry(lambda: workbook.Path, attempts=2, delay=0.1) or "")
        except Exception as exc:  # noqa: BLE001
            raise ExcelRestartError(
                f"Could not inspect workbook {index} of {count} ({exc}); refusing to "
                "terminate an Excel whose contents cannot be checked."
            ) from exc

        if not dirty or _is_ours(workbook):
            continue

        try:
            if path:
                com_retry(lambda: workbook.Save())
                _logger.info("rescued (saved in place): %s", Path(path) / name)
                saved.append(Path(path) / name)
            else:
                recovery_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                stem = _UNSAFE.sub("_", Path(name).stem) or "workbook"
                target = recovery_dir / f"{stem}-{stamp}.xlsx"
                com_retry(lambda: workbook.SaveAs(str(target)))
                _logger.warning(
                    "rescued an UNSAVED workbook before restarting Excel: %s -> %s",
                    name, target,
                )
                saved.append(target)
        except Exception as exc:  # noqa: BLE001
            raise ExcelRestartError(
                f"Workbook {name!r} has unsaved changes and could not be saved ({exc}). "
                "Refusing to restart Excel - that would discard someone's work. Save or "
                "close it by hand, or pass force=True knowingly."
            ) from exc
    return saved


# ------------------------------------------------------------------ #
#                          stop and start                            #
# ------------------------------------------------------------------ #


def quit_excel(
    *,
    recovery_dir: Optional[Path] = None,
    force: bool = False,
    grace_seconds: float = 45.0,
    logger: Optional[logging.Logger] = None,
) -> List[Path]:
    """Rescue unsaved work, ask Excel to quit, then terminate what is left.

    ``force=True`` skips the rescue. Returns the paths anything was rescued to.
    """
    log = logger or _logger
    rescued: List[Path] = []

    if not excel_pids():
        log.info("quit_excel: no EXCEL.EXE is running")
        return rescued

    app = None
    try:
        import pythoncom  # type: ignore
        import win32com.client as win32  # type: ignore

        pythoncom.CoInitialize()
        app = win32.GetActiveObject("Excel.Application")
    except Exception as exc:  # noqa: BLE001 - a wedged Excel has no reachable app
        log.warning("quit_excel: no COM handle on Excel (%s)", exc)

    if app is not None:
        if not force:
            rescued = rescue_unsaved_workbooks(
                app, recovery_dir=recovery_dir or _default_recovery_dir()
            )
        try:
            app.DisplayAlerts = False
        except Exception:  # noqa: BLE001
            pass
        try:
            app.Quit()
        except Exception as exc:  # noqa: BLE001 - a wedged Excel refuses Quit()
            log.warning("quit_excel: Application.Quit() refused (%s)", exc)
    elif not force:
        # No COM handle means the contents cannot be checked. A wedged Excel is
        # exactly the case this exists for, so this is not fatal - but it is the
        # one path where unsaved work can be lost, and it says so.
        log.warning(
            "quit_excel: Excel is unreachable over COM, so its workbooks could not be "
            "checked for unsaved changes. Terminating anyway - a wedged Excel cannot be "
            "saved from either."
        )

    deadline = time.time() + max(0.0, grace_seconds)
    while time.time() < deadline:
        if not excel_pids():
            log.info("quit_excel: Excel exited cleanly")
            return rescued
        time.sleep(1.0)

    survivors = excel_pids()
    if survivors:
        log.warning("quit_excel: terminating %d stuck EXCEL.EXE process(es): %s",
                    len(survivors), survivors)
        _terminate(survivors, logger=log)
    return rescued


def _terminate(pids: List[int], *, logger: logging.Logger) -> None:
    try:
        import psutil  # type: ignore
    except ImportError:  # pragma: no cover
        subprocess.run(["taskkill", "/F", "/IM", "EXCEL.EXE"], capture_output=True)
        return
    procs = []
    for pid in pids:
        try:
            procs.append(psutil.Process(pid))
        except Exception:  # noqa: BLE001
            continue
    for proc in procs:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    _gone, alive = psutil.wait_procs(procs, timeout=20)
    for proc in alive:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    psutil.wait_procs(alive, timeout=20)
    if excel_pids():
        logger.warning("quit_excel: EXCEL.EXE still present after kill: %s", excel_pids())


def _default_recovery_dir() -> Path:
    return Path.home() / "Documents" / "ARBS-excel-recovery"


def launch_excel(*, exe: Optional[Path] = None, logger: Optional[logging.Logger] = None) -> int:
    """Start Excel so the add-in loads and begins signing in. Returns the pid."""
    log = logger or _logger
    executable = Path(exe) if exe else excel_executable()
    # /x asks for a dedicated process rather than a new window on an existing
    # one; there should be no existing one here, and it makes the pid this call
    # returns the pid it actually started.
    anchor = signin_anchor_workbook()
    before = set(excel_pids())

    # ShellExecute, i.e. exactly what double-clicking the file does - NOT
    # subprocess.Popen with DETACHED_PROCESS and null handles. Measured
    # 2026-08-09 with everything else held equal (same anchor workbook, same
    # Login press): the ShellExecute instance signed in, the Popen one accepted
    # the InvokePattern call and did nothing, staying at 71 log lines.
    #
    # `/x` STAYS, but it must be paired with a file. On its own it opens the
    # Start screen: no workbook, therefore no ribbon, therefore no Login button -
    # and such an instance does not even register in the Running Object Table, so
    # `GetObject('Excel.Application')` creates a SECOND one rather than finding
    # it. Without `/x`, ShellExecute hands the file to the ALREADY-RUNNING Excel
    # and the process started here exits immediately, which is the opposite of
    # what a restart needs. Measured both ways.
    parameters = f'/x "{anchor}"' if anchor is not None else "/x"
    result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "open", str(executable), parameters, str(executable.parent), 1
    )
    if int(result) <= 32:
        raise ExcelRestartError(
            f"ShellExecute refused to start {executable} (code {result})."
        )

    # ShellExecute returns a shell handle, not Excel's pid, so diff the set.
    pid = 0
    deadline = time.time() + 30.0
    while time.time() < deadline:
        fresh = set(excel_pids()) - before
        if fresh:
            pid = sorted(fresh)[0]
            break
        time.sleep(0.5)
    log.info("launch_excel: started %s (pid %s)%s", executable, pid or "unknown",
             f" on {anchor.name}" if anchor else " with NO workbook (no ribbon, no Login button)")
    return int(pid)


def signin_anchor_workbook() -> Optional[Path]:
    """A tiny workbook to open Excel ON, created once and reused.

    **Excel started with no workbook has no ribbon**, and with no ribbon there is
    no ``Login`` button for :func:`press_addin_login` to press. That is why
    ``/x`` alone fails: it lands on the Start screen. Measured 2026-08-09 - the
    same launch that could not find the button with no workbook found it
    immediately with one.

    Marked in ``A1`` with the package's scratch prefix so
    :func:`rescue_unsaved_workbooks` recognises it as ours and never tries to
    save it back to the user's Documents.
    """
    from MDP.CitiVelocityExcel.com_client import WORKBOOK_MARKER_PREFIX

    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "excel-scratch"
    path = root / "velocity_signin_anchor.xlsx"
    if path.is_file():
        return path
    try:
        import openpyxl  # type: ignore

        root.mkdir(parents=True, exist_ok=True)
        book = openpyxl.Workbook()
        book.active["A1"] = f"{WORKBOOK_MARKER_PREFIX}SIGNIN_ANCHOR"
        book.save(path)
        return path
    except Exception as exc:  # noqa: BLE001 - fall back to a workbook-less launch
        _logger.warning("signin_anchor_workbook: could not create %s (%s)", path, exc)
        return None


def press_addin_login(
    pid: Optional[int] = None,
    *,
    timeout: float = 90.0,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """Click the Velocity ribbon's **Login** button. Returns True if it was pressed.

    This is the step that was missing, and without it an Excel started by a
    process never signs in no matter how long you wait.

    **The add-in does not resume its session on load.** Measured 2026-08-09 by
    diffing its own log across five launches: every programmatically started
    instance stopped at exactly 71 lines, the last being
    ``Citi.Excel.Presentation.CustomRibbon | onLoad:``. A human-opened one ran to
    1,329 lines, and the divergence is a single component appearing ~13 s in::

        TaskPaneConductor`1[[...ViewModels.LoginViewModel...]]
        CookieService   Using proxy: https://www.citivelocity.com/...
        PortalSession   Resuming user session. <user>@citi.com
        PortalSession   Report|User session resumed.

    The login **task pane** is what resumes the saved session. Opening it is what
    the ribbon's ``Login`` button does, and until something presses it the add-in
    sits there fully loaded and unauthenticated. Four hypotheses were tested and
    killed before this one - launch mode (``ShellExecute`` fails identically),
    credential freshness (a restart 37 minutes after a good sign-in failed),
    workbook presence (opening a real ``.xlsx`` failed), Windows session
    isolation (everything was already in session 1), and activating the Velocity
    ribbon *tab* rather than the button (failed).

    No password is typed here and none is available to type: the button opens the
    pane, and the pane resumes from credentials already saved in the add-in. On a
    machine where they are not saved this will surface a login form instead, and
    :func:`wait_for_addin` will simply time out as it did before.
    """
    log = logger or _logger
    try:
        from pywinauto import Application  # type: ignore
    except ImportError:
        log.warning("press_addin_login: pywinauto is not installed; cannot open the login pane.")
        return False

    candidates = [pid] if pid else excel_pids()
    for candidate in [c for c in candidates if c]:
        try:
            app = Application(backend="uia").connect(process=int(candidate), timeout=10)
            window = app.top_window()

            # The ribbon only materialises a tab's buttons once that tab is
            # SELECTED. Measured: 37 buttons and no `Login` before selecting
            # `Citi Velocity`, 38 with it. Skipping this step is why an earlier
            # version of this function returned False on an Excel where the very
            # same click worked by hand - the hand had activated the tab in the
            # previous command.
            tab = window.child_window(title=RIBBON_TAB, control_type="TabItem")
            tab.wait("exists enabled", timeout=max(5.0, timeout))
            tab.select()

            # The button enters the UIA tree a beat AFTER the tab is selected,
            # not with it. Measured: the first call found 37 buttons and no
            # Login; a second call moments later found 38 and pressed it. Poll
            # rather than assume, and re-select once in case the first did not
            # take.
            button = None
            spec = window.child_window(title=LOGIN_BUTTON, control_type="Button")
            deadline = time.time() + max(10.0, timeout)
            while time.time() < deadline:
                if spec.exists(timeout=1.0):
                    button = spec
                    break
                time.sleep(1.0)
                tab.select()
            if button is None:
                raise RuntimeError(
                    f"{LOGIN_BUTTON!r} never appeared on the {RIBBON_TAB!r} ribbon tab"
                )
            button.wait("exists enabled visible", timeout=max(5.0, timeout))
            button.invoke()
            log.info("press_addin_login: pressed %s on EXCEL.EXE pid %s",
                     LOGIN_BUTTON, candidate)
            return True
        except Exception as exc:  # noqa: BLE001 - a window that is not ready yet
            log.debug("press_addin_login: pid %s not ready (%s: %s)",
                      candidate, type(exc).__name__, exc)
    return False


def wait_for_addin(
    *,
    timeout: float = DEFAULT_READY_TIMEOUT,
    poll: float = 20.0,
    workbook_tag: str = "SCRATCH",
    readiness_timeout: float = 45.0,
    press_login: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """Block until ``=CVTODAY()`` answers, then return a connected client.

    ``AddInNotSignedInError`` means the add-in is loaded and not authenticated.
    That is **not** a state that resolves itself in a started Excel: see
    :func:`press_addin_login`. So the first time this sees it, it opens the login
    pane, and from then on the wait is the ordinary one - saved credentials
    resume in about half a minute.

    ``press_login=False`` restores the old behaviour of waiting only.
    """
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

    log = logger or _logger
    started = time.time()
    deadline = started + max(0.0, timeout)
    last = ""
    pressed = not press_login
    while True:
        try:
            client = CitiVelocityExcelClient.connect(
                attempts=1, workbook_tag=workbook_tag, readiness_timeout=readiness_timeout
            )
            log.info("wait_for_addin: signed in after %.1f min", (time.time() - started) / 60.0)
            return client
        except (AddInNotSignedInError, ExcelNotRunningError) as exc:
            state = type(exc).__name__
            if not pressed and isinstance(exc, AddInNotSignedInError):
                # The add-in is loaded and will NOT authenticate on its own.
                # Press once; a second press while the pane is already open is
                # noise, and a failure here is not fatal - the wait continues and
                # a human can still sign in.
                pressed = press_addin_login(logger=log) or pressed
        except Exception as exc:  # noqa: BLE001 - transient COM during startup
            state = f"{type(exc).__name__}: {exc}"
        if state != last:
            log.info("wait_for_addin: %s (%.1f min elapsed)", state, (time.time() - started) / 60.0)
            last = state
        if time.time() >= deadline:
            raise ExcelRestartError(
                f"The Citi Velocity add-in did not sign in within {timeout / 60:.0f} minutes "
                f"(last state: {state}). Saved credentials may have expired - sign in by hand "
                "once and re-run."
            )
        time.sleep(max(1.0, poll))


def restart_excel(
    *,
    workbook_tag: str = "SCRATCH",
    recovery_dir: Optional[Path] = None,
    force: bool = False,
    ready_timeout: float = DEFAULT_READY_TIMEOUT,
    settle_seconds: float = 10.0,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """Rescue, quit, relaunch, and wait for sign-in. Returns a connected client.

    The one call an unattended backfill needs when Excel has grown past its
    ceiling. Everything it can lose, it saves first; see the module docstring.
    """
    log = logger or _logger
    rescued = quit_excel(recovery_dir=recovery_dir, force=force, logger=log)
    if rescued:
        log.warning("restart_excel: rescued %d workbook(s) before restarting: %s",
                    len(rescued), [str(p) for p in rescued])
    time.sleep(max(0.0, settle_seconds))
    launch_excel(logger=log)
    time.sleep(max(0.0, settle_seconds))
    return wait_for_addin(timeout=ready_timeout, workbook_tag=workbook_tag, logger=log)
