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
    "restart_excel",
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
    proc = subprocess.Popen(
        [str(executable), "/x"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    log.info("launch_excel: started %s (pid %s)", executable, proc.pid)
    return int(proc.pid)


def wait_for_addin(
    *,
    timeout: float = DEFAULT_READY_TIMEOUT,
    poll: float = 20.0,
    workbook_tag: str = "SCRATCH",
    readiness_timeout: float = 45.0,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """Block until ``=CVTODAY()`` answers, then return a connected client.

    ``AddInNotSignedInError`` is the NORMAL state for most of this wait - the
    add-in is loaded and re-authenticating from saved credentials, which takes
    ~13 minutes and prints nothing - so it is a reason to keep waiting, not to
    give up. Only the wall clock ends the wait.
    """
    from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

    log = logger or _logger
    started = time.time()
    deadline = started + max(0.0, timeout)
    last = ""
    while True:
        try:
            client = CitiVelocityExcelClient.connect(
                attempts=1, workbook_tag=workbook_tag, readiness_timeout=readiness_timeout
            )
            log.info("wait_for_addin: signed in after %.1f min", (time.time() - started) / 60.0)
            return client
        except (AddInNotSignedInError, ExcelNotRunningError) as exc:
            state = type(exc).__name__
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
