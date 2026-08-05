r"""Use the Function Builder DATA BROWSER search box to enumerate tags by prefix.

RATES.BOND has no children in the category tree - bonds are not enumerated there
(there are far too many ISINs). But the browser has a Search box + DataGrid, so a
prefix search should list the concrete tags. Used here to discover what values
exist under a specific bond: RATES.BOND.<ISIN>.<value>
"""

from __future__ import annotations

import sys
import time

from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo

HWND = 3609176


def ct(c):
    try:
        return c.element_info.control_type
    except Exception:
        return "?"


def nm(c):
    try:
        return (c.element_info.name or "").replace("\n", " ")
    except Exception:
        return ""


def find_all(w, pred, depth=0, out=None):
    if out is None:
        out = []
    if depth > 14:
        return out
    try:
        if pred(w):
            out.append(w)
        kids = w.children()
    except Exception:
        return out
    for k in kids:
        find_all(k, pred, depth + 1, out)
    return out


def grid_rows(w):
    gs = find_all(w, lambda c: ct(c) == "DataGrid")
    if not gs:
        return []
    rows = []
    for r in gs[0].children():
        cells = [nm(c) for c in r.children()] if r.children() else []
        rows.append(nm(r) or " | ".join(x for x in cells if x))
    return rows


def search(w, text, settle=25):
    """Type into the browser's Search box and read the grid."""
    edits = find_all(w, lambda c: ct(c) == "Edit")
    # the search box is the one that is visible, enabled, and not PART_Editor
    cands = []
    for e in edits:
        try:
            r = e.rectangle()
            aid = e.element_info.automation_id or ""
            if r.width() > 40 and aid not in ("PART_Editor",):
                cands.append((e, aid, r))
        except Exception:
            continue
    if not cands:
        print("  no candidate search box")
        return []
    for e, aid, r in cands:
        try:
            e.set_focus()
        except Exception:
            pass
        try:
            e.set_edit_text("")
            e.type_keys(text, with_spaces=True, set_foreground=False)
        except Exception:
            try:
                e.set_edit_text(text)
            except Exception:
                continue
        before = None
        for _ in range(settle):
            time.sleep(0.4)
            rows = grid_rows(w)
            if rows and rows != before and len(rows) > 0:
                return rows
            before = rows
    return grid_rows(w)


def main():
    w = UIAWrapper(UIAElementInfo(HWND))
    for q in sys.argv[1:] or ["RATES.BOND.US912810UA42"]:
        print(f"\n=== search {q!r} ===", flush=True)
        rows = search(w, q)
        print(f"  {len(rows)} grid rows", flush=True)
        for r in rows[:60]:
            print("   ", r[:120], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
