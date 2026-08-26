"""STAGE 4 - verify the panel. Every check the brief asks for, plus the ones
that would catch this build being wrong in the direction that flatters it.
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

import global_hawk_dove_common as G
import s3_panel as S3

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
BARS_PKL = sys.argv[1] if len(sys.argv) > 1 else "bars_event_study.pkl"
LOG: list[str] = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ===========================================================================
def known_answer_test():
    """The rule tested against an input whose answer is known by hand."""
    p("=" * 78)
    p("0. KNOWN-ANSWER TEST of the bar-indexing rule")
    p("=" * 78)
    base = pd.Timestamp("2025-06-11 10:00", tz="America/New_York")
    # labels at +0, +1, +2, +5 (a 3-minute hole), +40 (far past the cap)
    labels = [base + pd.Timedelta(minutes=m) for m in (0, 1, 2, 5, 40)]
    closes = np.array([95.10, 95.11, 95.12, 95.13, 95.99])
    ix = np.array([int(x.value) for x in labels], dtype=np.int64)

    cases = [
        # (query minute offset from base, expected price, expected staleness, why)
        (0,  np.nan, np.nan, "no bar labelled strictly before 10:00"),
        (1,  95.10,  0.0,    "bar 10:00 covers [10:00,10:01) -> its close is the 10:01 price"),
        (2,  95.11,  0.0,    "bar 10:01"),
        (3,  95.12,  0.0,    "bar 10:02; bars 10:03/10:04 are missing"),
        (5,  95.12,  2.0,    "still bar 10:02 - 2 min stale, inside the cap"),
        (6,  95.13,  0.0,    "bar 10:05"),
        (21, 95.13,  15.0,   "bar 10:05, exactly at the 15-min cap -> kept"),
        (22, np.nan, 16.0,   "bar 10:05 is 16 min stale -> beyond the cap -> NaN"),
        (41, 95.99,  0.0,    "bar 10:40"),
    ]
    ok = True
    for off, want_px, want_st, why in cases:
        t = int((base + pd.Timedelta(minutes=off)).value)
        got_px, got_st, _ = S3.price_at(ix, closes, t)
        px_ok = (np.isnan(got_px) and np.isnan(want_px)) or np.isclose(got_px, want_px)
        st_ok = (np.isnan(got_st) and np.isnan(want_st)) or np.isclose(got_st, want_st)
        flag = "OK " if (px_ok and st_ok) else "FAIL"
        ok &= px_ok and st_ok
        p(f"  {flag}  T=10:{off:02d}  price={got_px!r:>8} (want {want_px!r:>8})  "
          f"stale={got_st!r:>5} (want {want_st!r:>5})   {why}")

    # mutation: break the rule the way it would be broken, confirm the test fails
    def leaky(ix_, cl_, t_ns):
        i = int(np.searchsorted(ix_, t_ns, side="right")) - 1   # label <= T  (LEAKS)
        return (np.nan, np.nan, 0) if i < 0 else (float(cl_[i]), 0.0, int(ix_[i]))

    t = int(base.value)
    leak_px, _, _ = leaky(ix, closes, t)
    good_px, _, _ = S3.price_at(ix, closes, t)
    p(f"  MUTATION: the 'side=right' variant (close of the bar labelled T) returns "
      f"{leak_px} at T=10:00 where the causal rule returns {good_px} - "
      f"the leak is visible, so the test is not vacuous")
    p(f"  VERDICT: {'all cases pass' if ok else 'FAILURES ABOVE'}")
    return ok


# ===========================================================================
def worked_example(panel: pd.DataFrame):
    p("")
    p("=" * 78)
    p("1. BAR-INDEXING RULE + a worked example")
    p("=" * 78)
    p(S3.BAR_RULE)
    p("")
    p("Why not the close of the bar labelled T: Barchart bars are START-stamped, so")
    p("the bar labelled 10:00 covers [10:00, 10:01) and its close is a print from")
    p("AFTER 10:00. Using it for 'the price at 10:00' puts the speech's own reaction")
    p("into the pre-event baseline and manufactures a step at offset 0.")

    G.load_bar_cache(HERE / BARS_PKL)
    ev = pd.read_parquet(HERE / "events.parquet")
    # a liquid, cleanly-timed, non-overlapping speech on a round minute
    cand = ev[(~ev["is_overlapping"]) & (ev["clock"].str.endswith(":00"))
              & (ev["date"] >= datetime.date(2024, 1, 1))
              & (ev["stance_sign"] != 0)]
    row = cand.iloc[len(cand) // 2]
    ts = pd.Timestamp(row["speech_ts"])
    sym = G.nth_quarterly_contract("SR3", row["date"], 3)
    bars = G._BAR_CACHE.get((sym, row["date"]))
    p("")
    p(f"EVENT  {row['title']}  ({row['speaker']}, {row['role']})")
    p(f"       speech_ts {ts}   symbol {sym} (rank 3)   stance_score_exante "
      f"{row['stance_score_exante']}   stance_sign {row['stance_sign']:+d}")
    p("")
    p(f"raw minute bars around the speech (index = bar LABEL = bar START):")
    w = bars.loc[ts - pd.Timedelta(minutes=4): ts + pd.Timedelta(minutes=4)]
    p(w.to_string())

    ix = bars.index.view("int64").astype(np.int64)
    cl = bars["Close"].to_numpy(dtype=float)
    p("")
    p("rule applied at offsets -1, 0, +1 (and the panel's -5 / 0 / +5):")
    for off in (-5, -1, 0, 1, 5):
        t = int((ts + pd.Timedelta(minutes=off)).value)
        px, st, lb = S3.price_at(ix, cl, t)
        lbl = pd.Timestamp(lb, tz="UTC").tz_convert(ts.tz) if lb else None
        naive = bars["Close"].get(ts + pd.Timedelta(minutes=off), np.nan)
        opn = bars["Open"].get(ts + pd.Timedelta(minutes=off), np.nan)
        p(f"  offset {off:+3d}  T={(ts+pd.Timedelta(minutes=off)).strftime('%H:%M')}  "
          f"-> bar labelled {lbl.strftime('%H:%M') if lbl is not None else '-'} , "
          f"close {px}  (stale {st:g} min)")
        p(f"              the NAIVE close-of-bar-T would be {naive} "
          f"(a print from up to a minute AFTER T); the bar's OPEN is {opn}")
    p("")
    p("The panel takes the close of the bar labelled T-1 (equivalently: the last")
    p("print that had already happened at T). The rule is identical at every offset,")
    p("so it cannot create a step at 0 - it can only understate the reaction.")

    # ---- how much would the hazard actually have cost? -------------------
    p("")
    p("HOW BIG IS THE LEAK? The same panel rebuilt with the naive rule (close of the")
    p("bar labelled T), differenced against the causal one, at rank 3:")
    r3 = panel[panel["contract_rank"] == 3]
    keys = r3[["event_id", "symbol", "speech_ts"]].drop_duplicates()
    keys = keys.head(300)
    rows = []
    for _, k in keys.iterrows():
        ts = pd.Timestamp(k["speech_ts"])
        b = G._BAR_CACHE.get((k["symbol"], ts.date()))
        if b is None or len(b) == 0:
            continue
        ix = b.index.view("int64").astype(np.int64)
        cl = b["Close"].to_numpy(dtype=float)
        for off in (-60, -5, 0, 5, 15, 60):
            t = int((ts + pd.Timedelta(minutes=off)).value)
            good, _, _ = S3.price_at(ix, cl, t)
            i = int(np.searchsorted(ix, t, side="right")) - 1     # <= T : LEAKS
            leak = float(cl[i]) if i >= 0 else np.nan
            if good == good and leak == leak:
                rows.append({"offset": off, "diff_bp": (good - leak) * -100.0,
                             "same": np.isclose(good, leak)})
    dd = pd.DataFrame(rows)
    if len(dd):
        g = dd.groupby("offset").agg(n=("same", "size"),
                                     pct_differs=("same", lambda s: 100 * (~s).mean()),
                                     mean_leak_bp=("diff_bp", "mean"),
                                     max_abs_bp=("diff_bp", lambda s: s.abs().max()))
        p(g.round(3).to_string())
        p("diff_bp is the RATE-space bp the naive rule would have imported from after T.")
        p("It is largest exactly at offset 0 - which is where a fake step would appear.")


# ===========================================================================
def sign_check(panel: pd.DataFrame):
    p("")
    p("=" * 78)
    p("2. SIGN CHECK")
    p("=" * 78)
    p("convention: rate = 100 - price; rate_bp = (100-price)*100.")
    p("hawkish surprise -> expected policy UP -> implied RATE up -> PRICE down ->")
    p("d_rate_bp_from_baseline POSITIVE. signed_d_bp = d_rate_bp * stance_sign, so a")
    p("hawk who moves rates up and a dove who moves rates down are BOTH positive.")
    p("")
    d = panel[panel["price"].notna()]
    id_ok = np.allclose(d["rate_bp"], (100.0 - d["price"]) * 100.0)
    p(f"identity rate_bp == (100-price)*100 holds on all {len(d):,} priced rows: {id_ok}")

    b = panel[panel["d_rate_bp_from_baseline"].notna() & panel["baseline_price"].notna()]
    dp = b["price"] - b["baseline_price"]
    dr = b["d_rate_bp_from_baseline"]
    nz = (dp.abs() > 1e-12)
    opp = bool((np.sign(dr[nz]) == -np.sign(dp[nz])).all())
    p(f"sign(d_rate) == -sign(d_price) on all {int(nz.sum()):,} rows that moved: {opp}")
    ss = panel[panel["signed_d_bp"].notna()]
    sok = np.allclose(ss["signed_d_bp"], ss["d_rate_bp_from_baseline"] * ss["stance_sign"])
    p(f"signed_d_bp == d_rate_bp_from_baseline * stance_sign: {sok}")

    p("")
    r3 = panel[(panel["contract_rank"] == 3) & (panel["offset_min"] == 240)
               & panel["signed_d_bp"].notna()]
    big = r3.reindex(r3["signed_d_bp"].abs().sort_values(ascending=False).index).iloc[0]
    p(f"LARGEST |signed_d_bp| at +240 (rank 3): {big['signed_d_bp']:+.2f} bp")
    _dump_path(panel, big)

    for lab, sub in (("largest HAWK move at +240", r3[r3["stance_sign"] == 1]),
                     ("largest DOVE move at +240", r3[r3["stance_sign"] == -1])):
        s = sub.reindex(sub["signed_d_bp"].abs().sort_values(ascending=False).index)
        if len(s):
            p("")
            p(f"--- {lab} ---")
            _dump_path(panel, s.iloc[0], short=True)

    p("")
    p("WHAT THE TWO EXTREMES ACTUALLY ARE - and the limitation they expose.")
    p("Both largest moves are macro events, not the speech:")
    p("  * the hawk, 2025-04-09, is the 90-day tariff-pause announcement (~13:18 ET).")
    p("    The path is flat through +120 and then moves 29bp between +120 and +180 -")
    p("    two hours after an 11:00 speech. NO calendar column in this panel flags it.")
    p("  * the dove, 2023-11-14, is the CPI downside surprise at 08:30 ET, five")
    p("    offsets before a 05:30 speech's +240. is_cpi_day DOES flag that one.")
    p("The +240/+300 window is five hours wide and the front end is not quiet for")
    p("five hours. This panel flags CPI, NFP and FOMC decision days and NOTHING ELSE,")
    p("so tariff headlines, Treasury refundings, geopolitics and ECB/BoE spillover sit")
    p("inside these windows unlabelled. That is a property of the question, not a bug")
    p("in the build - but a far-offset result must be read as 'what happened in the")
    p("five hours after a speech', not 'what the speech did'. The placebo band is the")
    p("only defence, and it is time-of-day, weekday and calendar-proximity matched")
    p("precisely so that ambient five-hour drift is inside the null rather than the")
    p("signal.")


def _dump_path(panel: pd.DataFrame, row, short: bool = False):
    stance = "HAWK" if row["stance_sign"] == 1 else "DOVE"
    p(f"  {row['title']}   {row['speech_ts']}   {row['symbol']}")
    p(f"  stance_score_exante {row['stance_score_exante']:+.1f} -> {stance} "
      f"(stance_sign {row['stance_sign']:+d}, bucket {row['bucket']:+d})   "
      f"is_overlapping {row['is_overlapping']}   days_to_fomc {row['days_to_fomc']}")
    pth = panel[(panel["event_id"] == row["event_id"])
                & (panel["contract_rank"] == row["contract_rank"])].sort_values("offset_min")
    show = pth if not short else pth[pth["offset_min"].isin([-60, -15, 0, 15, 60, 240])]
    p(f"  {'offset':>7} {'price':>10} {'rate_bp':>10} {'d_rate_bp':>10} {'signed':>9} {'stale':>6}")
    for _, q in show.iterrows():
        p(f"  {int(q['offset_min']):>7} {q['price']:>10.4f} {q['rate_bp']:>10.2f} "
          f"{q['d_rate_bp_from_baseline']:>10.2f} {q['signed_d_bp']:>9.2f} "
          f"{q['stale_min']:>6.1f}")
    b = pth[pth["offset_min"] == -60].iloc[0]
    e = pth[pth["offset_min"] == 240].iloc[0]
    dirn = ("PRICE FELL -> RATE ROSE" if e["price"] < b["price"]
            else "PRICE ROSE -> RATE FELL")
    p(f"  -60 -> +240: price {b['price']:.4f} -> {e['price']:.4f}  ({dirn}); "
      f"d_rate {e['d_rate_bp_from_baseline']:+.2f} bp; "
      f"{stance} x that = {e['signed_d_bp']:+.2f} bp")
    exp = "POSITIVE" if ((row["stance_sign"] == 1) == (e["price"] < b["price"])) else "NEGATIVE"
    p(f"  a {stance} whose rate went "
      f"{'UP' if e['price'] < b['price'] else 'DOWN'} must give a {exp} signed_d_bp -> "
      f"{'CONSISTENT' if (e['signed_d_bp'] > 0) == (exp == 'POSITIVE') else 'INCONSISTENT'}")


# ===========================================================================
def coverage(panel: pd.DataFrame, label: str):
    p("")
    p("=" * 78)
    p(f"3. COVERAGE - {label}")
    p("=" * 78)
    piv = (panel.assign(ok=panel["price"].notna())
           .pivot_table(index="offset_min", columns="contract_rank", values="ok",
                        aggfunc="mean"))
    p("% of (event, rank) with a non-NaN price, by offset:")
    p((piv * 100).round(1).to_string())
    r3 = panel[panel["contract_rank"] == 3]
    c3 = r3.groupby("offset_min")["price"].apply(lambda s: s.notna().mean())
    worst = c3.min()
    p("")
    p(f"rank 3: best {c3.max():.1%} at offset {int(c3.idxmax())}, "
      f"worst {worst:.1%} at offset {int(c3.idxmin())}")
    drops = [(int(a), int(b), c3[a], c3[b]) for a, b in zip(c3.index[:-1], c3.index[1:])
             if c3[b] < c3[a] - 0.03]
    if drops:
        p("coverage CLIFFS (a >3pp drop between adjacent offsets):")
        for a, b, x, y in drops:
            p(f"    {a:+d} -> {b:+d} : {x:.1%} -> {y:.1%}")
    else:
        p("no >3pp drop between adjacent offsets - the path does not taper into nothing")
    # what causes the loss at the far end
    far = r3[r3["offset_min"] == 300]
    lost = far[far["price"].isna()]
    if len(lost):
        p(f"at +300, {len(lost)} of {len(far)} event-rows have no price. By speech hour:")
        h = lost["speech_ts"].apply(lambda t: pd.Timestamp(t).hour).value_counts().sort_index()
        p(f"    {h.to_dict()}")
        p(f"    on a Friday: {int(lost['weekday'].eq(4).sum())}   "
          f"weekend speech: {int(lost['weekday'].ge(5).sum())}")
    nb = panel[panel["offset_min"] == 0].groupby("event_id")["price"].apply(
        lambda s: s.isna().all())
    p(f"events with NO price at offset 0 at ANY rank: {int(nb.sum())} / {len(nb)}")

    # WHERE the loss lives. A weekday _day_bars frame covers 00:00-23:43 ET with
    # only the 17:00-18:00 CME halt empty; a Friday frame stops at 16:59. Overnight
    # hours are thinly quoted, so the 15-min staleness cap bites there too.
    p("")
    p("coverage by SPEECH HOUR (rank 3, share of the 22 offsets priced) - this is")
    p("where the loss actually lives, and it is a session-structure fact, not a taper:")
    r3 = r3.copy()
    r3["hour"] = r3["speech_ts"].apply(lambda t: pd.Timestamp(t).hour)
    byh = r3.groupby("hour").agg(events=("event_id", "nunique"),
                                 priced=("price", lambda s: s.notna().mean()))
    byh["priced"] = (byh["priced"] * 100).round(1)
    p(byh.to_string())
    p("")
    p("coverage by WEEKDAY (rank 3): Mon=0 .. Sun=6")
    byw = r3.groupby("weekday").agg(events=("event_id", "nunique"),
                                    priced=("price", lambda s: s.notna().mean()))
    byw["priced"] = (byw["priced"] * 100).round(1)
    p(byw.to_string())
    p("Friday's session ends 16:59 ET and there is no weekend session, so a late-Friday")
    p("or weekend speech genuinely loses its far offsets. Reported, not clamped.")
    return piv


def cap_sensitivity(panel: pd.DataFrame):
    p("")
    p("coverage if the staleness cap were tightened / loosened (rank 3, from stale_min):")
    r3 = panel[panel["contract_rank"] == 3]
    rows = []
    for cap in (1, 2, 5, 15, 30):
        ok = (r3["stale_min"].notna() & (r3["stale_min"] <= cap)
              & (r3["price"].notna() | (r3["stale_min"] <= S3.STALE_CAP_MIN)))
        ok = r3["stale_min"].notna() & (r3["stale_min"] <= cap)
        rows.append({"cap_min": cap, "coverage": round(float(ok.mean()), 4)})
    p(pd.DataFrame(rows).to_string(index=False))
    p(f"(the panel stores prices at cap {S3.STALE_CAP_MIN:g} min and keeps stale_min, so a "
      f"tighter cap is a filter downstream, not a rebuild)")


# ===========================================================================
def composition(panel: pd.DataFrame, placebo: pd.DataFrame):
    p("")
    p("=" * 78)
    p("4. BOOK COMPOSITION")
    p("=" * 78)
    e = panel[(panel["contract_rank"] == 3) & (panel["offset_min"] == 0)]
    p(f"events in the panel: {e['event_id'].nunique()}   "
      f"{panel['date'].min()} -> {panel['date'].max()}")
    p(f"contracts: {sorted(panel['symbol'].unique())}")
    p("")
    p(f"OVERLAP  (is_overlapping = another Fed calendar entry within |dt| < 420 min,")
    p(f"          i.e. the two [-120,+300] windows share a minute)")
    p(f"  overlapping     {int(e['is_overlapping'].sum())}")
    p(f"  NON-overlapping {int((~e['is_overlapping']).sum())}   <- honest headline subset")
    p(f"  looser reading (another speech INSIDE [-120,+300]): "
      f"overlapping {int((e['n_other_in_window']>0).sum())}, "
      f"clean {int((e['n_other_in_window']==0).sum())}")
    p("")
    p(f"STANCE   hawk(+1) {int((e['stance_sign']==1).sum())}   "
      f"dove(-1) {int((e['stance_sign']==-1).sum())}   "
      f"unsigned(0, no ex-ante score) {int((e['stance_sign']==0).sum())}")
    ratio = (e['stance_sign'] == 1).sum() / max((e['stance_sign'] == -1).sum(), 1)
    p(f"  the roster is LOPSIDED: {ratio:.1f} hawks per dove. Any chart pooling the two")
    p(f"  is dominated by hawks; every later chart must weight the two arms or say so.")
    p(f"  by year:")
    yr = e.assign(y=pd.to_datetime(e['date']).dt.year).groupby(
        ["y", "stance_sign"]).size().unstack(fill_value=0)
    p("  " + yr.to_string().replace("\n", "\n  "))
    p("")
    p("STANCE_SIGN vs BUCKET - they are NOT the same cut, and the difference is big.")
    p("stance_sign is sign(stance_score_exante). `bucket` is the repo's own")
    p("absolute_bucket(), which calls |score| < 10 NEUTRAL (0). So an event can be")
    p("signed dove and bucket-neutral - the exemplar dove above, Jefferson at -5.0,")
    p("is exactly that. Cross-count of signed events:")
    sgn = e[e["stance_sign"] != 0]
    ct = pd.crosstab(sgn["stance_sign"], sgn["bucket"])
    p("  " + ct.to_string().replace("\n", "\n  "))
    weak = int((sgn["bucket"] == 0).sum())
    p(f"  {weak} of {len(sgn)} signed events ({weak/max(len(sgn),1):.0%}) sit in the "
      f"|score| < 10 band the repo calls neutral.")
    p(f"  So n_hawk={int((e['stance_sign']==1).sum())} / "
      f"n_dove={int((e['stance_sign']==-1).sum())} OVERSTATE conviction if read against")
    p(f"  the repo's convention. Filtering |bucket| >= 1 leaves "
      f"{int((sgn['bucket'].abs()>=1).sum())} events "
      f"(hawk {int(((sgn['stance_sign']==1)&(sgn['bucket'].abs()>=1)).sum())}, "
      f"dove {int(((sgn['stance_sign']==-1)&(sgn['bucket'].abs()>=1)).sum())}).")
    p("  Both columns are stored; the headline chart has to pick one and say which.")

    p("")
    p("EX-ANTE SCORE COVERAGE BY YEAR - the single most important structural fact:")
    yy = e.assign(y=pd.to_datetime(e["date"]).dt.year).groupby("y").agg(
        events=("event_id", "size"),
        signed=("stance_sign", lambda s: int((s != 0).sum())),
        pct_scored=("stance_score_exante", lambda s: round(100 * s.notna().mean(), 1)))
    p("  " + yy.to_string().replace("\n", "\n  "))
    p("  2022 carries ZERO signed events: the point-in-time lookup needs a score")
    p("  published BEFORE the speech, and the JPM FED corpus does not supply one that")
    p("  early. The SIGNED sample is therefore 2023-2026, not 2022-2026, whatever the")
    p("  panel's date range says. Any 'SR3 era' claim must carry that caveat.")

    p("")
    p(f"non-overlapping AND signed: "
      f"{int(((~e['is_overlapping']) & (e['stance_sign']!=0)).sum())} events "
      f"(hawk {int(((~e['is_overlapping']) & (e['stance_sign']==1)).sum())}, "
      f"dove {int(((~e['is_overlapping']) & (e['stance_sign']==-1)).sum())})")
    p("")
    p(f"is_fomc_day {int(e['is_fomc_day'].sum())}   is_cpi_day {int(e['is_cpi_day'].sum())}   "
      f"is_nfp_day {int(e['is_nfp_day'].sum())}")
    p(f"role {e['role'].value_counts().to_dict()}")
    p(f"is_voter {e['is_voter'].value_counts(dropna=False).to_dict()}")

    if placebo is not None and len(placebo):
        pe = placebo[(placebo["contract_rank"] == 3) & (placebo["offset_min"] == 0)]
        p("")
        p(f"PLACEBO  {pe['event_id'].nunique()} pseudo-events "
          f"({pe['event_id'].nunique()/max(e['event_id'].nunique(),1):.2f}x the real book) "
          f"on {pe['date'].nunique()} distinct no-speech days")
        p(f"  ranks built: {sorted(placebo['contract_rank'].unique())}")
        p(f"  stance mix   hawk {int((pe['stance_sign']==1).sum())}  "
          f"dove {int((pe['stance_sign']==-1).sum())}  "
          f"unsigned {int((pe['stance_sign']==0).sum())}")
        rw = e["weekday"].value_counts(normalize=True).sort_index().round(3)
        pw = pe["weekday"].value_counts(normalize=True).sort_index().round(3)
        p(f"  weekday mix   real {rw.to_dict()}")
        p(f"                fake {pw.to_dict()}")
        rh = e["clock"].value_counts(normalize=True).head(5).round(3)
        ph = pe["clock"].value_counts(normalize=True).head(5).round(3)
        p(f"  clock mix     real {rh.to_dict()}")
        p(f"                fake {ph.to_dict()}")
        ry = pd.to_datetime(e["date"]).dt.year.value_counts(normalize=True).sort_index().round(3)
        py_ = pd.to_datetime(pe["date"]).dt.year.value_counts(normalize=True).sort_index().round(3)
        p(f"  year mix      real {ry.to_dict()}")
        p(f"                fake {py_.to_dict()}")
        p(f"  NOT matched on the macro calendar - report it so downstream can condition:")
        p(f"    is_cpi_day  real {e['is_cpi_day'].mean():.1%}  fake {pe['is_cpi_day'].mean():.1%}")
        p(f"    is_nfp_day  real {e['is_nfp_day'].mean():.1%}  fake {pe['is_nfp_day'].mean():.1%}")
        p(f"    is_fomc_day real {e['is_fomc_day'].mean():.1%}  fake {pe['is_fomc_day'].mean():.1%} "
          f"(FOMC days are excluded from the quiet-day pool by construction)")
        pc = placebo[placebo["contract_rank"] == 3].groupby("offset_min")["price"].apply(
            lambda s: s.notna().mean())
        p(f"  placebo coverage rank 3, min {pc.min():.1%} max {pc.max():.1%}")


def pit_check():
    p("")
    p("=" * 78)
    p("5. POINT-IN-TIME LABELS")
    p("=" * 78)
    txt = (HERE / "s1_report.txt").read_text(encoding="utf-8")
    keep = False
    for line in txt.splitlines():
        if line.startswith("--- point-in-time"):
            keep = True
        elif line.startswith("--- ") and keep:
            break
        if keep:
            p(line)


# ===========================================================================
def main() -> None:
    ok = known_answer_test()
    panel = pd.read_parquet(HERE / "event_paths.parquet")
    pp = HERE / "placebo_paths.parquet"
    placebo = pd.read_parquet(pp) if pp.exists() else None
    worked_example(panel)
    sign_check(panel)
    coverage(panel, "real events")
    cap_sensitivity(panel)
    composition(panel, placebo)
    pit_check()
    p("")
    p("=" * 78)
    p(f"panel rows real {len(panel):,}" + (f"   placebo {len(placebo):,}" if placebo is not None else ""))
    p(f"known-answer test on the bar rule: {'PASS' if ok else 'FAIL'}")
    (HERE / "VERIFY.txt").write_text("\n".join(LOG), encoding="utf-8")
    p("WROTE VERIFY.txt")


if __name__ == "__main__":
    main()
