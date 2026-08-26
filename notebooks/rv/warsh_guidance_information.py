"""Does each Warsh speaker event carry more information than under guidance?

The claim under test, and the pushback it drew, are statements about **different
terms of the same decomposition**. Writing them out is most of the work:

    total information flow  =  lambda * E[I_e]  +  the non-event channel

where ``lambda`` is the event arrival rate and ``I_e = H_before - E[H_after]``
is what one event removes from the market's uncertainty ``H`` about the path.

* The claim -- "each speaker event carries more marginal information" -- is
  about **E[I_e]**, a conditional, per-event quantity.
* The pushback -- "pure optionality, he stays silent when it suits him, no
  information is information" -- is about **lambda** (down) and the **non-event
  channel** (up).

Both can hold at once, so "Warsh speaks less" does not by itself touch the
claim. The pushback does contain one objection that bites, and it is not the
obvious one: **selection**. If he speaks *because* there is news, ``E[I_e | he
spoke]`` rises with no change in how informative his communication is.

That objection has an identification, and it is the reason this module splits
every event universe two ways:

``scheduled``      fomc decisions, minutes, press conferences, testimony,
                   Jackson Hole. He **cannot** filter these -- the presser
                   happens because the meeting happened. Selection cannot
                   explain an elevated response here.
``discretionary``  ordinary speeches. He chooses whether to give them.

A third hypothesis arrives from the Citadel Securities note of 2026-08-25 --
that the presser response "reflects a lack of clarity around his reaction
function". That is neither the claim nor the pushback: it agrees the strip moves
and denies that the move is information. A big price change with **no reduction
in uncertainty** is noise. Hence :func:`uncertainty_around_events`.

Everything here is offline: the ZQ meeting ladder from the settle cache, the
speech corpora from disk, the release calendar from its parquet core.

See ``docs/reports/2026-08-25-warsh-guidance-information-PREREG.md`` for the
prediction table, fixed before any of this was run.
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_event_conditioning as FEC  # noqa: E402

#: The guidance drop was announced AT the June-2026 FOMC (announcement
#: 2026-06-17), so the first session priced knowing there is no guidance is the
#: 18th. ``project_front_month_premium`` fixes this date independently.
WARSH_BOUNDARY = pd.Timestamp("2026-06-18")

#: Reported as robustness only. The chair transition and the guidance drop are
#: different events and the study is about the second one.
ALT_BOUNDARY = pd.Timestamp("2026-05-01")

#: The FOMC registry's floor. Before it the ladder is corrupted, not absent.
LADDER_FLOOR = FEC.LADDER_FLOOR

#: The Fed moves in 25bp increments, so a meeting priced at a multiple of 25 is
#: priced as a near-certainty and one priced between them is priced as a coin
#: toss. Half a click is therefore the maximum possible distance.
CLICK_BP = 25.0
MAX_DEGENERACY_DISTANCE = CLICK_BP / 2.0


def era_of(dates, boundary: pd.Timestamp = WARSH_BOUNDARY) -> np.ndarray:
    d = pd.DatetimeIndex(pd.to_datetime(dates))
    return np.where(d >= boundary, "warsh", "guidance")


def klass_of(types) -> np.ndarray:
    t = pd.Series(list(types), dtype=object)
    return np.where(t.isin(FEC.SETPIECE_TYPES), "scheduled", "discretionary")


# ==========================================================================
# the price side -- a roll-safe daily path change, and a coin-toss measure
# ==========================================================================
def daily_path_change(hist: pd.DataFrame, n_meetings: int = 2) -> pd.DataFrame:
    """``[date, dpath_bp, meetings]`` -- the session-to-session change in the
    summed ``jump_bp`` of a **fixed** set of meetings.

    The fixing is not optional. Between two sessions a meeting can resolve, and
    "the next two meetings" then names a different pair on each side; the
    difference of those two sums is the roll, not the repricing. On an FOMC day
    the roll IS the whole decision, which is exactly where this study looks. The
    same discipline as :func:`fed_event_conditioning.event_panel`, applied to
    every consecutive session pair rather than to event windows.
    """
    sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
    steps = {d: FEC.steps_on(hist, d) for d in sess}
    nlive = (hist.drop_duplicates("as_of").set_index("as_of")["n_live"]).to_dict()

    rows: List[dict] = []
    for a, b in zip(sess[:-1], sess[1:]):
        sa, sb = steps[a], steps[b]
        if sa.empty or sb.empty:
            continue
        # strictly after the LATER session, so nothing resolves inside the step
        fut = [m for m in sa.index if m > b][:n_meetings]
        if len(fut) < n_meetings or any(m not in sb.index for m in fut):
            continue
        rows.append({"date": b,
                     "dpath_bp": float(sum(sb[m] - sa[m] for m in fut)),
                     "meetings": "/".join(str(m.date()) for m in fut),
                     "n_live": int(nlive.get(b, 0))})
    if not rows:
        # every step was dropped. Return the right SHAPE rather than raising on
        # a missing index column: callers group and share this frame, and a
        # KeyError here would surface far from the ladder gap that caused it.
        return pd.DataFrame(columns=["dpath_bp", "meetings", "n_live"],
                            index=pd.DatetimeIndex([], name="date"))
    return pd.DataFrame(rows).set_index("date")


def degeneracy_distance(hist: pd.DataFrame, n_meetings: int = 4
                        ) -> pd.DataFrame:
    """How far the priced ladder sits from an all-or-nothing outcome.

    For each session, the mean over the next ``n_meetings`` live meetings of
    ``|jump - 25*round(jump/25)|``. Zero means every meeting is priced as a
    near-certain hold or a near-certain click; 12.5 means every one is priced as
    a coin toss.

    **This is not entropy and is not called it.** ``jump_bp`` is a point
    estimate -- the expected move -- so its dispersion across meetings measures
    the shape of the mean path, not uncertainty about it. What this does measure
    is real and is the thing forward guidance acts on: guidance collapses a
    meeting onto an outcome, and ``project_front_month_premium`` recorded exactly
    that ("the T-1 distribution was degenerate (0 or 25)"). The Citadel note's
    "September is a coin toss" is a claim about this number.
    """
    sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
    rows: List[dict] = []
    for d in sess:
        s = FEC.steps_on(hist, d)
        s = s[s.index > d][:n_meetings]
        if len(s) < n_meetings:
            continue
        dist = (s - CLICK_BP * np.round(s / CLICK_BP)).abs()
        rows.append({"date": d, "degen_dist_bp": float(dist.mean()),
                     "degen_dist_front_bp": float(dist.iloc[0]),
                     "abs_path_bp": float(s.abs().sum()),
                     "n": int(len(s))})
    return pd.DataFrame(rows).set_index("date")


def fixed_window_degeneracy(hist: pd.DataFrame, T: pd.Timestamp,
                            *, pre_days: int = 1, max_post: int = 5,
                            n_meetings: int = 2) -> Optional[Dict[str, float]]:
    """Degeneracy distance before and after one event, on a FIXED meeting set.

    The meeting set is fixed to those strictly after ``T + max_post`` business
    days, so every horizon 0..``max_post`` reads the same meetings and none of
    them resolves inside any window. Returns the pre level and the change at
    each horizon, or ``None`` if the ladder cannot price the window.
    """
    sess = pd.DatetimeIndex(sorted(hist["as_of"].unique()))
    i = int(np.searchsorted(sess.values, np.datetime64(pd.Timestamp(T)), "left"))
    if i - pre_days < 0 or i + max_post >= len(sess):
        return None
    pre = sess[i - pre_days]
    posts = [sess[i + k] for k in range(0, max_post + 1)]
    s_pre = FEC.steps_on(hist, pre)
    if s_pre.empty:
        return None
    fut = [m for m in s_pre.index if m > posts[-1]][:n_meetings]
    if len(fut) < n_meetings:
        return None

    def _d(on):
        s = FEC.steps_on(hist, on)
        if any(m not in s.index for m in fut):
            return np.nan
        v = s[fut]
        return float((v - CLICK_BP * np.round(v / CLICK_BP)).abs().mean())

    d_pre = _d(pre)
    if not np.isfinite(d_pre):
        return None
    out = {"date": pd.Timestamp(T), "pre": pre, "degen_pre": d_pre,
           "meetings": "/".join(str(m.date()) for m in fut)}
    for k, p in enumerate(posts):
        dk = _d(p)
        out[f"degen_t{k}"] = dk
        out[f"d_degen_t{k}"] = dk - d_pre if np.isfinite(dk) else np.nan
    return out


# ==========================================================================
# T1 -- the arrival rate, season matched
# ==========================================================================
def arrival_rate(scores: pd.DataFrame, *, boundary: pd.Timestamp = WARSH_BOUNDARY,
                 end: pd.Timestamp = pd.Timestamp("2026-08-25"),
                 years: Sequence[int] = (2021, 2022, 2023, 2024, 2025),
                 dense_from: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Discretionary speeches per business day in the Warsh window, against the
    SAME calendar window of earlier years.

    Season matching is not a refinement here, it is the difference between a
    result and an artefact. The Warsh window is 18 June to 25 August: it
    contains the summer recess and the run-up to Jackson Hole, both of which
    suppress speaking. Comparing it to an all-season base rate would find
    "Warsh speaks less" even if his behaviour were identical to his
    predecessor's.

    ``dense_from`` drops matched years where the corpus is not yet dense (the
    JPM book carries rows back to 2008 but only becomes dense in 2023), because
    a sparse year would read as a low arrival rate that is a property of the
    corpus, not of the Fed.
    """
    sd = pd.to_datetime(scores["date"]).dt.normalize()
    md, mm = boundary.month, boundary.day
    ed, em = end.month, end.day
    rows: List[dict] = []
    for y in list(years) + [int(boundary.year)]:
        lo = pd.Timestamp(year=y, month=md, day=mm)
        hi = pd.Timestamp(year=y, month=ed, day=em)
        if dense_from is not None and hi < dense_from:
            continue
        n = int(((sd >= lo) & (sd <= hi)).sum())
        bd = int(len(pd.bdate_range(lo, hi)))
        rows.append({"year": y, "window": f"{lo.date()}..{hi.date()}",
                     "speeches": n, "business_days": bd,
                     "per_bd": n / bd if bd else np.nan,
                     "per_month": n / (((hi - lo).days + 1) / 30.44),
                     "is_warsh": y == int(boundary.year)})
    out = pd.DataFrame(rows)
    base = out[~out["is_warsh"]]["per_bd"]
    if len(base):
        w = float(out.loc[out["is_warsh"], "per_bd"].iloc[0])
        out.attrs["matched_mean_per_bd"] = float(base.mean())
        out.attrs["warsh_per_bd"] = w
        out.attrs["ratio"] = w / float(base.mean()) if base.mean() else np.nan
        # a count comparison deserves a count test
        out.attrs["poisson_p"] = _poisson_rate_p(
            k=int(out.loc[out["is_warsh"], "speeches"].iloc[0]),
            exposure=int(out.loc[out["is_warsh"], "business_days"].iloc[0]),
            rate0=float(base.mean()))
    return out


