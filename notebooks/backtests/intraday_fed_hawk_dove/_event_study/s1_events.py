"""STAGE 1 - the event book and the placebo draw. No bar fetching happens here.

Deliberately does NOT go through ``build_trade_events`` / ``gate_events``: that
machinery applies a policy blackout, drops neutral / no-score speakers, clamps
entry-exit into the session and enforces a 30-minute window. Every one of those
would silently reshape an event-study panel. This builds the book directly from
the raw ForexFactory calendar with the SAME timestamp handling, speaker
extraction and press-conference rule, and keeps everything else, flagged.

Writes:
    events.parquet          one row per real speech
    placebo_events.parquet  one row per pseudo-event (>=3x, time-of-day + weekday matched)
    quiet_days.parquet      the placebo candidate pool
    s1_report.txt           the funnel and every count
"""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import numpy as np
import pandas as pd
import QuantLib as ql

import global_hawk_dove_common as G
import fomc_extras as FX

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
HERE.mkdir(exist_ok=True)
DRIVER = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis")

SCORES_CSV = r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\global_hawk_dove_scores.csv"
FED_ONLY_CSV = r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv"
SCORE_METRIC = "trailing_5_avg"

# SR3 era only. CB_CONFIGS["FED"].root_splice puts SR3 from 2022-01-01; GE before
# that is a different contract and must not be spliced into one path.
SAMPLE_START = datetime.date(2022, 1, 1)
SAMPLE_END = datetime.date(2026, 8, 25)
# fetched wider so overlap detection sees neighbours either side of the sample edge
FETCH_START = "2021-11-01"
FETCH_END = "2026-09-30"

OFFSETS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0,
           5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]
BASELINE_OFFSET = -60
RANKS = [1, 2, 3, 4, 5]

#: window intersection: two events' [-120, +300] windows overlap iff |dt| < 420 min
WINDOW_SPAN_MIN = max(OFFSETS) - min(OFFSETS)      # 420
PLACEBO_PER_EVENT = 3
SEED = 20260825
#: calendar-time match: the narrowest of these half-windows (days either side of
#: the parent speech) that still holds PLACEBO_PER_EVENT same-weekday quiet days.
PLACEBO_WINDOWS_D = (60, 120, 240, 400, 99999)

