"""Trade the SURPRISE, not the price move.

Every earlier study in this directory measures the burst in the first minute and
takes the other side of it. That signal is derived from the price, which creates
a subtle problem: the same bid-ask bounce that sets the sign also sets the entry,
and the two have to be separated by construction (see
``assert_entry_is_after_the_signal``).

This one has no such problem. The signal is ``actual - consensus``, published on
the wire at the release minute and completely independent of what the price did.
There is nothing for the entry to be contaminated by.

The hypothesis, in the user's terms: a large surprise either **fades** -- the
initial move overshoots and comes back -- or it **reprices the regime**, and the
move keeps going. Those need opposite positions, and the asymmetry is the
strategy: take the fade, and if it turns out to be a repricing, a tight stop caps
what that costs. ``mode="fade_then_flip"`` goes further and reverses into the
move after being stopped.

Standardisation is POINT-IN-TIME and ROBUST
-------------------------------------------
A surprise in thousands of payrolls and a surprise in tenths of a percent of CPI
cannot be compared raw, so each is divided by its own scale. Two decisions there
are load-bearing.

*Point-in-time.* The scale at date ``t`` uses only surprises strictly before
``t``. A full-sample standard deviation would let 2026 tell 2019 how big a
surprise was. The workbook carries history back to 2012-2014, so by the start of
the backtest in 2019 every release already has 60+ prior observations and the
standardisation is estimated almost entirely out of sample.

*Robust.* Non-farm payrolls in 2020 printed a surprise of +10,839k against a
sample standard deviation of 856k. A mean-and-standard-deviation z would be
dragged around by those two months for years afterwards; a median and a MAD is
barely moved. Both are available and the choice is a config knob, because it is
a real modelling choice rather than an obvious one.

Direction
---------
For all three releases a beat is hawkish -- more inflation, more jobs, higher
rates -- so ``rate_dir = +sign(surprise)`` means "the release implies rates up".
Rates up is a lower futures price, so:

    fade      side = +rate_dir     expect the overshoot back -> long the future
    momentum  side = -rate_dir     expect the repricing to run -> short it

which is the same convention ``econ_fade_common`` uses with ``sign(move_bp)``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

import econ_fade_common as G
import econ_fade_exits as X

__all__ = [
    "SHEET_TO_TITLE", "load_surprises", "build_surprise_events", "build_surprise_book",
    "run_surprise_bracket", "point_in_time_z",
]

#: workbook sheet -> ForexFactory title, and whether a BEAT implies higher rates.
#: All three are +1: more inflation, more producer prices, more jobs all argue
#: for a higher policy path. A release like jobless claims would be -1, and
#: getting that sign wrong would silently invert the whole study -- which is why
#: it is a table rather than an assumption.
SHEET_TO_TITLE: Dict[str, Tuple[str, int]] = {
    "core cpi mom": ("Core CPI m/m", +1),
    "ppi mom": ("PPI m/m", +1),
    "nfp": ("Non-Farm Employment Change", +1),
}


def load_surprises(xlsx: str | Path) -> pd.DataFrame:
    """Parse the Citi Velocity CVTSHIST export into a tidy frame.

    Each sheet is one release: row 0 is the CVTSHIST formula, row 1 the column
    names, and the data descends from there.
    """
    xl = pd.ExcelFile(xlsx)
    out = []
    for sheet in xl.sheet_names:
        raw = xl.parse(sheet, header=None)
        body = raw.iloc[2:, :3].copy()
        body.columns = ["date", "actual", "expected"]
        body["date"] = pd.to_datetime(body["date"], errors="coerce")
        for c in ("actual", "expected"):
            body[c] = pd.to_numeric(body[c], errors="coerce")
        body = body.dropna(subset=["date", "actual", "expected"])
        body["sheet"] = sheet
        body["surprise"] = body["actual"] - body["expected"]
        out.append(body.sort_values("date"))
    df = pd.concat(out, ignore_index=True)
    return df.sort_values(["sheet", "date"]).reset_index(drop=True)


def point_in_time_z(surprises: pd.DataFrame, *, robust: bool = True,
                    min_obs: int = 12, scale_window: Optional[int] = None,
                    z_cap: Optional[float] = 5.0) -> pd.DataFrame:
    """Standardise each release's surprise using only its own past.

    ``shift(1)`` on the expanding statistic is what makes it point-in-time: the
    location and scale used at date t are computed from dates strictly before t.
    Without it the z-score of the largest surprise in the sample is deflated by
    its own contribution to the scale, which flatters every threshold filter
    built on top of it.
    """
    out = []
    for sheet, g in surprises.groupby("sheet", sort=False):
        g = g.sort_values("date").copy()
        s = g["surprise"]
        # A ROLLING scale adapts; an expanding one does not. Measured on
        # non-farm payrolls: an expanding MAD estimated from 2012-2019 data is
        # never widened by 2020, so the June-2020 surprise of +10,839k against a
        # scale of 61k scores z = 178 and every threshold filter above |z| = 2
        # becomes almost entirely payrolls. A 36-observation window lets the
        # scale learn that the world changed.
        win = None if scale_window is None else int(scale_window)
        roll = (lambda x: x.rolling(win, min_periods=max(6, min_obs))) if win             else (lambda x: x.expanding())
        if robust:
            loc = roll(s).median().shift(1)
            scale = roll((s - loc).abs()).median().shift(1) * 1.4826
        else:
            loc = roll(s).mean().shift(1)
            scale = roll(s).std(ddof=1).shift(1)
        n_prior = np.arange(len(g))
        z = (s - loc) / scale.replace(0.0, np.nan)
        z[n_prior < min_obs] = np.nan
        if z_cap is not None:
            # Winsorised, not dropped. The 2020 payrolls prints are real events a
            # desk had to trade; capping keeps them in the book at the top of the
            # ranking without letting one observation define what "large" means.
            z = z.clip(-float(z_cap), float(z_cap))
        g["surprise_loc"] = loc.to_numpy()
        g["surprise_scale"] = scale.to_numpy()
        g["z"] = z.to_numpy()
        g["n_prior"] = n_prior
        out.append(g)
    return pd.concat(out, ignore_index=True)


def build_surprise_events(surprises: pd.DataFrame, raw: pd.DataFrame,
                          *, sheets: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Attach each surprise to the calendar minute its release printed in."""
    ex = raw.explode("titles")
    rows = []
    for sheet, (title, hawkish) in SHEET_TO_TITLE.items():
        if sheets is not None and sheet not in sheets:
            continue
        cal = ex[ex["titles"] == title][
            ["release_ts", "release_ts_ny", "date", "titles", "lead_title",
             "n_events", "impact", "lead_outcome"]].copy()
        sub = surprises[surprises["sheet"] == sheet].copy()
        sub["d"] = sub["date"].dt.date
        j = sub.merge(cal.assign(d=cal["date"]), on="d", how="inner", suffixes=("", "_cal"))
        j["release"] = title
        j["hawkish_sign"] = hawkish
        j["rate_dir"] = hawkish * np.sign(j["surprise"])
        rows.append(j)
    out = pd.concat(rows, ignore_index=True)
    out = out.drop(columns=["d"]).sort_values("release_ts").reset_index(drop=True)
    return out