def _poisson_rate_p(k: int, exposure: int, rate0: float) -> float:
    """Two-sided exact Poisson test of ``k`` events against rate ``rate0``."""
    from scipy import stats

    mu = rate0 * exposure
    if mu <= 0:
        return np.nan
    p_obs = stats.poisson.pmf(k, mu)
    ks = np.arange(0, int(mu + 10 * np.sqrt(mu) + 20))
    return float(stats.poisson.pmf(ks, mu)[
        stats.poisson.pmf(ks, mu) <= p_obs * (1 + 1e-9)].sum())


# ==========================================================================
# T3 -- per-event response, and the placement table that replaces a t-test
# ==========================================================================
def placement_table(panel: pd.DataFrame, *,
                    boundary: pd.Timestamp = WARSH_BOUNDARY,
                    col: str = "y") -> pd.DataFrame:
    """Where each Warsh event's response sits in the guidance-era distribution
    OF THE SAME EVENT TYPE.

    With six scheduled events in the Warsh era, a t-statistic would be theatre.
    Six percentiles are honest, readable, and do not pretend to a standard
    error. Comparing within type matters: an FOMC decision and an ordinary
    speech are not draws from one distribution, and pooling them would let the
    single Warsh decision borrow the speeches' tighter spread.
    """
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"])
    p["era"] = era_of(p["date"], boundary)
    p["klass"] = klass_of(p["type"])
    p["abs"] = p[col].abs()
    rows: List[dict] = []
    for _, r in p[p["era"] == "warsh"].sort_values("date").iterrows():
        ref = p[(p["era"] == "guidance") & (p["type"] == r["type"])]["abs"]
        rows.append({
            "date": r["date"].date(), "type": r["type"], "klass": r["klass"],
            "abs_y_bp": float(r["abs"]), "signed_y_bp": float(r[col]),
            "n_guidance_same_type": int(len(ref)),
            "pct_in_guidance": (float((ref < r["abs"]).mean() * 100.0)
                                if len(ref) else np.nan),
            "guidance_median_abs": float(ref.median()) if len(ref) else np.nan})
    return pd.DataFrame(rows)


