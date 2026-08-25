r"""Does Fed LANGUAGE move the priced policy path? -- the link nobody measured.

The chain under test is ``data -> Fed language -> price``.

* **Link 1 measured, real.** ``fed_sentiment_lead`` (PR #490) and
  ``fedlock_sentiment_lead`` (#491): an inflation+labour surprise composite leads
  a Fed sentiment index by **11-14 weeks** on 2023-2026 (not the 5 the note
  claims), and by ~2 weeks over 21 years.
* **End to end measured, dead.** ``fed_detachment_rv`` (#497, 2048 cells) and
  ``fed_expected_sentiment`` (#501, three samples) both trade ``data -> price``
  and both die before costs.
* **Link 2 alone: never measured.** That is this module.

Why the end-to-end result cannot settle it
------------------------------------------
**Fed communication is discretised.** The stance does not drift; it updates at
set-piece events -- statement, press conference, testimony, Jackson Hole,
minutes -- and is stale by construction in between. A dislocation is therefore
not a mispricing that decays smoothly, it is a stock of unacknowledged
information released on a schedule.

A signal-hold-P&L backtest averages event days and non-event days together. If
the whole effect lands on ~19 days a year and the hold is four weeks, the
dilution is 15-25x: a real 2bp-per-event effect becomes 0.1bp a day and dies in
the noise, which is exactly what "dead before costs" looks like. That is a
testable claim, and :func:`study_a` tests it for the price of one regression.

**The decision rule is pre-registered.** If the coefficient at NON-DECISION
events is indistinguishable from zero, the market prices the data directly, Fed
language is confirmation rather than information, the 11-14 week lead is a fact
about how slowly the Fed talks, and nothing downstream can work. Stop there.

What is measured, and on what
-----------------------------
``y`` -- the **priced meeting step**, not an SR3 outright. An outright carries
supply, term premium, oil and cross-market; the meeting step carries only the
policy path, which is what the claim is about. It comes from
``RVUtils.MeetingProb.meeting_ladder``, a CME-FedWatch anchor-walk bootstrap on
ZQ settles -- *not*, as the brief supposed, a joint least-squares fit; there is
no such object in the repo. ``MeetingLattice.jump_bp`` is the per-meeting
expected move in bp of EFFR, and the ladder's first four jumps on 2026-08-21 sum
to 30.21bp against a ZQQ26->ZQG27 settle spread of 30.50bp, the residual being
intra-month day-weighting exactly as the CME identity predicts.

**y is defined on a FIXED PAIR OF MEETINGS and this is the one thing that must
not be got wrong.** At an FOMC event a meeting RESOLVES inside the window, so
"the next two meetings" at T-1 and at T+1 are different meetings. Differencing
those two sums measures the roll, not the repricing. :func:`event_panel`
therefore identifies the two meetings whose ``effective`` date is strictly after
the exit session and matches them **by effective date** on both marks. A meeting
that is not priced on both sides is dropped and counted.

``x`` -- the contemporaneous change in the Fed sentiment index across the event
window. The index is evaluated on a **daily** grid: a weekly index cannot move
inside a three-day window, which would make the primary regressor identically
zero for most events. Measured: the daily point-in-time index moves on 60.4% of
days.

A second, higher-powered reading is also reported: ``x_dev``, the event's own
hawk/dove score minus the prevailing index, i.e. how much more hawkish this
communication was than what was already in the running average. The EWMA damps a
single speech heavily, so ``x`` understates the language shock while ``x_dev``
measures it directly; neither is obviously right and both are shown.

Samples
-------
``jpm``      the publication-gated JPM NLP corpus. **Tradeable.** The daily
             point-in-time index runs 2023-05-03 onwards, so this arm is ~2.8
             years of events.
``fedlock``  FedLock V3. **Never tradeable** -- one vintage, TrueSkill fitted
             jointly across a graph spanning the future, and the judge has read
             decades of hindsight. It is here for the longer window and every
             number from it is labelled *historical association*.

**Using FedLock for the event CALENDAR is not the same as using it for scores.**
A press conference happened on a date; that is a fact, not a model output, and it
carries no hindsight. The scores do.

The binding constraint is the price side. The FOMC registry
(``SDRUtils.analytics.fomc.load_fomc_schedule``) starts **2021-01-27**, and an
unregistered meeting month is silently treated as a non-meeting anchor month,
which *corrupts* rather than truncates the bootstrap. So the meeting step is
usable from 2021-01-27 to the ZQ cache's last session, and no arm here reaches
further back however long its sentiment history is.

Two schedules disagree
----------------------
``RVUtils.MeanRev.meetings.fomc_schedule`` and
``SDRUtils.analytics.fomc.load_fomc_schedule`` differ by one day on at least one
meeting (effective 2025-03-20 vs 2025-03-19), and the same ZQ settles then give
different jumps. This module uses the SDRUtils one throughout, which is the one
``meeting_ladder`` is documented against, and :func:`gate_schedule_choice`
records the disagreement rather than letting it pass silently.
"""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_sentiment_lead_data as L  # noqa: E402

#: Communication types, most set-piece first. ``fomc_decision`` is derived from
#: the meeting registry; the rest come from the speech corpora.
EVENT_TYPES: Tuple[str, ...] = ("fomc_decision", "minutes", "press_conference",
                                "testimony", "jackson_hole", "speech")

#: Types at which a policy decision RESOLVES inside the window. The decision
#: itself moves the strip, so pooling these with the rest confounds "the Fed
#: said something" with "the Fed did something".
DECISION_TYPES: Tuple[str, ...] = ("fomc_decision",)