@dataclass
class SurpriseBook:
    """The same shape ``econ_fade_exits`` and ``econ_fade_mdp_exits`` consume."""

    config: dict
    instrument: G.Instrument
    events: pd.DataFrame
    funnel: Dict[str, Any]


DEFAULT_SURPRISE_CONFIG: Dict[str, Any] = {
    "name": "surprise",
    "instrument": {"family": "ust", "root": "TY", "rank": 1},
    "releases": ["core cpi mom", "ppi mom", "nfp"],
    "z": {"robust": True, "min_obs": 12, "min_abs_z": 0.0, "max_abs_z": None,
          "scale_window": 36, "z_cap": 5.0},
    "timing": {"entry_offset_min": 2, "max_staleness_min": 5},
    "signal": {"direction": "fade"},          # fade | momentum | fade_then_flip
    "contracts": 1,
}


def _merge(cfg: Optional[dict]) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
           for k, v in DEFAULT_SURPRISE_CONFIG.items()}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def build_surprise_book(cfg: Optional[dict], surprises: pd.DataFrame,
                        raw: pd.DataFrame) -> SurpriseBook:
    """Release minutes with a consensus -> the trades this config would take.

    The gate is the same one the rest of the study uses: an event survives only
    if the MDP-convention price exists at the entry minute. The signal, however,
    needs no price at all -- so unlike the move-based studies, an event is never
    dropped for "the release moved nothing".
    """
    cfg = _merge(cfg)
    inst = G.INSTRUMENTS[cfg["instrument"]["root"]]
    rank = int(cfg["instrument"].get("rank", 1))
    zc = cfg["z"]

    funnel: Dict[str, Any] = {"surprise rows": int(len(surprises))}
    z = point_in_time_z(surprises, robust=bool(zc["robust"]), min_obs=int(zc["min_obs"]),
                        scale_window=zc.get("scale_window"), z_cap=zc.get("z_cap"))
    ev = build_surprise_events(z, raw, sheets=cfg["releases"])
    funnel["joined to a release minute"] = int(len(ev))

    ev = ev[ev["z"].notna()]
    funnel["after point-in-time history requirement"] = int(len(ev))

    lo = float(zc.get("min_abs_z") or 0.0)
    if lo > 0:
        n0 = len(ev)
        ev = ev[ev["z"].abs() >= lo]
        funnel[f"dropped: |z| < {lo:g}"] = int(n0 - len(ev))
    hi = zc.get("max_abs_z")
    if hi is not None:
        n0 = len(ev)
        ev = ev[ev["z"].abs() <= float(hi)]
        funnel[f"dropped: |z| > {float(hi):g}"] = int(n0 - len(ev))

    n0 = len(ev)
    ev = ev[ev["rate_dir"] != 0]
    if n0 - len(ev):
        funnel["dropped: actual equalled consensus"] = int(n0 - len(ev))

    if ev.empty:
        funnel["TRADEABLE"] = 0
        return SurpriseBook(cfg, inst, ev, funnel)

    ev = ev.copy()
    ev["symbol"] = [G.contract_for(inst, d, rank) for d in ev["date_cal"]]
    ev["local_ts"] = ev["release_ts"].apply(lambda t: t.tz_convert(inst.tz))
    ev["entry_ts"] = ev["local_ts"] + pd.Timedelta(minutes=int(cfg["timing"]["entry_offset_min"]))
    ev["px_per_bp"] = [G.px_per_bp(inst, s) for s in ev["symbol"]]

    # The gate: can the provider price the entry minute? Nothing else is needed,
    # because the signal came off the wire rather than off the tape.
    import econ_fade_mdp_exits as MX
    entry_px = [MX._minute_close(s, t) for s, t in zip(ev["symbol"], ev["entry_ts"])]
    ev["entry_px"] = entry_px
    n0 = len(ev)
    ev = ev[ev["entry_px"].notna()]
    funnel["dropped: no print at the entry minute"] = int(n0 - len(ev))

    direction = cfg["signal"]["direction"]
    flip = -1.0 if direction == "momentum" else 1.0
    ev["side"] = flip * ev["rate_dir"].astype(float)
    ev["contracts"] = int(cfg.get("contracts", 1))
    # move_bp is carried so the fractional brackets in ExitRule have a scale.
    # Here it is the SURPRISE in units of its own robust sigma, not a price move.
    ev["move_bp"] = ev["z"].astype(float)
    ev["tag"] = [f"{cfg['name']}|{s}|{t.strftime('%Y%m%d%H%M')}"
                 for s, t in zip(ev["symbol"], ev["entry_ts"])]
    ev = ev.reset_index(drop=True)
    funnel["TRADEABLE"] = int(len(ev))
    return SurpriseBook(cfg, inst, ev, funnel)


