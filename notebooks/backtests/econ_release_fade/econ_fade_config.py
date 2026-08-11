"""One dict describes one backtest.

``run_config`` takes a CONFIG and the raw release book and returns everything
needed to judge it: the trades, the funnel that explains every event that did
not become one, and the summary statistics. ``compare`` runs a list of configs
and stacks their summaries.

Two pricing paths are available and they answer the same question:

``engine=True``  drives the shipped ``QueryDrivenBacktest`` -- real queries,
                 real position handlers, real unwinds. This is what the
                 configurable notebook reports.
``engine=False`` prices the same book arithmetically off the same causal bars.
                 Hundreds of times faster, which is what makes a grid search
                 possible, and only trustworthy because
                 ``econ_fade_common.validate_fast_vs_engine`` asserts the two
                 agree trade for trade.
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

import econ_fade_common as G


@dataclass
class Result:
    config: dict
    book: G.Book
    closed: pd.DataFrame
    stats: Dict[str, Any]

    @property
    def funnel(self) -> Dict[str, Any]:
        return self.book.funnel

    @property
    def name(self) -> str:
        return self.config.get("name", "config")


def run_config(cfg: dict, raw: pd.DataFrame, *, engine: bool = True,
               show_progress: bool = False) -> Result:
    book = G.build_book(cfg, raw)
    closed = (G.run_backtest(book, show_progress=show_progress) if engine
              else G.fast_backtest(book))
    if engine and len(book.events) and len(closed) != len(book.events):
        # QueryDrivenBacktest.run() catches every exception and PRINTS it, so a
        # pricing failure degrades the book instead of stopping the run. A trade
        # count that does not match the gated event count is that happening --
        # INCLUDING the case where it swallowed every single one and handed back
        # a clean-looking empty book.
        raise RuntimeError(
            f"{book.config['name']}: engine booked {len(closed)} of {len(book.events)} "
            f"gated events -- the engine swallowed an exception. Check its stdout.")
    return Result(config=book.config, book=book, closed=closed,
                  stats=G.summarize(closed))


def compare(cfgs: Sequence[dict], raw: pd.DataFrame, *, engine: bool = False,
            show_tqdm: bool = True) -> Tuple[pd.DataFrame, Dict[str, Result]]:
    it = list(cfgs)
    if show_tqdm:
        try:
            from tqdm.auto import tqdm
            it = tqdm(it, desc="configs")
        except Exception:  # noqa: BLE001
            pass

    out: Dict[str, Result] = {}
    rows: List[dict] = []
    errors: Dict[str, str] = {}
    for c in it:
        nm = c.get("name", "config")
        try:
            r = run_config(c, raw, engine=engine)
        except Exception as ex:  # noqa: BLE001
            # One un-priceable instrument must not take a whole sweep with it --
            # but it is RECORDED and printed, never swallowed. A row of NaN with
            # a reason is a result; a sweep that silently lost a leg is not.
            errors[nm] = f"{type(ex).__name__}: {ex}"[:200]
            rows.append({"config": nm, "trades": 0, "total_bp": np.nan, "avg_bp": np.nan,
                         "hit_rate": np.nan, "sharpe": np.nan, "sr_per_trade": np.nan,
                         "t_stat": np.nan, "max_dd_bp": np.nan, "error": errors[nm][:80]})
            continue
        out[nm] = r
        s = r.stats
        rows.append({
            "config": nm,
            "trades": s.get("trades", 0),
            "total_bp": s.get("total_bp", np.nan),
            "avg_bp": s.get("avg_bp", np.nan),
            "hit_rate": s.get("hit_rate", np.nan),
            "sharpe": s.get("sharpe", np.nan),
            "sr_per_trade": s.get("sr_per_trade", np.nan),
            "t_stat": s.get("t_stat", np.nan),
            "max_dd_bp": s.get("max_dd_bp", np.nan),
            "error": "",
        })
    tbl = pd.DataFrame(rows).set_index("config")
    if errors:
        print(f"{len(errors)} of {len(rows)} configurations could not be priced:")
        for nm, e in list(errors.items())[:10]:
            print(f"  {nm}: {e}")
    if "error" in tbl.columns and (tbl["error"] == "").all():
        tbl = tbl.drop(columns=["error"])
    return tbl, out


def spec(name: str, **over) -> dict:
    """A named config: DEFAULT_CONFIG with the given sub-dicts merged in."""
    c = copy.deepcopy(G.DEFAULT_CONFIG)
    c["name"] = name
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k].update(v)
        else:
            c[k] = v
    return c


def variant(base: dict, name: str, **over) -> dict:
    c = copy.deepcopy(base)
    c["name"] = name
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k] = {**c[k], **v}
        else:
            c[k] = v
    return c


# ===========================================================================
# Placebos
# ===========================================================================
def placebo_shift(raw: pd.DataFrame, *, days: int = 1, business_days: bool = True,
                  avoid_real: bool = True) -> pd.DataFrame:
    """The same book, on the WRONG day.

    Every release timestamp is moved by ``days`` onto a minute that had no
    release. Time of day, instrument, contract, holding period and the whole
    gate are unchanged; only the reason for trading is gone. An edge that
    survives this is a time-of-day effect -- 08:30 ET is also an hour before the
    cash equity open and the start of the most liquid stretch of the Treasury
    session -- and not a release effect.

    Two details decide whether this is a control or a different sample.

    **The shift is in BUSINESS days.** A calendar shift of +1 moves every Friday
    release to a Saturday, where the causal gate deletes it as ``no_bars_that
    day``. Non-farm payrolls is a Friday release, and jobless claims is a
    Thursday one, so a calendar +1/+2 placebo is not the same book on a quiet
    day -- it is the book with its two largest families removed, and the
    distribution it produces is skewed by the composition change rather than by
    the absence of news.

    **Shifted minutes that land on a REAL release are dropped.** A weekly print
    shifted by exactly a week lands on next week's print, which would make the
    placebo a second copy of the real book.
    """
    df = raw.copy()
    tz = raw["release_ts_ny"].iloc[0].tz

    if business_days:
        off = pd.offsets.BDay(abs(int(days)))
        # Shift in NEW YORK time, then convert back. Adding a business day to a
        # UTC-stamped release preserves the UTC wall clock, so a shift across a
        # DST boundary lands an 08:30 New York release at 09:30 New York -- and
        # the one thing this control has to hold fixed is the time of day.
        def shift(t, _off=off, _tz=tz, _fwd=days >= 0):
            local = pd.Timestamp(t).tz_convert(_tz)
            moved = (local + _off) if _fwd else (local - _off)
            return moved.tz_convert("UTC")
    else:
        off = pd.Timedelta(days=int(days))
        shift = lambda t: t + off  # noqa: E731
    df["orig_weekday"] = df["release_ts_ny"].apply(lambda t: t.strftime("%a"))
    df["orig_title"] = df["lead_title"].astype(str)
    df["release_ts"] = df["release_ts"].apply(shift)
    df["release_ts_ny"] = df["release_ts"].apply(lambda t: t.tz_convert(tz))
    df["date"] = df["release_ts_ny"].apply(lambda t: t.date())

    if avoid_real:
        real = set(pd.to_datetime(raw["release_ts"], utc=True))
        keep = ~pd.to_datetime(df["release_ts"], utc=True).isin(real)
        df = df[keep]

    df["lead_title"] = "PLACEBO " + df["lead_title"].astype(str)
    return df.sort_values("release_ts").reset_index(drop=True)


def placebo_composition(raw: pd.DataFrame, shifted: pd.DataFrame,
                        by: str = "weekday") -> pd.DataFrame:
    """How much of each release family the placebo kept.

    Grouped on the ORIGINAL weekday or title, not the shifted one -- the
    question is "did payrolls survive the shift", and grouping on where the
    trades landed cannot answer it. A family whose ``kept %`` is far below the
    others makes the placebo a different sample rather than a control.
    """
    if by == "weekday":
        a = raw["release_ts_ny"].apply(lambda t: t.strftime("%a"))
        b = shifted["orig_weekday"]
    else:
        a = raw["lead_title"].astype(str)
        b = shifted["orig_title"]
    out = pd.concat([a.value_counts().rename("real"),
                     b.value_counts().rename("placebo")], axis=1).fillna(0).astype(int)
    out["kept %"] = (out["placebo"] / out["real"].replace(0, np.nan) * 100).round(1)
    return out.sort_values("real", ascending=False)


def placebo_shuffle_direction(closed: pd.DataFrame, seed: int = 3) -> pd.DataFrame:
    """Keep the trades, randomise which way round they were taken."""
    rng = np.random.default_rng(seed)
    d = closed.copy()
    flip = rng.choice([-1.0, 1.0], size=len(d))
    d["pnl_bp_gross"] = d["pnl_bp_gross"] * flip
    d["pnl_bp"] = d["pnl_bp_gross"] - d["cost_bp"]
    d["profitable"] = d["pnl_bp"] > 0
    return d


# ===========================================================================
# Recipes
# ===========================================================================
BASELINE = spec("baseline")

RECIPES: Dict[str, dict] = {
    "tier 1 only": spec("tier 1 only", events={"impacts": ["high"]}),
    "tier 1+2": spec("tier 1+2", events={"impacts": ["high", "medium"]}),
    "CPI only": spec("CPI only", events={"impacts": ["high", "medium"],
                                         "titles_include": [r"\bCPI\b"]}),
    # ANCHORED. An unanchored "Non-Farm Employment Change" also matches
    # "ADP Non-Farm Employment Change" -- a private payroll estimate released on
    # a different day of the month, which made the "payrolls" book 44% ADP.
    "payrolls only": spec("payrolls only",
                          events={"impacts": ["high", "medium"],
                                  "titles_include": [r"^Non-Farm Employment Change$"]}),
    "08:30 block": spec("08:30 block", events={"impacts": ["high", "medium"],
                                               "release_times_ny": ["08:30"]}),
    "10:00 block": spec("10:00 block", events={"impacts": ["high", "medium"],
                                               "release_times_ny": ["10:00"]}),
    "clustered prints": spec("clustered prints",
                             events={"impacts": ["high", "medium"],
                                     "min_events_in_minute": 2}),
    "surprises only": spec("surprises only", events={"surprise": "surprised"}),
    "fast T+2/T+15": spec("fast T+2/T+15",
                          timing={"entry_offset_min": 2, "exit_offset_min": 15}),
    "slow T+2/T+240": spec("slow T+2/T+240",
                           timing={"entry_offset_min": 2, "exit_offset_min": 240}),
    "big moves only": spec("big moves only", signal={"min_move_bp": 2.0}),
    "momentum (placebo)": spec("momentum (placebo)", signal={"direction": "momentum"}),
    "10y future": spec("10y future", instrument={"family": "ust", "root": "TY", "rank": 1}),
    "2y future": spec("2y future", instrument={"family": "ust", "root": "TU", "rank": 1}),
    "net of 0.5bp": spec("net of 0.5bp", cost_bp=0.5),
}