#: The SET-PIECE calendar -- scheduled communications the market knows are
#: coming, roughly 19 a year. This is the brief's event universe and it is the
#: primary one here.
#:
#: The alternative -- every scored speech -- was tried first and is kept as a
#: separate arm, because it breaks the null rather than the regression: with
#: ~330 speeches in two years almost every business day is within a day of one,
#: and the matched non-event pool collapsed to 154 days. Making the universe
#: set-piece also sharpens the question, since an ordinary speech day is then an
#: eligible CONTROL and the test becomes "does the effect concentrate at
#: set-piece events above and beyond ordinary speech days".
SETPIECE_TYPES: Tuple[str, ...] = ("fomc_decision", "minutes", "press_conference",
                                   "testimony", "jackson_hole")

#: The registry's first effective date. Before this the ladder is corrupted,
#: not merely absent -- see the module docstring.
LADDER_FLOOR = pd.Timestamp("2021-01-27")

#: Jackson Hole keynote dates (the Friday of the symposium). Hand-entered
#: because no repo source carries the keynote day -- the calendar store has the
#: symposium SPAN only -- and cross-checked against the speech corpora by
#: :func:`gate_jackson_hole`, which requires a scored Fed communication within a
#: day of each. 2026-08-28 has not happened yet and is carried for the forward
#: read only, never as an event.
JACKSON_HOLE = {
    2019: "2019-08-23", 2020: "2020-08-27", 2021: "2021-08-27",
    2022: "2022-08-26", 2023: "2023-08-25", 2024: "2024-08-23",
    2025: "2025-08-22", 2026: "2026-08-28",
}


@dataclasses.dataclass(frozen=True)
class EventConfig:
    """Frozen. The pre-registered reading is the default."""

    #: ``jpm`` (tradeable) or ``fedlock`` (association only).
    source: str = "jpm"
    #: Business days before/after the event for the price and sentiment marks.
    #: 1 is the tightest window that still brackets the event.
    pre_days: int = 1
    post_days: int = 1
    #: How many future meetings the dependent variable sums.
    n_meetings: int = 2
    #: Trailing window for the sentiment z-score, in days (the daily analogue of
    #: the weekly 52/26 the lead studies use).
    z_window_d: int = 252
    z_min_d: int = 126
    #: Minimum live (non-stale) meetings the ladder must price for a date to be
    #: usable at all.
    min_live_meetings: int = 3
    seed: int = 20260825

    def rng(self, off: int = 0) -> np.random.Generator:
        return np.random.default_rng(self.seed + off)


PRIMARY = EventConfig()


# ==========================================================================
# the price side
# ==========================================================================
def load_fomc_schedule():
    from SDRUtils.analytics.fomc import load_fomc_schedule as _f

    return _f("USD-SOFR-1D")


def gate_schedule_choice() -> pd.DataFrame:
    """G-E1 -- record where the two in-repo FOMC schedules disagree.

    They differ by a day on at least one meeting and the same ZQ settles then
    give different jumps. This does not fail the build; it makes the choice
    visible, because a study that silently picked one would be unreproducible by
    anyone who picked the other.
    """
    a = load_fomc_schedule()[["effective_date"]].assign(src="SDRUtils")
    try:
        from RVUtils.MeanRev.meetings import fomc_schedule as _mr

        b = _mr()
        col = "effective_date" if "effective_date" in b.columns else b.columns[0]
        b = b[[col]].rename(columns={col: "effective_date"}).assign(src="MeanRev")
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame([{"note": f"MeanRev schedule unavailable: {exc}"}])
    A = sorted(pd.to_datetime(a["effective_date"]).dt.date)
    B = sorted(pd.to_datetime(b["effective_date"]).dt.date)
    SA, SB = set(A), set(B)
    # They disagree on essentially EVERY meeting, and by one day, because the two
    # tables use different conventions -- one stamps the announcement day and the
    # other the day the new rate is first effective. Dumping 200 rows hides that;
    # the modal offset is the fact worth reporting.
    import collections
    off = collections.Counter()
    for d in A:
        near = [x for x in B if abs((x - d).days) <= 3]
        off[(near[0] - d).days if near else None] += 1
    return pd.DataFrame([{
        "SDRUtils_rows": len(A), "MeanRev_rows": len(B),
        "exact_matches": len(SA & SB),
        "SDRUtils_only": len(SA - SB), "MeanRev_only": len(SB - SA),
        "modal_offset_days": off.most_common(1)[0][0] if off else None,
        "at_modal_offset": off.most_common(1)[0][1] if off else 0,
        "SDRUtils_first": A[0] if A else None, "MeanRev_first": B[0] if B else None,
    }])


