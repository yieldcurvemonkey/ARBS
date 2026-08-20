r"""Build the 15:00->16:00 seam panel once, offline, and cache it.

Everything downstream in the seam study (reversal, level/slope/idio decomposition,
the holdings regression, the month-end event study) reads the SAME frame produced
here, so that a hygiene decision made once cannot silently differ between scripts.

What this does and why each step is here
----------------------------------------
* Reads the warmed Citi HOURLY ``YIELD`` layer for the 97-bond universe with
  ``CitiVeloQuotes(offline=True)`` -- no Excel, no add-in.
* Reads the New York marks through ``RVUtils.ETFRebalance.intraday.ny_marks``,
  which applies the measured START-STAMPED convention (the mark at 16:00 lives on
  the bar stamped 15). Re-deriving ``stamp = hour - 1`` by hand in each script is
  exactly how one of them ends up measuring 16:00->17:00 and calling it the seam.
* Applies the long-end possibility gate (``drop_impossible``).
* Flags **early-close days**. SIFMA recommends a 14:00 New York close about nine
  times a year (July 3, the Friday after Thanksgiving, Christmas Eve, and so on).
  On those dates the 15:00 and 16:00 "marks" are the same post-close stale quote,
  so the seam move is mechanically zero and a naive average is diluted toward it.
  The flag is measured, not imported from a calendar: a date is flagged when more
  than half the bonds show an EXACTLY zero 15->16 yield change. Both the flagged
  and unflagged results are reported downstream so the exclusion can be audited.

Outputs
-------
``_data/seam_panel.parquet``  one row per (date, cusip) with the New York marks at
10, 13, 14, 15, 16, 17 and the next business day's 10:00, plus universe metadata
and day-type flags.
``_data/seam_early_close_days.csv``  the flagged dates and the evidence.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "notebooks" / "backtests" / "etf_rebalance" / "_data"

from RVUtils.ETFRebalance import intraday as ID  # noqa: E402

#: New York clock hours whose marks the seam study needs.
HOURS = (10, 13, 14, 15, 16, 17)

#: A date is an early close when more than this fraction of the bonds carrying
#: both marks show an exactly-zero 15->16 change.
EARLY_CLOSE_ZERO_FRAC = 0.50


def build_marks() -> dict[int, pd.DataFrame]:
    frame = ID.hourly_frame("YIELD")
    frame = ID.drop_impossible(frame, "YIELD")
    print(f"hourly YIELD cache: {frame.shape[0]:,} rows x {frame.shape[1]} bonds  "
          f"{frame.index.min()} .. {frame.index.max()}", flush=True)
    marks = {}
    for h in HOURS:
        m = ID.ny_marks(frame, h)
        m = m[m.index.to_series().dt.weekday < 5]
        marks[h] = m
    return marks


def flag_early_close(m15: pd.DataFrame, m16: pd.DataFrame) -> pd.DataFrame:
    common = m15.index.intersection(m16.index)
    d = m16.loc[common] - m15.loc[common]
    n = d.notna().sum(axis=1)
    z = (d == 0.0).sum(axis=1)
    frac = (z / n.replace(0, np.nan)).rename("zero_frac")
    out = pd.DataFrame({"n_bonds": n, "n_zero": z, "zero_frac": frac})
    out["is_early_close"] = out["zero_frac"] > EARLY_CLOSE_ZERO_FRAC
    return out


def main() -> int:
    uni = ID.universe().set_index("isin")
    marks = build_marks()

    # Long format keyed on (date, isin).
    pieces = []
    for h, m in marks.items():
        s = m.stack(future_stack=True).rename(f"y{h:02d}")
        s.index.names = ["date", "isin"]
        pieces.append(s)
    panel = pd.concat(pieces, axis=1).reset_index()

    # Next BUSINESS day's 10:00 mark, aligned on the trading dates actually present
    # in the layer (not a synthetic bdate_range, which would step onto holidays).
    dates = pd.DatetimeIndex(sorted(marks[16].index.unique()))
    nxt = pd.Series(dates[1:], index=dates[:-1], name="next_date")
    m10 = marks[10].stack(future_stack=True).rename("y10_next")
    m10.index.names = ["next_date", "isin"]
    m16n = marks[16].stack(future_stack=True).rename("y16_next")
    m16n.index.names = ["next_date", "isin"]
    panel["next_date"] = panel["date"].map(nxt)
    panel = panel.merge(m10.reset_index(), on=["next_date", "isin"], how="left")
    panel = panel.merge(m16n.reset_index(), on=["next_date", "isin"], how="left")

    # Universe metadata.
    panel["cusip"] = panel["isin"].map(uni["cusip"])
    panel["maturity_date"] = panel["isin"].map(uni["maturity_date"])
    panel["issue_date"] = panel["isin"].map(uni["issue_date"])
    panel["cpn"] = panel["isin"].map(uni["coupon"]).astype(float)
    panel["held_by_tlt"] = panel["isin"].map(uni["held_by_tlt"]).astype(bool)
    panel["ttm"] = ((panel["maturity_date"] - panel["date"]).dt.days / 365.25)

    # The bond has to exist. Citi serves a tag before issue as empty, but a stray
    # pre-issue row would put a phantom into the cross-section.
    panel = panel[panel["date"] >= panel["issue_date"]]
    panel = panel[panel["ttm"] > 0]

    # Day-type flags.
    ec = flag_early_close(marks[15], marks[16])
    ec.to_csv(DATA / "seam_early_close_days.csv")
    flagged = ec.index[ec["is_early_close"]]
    print(f"early-close days flagged: {len(flagged)} of {len(ec)} "
          f"({100 * len(flagged) / max(1, len(ec)):.2f}%)", flush=True)
    print(pd.Series(flagged).dt.strftime("%Y-%m-%d").tolist(), flush=True)
    panel["is_early_close"] = panel["date"].isin(set(flagged))

    panel = panel.dropna(subset=["y15", "y16"], how="all")
    panel.to_parquet(DATA / "seam_panel.parquet", index=False)
    print(f"\nseam_panel.parquet: {len(panel):,} bond-dates, "
          f"{panel['date'].nunique():,} dates, {panel['isin'].nunique()} bonds, "
          f"{panel['date'].min().date()} .. {panel['date'].max().date()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