LOG: list[str] = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def main() -> None:
    cfg = G.CB_CONFIGS["FED"]
    tz = cfg.tz
    p("=" * 78)
    p("STAGE 1  event book")
    p("=" * 78)
    p(f"sample      : {SAMPLE_START} -> {SAMPLE_END}  (SR3 era)")
    p(f"calendar    : {FETCH_START} -> {FETCH_END}  (wider, for overlap detection)")
    p(f"offsets     : {OFFSETS}")
    p(f"baseline    : offset {BASELINE_OFFSET} min")
    p(f"ranks       : {RANKS}")

    # ---------------------------------------------------------------- calendar
    p("")
    p("--- ForexFactory FED_SPEAKERS calendar ---")
    t0 = datetime.datetime.now()
    raw = G.fetch_events(cfg, FETCH_START, FETCH_END, show_tqdm=False)
    p(f"fetch_events returned {len(raw)} rows in {(datetime.datetime.now()-t0).total_seconds():.1f}s")
    p(f"columns: {list(raw.columns)}")

    # cross-check against the independently-fetched dump next door. A silent
    # disagreement here would mean one of the two studies is on a different book.
    xref = pd.read_parquet(DRIVER / "fed_calendar_raw.parquet")
    xref = xref[(xref["Date"].dt.date >= pd.Timestamp(FETCH_START).date())
                & (xref["Date"].dt.date <= pd.Timestamp(FETCH_END).date())]
    p(f"cross-check _driver_analysis/fed_calendar_raw.parquet over the same range: "
      f"{len(xref)} rows (this fetch: {len(raw)})")
    ids_a = set(raw["EventId"].dropna().astype(int))
    ids_b = set(xref["EventId"].dropna().astype(int))
    p(f"  EventId overlap {len(ids_a & ids_b)}   only-here {len(ids_a - ids_b)}   "
      f"only-there {len(ids_b - ids_a)}")

    # ------------------------------------------------- timestamp hygiene FIRST
    p("")
    p("--- timestamp hygiene ---")
    p(f"TimeLabel value counts (top 12):")
    for k, v in raw["TimeLabel"].astype(str).value_counts().head(12).items():
        p(f"    {k!r:>14} : {v}")
    odd = raw[raw["TimeLabel"].astype(str).str.lower().str.contains(
        "all day|tentative|day|tbd", regex=True, na=False)]
    p(f"'All Day'/'Tentative'-style rows: {len(odd)}")

    n_nat = int(raw["TimestampNYC"].isna().sum())
    p(f"NaT TimestampNYC: {n_nat} -> dropped")

    rows = []
    funnel: dict[str, int] = {}

    def bump(k):
        funnel[k] = funnel.get(k, 0) + 1

    for _, r in raw.iterrows():
        title = r.get("Title") or ""
        ts = r.get("TimestampNYC")
        if pd.isna(ts):
            bump("no_timestamp")
            continue
        ts = pd.Timestamp(ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("America/New_York")
        speech_ts = G._plain_dt(ts.tz_convert(tz))
        is_pc = "press conference" in title.lower()
        rows.append({
            "event_id": int(r["EventId"]) if pd.notna(r.get("EventId")) else -1,
            "title": title,
            "speaker": G.extract_speaker(title),
            "speech_ts": speech_ts,
            "date": speech_ts.date(),
            "clock": speech_ts.strftime("%H:%M"),
            "is_press_conf": is_pc,
        })

    cal = pd.DataFrame(rows)
    p(f"calendar rows with a usable timestamp: {len(cal)}")

    # duplicates: the same speaker stamped at the same minute is one speech
    dup = cal.duplicated(subset=["speaker", "speech_ts"], keep="first")
    p(f"duplicate (speaker, timestamp) rows dropped: {int(dup.sum())}")
    if dup.any():
        for _, d in cal[dup].head(8).iterrows():
            p(f"    dup: {d['speech_ts']}  {d['title']}")
    cal = cal[~dup].reset_index(drop=True)

    # midnight-stamped rows would fabricate an overnight event study
    mid = cal[cal["clock"] == "00:00"]
    p(f"midnight-stamped (00:00) rows: {len(mid)}")
    for _, d in mid.head(10).iterrows():
        p(f"    {d['speech_ts']}  {d['title']}")

    # the FULL calendar (press conferences included) is what contaminates a path
    cal_all = cal.copy()
    p(f"press conferences in the calendar: {int(cal['is_press_conf'].sum())} "
      f"(kept for overlap + quiet-day detection, EXCLUDED as events)")

    # ------------------------------------------------------------ event subset
    ev = cal[~cal["is_press_conf"]].copy()
    n_pre = len(ev)
    ev = ev[(ev["date"] >= SAMPLE_START) & (ev["date"] <= SAMPLE_END)].copy()
    p(f"events after press-conf exclusion: {n_pre}; inside the SR3 sample: {len(ev)}")

    blank = ev["speaker"].astype(str).str.strip() == ""
    p(f"events with an unparseable speaker: {int(blank.sum())} -> dropped")
    ev = ev[~blank].reset_index(drop=True)

    # --------------------------------------------------------------- PIT score
    p("")
    p("--- point-in-time stance labels ---")
    scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
    fed_scores = scores[scores["central_bank"] == "FED"]
    p(f"load_global_scores({Path(SCORES_CSV).name!r}, {SCORE_METRIC!r}) -> "
      f"{len(scores)} rows, FED {len(fed_scores)}")
    late = (fed_scores["pub_date"] > fed_scores["date"]).mean()
    p(f"FED rows published AFTER the speech they score: {late:.1%} "
      f"(median lag {np.median([(a-b).days for a, b in zip(fed_scores['pub_date'], fed_scores['date'])]):.0f}d)")

    # cross-check the FED-only CSV agrees where both carry a (speaker, date)
    fo = pd.read_csv(FED_ONLY_CSV)
    fo["date"] = pd.to_datetime(fo["date"]).dt.date
    m = fed_scores.merge(fo[["date", "speaker", SCORE_METRIC]], on=["date", "speaker"],
                         suffixes=("_glob", "_fed"))
    if len(m):
        agree = np.isclose(m[f"{SCORE_METRIC}_glob"].astype(float),
                           m[f"{SCORE_METRIC}_fed"].astype(float),
                           equal_nan=True)
        p(f"cross-check vs fed_hawk_dove_scores.csv: {len(m)} shared (speaker,date) rows, "
          f"{agree.mean():.2%} identical on {SCORE_METRIC}")
    else:
        p("cross-check vs fed_hawk_dove_scores.csv: NO shared (speaker,date) rows - investigate")

    LOOKUP_PIT = G.ScoreLookup(scores, "FED", SCORE_METRIC, point_in_time=True)
    LOOKUP_NOPIT = G.ScoreLookup(scores, "FED", SCORE_METRIC, point_in_time=False)
    p("constructor in force: G.ScoreLookup(scores, 'FED', 'trailing_5_avg', point_in_time=True)")
    p(f"  ._pit == {LOOKUP_PIT._pit}   (the NOPIT control is built only to measure the difference)")

    ev["stance_score_exante"] = [LOOKUP_PIT.get(s, d) for s, d in zip(ev["speaker"], ev["date"])]
    ev["stance_score_nopit"] = [LOOKUP_NOPIT.get(s, d) for s, d in zip(ev["speaker"], ev["date"])]

    a, b = ev["stance_score_exante"], ev["stance_score_nopit"]
    binding = int(((a.isna() & b.notna()) | (a.notna() & b.notna() & (a != b))).sum())
    p(f"PIT is BINDING on {binding} / {len(ev)} events "
      f"({binding/max(len(ev),1):.1%}): the non-PIT label differs or exists where PIT does not")
    p(f"  PIT NaN but non-PIT has a score : {int((a.isna() & b.notna()).sum())}")
    p(f"  both present, different value   : {int((a.notna() & b.notna() & (a != b)).sum())}")
    p(f"  PIT score present               : {int(a.notna().sum())} / {len(ev)}")

    ev["bucket"] = [G.absolute_bucket(x) for x in ev["stance_score_exante"]]
    ev["stance_sign"] = np.where(ev["stance_score_exante"] > 0, 1,
                                 np.where(ev["stance_score_exante"] < 0, -1, 0)).astype(int)
    ev.loc[ev["stance_score_exante"].isna(), "stance_sign"] = 0
    p(f"stance_sign: hawk(+1) {int((ev['stance_sign']==1).sum())}  "
      f"dove(-1) {int((ev['stance_sign']==-1).sum())}  "
      f"unsigned(0) {int((ev['stance_sign']==0).sum())}")
    p(f"bucket: {ev['bucket'].value_counts().sort_index().to_dict()}")

    # --------------------------------------------------------------- attributes
    ev["role"] = [FX.role_of(s, d) for s, d in zip(ev["speaker"], ev["date"])]
    ev["is_voter"] = [FX.is_voter(s, d) for s, d in zip(ev["speaker"], ev["date"])]
    meetings = FX.fomc_decision_dates()
    mset = set(meetings)
    ev["days_to_fomc"] = [FX.days_to_next_meeting(d, meetings) for d in ev["date"]]
    ev["is_fomc_day"] = [d in mset for d in ev["date"]]

    cn = pd.read_parquet(DRIVER / "cpi_nfp_raw.parquet")
    cpi_days = set(cn.loc[cn["Theme"] == "US_CPI", "Date"].dt.date)
    nfp_days = set(cn.loc[cn["Theme"] == "US_NFP", "Date"].dt.date)
    ev["is_cpi_day"] = [d in cpi_days for d in ev["date"]]
    ev["is_nfp_day"] = [d in nfp_days for d in ev["date"]]
    p("")
    p(f"is_fomc_day {int(ev['is_fomc_day'].sum())}   is_cpi_day {int(ev['is_cpi_day'].sum())}   "
      f"is_nfp_day {int(ev['is_nfp_day'].sum())}")
    p(f"role: {ev['role'].value_counts().to_dict()}")
    p(f"is_voter: {ev['is_voter'].value_counts(dropna=False).to_dict()}")

    # ---------------------------------------------------------------- overlap
    p("")
    p("--- overlap ---")
    p(f"definition: another FED_SPEAKERS calendar entry (PRESS CONFERENCES INCLUDED, and "
      f"speeches with no ex-ante score included) whose timestamp falls within")
    p(f"  (a) WINDOW-INTERSECTION reading: |dt| < {WINDOW_SPAN_MIN} min, i.e. the two "
      f"[{min(OFFSETS)}, +{max(OFFSETS)}] windows share at least one minute")
    p(f"  (b) IN-WINDOW reading: the other speech sits inside this one's "
      f"[{min(OFFSETS)}, +{max(OFFSETS)}] window")
    p("is_overlapping in the panel = (a), the strict window-intersection reading.")

    all_ts = np.array([pd.Timestamp(t).value for t in cal_all["speech_ts"]], dtype=np.int64)
    order = np.argsort(all_ts)
    all_ts = all_ts[order]
    NS = 60_000_000_000

    def nearest_other(t_ns: int) -> float:
        i = np.searchsorted(all_ts, t_ns)
        best = np.inf
        for j in (i - 2, i - 1, i, i + 1, i + 2):
            if 0 <= j < len(all_ts):
                d = abs(all_ts[j] - t_ns) / NS
                if d > 1e-9:            # itself
                    best = min(best, d)
        return best

    def n_in_window(t_ns: int) -> int:
        lo = t_ns + min(OFFSETS) * NS
        hi = t_ns + max(OFFSETS) * NS
        i0, i1 = np.searchsorted(all_ts, lo, "left"), np.searchsorted(all_ts, hi, "right")
        n = i1 - i0
        # subtract self (present exactly once in cal_all after the dedup)
        return max(n - 1, 0)

    ev_ns = np.array([pd.Timestamp(t).value for t in ev["speech_ts"]], dtype=np.int64)
    ev["min_abs_gap_min"] = [nearest_other(t) for t in ev_ns]
    ev["n_other_in_window"] = [n_in_window(t) for t in ev_ns]
    ev["is_overlapping"] = ev["min_abs_gap_min"] < WINDOW_SPAN_MIN

    p(f"(a) |dt| < {WINDOW_SPAN_MIN} min  -> overlapping {int(ev['is_overlapping'].sum())} / "
      f"{len(ev)}   clean {int((~ev['is_overlapping']).sum())}")
    p(f"(b) other speech inside [-120,+300] -> overlapping "
      f"{int((ev['n_other_in_window']>0).sum())}   clean {int((ev['n_other_in_window']==0).sum())}")
    for thr in (60, 120, 240, 300, 420):
        p(f"    |dt| < {thr:>3} min -> overlapping {int((ev['min_abs_gap_min']<thr).sum())}")

    ev = ev.sort_values(["speech_ts", "event_id"]).reset_index(drop=True)
    ev["symbol_rank3"] = [G.nth_quarterly_contract(cfg.root_for(d), d, 3) for d in ev["date"]]
    bad_root = [s for s in ev["symbol_rank3"] if not s.startswith("SR3")]
    p(f"non-SR3 root inside the sample: {len(bad_root)} (must be 0)")
    assert not bad_root, f"root splice leaked a non-SR3 contract: {set(bad_root)}"

    ev["is_placebo"] = False
    ev.to_parquet(HERE / "events.parquet", index=False)
    p("")
    p(f"WROTE events.parquet  {len(ev)} events  {ev['date'].min()} -> {ev['date'].max()}")

    # ---------------------------------------------------------------- placebo
    p("")
    p("--- placebo draw ---")
    uscal = cfg.ql_calendar
    speech_days = set(cal_all["date"])          # ANY calendar entry, press conf included
    d = SAMPLE_START
    quiet: list[datetime.date] = []
    n_bd = 0
    while d <= SAMPLE_END:
        if uscal.isBusinessDay(ql.Date(d.day, d.month, d.year)):
            n_bd += 1
            if d not in speech_days and d not in mset:
                quiet.append(d)
        d += datetime.timedelta(days=1)
    quiet = sorted(quiet)                        # SORTED LIST, never a set
    p(f"business days in sample {n_bd}; days carrying ANY Fed calendar entry "
      f"{len({x for x in speech_days if SAMPLE_START <= x <= SAMPLE_END})}; "
      f"FOMC decision days excluded too")
    p(f"quiet-day pool: {len(quiet)} days  {quiet[0]} -> {quiet[-1]}")
    by_wd: dict[int, list] = {w: sorted([x for x in quiet if x.weekday() == w]) for w in range(7)}
    p(f"quiet days by weekday: { {w: len(v) for w, v in sorted(by_wd.items()) if v} }")

    p("")
    p("MATCHED ON THREE THINGS, not two. The brief asks for weekday and clock time.")
    p("A uniform draw over the whole sample also has to be checked on CALENDAR time,")
    p("and it failed: measured on the first (uniform) draw the real hawk book had 0%")
    p("of its events in 2022 against 28% for its placebos, a 28pp year-share gap, and")
    p("the median placebo sat 525 days from its parent. 2022 was the fastest")
    p("tightening in forty years and 2024-25 was the cutting cycle, so a placebo drawn")
    p("from the wrong year carries a different drift AND a different intraday vol from")
    p("the event it is meant to null out - an error that runs in the direction that")
    p("flatters the hypothesis. So the pool is restricted to the narrowest window")
    p(f"around the parent date that still holds {PLACEBO_PER_EVENT} same-weekday quiet days.")
    rng = np.random.default_rng(SEED)
    prows = []
    n_no_pool = 0
    win_used: dict[int, int] = {}
    for _, r in ev.iterrows():                   # ev is sorted by (speech_ts, event_id)
        wd_pool = by_wd.get(r["speech_ts"].weekday(), [])
        if len(wd_pool) == 0:
            n_no_pool += 1
            continue
        pool, w_used = wd_pool, 99999
        for w in PLACEBO_WINDOWS_D:              # widen only when forced
            cand = [x for x in wd_pool if abs((x - r["date"]).days) <= w]
            if len(cand) >= PLACEBO_PER_EVENT:
                pool, w_used = cand, w
                break
        win_used[w_used] = win_used.get(w_used, 0) + 1
        k = min(PLACEBO_PER_EVENT, len(pool))
        picks = rng.choice(len(pool), size=k, replace=False)
        for j, pi in enumerate(sorted(int(x) for x in picks)):
            pd_day = pool[pi]
            pts = cfg.tz.localize(datetime.datetime(
                pd_day.year, pd_day.month, pd_day.day,
                r["speech_ts"].hour, r["speech_ts"].minute))
            prows.append({
                "event_id": int(f"9{r['event_id']:07d}{j}"),
                "parent_event_id": int(r["event_id"]),
                "title": f"PLACEBO {r['speaker']} @ {r['clock']}",
                "speaker": r["speaker"],
                "speech_ts": G._plain_dt(pts),
                "date": pd_day,
                "clock": r["clock"],
                "is_press_conf": False,
                "stance_score_exante": r["stance_score_exante"],
                "stance_score_nopit": r["stance_score_nopit"],
                "bucket": r["bucket"],
                "stance_sign": r["stance_sign"],
                "role": r["role"],
                "is_voter": r["is_voter"],
                # calendar flags come from the PLACEBO's own date, not the parent's
                "days_to_fomc": FX.days_to_next_meeting(pd_day, meetings),
                "is_fomc_day": pd_day in mset,
                "is_cpi_day": pd_day in cpi_days,
                "is_nfp_day": pd_day in nfp_days,
                "min_abs_gap_min": np.inf,
                "n_other_in_window": 0,
                "is_overlapping": False,
                "symbol_rank3": G.nth_quarterly_contract(cfg.root_for(pd_day), pd_day, 3),
                "is_placebo": True,
            })
    pl = pd.DataFrame(prows)
    p(f"events with no same-weekday quiet day: {n_no_pool}")
    p(f"placebo events drawn: {len(pl)}  ({len(pl)/max(len(ev),1):.2f}x the real book)")
    p(f"distinct placebo days used: {pl['date'].nunique()} of {len(quiet)} quiet days "
      f"(days are REUSED across placebos - unavoidable with this pool size)")
    p(f"weekday match: real {ev['speech_ts'].apply(lambda t: t.weekday()).value_counts().sort_index().to_dict()}")
    p(f"              placebo {pl['speech_ts'].apply(lambda t: t.weekday()).value_counts().sort_index().to_dict()}")
    rc = ev["clock"].value_counts(normalize=True).head(6)
    pc = pl["clock"].value_counts(normalize=True).head(6)
    p(f"clock-time match, top 6 real   : {rc.round(3).to_dict()}")
    p(f"clock-time match, top 6 placebo: {pc.round(3).to_dict()}")
    p(f"placebo stance_sign: hawk {int((pl['stance_sign']==1).sum())}  "
      f"dove {int((pl['stance_sign']==-1).sum())}  unsigned {int((pl['stance_sign']==0).sum())}")
    p(f"RNG: np.random.default_rng({SEED}); consumed once per real event in "
      f"(speech_ts, event_id) order, over a SORTED candidate list")
    p(f"proximity window actually used: "
      f"{ {('unrestricted' if k==99999 else f'+-{k}d'): v for k, v in sorted(win_used.items())} }")

    # --- did the calendar-time match actually work? measured, not asserted ---
    par = pl.merge(ev[["event_id", "date"]].rename(
        columns={"event_id": "parent_event_id", "date": "parent_date"}), on="parent_event_id")
    gap = (pd.to_datetime(par["date"]) - pd.to_datetime(par["parent_date"])).dt.days.abs()
    p(f"distance from parent: median {gap.median():.0f}d  mean {gap.mean():.0f}d  "
      f"p90 {gap.quantile(0.9):.0f}d   (uniform draw was median 525d, p90 1169d)")
    ey = pd.to_datetime(ev["date"]).dt.year
    py_ = pd.to_datetime(pl["date"]).dt.year
    p("year-share gap between real and placebo, by stance (pp):")
    for sg, lab in ((1, "hawk"), (-1, "dove"), (0, "unsigned")):
        a = ey[ev["stance_sign"] == sg].value_counts(normalize=True)
        b = py_[pl["stance_sign"] == sg].value_counts(normalize=True)
        t = pd.DataFrame({"real": a, "fake": b}).fillna(0.0)
        d_ = ((t["fake"] - t["real"]) * 100)
        p(f"    {lab:>8}: max |gap| {d_.abs().max():.1f} pp   "
          f"{ {int(k): round(float(v),1) for k, v in d_.items()} }")
    p("    (the uniform draw scored 27.7 pp for hawks and 33.2 pp for doves)")

    pl = pl.sort_values(["speech_ts", "event_id"]).reset_index(drop=True)
    pl.to_parquet(HERE / "placebo_events.parquet", index=False)
    pd.DataFrame({"date": quiet}).to_parquet(HERE / "quiet_days.parquet", index=False)
    p(f"WROTE placebo_events.parquet  {len(pl)} rows")
    p(f"WROTE quiet_days.parquet      {len(quiet)} rows")

    (HERE / "s1_report.txt").write_text("\n".join(LOG), encoding="utf-8")
    p(f"WROTE s1_report.txt")


if __name__ == "__main__":
    main()