def meeting_step_history(start: str, end: str, *, cfg: EventConfig = PRIMARY
                         ) -> pd.DataFrame:
    """Long frame ``[as_of, effective, jump_bp, stale, n_live]``, offline.

    One row per (business date, priced meeting). Stale legs are KEPT and
    flagged -- the ladder flags rather than drops them by design -- and every
    consumer here filters them, because a stale ZQ pair produces a jump of
    exactly 0.00 that is indistinguishable from a genuinely flat meeting.
    """
    from RVUtils.MeetingProb import meeting_ladder, zq_settle_panel

    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    if lo < LADDER_FLOOR:
        raise RuntimeError(
            f"the FOMC registry starts {LADDER_FLOOR.date()}; asking for "
            f"{lo.date()} would silently treat unregistered meeting months as "
            f"anchor months and corrupt the bootstrap")
    codes = "FGHJKMNQUVXZ"
    yrs = range(lo.year - 1 - 2000, hi.year + 2 - 2000)
    syms = [f"ZQ{c}{y}" for y in yrs for c in codes]   # chronological: the
    # staleness gate compares ADJACENT panel columns, so the order matters
    panel = zq_settle_panel(syms)
    fomc = load_fomc_schedule()

    rows: List[dict] = []
    for d in pd.bdate_range(lo, hi):
        lad = meeting_ladder(d.date(), panel, fomc)
        if not lad:
            continue
        n_live = sum(1 for m in lad if not m.stale)
        for m in lad:
            rows.append({"as_of": d, "effective": pd.Timestamp(m.effective),
                         "jump_bp": float(m.jump_bp), "stale": bool(m.stale),
                         "n_live": n_live, "contract": m.contract})
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError(f"no ladder priced between {start} and {end}")
    return out