def response_summary(panel: pd.DataFrame, *,
                     boundary: pd.Timestamp = WARSH_BOUNDARY,
                     col: str = "y") -> pd.DataFrame:
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"])
    p["era"] = era_of(p["date"], boundary)
    p["klass"] = klass_of(p["type"])
    p["abs"] = p[col].abs()
    g = (p.groupby(["klass", "era"])["abs"]
           .agg(n="size", mean_abs="mean", median_abs="median", sd="std")
           .reset_index())
    return g


def decidable_date(n_now: int, n_needed: int, per_month: float,
                   start: pd.Timestamp = pd.Timestamp("2026-08-25")
                   ) -> pd.Timestamp:
    """When the scheduled-only test stops being underpowered, at the observed
    scheduled-event arrival rate."""
    if per_month <= 0 or n_now >= n_needed:
        return start
    return start + pd.Timedelta(days=int(round((n_needed - n_now) / per_month * 30.44)))


# ==========================================================================
# T5 -- the three-bucket variance decomposition
# ==========================================================================
def release_days(start: str, end: str, *, impacts=("high",)) -> pd.DatetimeIndex:
    """High-impact scheduled US data releases.

    A **scheduled-release** bucket, not a **surprising-release** bucket. Bucketing
    on the size of the surprise would condition on the outcome -- days the data
    moved the market would be selected into the data bucket by construction,
    and the decomposition would be circular.
    """
    from RVUtils.forex_factory_calendar import fetch_forex_factory_calendar

    df = fetch_forex_factory_calendar(start, end, currencies="USD",
                                      impacts=list(impacts), show_tqdm=False,
                                      use_core=True)
    if df.empty:
        return pd.DatetimeIndex([])
    d = pd.to_datetime(df["TimestampNYC"]).dt.tz_localize(None).dt.normalize()
    return pd.DatetimeIndex(sorted(set(d)))


