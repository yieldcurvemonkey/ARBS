r"""Does RATES.BOND support intraday, or is it EOD-only?

RATES.BOND is absent from the desk's intraday capability map, but absence from a
document is not evidence. This asks the add-in directly.

Design: every bond request is paired with a CONTROL tag that is known-intraday
(RATES.TSY.TSY.OTR.10Y.YIELD, from which 4,091 one-minute rows were pulled
earlier). If the control returns many rows in the same window and frequency while
the bond returns one or none, that is a real EOD-only finding. If the control also
returns nothing, the window is wrong and the run proves nothing.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_probe import Prober, show  # noqa: E402

SCRATCH = pathlib.Path(__file__).parent

CONTROL = "RATES.TSY.TSY.OTR.10Y.YIELD"
BONDS = [
    "RATES.BOND.US91282CQQ77.YIELD",   # 10Y OTR at the time of harvest
    "RATES.BOND.US91282CRB99.YIELD",   # 2Y OTR
    "RATES.BOND.US912810UA42.PRICE",
    "RATES.BOND.US912810UA42.YIELD",
]
# (label, freq, period, start, end)
WINDOWS = [
    ("MI01 / last 2d", "MI01", None, "202608040000", "202608052359"),
    ("MI01 / period 1D", "MI01", "1D", None, None),
    ("SE10 / last 1d", "SE10", None, "202608050000", "202608052359"),
    ("HOURLY / last 4d", "HOURLY", None, "202608020000", "202608052359"),
    ("DAILY / 1M (sanity)", "DAILY", "1M", None, None),
]


def raw(p, tags, freq, period, start, end):
    """One CVTSHIST call; return {tag: (nrows, first_ts, first_val)}."""
    anchor = p._anchor(40)
    per = f'"{period}"' if period else ""
    st = f'"{start}"' if start else ""
    en = f'"{end}"' if end else ""
    formula = f'=CVTSHIST("{",".join(tags)}","{freq}",{per},{st},{en},"CLOSE")'
    p.ws.Range(anchor).Formula = formula
    try:
        p.app.CalculateUntilAsyncQueriesDone()
    except Exception:
        pass
    v = p._settle(anchor, timeout=180)
    reg = p.ws.Range(anchor).CurrentRegion
    p._advance_past(anchor, reg)
    vals = reg.Value
    if not isinstance(vals, tuple):
        return {t: (0, None, show(v)) for t in tags}, show(v)
    rows = [list(r) if isinstance(r, tuple) else [r] for r in vals]
    hdr = next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Date"), None)
    if hdr is None:
        return {t: (0, None, "no header") for t in tags}, show(v)
    headers = [str(c) if c is not None else "" for c in rows[hdr]]
    body = rows[hdr + 1:]
    out = {}
    for t in tags:
        col = next((j for j, h in enumerate(headers) if h.startswith(t + " ")), None)
        if col is None:
            out[t] = (0, None, "no column")
            continue
        vals_t = [(r[0], r[col]) for r in body
                  if col < len(r) and r[col] is not None
                  and not (isinstance(r[col], str) and r[col].startswith("Bad tag"))]
        first = vals_t[0] if vals_t else (None, None)
        out[t] = (len(vals_t), first[0], first[1])
    return out, None


def main():
    p = Prober(SCRATCH / "bond_intraday.json", batch=10)
    try:
        for label, freq, period, start, end in WINDOWS:
            print(f"\n=== {label} ===", flush=True)
            res, err = raw(p, [CONTROL] + BONDS, freq, period, start, end)
            c_n, c_ts, c_v = res[CONTROL]
            print(f"  CONTROL {CONTROL:<34} rows={c_n:<6} first={c_ts} {c_v}", flush=True)
            if c_n <= 1:
                print("  !! control returned <=1 row - window/freq unusable, "
                      "bond result proves nothing", flush=True)
            for b in BONDS:
                n, ts, val = res[b]
                print(f"  bond    {b:<34} rows={n:<6} first={ts} {val}", flush=True)
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
