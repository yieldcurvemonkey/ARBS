"""Golden test: can the ZQ strip be recovered from a curve, and to what accuracy?

Three things are decided here by measurement rather than assertion.

1. **The spec.** ``usd_stir1`` is the monthly, ARITHMETIC-AVERAGE spec
   (``rfr_payment_delay_avg``, $41.67/bp); ``usd_stir`` is quarterly IMM and
   COMPOUNDED ($25/bp). The repo's ``is_ser`` predicates key off
   ``root in {SR1, SER, SL}`` and **ZQ is not in that set**, so a ZQ routed
   through them silently gets the wrong contract. The compounding gap is
   ~0.7bp on a 31-day month at 4% -- larger than a ZQ half tick.

2. **The accrual window.** ``SDRUtils.stir_flow.ladder.contract_grid`` gives
   monthly contracts a **business-day** window: first business day of the month
   to first business day of the next. The rulebook settles on **every calendar
   day** of the delivery month. Those differ whenever the 1st is not a business
   day, and the difference is not cosmetic -- it re-weights the pre/post split
   around a mid-month meeting by ~1.4% of the jump, ~0.35bp on a 25bp move.

3. **Whether MIX23 can price EFFR at all.** MIX23 fetches FFCM1-12 but pulls the
   ZQ pricers out of the solver instrument set and uses them only to build a
   SER-FF basis skew, so it is a SOFR-space curve. If it cannot reprice ZQ, the
   curve path is a diagnostic and not a mark -- which is what the house rule
   says anyway.

Run: conda run -n stir python notebooks/rv/_probe_zq_curve.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")   # before any Caching import

import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import pytz

pd.set_option("display.width", 240, "display.max_columns", 40)

from RVUtils.MeanRev.ff import delivery_window, month_code

NY = pytz.timezone("America/New_York")
ASSET = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
SOFR_ASSET = "USD-SOFR-1D-Q12STIRT"
PANEL = REPO / "notebooks" / "data" / "zq_kink_fade" / "contracts.parquet"


def curve_at(asset, ts):
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    return mdp.get_pricer({"curve_name": asset, "timestamp": ts})


def strip_from_curve(handle, codes, *, calendar_month: bool, is_ser: bool):
    """Curve-implied ZQ rate per contract, in percent."""
    import rateslib as rl
    from SDRUtils.stir_flow.ladder import contract_grid

    try:
        fixings = handle.index()
    except Exception:
        fixings = None
    dense = handle._rl_curve_handle
    grid = {bbg[2:]: (eff, mat) for bbg, eff, mat in
            contract_grid(datetime.date(2026, 7, 10), "ZQ", 24)}
    out = {}
    for c in codes:
        if calendar_month:
            s, e, _ = delivery_window(c)
            eff = datetime.datetime(s.year, s.month, s.day)
            mat = datetime.datetime(e.year, e.month, e.day)
        else:
            if c not in grid:
                continue
            eff, mat = grid[c]
            eff = pd.Timestamp(eff).to_pydatetime()
            mat = pd.Timestamp(mat).to_pydatetime()
        try:
            f = handle.build_stirf(effective_date=eff, maturity_date=mat,
                                   is_ser=is_ser, fixings=fixings)
            out[c] = float(f.rate(curves=dense).real)
        except Exception as exc:
            out[c] = np.nan
            print(f"    {c}: {type(exc).__name__}: {str(exc)[:90]}", flush=True)
    return pd.Series(out, name="curve_rate_pct")


def main() -> int:
    panel = pd.read_parquet(PANEL)
    panel["as_of"] = pd.to_datetime(panel["as_of"])

    for label, hh, mm in (("15:40 ET (the brief's timestamp)", 15, 40),
                          ("17:00 ET (matches the EOD settle)", 17, 0)):
        d = datetime.date(2026, 7, 10)
        ts = NY.localize(datetime.datetime(d.year, d.month, d.day, hh, mm))
        print("=" * 100, flush=True)
        print(f"GOLDEN TEST {d} {label}", flush=True)
        print("=" * 100, flush=True)

        handle = curve_at(ASSET, ts)
        print(f"curve: {type(handle).__name__}", flush=True)
        if handle is None:
            print("  NO CURVE -- store miss", flush=True)
            continue

        # the first 12 pre-accrual monthly contracts as of that date
        live = panel[(panel["as_of"] == pd.Timestamp(d)) & (~panel["accruing"])]
        live = live.sort_values("imm_start").head(12)
        codes = list(live["code"])
        actual = live.set_index("code")["rate_pct"]
        print(f"contracts: {codes}", flush=True)

        rows = {}
        for cm in (True, False):
            for ser in (True, False):
                tag = ("calendar-month" if cm else "business-day") + \
                      (" / usd_stir1 (AVG)" if ser else " / usd_stir (CMP)")
                rows[tag] = strip_from_curve(handle, codes, calendar_month=cm,
                                             is_ser=ser)
        tab = pd.DataFrame(rows)
        tab.insert(0, "actual_settle_pct", actual)
        for c in list(rows):
            tab[f"gap_bp::{c}"] = (tab[c] - tab["actual_settle_pct"]) * 100.0
        print("\ncurve-implied rate (percent) vs the actual ZQ settle:", flush=True)
        print(tab[["actual_settle_pct"] + list(rows)].round(4).to_string(), flush=True)
        print("\ngap to the settle, bp:", flush=True)
        gaps = tab[[f"gap_bp::{c}" for c in rows]]
        gaps.columns = list(rows)
        print(gaps.round(2).to_string(), flush=True)
        print("\nsummary (bp):", flush=True)
        print(pd.DataFrame({
            "mean_gap": gaps.mean(), "median_abs_gap": gaps.abs().median(),
            "max_abs_gap": gaps.abs().max(), "n": gaps.notna().sum(),
        }).round(3).to_string(), flush=True)

    # ---------------------------------------------------------------- SOFR
    print("\n" + "=" * 100, flush=True)
    print("CONTROL: the same machinery on the SOFR curve, for reference", flush=True)
    print("=" * 100, flush=True)
    ts = NY.localize(datetime.datetime(2026, 7, 10, 17, 0))
    h2 = curve_at(SOFR_ASSET, ts)
    if h2 is not None:
        live = panel[(panel["as_of"] == pd.Timestamp(2026, 7, 10))
                     & (~panel["accruing"])].sort_values("imm_start").head(6)
        s = strip_from_curve(h2, list(live["code"]), calendar_month=True, is_ser=True)
        cmp2 = pd.DataFrame({"actual_ZQ_settle": live.set_index("code")["rate_pct"],
                             "SOFR_curve_month_rate": s})
        cmp2["gap_bp"] = (cmp2["SOFR_curve_month_rate"]
                          - cmp2["actual_ZQ_settle"]) * 100.0
        print(cmp2.round(4).to_string(), flush=True)
        print("\n  A ZQ built on the SOFR curve should sit ABOVE the FF settle by")
        print("  roughly the SOFR-FF basis. If the MIX23 gap looks like this one,")
        print("  MIX23 is pricing SOFR, not EFFR.", flush=True)
    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
