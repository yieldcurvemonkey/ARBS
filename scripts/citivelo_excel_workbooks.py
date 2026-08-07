r"""List and tidy the scratch workbooks this package has left in the user's Excel.

    conda run -n stir python scripts/citivelo_excel_workbooks.py list
    conda run -n stir python scripts/citivelo_excel_workbooks.py cleanup            # dry run
    conda run -n stir python scripts/citivelo_excel_workbooks.py cleanup --apply

Why this exists
---------------
Every ``connect()`` used to call ``Workbooks.Add()``, and any process that did not
reach ``close()`` left the workbook behind - a streaming daemon by design, a
killed run by accident. **62 had accumulated by 2026-08-07.** Clients now share
one tagged workbook per purpose (``SCRATCH`` for request/response, ``STREAM_<ccy>``
per streamed currency) and reuse it across runs, so the count no longer grows.
This cleans up what the old behaviour left.

What it will and will not close
-------------------------------
It closes only workbooks that are **unsaved, single-sheet, and carry the footprint
of this package's own scratch use** - either the reuse marker in ``A1`` or the
readiness probe's shape. It NEVER touches:

* a saved workbook (it has a path, so it is the user's);
* a workbook holding a live ``CVSTREAM`` cell - an RTD cell always has queued
  add-in actions against it, and tearing one down is the documented
  ``AccessViolation`` trigger that kills the whole Excel process;
* the currently active workbook;
* anything it cannot positively identify.

It is a **dry run unless you pass ``--apply``**, closes one workbook at a time
with a drain pause between, and stops at the first refusal.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: A workbook whose only content matches one of these is ours to close. The
#: readiness probe writes `=CVTODAY()`, which spills a small block - measured at
#: `$A$1:$C$71` on 62 orphans.
_PROBE_SHAPES = {"$A$1:$C$71", "$A$1:$C$33", "$A$1:$B$2", "$A$1:$A$1"}


def _describe(workbook):
    from MDP.CitiVelocityExcel.com_client import WORKBOOK_MARKER_PREFIX

    info = {"name": "?", "saved_path": "", "used": "?", "marker": "", "streaming": False}
    try:
        info["name"] = str(workbook.Name)
        info["saved_path"] = str(workbook.Path or "")
        sheet = workbook.Worksheets(1)
        info["used"] = str(sheet.UsedRange.Address)
        a1 = sheet.Range("A1").Value
        if isinstance(a1, str) and a1.startswith(WORKBOOK_MARKER_PREFIX):
            info["marker"] = a1
        info["sheets"] = int(workbook.Worksheets.Count)
        # A live CVSTREAM cell makes the workbook untouchable.
        try:
            found = sheet.Cells.Find("CVSTREAM", LookIn=-4123)  # xlFormulas
            info["streaming"] = found is not None
        except Exception:  # noqa: BLE001 - Find is unavailable on an empty sheet
            info["streaming"] = False
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _is_ours_and_safe(info) -> tuple[bool, str]:
    if info.get("error"):
        return False, f"unreadable ({info['error']})"
    if info.get("saved_path"):
        return False, "saved to disk - the user's"
    if info.get("streaming"):
        return False, "holds a live CVSTREAM cell"
    if int(info.get("sheets", 1)) != 1:
        return False, "more than one sheet - not our shape"
    if info.get("marker"):
        return True, f"our scratch workbook ({info['marker']})"
    if info.get("used") in _PROBE_SHAPES:
        return True, "readiness-probe footprint"
    return False, "not identifiable as ours"


def _connect():
    import pythoncom
    import win32com.client as win32

    pythoncom.CoInitialize()
    return win32.GetActiveObject("Excel.Application")


def cmd_list(args) -> int:
    app = _connect()
    n = int(app.Workbooks.Count)
    print(f"{n} open workbook(s)\n")
    print(f"{'#':>4}  {'name':<22}{'used':<18}{'verdict'}")
    ours = 0
    for i in range(1, n + 1):
        info = _describe(app.Workbooks(i))
        ok, why = _is_ours_and_safe(info)
        ours += ok
        print(f"{i:>4}  {info['name']:<22}{str(info['used']):<18}{'CLOSE  ' if ok else 'keep   '}{why}")
    print(f"\n{ours} closable, {n - ours} kept")
    return 0


def cmd_cleanup(args) -> int:
    app = _connect()
    active = None
    try:
        active = str(app.ActiveWorkbook.Name)
    except Exception:  # noqa: BLE001
        pass

    targets = []
    for i in range(1, int(app.Workbooks.Count) + 1):
        info = _describe(app.Workbooks(i))
        ok, why = _is_ours_and_safe(info)
        if ok and info["name"] != active:
            targets.append((info["name"], why))

    keep = max(0, int(args.keep))
    if keep and len(targets) > keep:
        # Leave the newest few so the next run reuses one instead of adding one.
        targets = targets[:-keep]

    print(f"{len(targets)} workbook(s) would be closed"
          f"{'' if args.apply else '  (dry run - pass --apply)'}")
    for name, why in targets:
        print(f"  {name:<22}{why}")
    if not args.apply or not targets:
        return 0

    closed = 0
    for name, _why in targets:
        try:
            workbook = app.Workbooks(name)
        except Exception as exc:  # noqa: BLE001 - it may already be gone
            print(f"  {name}: vanished ({exc})")
            continue
        try:
            workbook.Close(SaveChanges=False)
            closed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: REFUSED ({type(exc).__name__}: {exc}) - stopping here.")
            break
        # The add-in queues ExcessClr/Format/AutoFit against cells it wrote;
        # closing in a tight loop is how those get pulled out from under it.
        time.sleep(args.pause)
    print(f"closed {closed}; {int(app.Workbooks.Count)} workbook(s) remain")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list")
    ls.set_defaults(func=cmd_list)
    cl = sub.add_parser("cleanup")
    cl.add_argument("--apply", action="store_true", help="actually close them")
    cl.add_argument("--keep", type=int, default=1, help="leave this many for reuse")
    cl.add_argument("--pause", type=float, default=0.75, help="seconds between closes")
    cl.set_defaults(func=cmd_cleanup)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