def variance_buckets(dpath: pd.DataFrame, event_days: pd.DatetimeIndex,
                     rel_days: pd.DatetimeIndex, *,
                     boundary: pd.Timestamp = WARSH_BOUNDARY) -> pd.DataFrame:
    """Share of squared path change falling on speaker / release / quiet days.

    Three buckets, not two. The Citadel note records that the Warsh window's
    data ran dovish -- payroll misses and revisions, two better inflation
    prints. A two-bucket split books that variance into "non-event" and hands
    the optionality hypothesis an artefact it did not earn.

    Speaker days take precedence over release days where they collide, so the
    speaker bucket is the generous one: if the result is that the speaker share
    FELL, the assignment was not what produced it.
    """
    d = dpath.copy()
    d["era"] = era_of(d.index, boundary)
    ev = set(pd.DatetimeIndex(event_days).normalize())
    rl = set(pd.DatetimeIndex(rel_days).normalize())
    idx = pd.DatetimeIndex(d.index).normalize()
    d["bucket"] = np.where([x in ev for x in idx], "speaker",
                           np.where([x in rl for x in idx], "release", "quiet"))
    d["sq"] = d["dpath_bp"] ** 2
    rows: List[dict] = []
    for era, sub in d.groupby("era"):
        tot = float(sub["sq"].sum())
        for b in ("speaker", "release", "quiet"):
            s = sub[sub["bucket"] == b]
            rows.append({"era": era, "bucket": b, "days": int(len(s)),
                         "day_share_pct": 100.0 * len(s) / len(sub) if len(sub) else np.nan,
                         "var_share_pct": 100.0 * float(s["sq"].sum()) / tot if tot else np.nan,
                         "rms_bp": float(np.sqrt(s["sq"].mean())) if len(s) else np.nan})
    return pd.DataFrame(rows)


