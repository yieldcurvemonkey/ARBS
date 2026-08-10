"""One dict describes one backtest.

The hand-labelled study fixed every choice it made: the 3rd quarterly contract,
a T-45/T+180 window, every speaker the roster carried. Each of those was a
decision, and none of them was obviously right. This module makes them
parameters, so a config is a complete description of a backtest and two configs
can be compared without editing code.

    CONFIG = {
        "instrument": {"kind": "outright", "rank": 3},
        "timing":     {"entry_offset_min": -45, "exit_offset_min": 180},
        "filters":    {"voters": "voters", "roles": ["President"]},
        "sizing":     "equal",
        "cost_bp":    0.25,
    }
    res = run_config(CONFIG, raw_events, mdp)

Three things this deliberately does NOT let a config do.

**It cannot fetch.** Barchart's fetcher raises inside a Jupyter kernel, so a
config whose bars are not already cached is refused up front by
``check_coverage`` with the exact prewarm command — never half-run, and never
silently reduced to whatever happened to be warm.

**It cannot resolve overlaps after filtering.** The one-position-at-a-time rule
runs AFTER the filters, on the filtered book. That is the whole reason this reads
the raw pre-overlap event dump: filtering the already-resolved book would inherit
an overlap decision made by speeches the config is no longer trading. A
voters-only config here trades more voter events than a voters-only *split* of
the mixed book does, and it is the config that answers "what if I only traded
voters".

**It cannot search for you.** Every knob added here multiplies the number of
configurations that can be tried, and ranking a few hundred of them by Sharpe
finds a good one whether or not any signal exists. ``compare`` reports the trial
count for that reason; treat a winner picked from a wide sweep as a hypothesis.
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

import global_hawk_dove_common as G
import global_hawk_dove_grid as GRID
import fomc_extras as FX


# ===========================================================================
# The config
# ===========================================================================
DEFAULT_CONFIG: Dict[str, Any] = {
    "name": "baseline",
    "bank": "FED",

    # WHAT IS TRADED ------------------------------------------------------
    # {"kind": "outright", "rank": n}                a single quarterly contract
    # {"structure": "FLY_2_3_4"}                     a named package (see catalogue)
    # {"legs": [[2, -1.0], [4, 1.0]], "name": "..."} explicit RATE-space weights
    "instrument": {"kind": "outright", "rank": 3},

    # WHEN ----------------------------------------------------------------
    "timing": {
        "entry_offset_min": -45,     # relative to the speech, market-local
        "exit_offset_min": 180,
        "max_staleness_min": 45,     # how old the causal bar may be
        # Synthetic events know the DAY but not the minute, so they trade the
        # session. Re-timing them around a made-up 09:00 would be inventing
        # precision that does not exist; off by default.
        "retime_synthetic": False,
    },

    # WHO / WHICH TRADES --------------------------------------------------
    "filters": {
        "start": None,               # "2022-01-01"
        "end": None,
        "voters": "all",             # all | voters | nonvoters
        "roles": None,               # ["Chair","Governor","President","President (NY)"]
        "speakers_include": None,
        "speakers_exclude": None,
        "timestamp_source": "all",   # all | forexfactory | synthetic
        "min_abs_bucket": 1,         # 2 = conviction trades only
        "direction": "both",         # both | hawk | dove
        "era": "all",                # all | GE | SR3
        "days_to_fomc_max": None,    # e.g. 10 -> only the run-up to a meeting
        "days_to_fomc_min": None,
        "weekdays": None,            # [0..4], Monday=0
    },

    # HOW MUCH ------------------------------------------------------------
    "sizing": "equal",               # equal | conviction  (x |bucket|)
    "cost_bp": 0.0,                  # round trip, per unit of gross risk
}


def merge(*overrides: Dict[str, Any]) -> Dict[str, Any]:
    """DEFAULT_CONFIG with nested overrides applied, left to right."""
    out = copy.deepcopy(DEFAULT_CONFIG)
    for o in overrides:
        for k, v in (o or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = v
    return out


# ===========================================================================
# Instruments
# ===========================================================================
def catalogue(max_rank: int = 6) -> Dict[str, GRID.Structure]:
    """Every named package the config can ask for, keyed by name."""
    return {s.name: s for s in GRID.build_structures(max_rank)}


def resolve_instrument(spec: Dict[str, Any], max_rank: int = 8) -> GRID.Structure:
    if "legs" in spec:
        legs = tuple((int(r), float(w)) for r, w in spec["legs"])
        kind = spec.get("kind") or ("outright" if len(legs) == 1 else "custom")
        return GRID.Structure(spec.get("name") or
                              "_".join(f"{r}x{w:g}" for r, w in legs), kind, legs)
    if "structure" in spec:
        cat = catalogue(max_rank)
        if spec["structure"] not in cat:
            raise KeyError(f"unknown structure {spec['structure']!r}; "
                           f"have {sorted(cat)}")
        return cat[spec["structure"]]
    kind = spec.get("kind", "outright")
    if kind != "outright":
        raise ValueError(f"instrument kind {kind!r} needs 'structure' or 'legs'")
    n = int(spec.get("rank", 3))
    return GRID.Structure(f"OUT_{n}", "outright", ((n, 1.0),))


# ===========================================================================
# Filters — applied BEFORE the overlap rule
# ===========================================================================
_ROLE_CACHE: Dict[Any, Any] = {}


def _meetings() -> List[datetime.date]:
    if "m" not in _ROLE_CACHE:
        _ROLE_CACHE["m"] = FX.fomc_decision_dates()
    return _ROLE_CACHE["m"]


def event_attrs(ev: dict) -> dict:
    """The per-event facts the filters read. All known at trade time."""
    d = ev["speech_ts"].date()
    sym = ev["symbol"]
    return {
        "date": d,
        "role": FX.role_of(ev["speaker"], d),
        "is_voter": FX.is_voter(ev["speaker"], d),
        "days_to_fomc": FX.days_to_next_meeting(d, _meetings()),
        "era": "GE" if sym.startswith("GE") else "SR3",
        "weekday": d.weekday(),
    }


def apply_filters(events: List[dict], f: Dict[str, Any]) -> tuple:
    """-> (kept, {reason: n}). Reasons are counted, never swallowed."""
    from collections import defaultdict
    dropped: Dict[str, int] = defaultdict(int)
    kept: List[dict] = []
    start = pd.Timestamp(f["start"]).date() if f.get("start") else None
    end = pd.Timestamp(f["end"]).date() if f.get("end") else None

    for ev in events:
        a = event_attrs(ev)
        if start and a["date"] < start:
            dropped["before_start"] += 1; continue
        if end and a["date"] > end:
            dropped["after_end"] += 1; continue

        v = f.get("voters", "all")
        if v == "voters" and a["is_voter"] is not True:
            dropped["not_a_voter"] += 1; continue
        if v == "nonvoters" and a["is_voter"] is not False:
            dropped["is_a_voter_or_unknown"] += 1; continue

        if f.get("roles") and a["role"] not in f["roles"]:
            dropped["role"] += 1; continue
        if f.get("speakers_include") and ev["speaker"] not in f["speakers_include"]:
            dropped["speaker_not_included"] += 1; continue
        if f.get("speakers_exclude") and ev["speaker"] in f["speakers_exclude"]:
            dropped["speaker_excluded"] += 1; continue

        ts = f.get("timestamp_source", "all")
        if ts != "all" and ev.get("timestamp_source", "forexfactory") != ts:
            dropped["timestamp_source"] += 1; continue

        if abs(ev["bucket"]) < int(f.get("min_abs_bucket", 1)):
            dropped["below_min_conviction"] += 1; continue
        dirn = f.get("direction", "both")
        if dirn == "hawk" and ev["bucket"] <= 0:
            dropped["not_hawk"] += 1; continue
        if dirn == "dove" and ev["bucket"] >= 0:
            dropped["not_dove"] += 1; continue

        if f.get("era", "all") != "all" and a["era"] != f["era"]:
            dropped["era"] += 1; continue

        dmax, dmin = f.get("days_to_fomc_max"), f.get("days_to_fomc_min")
        if dmax is not None and (a["days_to_fomc"] is None or a["days_to_fomc"] > dmax):
            dropped["too_far_from_fomc"] += 1; continue
        if dmin is not None and (a["days_to_fomc"] is None or a["days_to_fomc"] < dmin):
            dropped["too_close_to_fomc"] += 1; continue

        if f.get("weekdays") is not None and a["weekday"] not in f["weekdays"]:
            dropped["weekday"] += 1; continue

        e = dict(ev)
        e["_attrs"] = a
        kept.append(e)
    return kept, dict(dropped)


# ===========================================================================
# Re-timing
# ===========================================================================
def retime(events: List[dict], cfg: G.CBConfig, entry_min: int, exit_min: int,
           retime_synthetic: bool = False) -> tuple:
    """Move entry/exit relative to the speech, re-clamping into the session.

    ``G.rebuild_with_offsets`` would do this, but it re-times SYNTHETIC events
    too — and a synthetic event's ``speech_ts`` is not a speech time, it is the
    session open standing in for a minute nobody recorded. Offsetting from it
    invents precision. Those events keep their session window unless asked.
    """
    entry_off = datetime.timedelta(minutes=int(entry_min))
    exit_off = datetime.timedelta(minutes=int(exit_min))
    out, dropped = [], 0
    for ev in events:
        if ev.get("timestamp_source") == "synthetic" and not retime_synthetic:
            out.append(dict(ev))
            continue
        s = ev["speech_ts"]
        day_open = s.replace(hour=cfg.session_start.hour,
                             minute=cfg.session_start.minute, second=0, microsecond=0)
        day_close = s.replace(hour=cfg.session_end.hour,
                              minute=cfg.session_end.minute, second=0, microsecond=0)
        entry_ts = max(s + entry_off, day_open)
        exit_ts = min(s + exit_off, day_close)
        if exit_ts - entry_ts < datetime.timedelta(minutes=30):
            dropped += 1
            continue
        e = dict(ev)
        e["entry_ts"], e["exit_ts"] = entry_ts, exit_ts
        out.append(e)
    kept, n_ovl = G.drop_overlaps(out)
    return kept, {"window_too_short": dropped, "overlap": n_ovl}


# ===========================================================================
# Bar coverage — the notebook cannot fetch, so refuse rather than under-run
# ===========================================================================
def check_coverage(events: List[dict], cfg: G.CBConfig,
                   ranks: Sequence[int]) -> Dict[str, Any]:
    want = set()
    for rank in ranks:
        for e in G.rebuild_with_contract(events, cfg, rank):
            want.add((e["symbol"], e["entry_ts"].date()))
    missing = sorted(want - set(G._BAR_CACHE))
    return {"wanted": len(want), "missing": missing,
            "ok": not missing,
            "hint": ("python _prewarm_manual_ranks.py --events events_manual_raw.pkl "
                     f"--ranks {','.join(str(r) for r in sorted(set(ranks)))}")}


# ===========================================================================
# Run one config
# ===========================================================================
@dataclass
class Result:
    config: Dict[str, Any]
    structure: GRID.Structure
    closed: pd.DataFrame
    funnel: Dict[str, Any]

    @property
    def summary(self) -> Dict[str, Any]:
        if self.closed.empty:
            return {"name": self.config.get("name"), "trades": 0}
        s = G.summarize(self.closed)
        s["name"] = self.config.get("name")
        s["structure"] = self.structure.name
        return s


def run_config(config: Dict[str, Any], raw_events: List[dict], mdp,
               *, show_progress: bool = False, strict: bool = True) -> Result:
    """Filter -> re-time -> resolve overlaps -> gate -> price. In that order."""
    cf = merge(config)
    cfg = G.CB_CONFIGS[cf["bank"]]
    st = resolve_instrument(cf["instrument"])
    t = cf["timing"]

    filtered, drops = apply_filters(raw_events, cf["filters"])
    timed, tdrops = retime(filtered, cfg, t["entry_offset_min"], t["exit_offset_min"],
                           t.get("retime_synthetic", False))

    cov = check_coverage(timed, cfg, st.ranks)
    if not cov["ok"] and strict:
        raise RuntimeError(
            f"{len(cov['missing'])} of {cov['wanted']} symbol-days are not in the bar "
            f"cache, and this process cannot fetch them. First few: "
            f"{cov['missing'][:5]}.  Warm them with:\n    {cov['hint']}")

    # One gate per rank, then an INNER join: every leg must have a causal mark on
    # the same event, or the structure is priced on a different sample than its
    # neighbours and the comparison is between instruments AND books at once.
    frames, gate_reasons = [], {}
    for rank in sorted(set(st.ranks)):
        variant = G.rebuild_with_contract(timed, cfg, rank)
        gated, reasons, _diag = G.gate_events(
            variant, cfg, mdp, max_staleness_min=int(t["max_staleness_min"]),
            show_progress=show_progress)
        gate_reasons[rank] = reasons
        if not gated:
            continue
        frames.append(pd.DataFrame([{"tag": e["tag"], "rank": rank,
                                     "entry_px": e["entry_bar_px"],
                                     "exit_px": e["exit_bar_px"]} for e in gated]))

    funnel = {"raw": len(raw_events), "after_filters": len(filtered),
              "filter_drops": drops, "after_retime_overlap": len(timed),
              "retime_drops": tdrops, "gate_reasons": gate_reasons,
              "coverage": {k: v for k, v in cov.items() if k != "missing"},
              "n_missing_bars": len(cov["missing"])}

    if not frames:
        return Result(cf, st, pd.DataFrame(), funnel)

    panel = pd.concat(frames, ignore_index=True).pivot(
        index="tag", columns="rank", values=["entry_px", "exit_px"])
    before = len(panel)
    panel = panel.dropna(how="any")
    funnel["panel_incomplete_dropped"] = before - len(panel)

    d_rate = GRID.structure_pnl_bp(panel, st)
    by_tag = {e["tag"]: e for e in timed}
    gross = st.gross or 1.0
    cost = float(cf.get("cost_bp", 0.0))
    sized = cf.get("sizing", "equal") == "conviction"

    rows = []
    for tag, dr in d_rate.items():
        ev = by_tag.get(tag)
        if ev is None or not np.isfinite(dr):
            continue
        # `side` is the PRICE side (-1 short the future for a hawk); in rate space
        # a hawk is +1, so side_rate = -side and the structure's own sign never
        # has to be guessed.
        unit = (-ev["side"]) * dr / gross
        size = abs(ev["bucket"]) if sized else 1.0
        a = ev.get("_attrs") or event_attrs(ev)
        rows.append({
            "tag": tag, "bank": ev["bank"], "ccy": ev["ccy"], "speaker": ev["speaker"],
            "role": a["role"], "is_voter": a["is_voter"], "era": a["era"],
            "days_to_fomc": a["days_to_fomc"],
            "timestamp_source": ev.get("timestamp_source", "forexfactory"),
            "symbol": ev["symbol"], "structure": st.name,
            "bucket": ev["bucket"], "abs_bucket": abs(ev["bucket"]),
            "opened_at": pd.Timestamp(ev["entry_ts"]),
            "closed_at": pd.Timestamp(ev["exit_ts"]),
            "d_rate_bp": dr,
            "pnl_bp": unit * size - cost * size,
            "pnl_bp_gross": unit * size,
        })
    if not rows:
        return Result(cf, st, pd.DataFrame(), funnel)

    df = pd.DataFrame(rows).sort_values("opened_at").reset_index(drop=True)
    df["year"] = df["opened_at"].dt.year
    df["direction"] = np.where(df["bucket"] > 0, "hawk (short fut)", "dove (long fut)")
    df["profitable"] = df["pnl_bp"] > 0
    return Result(cf, st, df, funnel)


# ===========================================================================
# Comparing configs
# ===========================================================================
def compare(configs: Sequence[Dict[str, Any]], raw_events: List[dict], mdp,
            *, raise_on_cold: bool = False) -> tuple:
    """Run several configs and tabulate. Returns (table, {name: Result}).

    A cold bar cache reports itself as a row carrying the reason rather than
    killing the whole comparison — but it is never silently priced on partial
    data, because ``run_config`` still refuses. Pass ``raise_on_cold=True`` to
    stop at the first one instead.
    """
    rows, results = [], {}
    for c in configs:
        cf = merge(c)
        nm = cf.get("name") or cf["instrument"].get("structure", "cfg")
        try:
            res = run_config(cf, raw_events, mdp, strict=True)
        except RuntimeError as e:
            if raise_on_cold:
                raise
            rows.append({"name": nm, "trades": 0, "note": str(e).split("\n")[0][:80]})
            continue
        results[nm] = res
        s = res.summary
        rows.append({
            "name": nm, "structure": res.structure.name,
            "trades": s.get("trades", 0), "total_bp": s.get("total"),
            "avg_bp": s.get("avg"), "hit": s.get("hit_rate"),
            "sharpe": s.get("sharpe"), "t_stat": s.get("t_stat"),
            "max_dd": s.get("max_dd"),
            "first": str(s["first"].date()) if s.get("trades") else None,
            "last": str(s["last"].date()) if s.get("trades") else None,
        })
    return pd.DataFrame(rows).set_index("name"), results


def sweep_knob(base: Dict[str, Any], path: Sequence[str], values: Sequence[Any],
               raw_events: List[dict], mdp, *, label: Optional[str] = None) -> tuple:
    """Vary ONE knob, hold everything else. `path` is e.g. ("timing","exit_offset_min")."""
    configs = []
    for v in values:
        c = copy.deepcopy(merge(base))
        node = c
        for k in path[:-1]:
            node = node.setdefault(k, {})
        node[path[-1]] = v
        c["name"] = f"{label or '.'.join(path)}={v}"
        configs.append(c)
    return compare(configs, raw_events, mdp)
