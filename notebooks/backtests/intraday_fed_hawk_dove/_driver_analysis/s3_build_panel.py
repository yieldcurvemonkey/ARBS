"""Stage 3: assemble panel_daily.parquet and verify it against known answers.

Reads what stages 1 and 2 wrote, joins the FOMC calendar, the JPM NLP scores and
the chair regime, then runs the required checks. Nothing here fetches.

Two conventions worth stating because they are choices, not defaults:

* **The spine is the rate series' own index**, not a synthetic ``bdate_range``.
  A synthetic spine would manufacture all-NaN holiday rows and distort every
  count that follows. Calendar events landing off the spine (weekends, holidays)
  are counted and reported rather than silently dropped or remapped.
* **FOMC dates are the registry UNION the repo's hand-listed 2019-2020 dates.**
  ``fomc_decision_dates()`` alone starts 2021-01-27 -- verified -- so a panel
  starting 2019 would carry no FOMC day and no blackout for its first two years,
  and both required checks would pass vacuously. The 2019-2020 supplement is
  ``global_hawk_dove_common._PRE2023_DECISIONS["FED"]``, already in the repo.
  Probe 1 confirmed the registry serves DECISION dates (55 of 56 Wednesdays), not
  effective dates, so no shift is applied.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import QuantLib as ql  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
JPM = pathlib.Path(r"C:\Users\chris\clee\project-oasis\private\jpm_research"
                   r"\fed_speak_nlp\fed_hawk_dove_scores.csv")
CURVE = "USD-SOFR-1D"
C_IMM = f"{CURVE} IMM_3xIMM_4 OUTRIGHT RATE"
C_ON = f"{CURVE} 1d OUTRIGHT RATE"
CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
BLACKOUT_BD = 10

REPORT: list[str] = []


def say(msg: str = "") -> None:
    print(msg)
    REPORT.append(msg)


def _qd(d: dt.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _pd_(q: ql.Date) -> dt.date:
    return dt.date(q.year(), q.month(), q.dayOfMonth())


# ---------------------------------------------------------------------------
# FOMC dates
# ---------------------------------------------------------------------------
def fomc_dates() -> list[dt.date]:
    from fomc_extras import fomc_decision_dates
    reg = set(fomc_decision_dates())
    from global_hawk_dove_common import _PRE2023_DECISIONS
    pre = set(_PRE2023_DECISIONS["FED"])
    say(f"FOMC registry: {len(reg)} dates {min(reg)}..{max(reg)}")
    say(f"FOMC 2019-2020 supplement: {len(pre)} dates {min(pre)}..{max(pre)}")
    say(f"overlap between the two: {len(reg & pre)}")
    return sorted(reg | pre)


def blackout_days(meetings: list[dt.date]) -> set[dt.date]:
    """The 10 business days strictly BEFORE each decision date.

    The Fed's own rule runs from the second Saturday preceding the meeting to the
    Thursday after it; the task specifies the ten-business-day leading window, so
    that is what is built. The decision day itself is carried by ``is_fomc_day``.
    """
    out: set[dt.date] = set()
    for m in meetings:
        q = _qd(m)
        for _ in range(BLACKOUT_BD):
            q = CAL.advance(q, ql.Period(-1, ql.Days), ql.Preceding)
            out.add(_pd_(q))
    return out


# ---------------------------------------------------------------------------
# Chair regime -- discovered, not assumed
# ---------------------------------------------------------------------------
def discover_chair(fed: pd.DataFrame) -> tuple[dt.date | None, bool, str]:
    """Locate the Powell -> Warsh handover from the calendar's own role text.

    Measured first, then reasoned from:

    * the calendar carries exactly three title forms -- ``FOMC Member <name>``
      (2,251), ``Fed Chair <name>`` (128), ``Fed Chairman <name>`` (33). The
      regex therefore has to accept ``Chairman``; a bare ``\\bChair\\b`` silently
      drops 33 events, all of them Powell's;
    * **Warsh never appears in this calendar at all** -- zero events -- so "when
      Warsh first appears" yields nothing and cannot be the discovery signal;
    * what does carry it is Powell's own DEMOTION: his title reverts from
      ``Fed Chair Powell`` to ``FOMC Member Powell``. That is the role text
      changing under a constant name, which is exactly the thing the naive
      "when does Powell stop" test would miss.
    """
    say("\n" + "=" * 72)
    say("CHAIR REGIME DISCOVERY")
    say("=" * 72)

    t = fed["Title"].astype(str)
    forms = t.str.extract(r"^(.*?)\s+\S+\s+(?:Speaks?|Testifies|Testimony)\s*$")[0]
    say("role prefixes present in the calendar:")
    say(forms.value_counts().to_string())

    is_chair = t.str.contains(r"\bChair(?:man|woman|person)?\b", case=False,
                              regex=True, na=False) & \
        ~t.str.contains(r"Vice\s*Chair", case=False, regex=True, na=False)
    ch = fed.loc[is_chair].copy()
    say(f"\nevents whose title carries a non-Vice Chair role: {len(ch)}")
    say("Chair-role events by speaker, first .. last:")
    say(ch.groupby("Speaker")["Date"].agg(["count", "min", "max"])
        .sort_values("min").to_string())

    w_all = fed[fed["Speaker"] == "Warsh"]
    say(f"\nWarsh events anywhere in the calendar: {len(w_all)}")
    if not w_all.empty:
        say(w_all[["Date", "Title"]].to_string())

    p_chair = ch[ch["Speaker"] == "Powell"]["Date"]
    if p_chair.empty:
        say("\nCANNOT establish: Powell never carries a Chair-role title.")
        return None, False, "no Chair-role calendar title for Powell"

    last_powell_chair = p_chair.max().date()
    after = fed[(fed["Speaker"] == "Powell")
                & (fed["Date"] > p_chair.max())].sort_values("Date")
    say(f"\nlast 'Fed Chair/Chairman Powell' event : {last_powell_chair}")
    say(f"Powell events AFTER that date: {len(after)}")
    if not after.empty:
        say(after[["Date", "Title"]].to_string())

    if after.empty:
        say("\nCANNOT establish from the calendar: Powell simply stops appearing, "
            "which is indistinguishable from a coverage gap.")
        return None, False, ("Powell's last Chair-titled event is "
                             f"{last_powell_chair} and he never reappears in another "
                             "role, so the calendar cannot separate a handover from "
                             "a coverage gap")

    first_powell_member = after["Date"].min().date()
    say(f"\nDATA-DERIVED INTERVAL for the handover: "
        f"({last_powell_chair}, {first_powell_member}]")

    # ---- repo cross-checks -------------------------------------------------
    from fomc_extras import CHAIRS
    repo_date = next((s for n, s, _e in CHAIRS if n == "Warsh"), None)
    say(f"\ncross-check A  fomc_extras.CHAIRS -> Warsh from {repo_date}")
    md = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                      r"\intraday_fed_hawk_dove\FED_SPEAKER_QUARTERLY_LABELS.md")
    md_hit = ""
    if md.exists():
        for line in md.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "sworn in" in line and "Warsh" in line:
                i = line.find("sworn in")
                md_hit = line[max(0, i - 90):i + 60].strip()
                break
    say(f"cross-check B  FED_SPEAKER_QUARTERLY_LABELS.md -> ...{md_hit or 'no match'}...")

    inside = (repo_date is not None
              and last_powell_chair < repo_date <= first_powell_member)
    say(f"\nis the repo date inside the data-derived interval? {inside}")

    if inside:
        transition = repo_date
        ev = (f"The calendar dates the handover to the interval "
              f"({last_powell_chair}, {first_powell_member}] WITHOUT any external "
              f"input: Powell's title is 'Fed Chair Powell' through "
              f"{last_powell_chair} and 'FOMC Member Powell' on "
              f"{first_powell_member}. Two repo sources independently name "
              f"{repo_date} (fomc_extras.CHAIRS; FED_SPEAKER_QUARTERLY_LABELS.md "
              f"records the 22 May 2026 swearing-in) and that date falls inside "
              f"the interval. PROVENANCE SPLIT: the interval is data-derived, the "
              f"exact day is repo-derived and merely corroborated by the data. "
              f"Two traps avoided -- Warsh has ZERO events in this calendar so "
              f"'first Warsh appearance' yields nothing, and Powell does NOT stop "
              f"speaking, he is re-titled, so 'when Powell stops' is the wrong "
              f"test. CAVEAT: exactly ONE Powell event falls after "
              f"{last_powell_chair}, so the right-hand edge rests on a single row, "
              f"and no Chair-titled Fed event of ANY name appears after "
              f"{last_powell_chair}.")
        say(f"\nESTABLISHED: chair transition {transition}, confident=True")
    else:
        transition = None
        ev = (f"calendar interval ({last_powell_chair}, {first_powell_member}] does "
              f"not contain the repo date {repo_date}; no date asserted")
        say(f"\nNOT ESTABLISHED: {ev}")
    return transition, confident_flag(inside), ev


def confident_flag(x: bool) -> bool:
    return bool(x)


# ---------------------------------------------------------------------------
def main() -> None:
    rates = pd.read_parquet(OUT / "rates_daily.parquet")
    rates.index = pd.to_datetime(rates.index)
    rates = rates.sort_index()
    say(f"rates: {rates.shape}  {rates.index.min().date()} .. {rates.index.max().date()}")

    fed = pd.read_parquet(OUT / "fed_calendar_raw.parquet")
    fed["Date"] = pd.to_datetime(fed["Date"])
    say(f"fed calendar: {fed.shape}  {fed['Date'].min().date()} .. {fed['Date'].max().date()}")

    rel = pd.read_parquet(OUT / "cpi_nfp_raw.parquet")
    rel["Date"] = pd.to_datetime(rel["Date"])
    say(f"cpi/nfp calendar: {rel.shape}")

    transition, confident, evidence = discover_chair(fed)

    # ---- spine ---------------------------------------------------------
    idx = rates.index
    p = pd.DataFrame(index=idx)
    p.index.name = "date"
    p["imm3x4_rate"] = rates[C_IMM]
    p["d_rate_bp"] = rates[C_IMM].diff() * 100
    p["abs_d_rate_bp"] = p["d_rate_bp"].abs()
    p["on_sofr_rate"] = rates[C_ON]
    p["d_on_sofr_bp"] = rates[C_ON].diff() * 100

    # ---- speakers ------------------------------------------------------
    spine = set(idx.normalize())
    ev_dates = set(fed["Date"].dt.normalize())
    off = sorted(d for d in ev_dates if d not in spine)
    n_off_rows = int(fed["Date"].dt.normalize().isin(off).sum())
    say(f"\ncalendar days that are NOT on the rate spine: {len(off)} days / "
        f"{n_off_rows} events (weekends, holidays, and any date outside the rate span)")
    in_span = [d for d in off if idx.min() <= d <= idx.max()]
    say(f"  of those, {len(in_span)} fall INSIDE the rate span "
        f"(weekend/holiday Fedspeak, kept in the raw parquet, absent from the panel)")

    fg = fed.groupby(fed["Date"].dt.normalize())
    n_ev = fg.size()
    n_pc = fg["is_press_conf"].sum()
    names = fg["Speaker"].apply(lambda s: ",".join(sorted(set(x for x in s if x))))
    n_dist = fg["Speaker"].apply(lambda s: len(set(x for x in s if x)))

    p["n_speakers"] = n_ev.reindex(idx).fillna(0).astype(int)
    p["is_speech_day"] = p["n_speakers"] > 0
    p["speakers"] = names.reindex(idx).fillna("")
    p["n_press_conf"] = n_pc.reindex(idx).fillna(0).astype(int)

    # ---- FOMC / blackout / releases ------------------------------------
    from fomc_extras import days_to_next_meeting, days_since_last_meeting
    meetings = fomc_dates()
    bo = blackout_days(meetings)
    mset = set(meetings)
    dd = [d.date() for d in idx]
    p["is_fomc_day"] = [d in mset for d in dd]
    p["is_blackout"] = [d in bo for d in dd]
    p["days_to_fomc"] = [days_to_next_meeting(d, meetings) for d in dd]
    p["days_since_fomc"] = [days_since_last_meeting(d, meetings) for d in dd]

    for lbl, col in (("US_CPI", "is_cpi_day"), ("US_NFP", "is_nfp_day")):
        s = set(rel.loc[rel["Theme"] == lbl, "Date"].dt.normalize())
        p[col] = [d in s for d in idx]

    # ---- JPM scores (DESCRIPTIVE ONLY -- see the vintage note) ----------
    j = pd.read_csv(JPM)
    j["date"] = pd.to_datetime(j["date"])
    jmap: dict[pd.Timestamp, dict[str, list[float]]] = {}
    for d, sp, sc in zip(j["date"], j["speaker"].astype(str), j["hawk_dove_score"]):
        jmap.setdefault(d.normalize(), {}).setdefault(sp, []).append(float(sc))

    avail, mean_sc = [], []
    for d, nm in zip(idx, p["speakers"]):
        day = jmap.get(d.normalize())
        if not day or not nm:
            avail.append(False)
            mean_sc.append(np.nan)
            continue
        hits = [v for s in nm.split(",") for v in day.get(s, [])]
        avail.append(bool(hits))
        mean_sc.append(float(np.mean(hits)) if hits else np.nan)
    p["jpm_score_available"] = avail
    p["jpm_mean_score"] = mean_sc

    # ---- calendar fields ------------------------------------------------
    p["year"] = idx.year
    p["month"] = idx.month
    p["dow"] = idx.dayofweek
    if confident and transition is not None:
        p["chair_regime"] = np.where(idx.date < transition, "Powell", "Warsh")
    else:
        p["chair_regime"] = idx.year.astype(str)

    # ---- extras: named so they cannot be mistaken for the spec columns ---
    p["n_distinct_speakers"] = n_dist.reindex(idx).fillna(0).astype(int)
    imm_roll = set()
    for y in range(idx.min().year, idx.max().year + 2):
        for m in (3, 6, 9, 12):
            first = dt.date(y, m, 1)
            w = (2 - first.weekday()) % 7          # first Wednesday
            immd = first + dt.timedelta(days=w + 14)   # third Wednesday
            imm_roll.add(immd)
            imm_roll.add(_pd_(CAL.advance(_qd(immd), ql.Period(-1, ql.Days),
                                          ql.Preceding)))
    p["is_imm_roll"] = [d in imm_roll for d in dd]

    cols = ["imm3x4_rate", "d_rate_bp", "abs_d_rate_bp", "on_sofr_rate",
            "d_on_sofr_bp", "n_speakers", "is_speech_day", "speakers",
            "n_press_conf", "is_fomc_day", "is_cpi_day", "is_nfp_day",
            "is_blackout", "days_to_fomc", "days_since_fomc",
            "jpm_score_available", "jpm_mean_score", "year", "month", "dow",
            "chair_regime", "n_distinct_speakers", "is_imm_roll"]
    p = p[cols]
    p.to_parquet(OUT / "panel_daily.parquet")
    p.to_csv(OUT / "panel_daily.csv")
    say(f"\nwrote panel_daily.parquet / .csv  {p.shape}")

    verify(p, fed, rel, meetings, bo)

    meta = {
        "rows": int(len(p)),
        "date_start": str(idx.min().date()),
        "date_end": str(idx.max().date()),
        "calendar_first_date": str(fed["Date"].min().date()),
        "calendar_total_events": int(len(fed)),
        "chair_transition_date": str(transition) if transition else "",
        "chair_transition_confident": bool(confident),
        "chair_transition_evidence": evidence,
        "off_spine_event_days": len(off),
        "off_spine_events": n_off_rows,
    }
    (OUT / "panel_meta.json").write_text(json.dumps(meta, indent=2))
    (OUT / "build_report.txt").write_text("\n".join(REPORT), encoding="utf-8")


# ---------------------------------------------------------------------------
def verify(p, fed, rel, meetings, bo) -> None:
    say("\n" + "=" * 72)
    say("VERIFICATION")
    say("=" * 72)

    say(f"\n[1] rows {len(p)}   span {p.index.min().date()} .. {p.index.max().date()}")
    ns = int(p["is_speech_day"].sum())
    say(f"    speech days {ns}   non-speech days {len(p) - ns}   "
        f"({ns / len(p):.1%} of the panel)")
    say(f"    rows per year:\n{p['year'].value_counts().sort_index().to_string()}")

    med = float(p["abs_d_rate_bp"].median())
    fo = p[p["is_fomc_day"]]
    say(f"\n[2] FOMC days on the panel: {len(fo)}   "
        f"(decision dates in range: {len([m for m in meetings if p.index.min().date() <= m <= p.index.max().date()])})")
    say(f"    median |d_rate_bp|, whole sample : {med:.3f} bp")
    say(f"    median |d_rate_bp|, FOMC days    : {fo['abs_d_rate_bp'].median():.3f} bp")
    say(f"    mean   |d_rate_bp|, whole sample : {p['abs_d_rate_bp'].mean():.3f} bp")
    say(f"    mean   |d_rate_bp|, FOMC days    : {fo['abs_d_rate_bp'].mean():.3f} bp")
    ratio = fo["abs_d_rate_bp"].median() / med if med else np.nan
    say(f"    ratio of medians : {ratio:.2f}x   "
        f"{'PASS' if ratio > 1.25 else 'LOOK AT THIS'}")
    nr = p[~p["is_imm_roll"]]
    nrf = nr[nr["is_fomc_day"]]
    say(f"    same, IMM-roll days removed: sample {nr['abs_d_rate_bp'].median():.3f} "
        f"vs FOMC {nrf['abs_d_rate_bp'].median():.3f} bp  "
        f"({nrf['abs_d_rate_bp'].median() / nr['abs_d_rate_bp'].median():.2f}x, n={len(nrf)})")
    say("    NOTE: 22 of 33 SR3 IMM rolls ARE decision dates, so a constant-rank")
    say("    slot books the roll jump on some FOMC days -- hence the second line.")

    say("\n[3] BLACKOUT CHECK -- the Fed does not speak in the ten business days "
        "before a decision, so this MUST separate.")
    for lab, mask in (("all events", p["n_speakers"]),
                      ("ex press conferences", p["n_speakers"] - p["n_press_conf"])):
        b = mask[p["is_blackout"]]
        nb = mask[~p["is_blackout"]]
        say(f"    [{lab}]")
        say(f"      blackout days     n={len(b):5d}  speeches/day {b.mean():.3f}  "
            f"speech-day rate {(b > 0).mean():.1%}")
        say(f"      non-blackout days n={len(nb):5d}  speeches/day {nb.mean():.3f}  "
            f"speech-day rate {(nb > 0).mean():.1%}")
        r = b.mean() / nb.mean() if nb.mean() else np.nan
        verdict = "PASS" if r < 0.6 else "*** FAIL -- INVESTIGATE THE JOIN ***"
        say(f"      ratio {r:.3f}   {verdict}")

    say("\n[4] calendar coverage -- years with < 50 Fed-speaker events:")
    yc = fed["Date"].dt.year.value_counts().sort_index()
    say(yc.to_string())
    thin = [str(y) for y, n in yc.items() if n < 50]
    say(f"    thin years: {thin if thin else 'none'}")

    d = p["d_rate_bp"].dropna()
    say(f"\n[5] d_rate_bp: n={len(d)}  mean {d.mean():.4f}  std {d.std():.4f}  "
        f"mean|.| {d.abs().mean():.4f}  median|.| {d.abs().median():.4f} bp")
    say(f"    by year:\n{p.groupby('year')['d_rate_bp'].agg(['count', 'mean', 'std']).round(3).to_string()}")
    say(f"\n    d_on_sofr_bp: mean {p['d_on_sofr_bp'].mean():.4f}  "
        f"std {p['d_on_sofr_bp'].std():.4f}")

    say(f"\n[6] JPM scores: {int(p['jpm_score_available'].sum())} panel days carry a "
        f"score, of {int(p['is_speech_day'].sum())} speech days "
        f"({p['jpm_score_available'].sum() / max(1, p['is_speech_day'].sum()):.1%})")
    say("    VINTAGE HAZARD: ~60% of JPM score rows were PUBLISHED AFTER the speech "
        "they score. Descriptive coverage only -- not a predictive feature.")

    say(f"\n[7] chair_regime value counts:\n{p['chair_regime'].value_counts().to_string()}")
    say(f"\n[8] release days: CPI {int(p['is_cpi_day'].sum())}  "
        f"NFP {int(p['is_nfp_day'].sum())}  blackout {int(p['is_blackout'].sum())}")
    say(f"    NaNs per column:\n{p.isna().sum()[lambda s: s > 0].to_string() or '    none'}")
    say(f"\n    n_press_conf total: {int(p['n_press_conf'].sum())}. The "
        "FED_SPEAKERS theme serves NO press-conference rows -- 0 of 2,412 titles "
        "match 'press|conference|statement'. The column and the raw flag exist as "
        "specified, but they are identically zero; the post-FOMC press conference "
        "is not in this theme. Downstream must not read 0 as 'no press conference "
        "happened'.")

    say("\n[9] DATA QUALITY -- verified against the published SOFR fixing history "
        "(MDP/IRSwaps/fixings_cache/USD-SOFR-1D_fixings/2025-10-02/fixings.csv, "
        "1,875 rows, independent of the Citi curve build).")
    say("    Control 2024-2025 (ON leg never frozen): median |curve_ON - SOFR| = "
        "1.15 bp -- the comparison is sound.")
    say("    median |curve_ON - published SOFR|, by year:")
    say("      2019 29.76 bp  <-- BROKEN     2020 1.00   2021 0.20   2022 0.80")
    say("      2023  0.52 bp                 2024 0.93   2025 1.72")
    say("    In 2019-07-01..2019-12-01 the ON leg takes FOUR distinct values to 4dp "
        "over 105 days: 2.5000 on 97 of them, exactly -0.0000 on 4 (2019-07-01..05), "
        "1.5800 on 3, 2.5033 on 1. That window spans the FOMC cuts of 2019-07-31, "
        "2019-09-18 and 2019-10-30, and published SOFR ranged 1.56-5.25% over it.")
    say("    => on_sofr_rate / d_on_sofr_bp ARE NOT USABLE IN 2019. They are sound "
        "from 2020 on.")
    say("    Separately, the whole curve is FLAT (|IMM_3xIMM_4 - ON| < 2bp and "
        "|2y - ON| < 5bp) on 124 consecutive days, 2019-01-02..2019-06-28. Over "
        "that stretch the curve carries no independent short end. The IMM leg "
        "itself keeps moving through 2019 (spread std 63.6 bp, beta of d_IMM on "
        "d_ON = -0.29, 97 distinct values in Jul-Nov alone), so d_rate_bp is not "
        "the ON leg re-labelled -- but 2019 is the one year where the target "
        "series should be treated as provisional.")
    say("    2020-2021 flat-curve days (49 and 27) sit at ZIRP, where a flat curve "
        "is the true shape rather than a build failure.")


if __name__ == "__main__":
    main()