def steps_on(hist: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """``effective -> jump_bp`` for one date, stale legs dropped."""
    sub = hist[(hist["as_of"] == as_of) & (~hist["stale"])]
    return sub.set_index("effective")["jump_bp"]


# ==========================================================================
# the language side
# ==========================================================================
def load_daily_sentiment(cfg: EventConfig, start: str, end: str
                         ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """``(daily sentiment frame, the underlying score book)``.

    The index is evaluated on a DAILY business-day grid rather than the weekly
    one the lead studies use. A weekly index cannot move inside a three-day
    event window, which would make the primary regressor identically zero on
    most events; the daily point-in-time index moves on 60.4% of days.

    Everything else -- the 21-day half-life, the 126-day truncation, the
    5-speech minimum, and for ``jpm`` the publication gate -- is
    ``fed_sentiment_lead_data``'s, unchanged.
    """
    lead = L.LeadConfig()
    grid = pd.bdate_range(start, end)
    if cfg.source == "jpm":
        scores = L.load_fed_scores(lead)
        pit = True
    elif cfg.source == "fedlock":
        import fedlock_data as F

        sp, prov = F.load_speeches()
        F.gate_single_vintage(sp, prov)
        scores = F.to_score_book(sp, score_column="m")
        pit = False
    else:
        raise ValueError(f"unknown source {cfg.source!r}; use 'jpm' or 'fedlock'")

    sent = L.sentiment_index(scores, grid, lead, point_in_time=pit)
    sent["z"] = L.trailing_z(sent["sentiment"], cfg.z_window_d, cfg.z_min_d)
    return sent, scores


def setpiece_calendar(start: str, end: str) -> pd.DataFrame:
    """The scheduled-communication calendar, built once and shared by both arms.

    Sources, in order of how much they can be trusted:

    ``fomc_decision``     the meeting registry. Exact.
    ``minutes``           ``decision + 21 days``, business-day adjusted. That has
                          been the release rule since early 2005 (before then
                          minutes followed the NEXT meeting), so it is exact over
                          this sample -- but it is DERIVED and flagged as such.
    ``press_conference``  FedLock's ``speech_type``. A DATE, not a score.
    ``testimony``         FedLock's ``speech_type``, plus a title regex for the
                          semiannual monetary-policy report.
    ``jackson_hole``      the hand table above, gated by :func:`gate_jackson_hole`.

    **Taking the calendar from FedLock is not taking its scores.** FedLock's
    ratings are one jointly-fitted vintage and carry hindsight; the fact that a
    press conference occurred on 2024-03-20 does not. Doing it this way is what
    makes the JPM and FedLock arms comparable at all: the JPM corpus has no
    field identifying the kind of communication, so without a shared calendar
    its set-piece universe would silently be ``fomc_decision`` + ``minutes``
    only, and a sign disagreement between the arms would be a difference of
    universe rather than of judge.
    """
    import fedlock_data as F

    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    rows: List[dict] = []

    fomc = load_fomc_schedule()
    for d in pd.to_datetime(fomc["effective_date"]) - pd.Timedelta(days=1):
        if lo <= d <= hi:
            rows.append({"date": d, "type": "fomc_decision", "speaker": None,
                         "derived": False})
        m = d + pd.Timedelta(days=21)
        while m.weekday() >= 5:
            m += pd.Timedelta(days=1)
        if lo <= m <= hi:
            rows.append({"date": m, "type": "minutes", "speaker": None,
                         "derived": True})

    sp, prov = F.load_speeches()
    F.gate_single_vintage(sp, prov)
    sp = sp.copy()
    sp["date"] = pd.to_datetime(sp["date"])
    title = sp["title"].astype(str).str.lower()
    semi = title.str.contains("semiannual|semi-annual", na=False)
    for _, r in sp[(sp["date"] >= lo) & (sp["date"] <= hi)].iterrows():
        k = str(r["speech_type"])
        t = ("press_conference" if k == "press_conference"
             else "testimony" if (k == "testimony" or semi.loc[r.name]) else None)
        if t:
            rows.append({"date": pd.Timestamp(r["date"]), "type": t,
                         "speaker": r.get("speaker"), "derived": False})

    cal = pd.DataFrame(rows)
    jh = {pd.Timestamp(v) for v in JACKSON_HOLE.values()}
    for d in sorted(jh):
        if lo <= d <= hi:
            rows.append({"date": d, "type": "jackson_hole", "speaker": None,
                         "derived": False})
    cal = pd.DataFrame(rows)
    cal.loc[cal["date"].isin(jh), "type"] = "jackson_hole"
    cal = (cal.sort_values(["date", "type"])
              .drop_duplicates(subset=["date", "type"])
              .reset_index(drop=True))
    return cal


def build_events(cfg: EventConfig, scores: pd.DataFrame, start: str, end: str,
                 *, calendar: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """The communication-event universe, one row per scored communication.

    Built from the corpus itself rather than from a hand-typed calendar, and
    tagged by type. Two types are added that a speech corpus cannot supply:

    ``fomc_decision``  the meeting registry's decision days.
    ``minutes``        ``decision + 21 days``, business-day adjusted. That has
                       been the release rule since early 2005 (before then
                       minutes came out after the *following* meeting), so it is
                       exact over this sample -- but it is DERIVED, is flagged
                       as such, and is reported separately from the types that
                       come from a source.

    ``jackson_hole`` overrides ``speech``/``press_conference`` on its date.
    """
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    cal = setpiece_calendar(start, end) if calendar is None else calendar.copy()
    setpiece_days = set(pd.DatetimeIndex(cal["date"]).normalize())

    scol = ("hawk_dove_score" if "hawk_dove_score" in scores.columns
            else "score" if "score" in scores.columns else None)
    rows: List[dict] = []
    for _, r in scores.iterrows():
        d = pd.Timestamp(r["date"])
        if not (lo <= d <= hi):
            continue
        # a scored communication that falls on a set-piece day IS that
        # set-piece; the calendar decides the type, the corpus supplies the score
        rows.append({"date": d, "type": "speech", "speaker": r.get("speaker"),
                     "score": float(r[scol]) if scol else np.nan,
                     "derived": False})
    ev = pd.concat([cal.assign(score=np.nan), pd.DataFrame(rows)],
                   ignore_index=True)
    # where a speech shares a day with a set-piece, keep the set-piece TYPE and
    # carry the speech's score onto it, so `x_dev` exists for pressers and
    # testimony rather than being NaN by construction
    ev["_sp"] = ev["date"].isin(setpiece_days)
    score_by_day = (ev.loc[ev["type"] == "speech"]
                      .groupby(ev["date"].dt.normalize())["score"].mean())
    is_sp = ev["type"].isin(SETPIECE_TYPES)
    ev.loc[is_sp, "score"] = ev.loc[is_sp, "date"].dt.normalize().map(score_by_day)
    ev = ev[~((ev["type"] == "speech") & ev["_sp"])].drop(columns=["_sp"])
    ev = ev.sort_values(["date", "type"]).reset_index(drop=True)
    return ev


def gate_jackson_hole(events: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """G-E2 -- every hand-entered Jackson Hole date must have a real
    communication within one day of it in the corpus.

    The JH dates are the only hand-typed input in this study. A wrong one would
    put an "event" on a day nothing happened, and a study of event windows
    cannot notice that by itself. Requiring corroboration from a source turns
    the hand entry into a checkable claim. 2026 is excluded: it has not happened.
    """
    sd = pd.to_datetime(scores["date"]).dt.normalize()
    rows = []
    for y, v in sorted(JACKSON_HOLE.items()):
        d = pd.Timestamp(v)
        near = int(((sd - d).abs() <= pd.Timedelta(days=1)).sum())
        # DENSITY, not span. The JPM corpus carries rows dated back to 2008 but
        # only becomes dense in 2023, so "inside the corpus's date range" would
        # demand corroboration the corpus cannot give and fail on a correct
        # date. A year is checkable only where the corpus has real coverage
        # around that month.
        dense = int(((sd - d).abs() <= pd.Timedelta(days=30)).sum())
        rows.append({"year": y, "keynote": d.date(), "weekday": d.day_name(),
                     "communications_within_1d": near,
                     "communications_within_30d": dense,
                     "corpus_is_dense_here": bool(dense >= 5)})
    out = pd.DataFrame(rows)
    checkable = out[out["corpus_is_dense_here"] & (out["year"] < 2026)]
    bad = checkable[checkable["communications_within_1d"] == 0]
    assert bad.empty, (
        f"G-E2 FAILED: no Fed communication within a day of the Jackson Hole "
        f"date(s) {list(bad['keynote'])} -- the hand-entered date is wrong or "
        f"the corpus does not cover it")
    assert len(checkable) >= 2, (
        f"G-E2 checked only {len(checkable)} Jackson Hole dates against a dense "
        f"corpus -- too few to be a check")
    return out


# ==========================================================================
# the event panel -- where y is defined
# ==========================================================================
def event_panel(events: pd.DataFrame, hist: pd.DataFrame, sent: pd.DataFrame,
                cfg: EventConfig = PRIMARY) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """One row per usable event, carrying ``x``, ``x_dev`` and ``y``.

    ``y`` is the change in the summed ``jump_bp`` of a FIXED pair of meetings --
    the first ``n_meetings`` whose ``effective`` is strictly AFTER the exit
    session -- matched **by effective date** on both marks.

    That fixing is the whole point. At an FOMC event a meeting resolves inside
    the window, so "the next two meetings" at entry and at exit are not the same
    two meetings; differencing those sums measures the roll, not the repricing.
    Any meeting missing or stale on either side drops the event, counted.
    """
    sessions = np.asarray(pd.DatetimeIndex(sorted(hist["as_of"].unique())).values,
                          dtype="datetime64[ns]")
    sdates = np.asarray(pd.DatetimeIndex(sent.index).values, dtype="datetime64[ns]")
    z = sent["z"]
    raw = sent["sentiment"]

    reasons: Dict[str, int] = {}

    def _bump(k):
        reasons[k] = reasons.get(k, 0) + 1

    def _shift(arr, on, k):
        i = int(np.searchsorted(arr, np.datetime64(pd.Timestamp(on)),
                                side="right" if k > 0 else "left"))
        i = i - 1 if k <= 0 else i
        i += (k - 1) if k > 0 else (k + 1)
        if i < 0 or i >= len(arr):
            return None
        return pd.Timestamp(arr[i])

    rows: List[dict] = []
    for _, e in events.iterrows():
        T = pd.Timestamp(e["date"])
        pre = _shift(sessions, T, -cfg.pre_days)
        post = _shift(sessions, T, +cfg.post_days)
        if pre is None or post is None or post <= pre:
            _bump("no session pair"); continue
        s_pre = steps_on(hist, pre)
        s_post = steps_on(hist, post)
        if s_pre.empty or s_post.empty:
            _bump("no priced ladder"); continue
        nlive = int(hist.loc[hist["as_of"] == pre, "n_live"].iloc[0])
        if nlive < cfg.min_live_meetings:
            _bump("too few live meetings"); continue

        # the fixed pair: strictly after the EXIT session, so neither resolves
        # inside the window
        fut = [m for m in s_pre.index if m > post][: cfg.n_meetings]
        if len(fut) < cfg.n_meetings:
            _bump("fewer than n_meetings ahead"); continue
        if any(m not in s_post.index for m in fut):
            _bump("meeting not priced on both marks"); continue
        y = float(sum(s_post[m] - s_pre[m] for m in fut))

        zp = _shift(sdates, T, -cfg.pre_days)
        zq_ = _shift(sdates, T, +cfg.post_days)
        if zp is None or zq_ is None:
            _bump("no sentiment marks"); continue
        x = float(z.get(zq_, np.nan) - z.get(zp, np.nan))
        if not np.isfinite(x):
            _bump("sentiment not finite"); continue

        sc = e.get("score")
        x_dev = np.nan
        if sc is not None and np.isfinite(sc):
            sd_ = raw.get(zp, np.nan)
            x_dev = float(sc - sd_) if np.isfinite(sd_) else np.nan

        rows.append({"date": T, "type": e["type"], "speaker": e.get("speaker"),
                     "derived": bool(e.get("derived", False)),
                     "entry": pre, "exit": post,
                     "meetings": "/".join(str(m.date()) for m in fut),
                     "n_live": nlive, "x": x, "x_dev": x_dev, "y": y,
                     "is_decision": e["type"] in DECISION_TYPES,
                     "is_setpiece": e["type"] in SETPIECE_TYPES})
    panel = pd.DataFrame(rows)
    reasons["kept"] = int(len(panel))
    return panel, reasons


def gate_y_is_a_fixed_pair(panel: pd.DataFrame) -> Dict[str, object]:
    """G-E3 -- no event's dependent variable spans a meeting that resolved.

    Every row's meeting pair must lie strictly after its own exit session. If it
    does not, ``y`` contains the roll from one meeting to the next, which on an
    FOMC day is the whole decision and dwarfs any language effect.
    """
    if panel.empty:
        return {"rows": 0, "checked": False}
    bad = 0
    for _, r in panel.iterrows():
        for m in str(r["meetings"]).split("/"):
            if pd.Timestamp(m) <= pd.Timestamp(r["exit"]):
                bad += 1
    assert bad == 0, (
        f"G-E3 FAILED: {bad} meeting legs resolve on or before their own exit "
        f"session -- y is measuring the roll, not the repricing")
    return {"rows": int(len(panel)), "checked": True, "legs_inside_window": bad}


# ==========================================================================
# Study A
# ==========================================================================
def ols(y: np.ndarray, x: np.ndarray) -> Dict[str, float]:
    """Slope, intercept and an HC3 t-stat. Small n, so heteroskedasticity-robust."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = x.size
    if n < 8 or np.std(x) == 0:
        return {"n": int(n), "beta": np.nan, "t": np.nan, "r2": np.nan,
                "se": np.nan, "alpha": np.nan}
    X = np.column_stack([np.ones(n), x])
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    r = y - X @ b
    h = np.einsum("ij,jk,ik->i", X, XtXi, X)
    om = (r / np.maximum(1e-12, 1 - h)) ** 2
    V = XtXi @ (X.T * om) @ X @ XtXi
    se = float(np.sqrt(max(V[1, 1], 0.0)))
    ss = float(((y - y.mean()) ** 2).sum())
    return {"n": int(n), "beta": float(b[1]), "alpha": float(b[0]), "se": se,
            "t": float(b[1] / se) if se > 0 else np.nan,
            "r2": float(1 - (r ** 2).sum() / ss) if ss > 0 else np.nan}


def matched_non_event_null(panel: pd.DataFrame, events: pd.DataFrame,
                           hist: pd.DataFrame, sent: pd.DataFrame,
                           cfg: EventConfig, *, draws: int = 400,
                           col: str = "x") -> Dict[str, object]:
    """The same regression on business days that are NOT communication events.

    The claim under test is that the effect *concentrates in event windows*. If
    an equal number of matched non-event days produces the same coefficient,
    there is no event effect -- only a correlation between two series that both
    move every day.

    Days within +/-1 business day of ANY event are excluded from the pool, so a
    "non-event" day is never a shoulder of a real one.
    """
    if panel.empty:
        return {"draws": 0, "note": "empty panel"}
    # Buffer on SET-PIECE events only. An ordinary speech day is deliberately
    # eligible as a control: the claim under test is that the effect
    # concentrates at scheduled communications, and a control set that excluded
    # every speech day would be testing something weaker.
    sp = events[events["type"].isin(SETPIECE_TYPES)]
    ev_days = set(pd.DatetimeIndex(sp["date"]).normalize())
    buffer = set()
    for d in ev_days:
        for k in (-2, -1, 0, 1, 2):
            buffer.add(pd.Timestamp(d) + pd.Timedelta(days=k))
    pool = [d for d in pd.DatetimeIndex(sorted(hist["as_of"].unique()))
            if d not in buffer]
    if len(pool) < len(panel) * 2:
        return {"draws": 0, "note": f"pool too small ({len(pool)})"}

    fake = pd.DataFrame({"date": pool, "type": "placebo", "speaker": None,
                         "score": np.nan, "derived": True})
    fp, _r = event_panel(fake, hist, sent, cfg)
    if fp.empty or len(fp) < len(panel):
        return {"draws": 0, "note": f"placebo panel too small ({len(fp)})"}

    rng = cfg.rng(3)
    k = int(len(panel))
    betas, ts = [], []
    for _ in range(int(draws)):
        s = fp.sample(k, replace=False, random_state=int(rng.integers(1 << 31)))
        o = ols(s["y"].to_numpy(float), s[col].to_numpy(float))
        if np.isfinite(o["beta"]):
            betas.append(o["beta"]); ts.append(o["t"])
    b = np.asarray(betas)
    return {"draws": int(b.size), "pool_days": int(len(pool)),
            "placebo_panel": int(len(fp)),
            "beta_q50": float(np.median(b)) if b.size else np.nan,
            "beta_q05": float(np.quantile(b, 0.05)) if b.size else np.nan,
            "beta_q95": float(np.quantile(b, 0.95)) if b.size else np.nan,
            "abs_t_q95": float(np.quantile(np.abs(ts), 0.95)) if b.size else np.nan}


def bootstrap_beta(panel: pd.DataFrame, col: str = "x", *, draws: int = 5000,
                   rng: Optional[np.random.Generator] = None) -> Dict[str, float]:
    """Percentile CI on the slope by resampling EVENTS, which is the unit."""
    rng = rng or np.random.default_rng(0)
    y = panel["y"].to_numpy(float)
    x = panel[col].to_numpy(float)
    m = np.isfinite(x) & np.isfinite(y)
    y, x = y[m], x[m]
    if y.size < 8:
        return {"n": int(y.size), "lo": np.nan, "hi": np.nan}
    out = np.empty(draws)
    for i in range(draws):
        idx = rng.integers(0, y.size, y.size)
        o = ols(y[idx], x[idx])
        out[i] = o["beta"]
    out = out[np.isfinite(out)]
    return {"n": int(y.size), "lo": float(np.quantile(out, 0.025)),
            "hi": float(np.quantile(out, 0.975)),
            "share_positive": float((out > 0).mean())}


def study_a(panel: pd.DataFrame, events: pd.DataFrame, hist: pd.DataFrame,
            sent: pd.DataFrame, cfg: EventConfig = PRIMARY,
            *, null_draws: int = 400) -> Dict[str, object]:
    """The decisive regression, on every split that has to be reported apart.

    The pre-registered read is the **set-piece, non-decision** row: minutes,
    press conferences, semiannual testimony and Jackson Hole. At a decision
    event the policy move itself reprices the strip, so a positive coefficient
    there is consistent with "the Fed did something" rather than "the Fed said
    something", and that row is labelled confounded wherever it appears.

    Ordinary speeches are reported as a separate secondary arm. They are far
    more numerous, they are not scheduled set-pieces, and including them in the
    primary would let a large low-information sample dominate a small
    high-information one.
    """
    out: Dict[str, object] = {"config": cfg, "n_events": int(len(panel))}
    if panel.empty:
        return out

    sp = panel[panel["is_setpiece"]]
    prim = sp[~sp["is_decision"]]
    cuts = [("all events", panel),
            ("set-piece, all", sp),
            ("set-piece, decision (confounded)", sp[sp["is_decision"]]),
            ("PRIMARY set-piece, NON-decision", prim),
            ("speeches only (secondary)", panel[~panel["is_setpiece"]])]
    for t in EVENT_TYPES:
        sub = panel[panel["type"] == t]
        if len(sub) >= 8:
            cuts.append((f"  type: {t}", sub))
    cuts.append(("  PRIMARY, x > 0", prim[prim["x"] > 0]))
    cuts.append(("  PRIMARY, x < 0", prim[prim["x"] < 0]))

    rows = []
    for name, sub in cuts:
        if sub.empty:
            continue
        a = ols(sub["y"].to_numpy(float), sub["x"].to_numpy(float))
        b = ols(sub["y"].to_numpy(float), sub["x_dev"].to_numpy(float))
        rows.append({"cut": name, "n": a["n"],
                     "beta_x": a["beta"], "t_x": a["t"], "r2_x": a["r2"],
                     "n_dev": b["n"], "beta_dev": b["beta"], "t_dev": b["t"],
                     "mean_y_bp": float(sub["y"].mean()),
                     "sd_y_bp": float(sub["y"].std(ddof=1)) if len(sub) > 1 else np.nan})
    out["table"] = pd.DataFrame(rows)

    nd = prim
    out["primary_cut"] = "set-piece, NON-decision (minutes / presser / testimony / JH)"
    out["primary"] = ols(nd["y"].to_numpy(float), nd["x"].to_numpy(float))
    out["primary_dev"] = ols(nd["y"].to_numpy(float), nd["x_dev"].to_numpy(float))
    out["primary_boot"] = bootstrap_beta(nd, "x", rng=cfg.rng(5))
    out["primary_boot_dev"] = bootstrap_beta(nd, "x_dev", rng=cfg.rng(6))
    out["null"] = matched_non_event_null(nd, events, hist, sent, cfg,
                                         draws=null_draws, col="x")

    # THE ECONOMIC SIZE, which is a different question from significance.
    # `beta` is bp of priced path per SD OF THE SENTIMENT INDEX, but an event
    # window does not move the index by a whole sd -- the EWMA damps one
    # communication heavily. What a trade would actually collect is
    # `beta * sd(x)`, i.e. the path move at a typical event. Against an SR3
    # round trip of 0.50bp (reference_sfr_fly_conventions) that number decides
    # whether a positive coefficient could ever have been worth trading, and it
    # is worth computing even when the coefficient is not significant -- because
    # if it is smaller than the spread, resolving the significance would not
    # change the answer.
    xs = nd["x"].to_numpy(float)
    xs = xs[np.isfinite(xs)]
    b = out["primary"].get("beta", np.nan)
    sd_x = float(np.std(xs, ddof=1)) if xs.size > 1 else np.nan
    out["size"] = {
        "sd_of_x": sd_x,
        "mean_abs_x": float(np.mean(np.abs(xs))) if xs.size else np.nan,
        "bp_per_1sd_of_x": float(b * sd_x) if np.isfinite(b) else np.nan,
        "bp_at_the_90th_pct_event": (
            float(b * np.quantile(np.abs(xs), 0.90)) if xs.size and np.isfinite(b)
            else np.nan),
        "sr3_round_trip_bp": 0.50,
        "events_per_year": float(len(nd) / max(
            (pd.Timestamp(nd["date"].max()) - pd.Timestamp(nd["date"].min())).days
            / 365.25, 1e-9)) if len(nd) > 1 else np.nan,
    }
    sz = out["size"]
    sz["clears_the_spread"] = bool(np.isfinite(sz["bp_per_1sd_of_x"])
                                   and abs(sz["bp_per_1sd_of_x"]) > 0.50)

    # HOW MUCH DATA WOULD SETTLE IT. If the effect clears the spread at face
    # value but the t-statistic cannot reject zero, the binding constraint is
    # the SAMPLE, not the size -- and the useful number is then how many events
    # it would take. The standard error of a slope falls as 1/sqrt(n), so
    # holding the point estimate and the residual noise fixed,
    # n* = n * (t_target / t_observed)^2. This assumes the effect is real and
    # exactly what was measured, which is the most generous assumption
    # available; it is a LOWER bound on what would be needed.
    t_obs = out["primary"].get("t", np.nan)
    n_obs = out["primary"].get("n", 0)
    per_yr = sz.get("events_per_year", np.nan)
    need = (n_obs * (2.0 / t_obs) ** 2 if np.isfinite(t_obs) and t_obs != 0
            else np.nan)
    out["power"] = {
        "t_observed": t_obs, "n_observed": int(n_obs),
        "events_for_abs_t_2": float(need) if np.isfinite(need) else np.nan,
        "extra_events_needed": float(need - n_obs) if np.isfinite(need) else np.nan,
        "years_at_this_rate": (float((need - n_obs) / per_yr)
                               if np.isfinite(need) and per_yr else np.nan),
        "note": ("assumes the measured slope is real and the residual noise is "
                 "unchanged -- a LOWER bound on the data required"),
    }

    # tercile buckets: the relationship need not be linear, and n is small
    if len(nd) >= 15:
        q = pd.qcut(nd["x"], 3, labels=["low x", "mid x", "high x"],
                    duplicates="drop")
        g = nd.groupby(q, observed=True)["y"]
        out["terciles"] = pd.DataFrame({"n": g.size(), "mean_y_bp": g.mean(),
                                        "sd_y_bp": g.std(ddof=1)})
    return out


def verdict(res: Dict[str, object]) -> Dict[str, object]:
    """The pre-registered decision rule, applied mechanically.

    ALIVE requires all three: the non-decision slope is positive, its bootstrap
    CI excludes zero, and it beats the 95th percentile of the matched
    non-event-day null. Anything else stops the programme at Study A.
    """
    p = res.get("primary") or {}
    b = res.get("primary_boot") or {}
    n = res.get("null") or {}
    beta, lo, hi = p.get("beta", np.nan), b.get("lo", np.nan), b.get("hi", np.nan)
    q95 = n.get("beta_q95", np.nan)
    tests = {
        "slope is positive": bool(np.isfinite(beta) and beta > 0),
        "bootstrap CI excludes zero": bool(np.isfinite(lo) and np.isfinite(hi)
                                           and (lo > 0 or hi < 0)),
        "beats the non-event null q95": bool(np.isfinite(beta) and np.isfinite(q95)
                                             and beta > q95),
    }
    return {"tests": tests, "alive": all(tests.values()), "beta": beta,
            "ci": (lo, hi), "null_q95": q95}


# ==========================================================================
# the forward read -- what the measured lead says about a given date
# ==========================================================================
def forward_read(dates: Sequence[str], leads_w: Sequence[int] = (5, 11, 14),
                 *, lead_cfg: Optional[L.LeadConfig] = None) -> pd.DataFrame:
    """What the surprise composite implies for Fedspeak on each date.

    At a lead of L weeks, the data that should be surfacing in Fed language on
    date D is the composite as it stood L weeks earlier. This is arithmetic on
    an already-measured lead, not a new estimate -- and it is the number the
    Jackson Hole question actually turns on.
    """
    lead_cfg = lead_cfg or L.LeadConfig()
    panel, _ = L.load_surprise_panel()
    comp, _legs = L.build_surprise_composite(panel, lead_cfg)
    zc = L.weekly_last(comp, lead_cfg.week_anchor).dropna()
    rows = []
    for d in dates:
        D = pd.Timestamp(d)
        row = {"date": D.date()}
        for Lw in leads_w:
            t = D - pd.Timedelta(weeks=int(Lw))
            past = zc.index[zc.index <= t]
            v = float(zc.loc[past[-1]]) if len(past) else np.nan
            row[f"z_composite_at_L{Lw}"] = v
            row[f"reads_data_of_L{Lw}"] = str(past[-1].date()) if len(past) else None
        rows.append(row)
    return pd.DataFrame(rows)


# ==========================================================================
# section 4 -- the regime reading of #491, tested rather than asserted
# ==========================================================================
#: Forward-guidance regimes. The claim being tested is that the lead needs
#: front-meeting premium to exist, and that under guidance there was none to
#: harvest -- so a 21-year sample pools a regime where the mechanism is
#: mechanically impossible with one where it might work. If the effect tracks
#: these boundaries it is a mechanism; if it appears at random across them,
#: #491's overfitting reading was right.
GUIDANCE_REGIMES: Tuple[Tuple[str, str, str], ...] = (
    ("pre-statement", "1985-01-01", "1994-02-03"),
    ("statement, no projections", "1994-02-04", "2003-05-05"),
    ("balance of risks", "2003-05-06", "2011-12-31"),
    ("dots / guidance", "2012-01-01", "2025-12-31"),
    ("no guidance (Warsh)", "2026-01-01", "2027-12-31"),
)


def regime_lead_split(*, lags: Sequence[int] = tuple(range(-13, 14)),
                      transform: str = "changes",
                      lead_cfg: Optional[L.LeadConfig] = None) -> pd.DataFrame:
    """The lead correlation, computed inside each guidance regime separately.

    Uses FedLock (the only sentiment series long enough to see more than one
    regime) and therefore measures a HISTORICAL ASSOCIATION, never a backtest --
    the scores are one jointly-fitted vintage.

    Reports the argmax lag and its correlation per regime, plus the number of
    joint weeks, because a regime with 30 weeks in it cannot support an argmax
    over a 27-lag grid and the honest answer there is "not measurable" rather
    than a number.

    **The two earliest regimes are empty, and the reason is the SURPRISE side,
    not FedLock.** FedLock carries 307 dated speeches in the 1990s. Citi's daily
    CESI sub-indices begin in 2003, so the composite -- and therefore any joint
    week -- cannot exist before then whatever the sentiment history is. The
    brief's proposed pre-1994 and 1994-2003 splits are unavailable for that
    reason and are reported as unmeasurable rather than as zero effect.
    """
    import fedlock_data as F

    lead_cfg = lead_cfg or L.LeadConfig()
    panel, _ = L.load_surprise_panel()
    comp, _legs = L.build_surprise_composite(panel, lead_cfg)
    zc = L.weekly_last(comp, lead_cfg.week_anchor)

    sp, prov = F.load_speeches()
    F.gate_single_vintage(sp, prov)
    book = F.to_score_book(sp, score_column="m")
    grid = L.weekly_grid(pd.Timestamp(book["date"].min()),
                         pd.Timestamp(book["date"].max()), lead_cfg.week_anchor)
    sent = L.sentiment_index(book, grid, lead_cfg, point_in_time=False)["sentiment"]
    zs = L.trailing_z(sent, 52, 26)

    rows = []
    for name, lo, hi in GUIDANCE_REGIMES:
        lo_, hi_ = pd.Timestamp(lo), pd.Timestamp(hi)
        x = zc[(zc.index >= lo_) & (zc.index <= hi_)]
        y = zs[(zs.index >= lo_) & (zs.index <= hi_)]
        joint = int(len(x.dropna().index.intersection(y.dropna().index)))
        row = {"regime": name, "from": lo_.date(), "to": hi_.date(),
               "joint_weeks": joint}
        # 3 * (2*max_lag + 1) is the floor the shift-null needs to exist at all;
        # below it an argmax is noise and is reported as such
        if joint < 3 * (2 * max(lags) + 1):
            row.update({"argmax_lag_w": np.nan, "corr_at_argmax": np.nan,
                        "measurable": False,
                        "note": f"needs >= {3 * (2 * max(lags) + 1)} joint weeks"})
            rows.append(row)
            continue
        xa, ya, _info = L.transform_pair(x, y, transform)
        X, Y, _idx = L.lag_matrix(xa, ya, lags)
        curve = L.lag_curve_common(X, Y, lags)
        c = curve.dropna(subset=["corr"])
        if c.empty:
            row.update({"argmax_lag_w": np.nan, "corr_at_argmax": np.nan,
                        "measurable": False, "note": "no finite correlation"})
        else:
            best = c.loc[c["corr"].idxmax()]
            row.update({"argmax_lag_w": int(best["lag_weeks"]),
                        "corr_at_argmax": float(best["corr"]),
                        "corr_at_L5": float(c.loc[c["lag_weeks"] == 5, "corr"].iloc[0])
                        if (c["lag_weeks"] == 5).any() else np.nan,
                        "corr_at_L11": float(c.loc[c["lag_weeks"] == 11, "corr"].iloc[0])
                        if (c["lag_weeks"] == 11).any() else np.nan,
                        "n_used": int(best["n"]), "measurable": True, "note": ""})
        rows.append(row)
    return pd.DataFrame(rows)