# ==========================================================================
# T6 -- silence gaps
# ==========================================================================
def silence_gaps(scores: pd.DataFrame, dpath: pd.DataFrame, *,
                 boundary: pd.Timestamp = WARSH_BOUNDARY,
                 min_gap_bd: int = 3) -> pd.DataFrame:
    """Path movement accumulated during runs of consecutive non-speech days.

    "No information is information" predicts the strip does MORE work during
    Warsh silences than during guidance-era silences of the same length. Gaps
    are measured in business days and compared like-for-like on length, because
    a longer gap trivially accumulates more movement.
    """
    sd = set(pd.to_datetime(scores["date"]).dt.normalize())
    idx = pd.DatetimeIndex(dpath.index).normalize()
    quiet = ~np.array([x in sd for x in idx])
    rows: List[dict] = []
    i = 0
    while i < len(idx):
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(idx) and quiet[j + 1]:
            j += 1
        n = j - i + 1
        if n >= min_gap_bd:
            seg = dpath.iloc[i:j + 1]["dpath_bp"]
            rows.append({"start": idx[i], "end": idx[j], "len_bd": int(n),
                         "era": era_of([idx[i]], boundary)[0],
                         "abs_move_bp": float(seg.abs().sum()),
                         "net_move_bp": float(seg.sum()),
                         "rms_bp": float(np.sqrt((seg ** 2).mean()))})
        i = j + 1
    return pd.DataFrame(rows)


# ==========================================================================
# gates
# ==========================================================================
def gate_boundary_is_a_real_meeting(hist: pd.DataFrame) -> Dict[str, object]:
    """G-W1 -- the era boundary must fall the day after an FOMC announcement.

    The whole study is a before/after on one date. If that date drifted to an
    arbitrary session the comparison would still run and still produce numbers.
    """
    fomc = FEC.load_fomc_schedule()
    eff = pd.DatetimeIndex(pd.to_datetime(fomc["effective_date"]))
    gaps = (WARSH_BOUNDARY - eff).days
    near = gaps[(gaps >= 0) & (gaps <= 3)]
    assert len(near) > 0, (
        f"G-W1 FAILED: {WARSH_BOUNDARY.date()} is not within 3 days after any "
        f"FOMC effective date -- the era boundary is not a meeting")
    return {"boundary": WARSH_BOUNDARY.date(),
            "days_after_nearest_effective": int(near.min()),
            "nearest_effective": str(eff[(gaps >= 0) & (gaps <= 3)][0].date())}


def gate_dpath_never_spans_a_resolution(hist: pd.DataFrame,
                                        dpath: pd.DataFrame,
                                        sample: int = 400,
                                        seed: int = 20260825) -> Dict[str, object]:
    """G-W2 -- every daily step reads meetings strictly after its own later
    session, on both marks.

    A step that spans a resolution books the meeting roll as a repricing. On an
    FOMC day that roll is the entire decision, and the FOMC days are exactly the
    ones this study weighs most heavily -- so this gate protects the finding it
    is most able to fake.
    """
    rng = np.random.default_rng(seed)
    idx = pd.DatetimeIndex(dpath.index)
    take = idx if len(idx) <= sample else idx[np.sort(
        rng.choice(len(idx), sample, replace=False))]
    checked = bad = 0
    for b in take:
        ms = [pd.Timestamp(x) for x in str(dpath.at[b, "meetings"]).split("/")]
        s_b = FEC.steps_on(hist, b)
        for m in ms:
            checked += 1
            if not (m > b) or m not in s_b.index:
                bad += 1
    assert checked > 0, "G-W2 checked nothing -- the gate proves nothing"
    assert bad == 0, f"G-W2 FAILED: {bad} of {checked} meeting legs resolve inside their own step"
    return {"steps_checked": int(len(take)), "legs_checked": int(checked),
            "violations": int(bad)}


def gate_warsh_window_is_not_empty(panel: pd.DataFrame,
                                   boundary: pd.Timestamp = WARSH_BOUNDARY
                                   ) -> Dict[str, object]:
    """G-W3 -- the Warsh side of every comparison must actually contain events.

    A before/after split whose "after" is empty returns NaN, and a NaN read as
    "no difference" is the failure mode this study is most exposed to.
    """
    p = panel.copy()
    p["era"] = era_of(pd.to_datetime(p["date"]), boundary)
    p["klass"] = klass_of(p["type"])
    counts = p.groupby(["klass", "era"]).size().unstack(fill_value=0)
    assert "warsh" in counts.columns, "G-W3 FAILED: no Warsh-era events at all"
    for k in counts.index:
        assert counts.loc[k, "warsh"] > 0, (
            f"G-W3 FAILED: zero Warsh-era events of class {k!r}")
    return {"counts": counts.to_dict()}
