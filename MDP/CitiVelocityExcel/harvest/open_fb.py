r"""Open the Citi Velocity Function Builder from the ribbon via UI Automation.

Needed after an Excel restart: the DAG harvesters drive the Function Builder's
DATA BROWSER, which only exists while that window is open.
"""

import sys
import time

from pywinauto import Desktop


def ct(c):
    try:
        return c.element_info.control_type
    except Exception:
        return "?"


def nm(c):
    try:
        return (c.element_info.name or "").strip()
    except Exception:
        return ""


def walk(c, pred, depth=0, max_depth=8, out=None):
    if out is None:
        out = []
    if depth > max_depth:
        return out
    try:
        if pred(c):
            out.append(c)
        kids = c.children()
    except Exception:
        return out
    for k in kids:
        walk(k, pred, depth + 1, max_depth, out)
    return out


def main():
    d = Desktop(backend="uia")
    xl = None
    for w in d.windows():
        try:
            if w.element_info.class_name == "XLMAIN":
                xl = w
                break
        except Exception:
            pass
    if xl is None:
        print("no Excel window")
        return 1
    print("Excel:", xl.window_text(), flush=True)

    tabs = walk(xl, lambda c: ct(c) == "TabItem")
    print("ribbon tabs:", [nm(t) for t in tabs], flush=True)

    velo = next((t for t in tabs if "velocity" in nm(t).lower()
                 or "citi" in nm(t).lower()), None)
    if velo is None:
        print("no Citi Velocity ribbon tab found")
        return 2
    print("selecting tab:", nm(velo), flush=True)
    try:
        velo.select()
    except Exception:
        velo.click_input()
    time.sleep(3)

    btns = walk(xl, lambda c: ct(c) in ("Button", "SplitButton", "MenuItem") and nm(c))
    names = [nm(b) for b in btns]
    print("buttons on tab:", names[:40], flush=True)

    target = next((b for b in btns if "function" in nm(b).lower()
                   and "builder" in nm(b).lower()), None)
    if target is None:
        target = next((b for b in btns if "builder" in nm(b).lower()), None)
    if target is None:
        print("no Function Builder button found")
        return 3
    print("clicking:", nm(target), flush=True)
    try:
        target.invoke()
    except Exception:
        target.click_input()
    time.sleep(6)

    for w in Desktop(backend="uia").windows():
        try:
            if "function builder" in (w.window_text() or "").lower():
                print("OPENED hwnd=", w.element_info.handle, flush=True)
                return 0
        except Exception:
            pass
    print("clicked, but no Function Builder window detected yet", flush=True)
    return 4


if __name__ == "__main__":
    sys.exit(main())