def run_surprise_bracket(book: SurpriseBook, rule: X.ExitRule, *,
                         cost_bp: float = 0.0, flip_rule: Optional[X.ExitRule] = None,
                         ) -> pd.DataFrame:
    """Price the book with a bracket, optionally reversing after a stop.

    ``flip_rule`` implements the second half of the hypothesis. If the fade is
    stopped, that is evidence the release repriced the regime rather than
    overshooting -- so the position is reversed for the remainder of the window
    under its own bracket. The reversal is booked as a SEPARATE trade with its
    own tag, so it is a real second round trip and pays a second round of costs
    rather than being netted invisibly into the first.
    """
    import econ_fade_mdp_exits as MX

    base = MX.run_bracket_fast(book, rule, cost_bp=cost_bp)      # type: ignore[arg-type]
    if base.empty or flip_rule is None:
        return base

    stopped = base[base["exit_reason"].isin(["stop", "trail"])]
    if stopped.empty:
        base["leg"] = 1
        return base

    legs: List[pd.DataFrame] = [base.assign(leg=1)]
    ev = book.events.set_index("tag")
    rows = []
    for _, r in stopped.iterrows():
        src = ev.loc[r["tag"]]
        remaining = int(rule.time_stop_min) - int(round(r["hold_min"]))
        if remaining <= 1:
            continue
        flipped = src.copy()
        flipped["side"] = -float(src["side"])
        flipped["entry_ts"] = r["exit_ts_rule"]
        px = MX._minute_close(src["symbol"], r["exit_ts_rule"])
        if px is None:
            continue
        flipped["entry_px"] = px
        flipped["tag"] = f"{r['tag']}|flip"
        rows.append(flipped)
    if not rows:
        base["leg"] = 1
        return base

    flip_book = SurpriseBook(book.config, book.instrument,
                             pd.DataFrame(rows).reset_index(drop=True), {})
    fr = X.ExitRule(name=flip_rule.name, tp_bp=flip_rule.tp_bp, tp_frac=flip_rule.tp_frac,
                    sl_bp=flip_rule.sl_bp, sl_frac=flip_rule.sl_frac,
                    trail_bp=flip_rule.trail_bp, time_stop_min=int(rule.time_stop_min),
                    min_hold_min=flip_rule.min_hold_min, mode="close")
    leg2 = MX.run_bracket_fast(flip_book, fr, cost_bp=cost_bp)   # type: ignore[arg-type]
    if not leg2.empty:
        legs.append(leg2.assign(leg=2))
    out = pd.concat(legs, ignore_index=True)
    return out.sort_values("release_ts").reset_index(drop=True)


