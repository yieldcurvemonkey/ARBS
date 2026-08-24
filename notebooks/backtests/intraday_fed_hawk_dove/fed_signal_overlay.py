r"""The weekly macro state that conditions a Fed speaker's intraday trade.

The question
-----------
The intraday hawk/dove book trades a speech's label: hawk -> short the future,
dove -> long it. It reads every speech the same way, and
``project_global_cb_hawk_dove`` measured what that is worth on the FED leg --
**+0.219bp per trade against a ~0.25bp round trip**, i.e. an edge that does not
clear costs and whose pooled sign-flip p is 0.154.

JWS Macro #8 (23-Aug-2026) suggests where the missing structure might be:

    *"Fed speakers will become/shift more dovish/hawkish on where the data is
    going ... this allows us to predict how a speaker is thinking going into an
    event."*

If that is right, a speech is only NEWS to the extent it departs from what the
data already implied. A hawk speaking into three months of hot data is telling
the market nothing it could not have worked out; a hawk speaking into a
softening patch is. This module builds the weekly macro state that lets a config
condition on that, and nothing else -- the trading is left entirely to
``hawk_dove_config``.

Two states, and why both
------------------------
``data``     the surprise composite alone, read ``lead_w`` weeks back:
             ``Ldata_t = C_{t-L}``. Positive = the data has run hot, so the
             committee is expected to LEAN HAWKISH.

             This is the arm that matches the sentence above, and it is the one
             that covers the whole event book: the composite runs from 2005, so
             every FED event from 2019-01 onwards has a state. It needs no Fed
             sentiment index at all, which also means it inherits none of that
             index's vintage problems.

``detach``   the gap between where Fedspeak actually IS and where the data says
             it should be: ``D_t = z(S)_t - z(C)_{t-L}``, from
             ``fed_detachment_data.detachment``. Positive = Fedspeak is MORE
             HAWKISH than the data warrants.

             The stronger reading of the same idea, and much the shorter sample:
             the point-in-time JPM sentiment index starts 2023-10 and a
             52-week trailing z burns the first 26, so this arm sees about 146
             weeks and, because two smoothed series disagree in multi-month
             EPISODES rather than weekly, only a handful of independent states.
             That is why it is co-primary with ``data`` rather than the headline.

Both are strictly trailing and both are computed by machinery already on
``main``; nothing here forks an estimator.

How a state becomes a position
------------------------------
This module does not decide. It attaches, per event, ``state_value`` and
``state_sign``, and ``hawk_dove_config`` reads them. The reading the configs
express is:

    **agree** -- ``sign(bucket) == state_sign``. What "agreeing" MEANS depends on
    which state is in use, and the two are not the same sentence:

        ``data``    the speech says what the DATA already implied. On the "it is
                    already priced" thesis this is the speech to fade.
        ``detach``  the speech continues the direction FEDSPEAK has already run
                    in relative to the data -- one more hawk when the committee
                    is already more hawkish than the numbers warrant. That is
                    the speech the "the gap will close" thesis says to fade.

    They point the same way as trading rules and mean different things as
    sentences. A reader who carries the first gloss onto the second arm has the
    wrong mental model of what is being faded, which is why both are written out.

    **disagree** -- the complement. Under ``data`` it is the speech that is news;
    under ``detach`` it is the speech that pulls the committee back toward the
    data.

The opposite assignment is a second cell, not a robustness check: which way
round to trade a state is a free parameter and the search pays for it.

The join, and the vintage cutoff
--------------------------------
An event's state is the last W-FRI value stamped strictly before the **DAY** the
position opens. Two decisions there, and both were wrong in the first version.

**The day, not the instant.** A W-FRI weekly value is the last daily observation
in the ``(Sat..Fri]`` bin -- a number computed at that Friday's CLOSE -- but it
is stamped at that Friday's midnight. Comparing an entry timestamp against the
stamp therefore lets a Friday 09:00 entry read a value that does not exist until
16:00 that day, a look-ahead of most of a session on every Friday speech.
Normalising the entry to midnight first makes the rule "the last Friday strictly
before the day the position opened", and a Friday close is genuinely readable
from the next session on. :func:`gate_cutoff_is_before_entry` asserts the
resulting state age is at least one day.

**The entry, not the speech.** The default config opens 45 minutes before the
speech and the notebook's live config 60. Keying off the speech when the entry is
earlier only ever errs in the direction that flatters.

:func:`join_report` prints the match rate. It has to be read, not assumed: FED
events are business-day only and the weekly grid lands on Fridays, so an
equality join matches nothing at all, and a "drop if missing" filter would then
produce a silently empty book. It also reports the rate per YEAR, because a
state whose history starts in 2023 turns "condition on the data" into "trade
only the SR3 era" -- which would read as a result.

What is NOT gated
-----------------
The Citi surprise snapshot is a single vintage with no publication axis -- see
``fed_expected_sentiment`` for the full statement. It is the largest residual
look-ahead in this stack and it reaches the ``data`` arm directly.
"""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import sys
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
RV = REPO / "notebooks" / "rv"
for _p in (str(REPO), str(RV), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: The states a config may name.
STATES: Tuple[str, ...] = ("data", "detach")

#: What the mode does. ``off`` must be a perfect no-op -- that is the
#: known-answer check the whole overlay rests on.
MODES: Tuple[str, ...] = ("off", "flip", "gate", "size")

#: Which side of the comparison the mode acts on.
WHENS: Tuple[str, ...] = ("agree", "disagree")

#: The default signal block. Merged into every config, so an existing config
#: that has never heard of this module keeps its exact behaviour.
DEFAULT_SIGNAL: Dict[str, Any] = {
    "mode": "off",
    "state": "data",
    "lead_w": 0,
    "threshold": 0.0,
    "when": "agree",
    # only read when state == 'detach'
    "source": "jpm",
    "construction": "gap",
    # sizing knob, only read when mode == 'size'
    "size_cap": 3.0,
}

#: ``key -> weekly Series``. Keyed by every field that changes the series, so
#: two configs pointing at different states in one process cannot collide. It is
#: deliberately NOT ``hawk_dove_config._ROLE_CACHE``, which is keyed by a
#: constant and is config-blind.
_SIGNAL_CACHE: Dict[Tuple, pd.Series] = {}


def normalise(block: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill the defaults and reject a typo up front rather than per trade.

    A misspelled mode that fell through to ``off`` would produce a book
    indistinguishable from a conditioned one that found no edge -- the exact
    failure ``hawk_dove_config``'s own flip validation exists to prevent.
    """
    s = {**DEFAULT_SIGNAL, **(block or {})}
    if s["mode"] not in MODES:
        raise ValueError(f"unknown signal mode {s['mode']!r}; use one of {MODES}")
    if s["state"] not in STATES:
        raise ValueError(f"unknown signal state {s['state']!r}; use one of {STATES}")
    if s["when"] not in WHENS:
        raise ValueError(f"unknown signal when {s['when']!r}; use one of {WHENS}")
    if float(s["threshold"]) < 0:
        raise ValueError("signal threshold is a magnitude and cannot be negative")
    # `source`, `construction` and `lead_w` all reach build_state and CHANGE THE
    # SERIES. Leaving them unvalidated does not fall through to a default -- but a
    # value that happens to be legal downstream would build a different state
    # than the config's author meant, and nothing would say so.
    if s["source"] not in ("jpm", "fedlock"):
        raise ValueError(
            "unknown signal source " + repr(s["source"]) + "; use 'jpm' or 'fedlock'")
    if s["construction"] not in ("gap", "resid", "dchg", "rankgap"):
        raise ValueError("unknown signal construction " + repr(s["construction"]))
    if int(s["lead_w"]) < 0:
        raise ValueError("signal lead_w is a lag in weeks and cannot be negative")
    return s


def cache_key(sig: Dict[str, Any]) -> Tuple:
    """Everything that changes the SERIES. Not mode/when/threshold, which change
    only how the series is read."""
    return (sig["state"], int(sig["lead_w"]), sig["source"], sig["construction"])


# ==========================================================================
# building the state
# ==========================================================================
def _build_data_state(zc: pd.Series, sig: Dict[str, Any]) -> pd.Series:
    """Ldata_t = C_{t-L} -- where the data stood L weeks ago.

    That is the reading under which a measured lead of L makes the composite
    contemporaneous with what the committee sounds like today.

    Factored out so :func:`build_state` and :func:`gate_state_is_trailing` share
    ONE definition. When the gate had its own copy it could not fail: it
    computed the right answer and then compared that answer with itself, so
    breaking build_state (shifting the wrong way, say) left the gate passing.
    """
    return zc.shift(int(sig["lead_w"])).rename("state").dropna()


def build_state(sig: Dict[str, Any]) -> Tuple[pd.Series, Dict[str, Any]]:
    """``(weekly state series on a W-FRI grid, provenance)``.

    Raises ``RuntimeError`` rather than a bare exception on any data problem, so
    a caller running many configs through ``hawk_dove_config.compare`` gets a
    row carrying the reason instead of losing the whole comparison -- ``compare``
    catches ``RuntimeError`` and nothing else.
    """
    sig = normalise(sig)
    key = cache_key(sig)
    if key in _SIGNAL_CACHE:
        s = _SIGNAL_CACHE[key]
        return s, {"cached": True, "key": key}

    try:
        import fed_detachment_data as D
        import fed_sentiment_lead_data as L
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"cannot import the surprise/sentiment estimators from {RV}: "
            f"{type(exc).__name__}: {exc}") from exc

    lead_cfg = L.LeadConfig()
    try:
        panel, prov = L.load_surprise_panel()
        L.gate_surprise_sanity(panel, lead_cfg)
        composite, _legs = L.build_surprise_composite(panel, lead_cfg)
        zc = L.weekly_last(composite, lead_cfg.week_anchor)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"surprise composite unavailable: "
                           f"{type(exc).__name__}: {exc}") from exc

    if sig["state"] == "data":
        out = _build_data_state(zc, sig)
        prov = {**prov, "state": "data", "lead_w": int(sig["lead_w"]),
                "weeks": int(len(out)),
                "first": str(out.index.min().date()) if len(out) else None,
                "last": str(out.index.max().date()) if len(out) else None}
    else:
        try:
            dcfg = dataclasses.replace(
                D.PRIMARY, source=sig["source"],
                construction=sig["construction"], lead_k=int(sig["lead_w"]))
            zc2, zs, dprov = D.load_sides(dcfg)
            out = D.detachment(zc2, zs, dcfg).rename("state").dropna()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"detachment state unavailable: "
                               f"{type(exc).__name__}: {exc}") from exc
        prov = {**dprov, "state": "detach", "source": sig["source"],
                "construction": sig["construction"], "lead_w": int(sig["lead_w"]),
                "weeks": int(len(out)),
                "first": str(out.index.min().date()) if len(out) else None,
                "last": str(out.index.max().date()) if len(out) else None}

    if out.empty:
        raise RuntimeError(f"signal state {cache_key(sig)} came back empty")
    _SIGNAL_CACHE[key] = out
    return out, prov


def clear_cache() -> None:
    _SIGNAL_CACHE.clear()


# ==========================================================================
# the join
# ==========================================================================
def _asof_position(state: pd.Series, when: pd.Timestamp) -> int:
    """Index of the last state week readable by a position opening at ``when``.

    **The cutoff is the entry DAY, not the entry instant, and that is not a
    detail.** A W-FRI weekly value is the last daily observation in the
    ``(Sat..Fri]`` bin -- i.e. it is a value computed at that Friday's CLOSE --
    but it is stamped at that Friday's midnight. Comparing an entry timestamp
    against the stamp therefore lets a position opened at 09:00 on a Friday read
    a number that will not exist until 16:00 that day.

    Normalising the entry to midnight first turns the rule into "the last Friday
    strictly before the day the position opened", which is the earliest reading
    that is genuinely knowable: a Friday close is available from the next
    session onwards.

    Returns ``-1`` when nothing is readable yet.
    """
    if state is None or state.empty or when is None or pd.isna(when):
        return -1
    day = pd.Timestamp(when).normalize()
    idx = state.index.values
    return int(np.searchsorted(idx, np.datetime64(day), side="left")) - 1


def asof_value(state: pd.Series, when: pd.Timestamp) -> Optional[float]:
    """The last state readable by a position opening at ``when``.

    See :func:`_asof_position` for why the cutoff is the entry DAY.
    """
    i = _asof_position(state, when)
    if i < 0:
        return None
    v = float(state.iloc[i])
    return v if np.isfinite(v) else None


def attach(ev: dict, state: pd.Series, sig: Dict[str, Any]) -> Dict[str, Any]:
    """``{state_value, state_sign, state_week, state_missing}`` for one event.

    The cutoff is the event's ENTRY, not its speech: the default config opens 45
    minutes before the speech and the notebook's live one 60, and the difference
    only ever matters in the direction that flatters.

    ``state_sign`` is 0 both when the state is missing and when it is inside the
    threshold band. A zero sign never flips and never sizes -- it means "this
    rule has nothing to say about this event", which is different from "this
    rule says do not trade it", and the two are kept apart because a zero-sized
    trade booked as a trade dilutes every statistic in the book.
    """
    when = ev.get("entry_ts") or ev.get("speech_ts")
    if when is not None and getattr(when, "tzinfo", None) is not None:
        when = pd.Timestamp(when).tz_localize(None)
    i = _asof_position(state, when)
    thr = float(sig.get("threshold", 0.0))
    if i < 0 or not np.isfinite(float(state.iloc[i])):
        return {"state_value": np.nan, "state_sign": 0, "state_week": None,
                "state_missing": True}
    v = float(state.iloc[i])
    sign = 0
    if abs(v) >= thr and v != 0.0:
        sign = 1 if v > 0 else -1
    return {"state_value": v, "state_sign": int(sign),
            "state_week": pd.Timestamp(state.index[i]).date(),
            "state_missing": False}


def join_report(events: Sequence[dict], state: pd.Series,
                sig: Dict[str, Any]) -> pd.DataFrame:
    """The match rate, per year, printed rather than assumed.

    FED events are business-day only and the state grid lands on Fridays, so an
    equality join matches ZERO events; a filter that dropped the unmatched would
    then return an empty book without raising. This is the number that says
    whether the join works at all, and whether "condition on the state" has
    quietly become "trade only after 2023".
    """
    rows = []
    for ev in events:
        a = attach(ev, state, sig)
        d = ev["speech_ts"].date() if ev.get("speech_ts") is not None else None
        rows.append({"year": d.year if d else None, "matched": not a["state_missing"],
                     "in_band": a["state_sign"] != 0,
                     "bucket": ev.get("bucket"), "state_value": a["state_value"]})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    g = df.groupby("year")
    out = pd.DataFrame({
        "events": g.size(),
        "matched": g["matched"].sum(),
        "match_rate": g["matched"].mean(),
        "outside_band": g["in_band"].sum(),
        "band_rate": g["in_band"].mean(),
        "mean_state": g["state_value"].mean(),
    })
    out.loc["ALL"] = [len(df), int(df["matched"].sum()), float(df["matched"].mean()),
                      int(df["in_band"].sum()), float(df["in_band"].mean()),
                      float(df["state_value"].mean())]
    return out


# ==========================================================================
# reading the state
# ==========================================================================
def agrees(attrs: Dict[str, Any], bucket: int) -> Optional[bool]:
    """Does the speech say what the state already implied?

    ``None`` when the state has nothing to say -- missing, or inside the
    threshold band. Callers must treat ``None`` as "leave this event alone",
    never as ``False``: unknown is not disagreement, the same distinction
    ``hawk_dove_config`` already makes for an unknown voting status.
    """
    s = int(attrs.get("state_sign", 0) or 0)
    if s == 0:
        return None
    return (bucket > 0) == (s > 0)


def signal_sign(attrs: Dict[str, Any], bucket: int,
                sig: Optional[Dict[str, Any]]) -> float:
    """``-1.0`` to trade this event backwards, ``+1.0`` to leave it alone.

    Composes multiplicatively with ``hawk_dove_config.flip_sign``, so a config
    can fade the non-voters AND fade the anticipatable speeches, and each rule
    keeps its own meaning.
    """
    if not sig or sig.get("mode") != "flip":
        return 1.0
    ag = agrees(attrs, bucket)
    if ag is None:
        return 1.0
    want_agree = sig.get("when", "agree") == "agree"
    return -1.0 if (ag == want_agree) else 1.0


def signal_size(attrs: Dict[str, Any], bucket: int,
                sig: Optional[Dict[str, Any]]) -> float:
    """A multiplier on the position, ``>= 0``.

    Only ``mode == 'size'`` does anything. The multiplier is
    ``1 + |state|`` on the side the rule favours and ``1`` on the other, capped
    -- an uncapped ``|state|`` lets one three-sigma week carry the whole book,
    which is how a Sharpe gets manufactured out of a single episode.

    It never returns 0: a zero-sized trade is still booked as a trade, and a
    booked zero halves the hit rate, shrinks the standard deviation and thereby
    inflates the Sharpe of a book that did nothing. Standing aside is
    ``mode == 'gate'``, which removes the event and counts it.
    """
    if not sig or sig.get("mode") != "size":
        return 1.0
    ag = agrees(attrs, bucket)
    if ag is None:
        return 1.0
    want_agree = sig.get("when", "agree") == "agree"
    if ag != want_agree:
        return 1.0
    cap = float(sig.get("size_cap", 3.0))
    v = abs(float(attrs.get("state_value", 0.0) or 0.0))
    return float(min(1.0 + v, cap))


def keeps(attrs: Dict[str, Any], bucket: int,
          sig: Optional[Dict[str, Any]]) -> bool:
    """``mode == 'gate'``: keep only the events the rule selects.

    A gate runs BEFORE the one-position-at-a-time rule, so it changes which
    events win the book's single slot -- the conditioned book is NOT a subset of
    the unconditioned one's trades. That is deliberate and it is why a gated
    config is only ever compared against a baseline carrying the same date
    filters, never against the headline book.
    """
    if not sig or sig.get("mode") != "gate":
        return True
    ag = agrees(attrs, bucket)
    if ag is None:
        return False
    return ag == (sig.get("when", "agree") == "agree")


# ==========================================================================
# gates
# ==========================================================================
def gate_state_is_trailing(sig: Dict[str, Any], *,
                           probe_dates: Sequence) -> pd.DataFrame:
    """G-S1 -- the state at a week must not move when later data is removed.

    Delegates to whichever estimator built the state, so the composition is what
    gets tested rather than its parts. For ``data`` that is a shift of a
    trailing z-score; for ``detach`` it is ``fed_detachment_data``'s own G-D1.
    """
    sig = normalise(sig)
    import fed_detachment_data as D
    import fed_sentiment_lead_data as L

    if sig["state"] == "data":
        # Compare against what BUILD_STATE returns, not against a second
        # implementation written here. An earlier version rebuilt the composite
        # and shifted it inline, which meant the gate computed its own correct
        # answer and checked it against itself -- so breaking build_state left
        # G-S1 passing. That is the defect this gate exists to prevent, applied
        # to the gate itself.
        full, _ = build_state(sig)
        lead_cfg = L.LeadConfig()
        panel, _ = L.load_surprise_panel()
        composite, _legs = L.build_surprise_composite(panel, lead_cfg)
        zc_all = L.weekly_last(composite, lead_cfg.week_anchor)

        rows = []
        for t in probe_dates:
            t = pd.Timestamp(t)
            cut = _build_data_state(zc_all[zc_all.index <= t], sig)
            if t not in cut.index or t not in full.index:
                continue
            rows.append({"date": t, "truncated": float(cut.loc[t]),
                         "full_history": float(full.loc[t]),
                         "abs_diff": abs(float(cut.loc[t]) - float(full.loc[t]))})
        out = pd.DataFrame(rows)
        assert len(out) >= 3, (
            "G-S1 checked " + str(len(out)) + " probes for state='data' -- fewer "
            "than 3 is a vacuous pass; widen probe_dates")
        worst = float(out["abs_diff"].max())
        assert worst < 1e-9, (
            f"G-S1 FAILED for state='data' lead_w={sig['lead_w']}: worst "
            f"|diff| {worst:.3e} -- the state is not computable in real time")
        return out

    dcfg = dataclasses.replace(D.PRIMARY, source=sig["source"],
                               construction=sig["construction"],
                               lead_k=int(sig["lead_w"]))
    zc2, zs, _ = D.load_sides(dcfg)
    out = D.gate_trailing_detachment(zc2, zs, dcfg, probe_dates=probe_dates)
    assert len(out) >= 3, (
        "G-S1 checked " + str(len(out)) + " probes for state='detach' -- fewer "
        "than 3 is a vacuous pass; widen probe_dates")
    return out


def gate_cutoff_is_before_entry(events: Sequence[dict], state: pd.Series,
                                sig: Dict[str, Any], *, n: int = 200) -> pd.DataFrame:
    """G-S2 -- every state a trade reads was stamped strictly before its entry.

    The one assertion that a point-in-time join actually needs. Without it a
    single off-by-one in the ``searchsorted`` side turns "last Friday before"
    into "this Friday", which on a Friday speech reads a state published at the
    close of the day the position opened.
    """
    # Sample ACROSS the book, not the first n. The detach state starts in 2023
    # and the raw book starts in 2019, so taking a prefix checks zero matched
    # events and the gate passes vacuously -- measured: 0 of 400 on the first
    # version of this probe.
    evs = list(events)
    if len(evs) > n:
        step = max(1, len(evs) // n)
        evs = evs[::step]
    rows = []
    for ev in evs:
        a = attach(ev, state, sig)
        if a["state_missing"]:
            continue
        when = pd.Timestamp(ev["entry_ts"]).tz_localize(None)
        wk = pd.Timestamp(a["state_week"])
        rows.append({"tag": ev.get("tag"), "entry": when, "entry_day": when.normalize(),
                     "state_week": wk,
                     "before_entry_day": wk < when.normalize(),
                     "lag_days": (when.normalize() - wk).days})
    out = pd.DataFrame(rows)
    if not out.empty:
        bad = int((~out["before_entry_day"]).sum())
        assert bad == 0, (
            f"G-S2 FAILED: {bad} of {len(out)} events read a state stamped on or "
            f"after the DAY their position opened. A W-FRI value is that "
            f"Friday's CLOSE, so a same-day read is a look-ahead of up to a "
            f"full session")
        assert int(out["lag_days"].min()) >= 1, (
            f"G-S2 FAILED: minimum state age is {int(out['lag_days'].min())} days")
    return out


def gate_join_is_not_vacuous(report: pd.DataFrame, *, min_checked: int = 25,
                             name: str = "state") -> int:
    """G-S3 -- a point-in-time gate that checked nothing has proved nothing.

    ``gate_cutoff_is_before_entry`` returns only the events whose state EXISTS,
    so on a state whose history starts after most of the book it can return an
    empty frame and pass. That is the shape of a vacuous test: measured on the
    first version of the probe, the ``detach`` gate reported PASS having checked
    0 of 400 events.
    """
    n = 0 if report is None or report.empty else int(len(report))
    assert n >= min_checked, (
        f"G-S3 FAILED: the point-in-time gate for {name!r} checked {n} events, "
        f"fewer than {min_checked} -- it passed vacuously")
    return n