def shift_surprise_book(book: SurpriseBook, days: int = 1,
                        avoid: Optional[set] = None) -> SurpriseBook:
    """The same surprises, the same sides, the same clock -- the WRONG day.

    The placebo for a move-based study can be built by shifting the calendar and
    rebuilding, because the signal is read off the price. This signal is not: it
    is joined to the calendar ON DATE, so shifting the calendar destroys the join
    and returns an EMPTY book -- which reads as "the placebo made nothing" and is
    the most flattering possible failure. Measured: the pooled-calendar placebo
    produced zero events and printed nothing at all.

    So the shift is applied to the BOOK. Every event keeps its surprise, its
    z-score and the side that surprise implies, and only the minute it is traded
    in moves. What is removed is the coincidence of the two: the position is the
    one the release argued for, taken on a day when that release did not happen.
    """
    import econ_fade_mdp_exits as MX

    ev = book.events
    if ev.empty:
        return book
    off = pd.offsets.BDay(abs(int(days)))
    fwd = days >= 0
    tz = ev["local_ts"].iloc[0].tz

    out = ev.copy()
    def _mv(t):
        loc = pd.Timestamp(t).tz_convert(tz)
        return (loc + off) if fwd else (loc - off)

    out["local_ts"] = out["local_ts"].apply(_mv)
    out["entry_ts"] = out["entry_ts"].apply(_mv)
    out["release_ts"] = out["local_ts"].apply(lambda t: t.tz_convert("UTC"))
    out["date_cal"] = out["local_ts"].apply(lambda t: t.date())
    # The contract is re-resolved for the shifted date -- a shift across a roll
    # must trade the contract that was actually front THEN, not the original one.
    inst = book.instrument
    rank = int(book.config["instrument"].get("rank", 1))
    out["symbol"] = [G.contract_for(inst, d, rank) for d in out["date_cal"]]
    out["px_per_bp"] = [G.px_per_bp(inst, s) for s in out["symbol"]]
    out["entry_px"] = [MX._minute_close(s, t) for s, t in zip(out["symbol"], out["entry_ts"])]
    out = out[out["entry_px"].notna()]

    if avoid is not None:
        # A shifted minute that lands on ANOTHER real tier-1/2 release is not a
        # control -- it is a different release. Measured on this book: a -1
        # business-day shift of payrolls lands on Thursday, which is jobless
        # claims at the same 08:30, and 59% of that replica's events sat on a
        # real release minute (+1bd 38%, +2bd 40%, +3bd 43%, +5bd 44%). Without
        # this the "no news" placebo is substantially a news placebo.
        keep = ~pd.to_datetime(out["release_ts"], utc=True).isin(avoid)
        out = out[keep]
    out = out.reset_index(drop=True)
    out["tag"] = [f"{book.config['name']}|shift{days:+d}|{s}|{t.strftime('%Y%m%d%H%M')}"
                  for s, t in zip(out["symbol"], out["entry_ts"])]
    funnel = dict(book.funnel)
    funnel[f"placebo shift {days:+d}bd, priceable"] = int(len(out))
    return SurpriseBook(book.config, inst, out, funnel)
