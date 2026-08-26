"""Build four independent point-in-time stance labels + three contaminated comparison arms.

Writes:
  _realtime/pit_labels.parquet         one row per (speaker, quarter), one column per construction
  _realtime/pit_labels_events.parquet  one row per panel event, every label joined + the
                                       per-speech L3 arms (which are finer than quarterly)
  _realtime/pit_labels_report.txt      the documentation, incl. the leakage argument per arm
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_realtime")

import pit_common as pc
import fomc_extras as fx

BT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
ES = BT + r"\_event_study"
OUT = BT + r"\_realtime"

REP: list[str] = []


def say(s=""):
    print(s)
    REP.append(str(s))


def hdr(s):
    say("")
    say("=" * 92)
    say(s)
    say("=" * 92)


# --------------------------------------------------------------------------- #
# 0.  load
# --------------------------------------------------------------------------- #
lab = json.load(open(f"{BT}/fed_quarterly_labels.json"))
ALL_Q = pc.qseq("2019Q1", "2026Q3")

flat = {}                      # (speaker, q) -> stance   (matches zz_manual_label_lag.py)
meta = {}                      # (speaker, q) -> dict(period info)
periods = []                   # one row per period
for name, rec in lab["speakers"].items():
    for i, per in enumerate(rec.get("periods", [])):
        why = per.get("why", "") or ""
        ds, n_unres = pc.parse_evidence_dates(why)
        qs = pc.qseq(per["start_q"], per["end_q"])
        periods.append(dict(
            speaker=str(name), pidx=i, start_q=per["start_q"], end_q=per["end_q"],
            stance=per["stance"], confidence=per.get("confidence"),
            n_q=len(qs), n_dates=len(ds), n_unresolved=n_unres,
            first_evidence=(min(ds) if ds else None),
            last_evidence=(max(ds) if ds else None),
            n_bare_years=len(pc.re.findall(r"\b(?:19|20)\d{2}\b", why)),
            why_len=len(why)))
        for q in qs:
            if (str(name), q) in flat:
                say(f"!! OVERLAPPING PERIODS for {name} at {q}")
            flat[(str(name), q)] = per["stance"]
            meta[(str(name), q)] = dict(
                pidx=i, start_q=per["start_q"], end_q=per["end_q"],
                confidence=per.get("confidence"),
                first_evidence=(min(ds) if ds else None),
                last_evidence=(max(ds) if ds else None),
                n_dates=len(ds), n_unresolved=n_unres)
PER = pd.DataFrame(periods)

# --------------------------------------------------------------------------- #
# 1.  reconcile against the existing lag test's flat dict
# --------------------------------------------------------------------------- #
hdr("0.  RECONCILIATION against _event_study/zz_manual_label_lag.py")
ref = {}
for name, rec in lab["speakers"].items():
    for per in rec.get("periods", []):
        for q in pc.qseq(per["start_q"], per["end_q"]):
            ref[(str(name), q)] = per["stance"]
say(f"zz_manual_label_lag.py flat dict : {len(ref)} speaker-quarters")
say(f"this build's flat dict           : {len(flat)} speaker-quarters")
assert flat == ref, "FLAT MAP DIVERGES from the existing lag test"
say("IDENTICAL - keys and values match exactly.")
say(f"speakers {len(lab['speakers'])}   periods {len(PER)}   "
    f"quarter grid {ALL_Q[0]}..{ALL_Q[-1]} ({len(ALL_Q)} quarters)")

# contiguity
noncontig = []
for name, rec in lab["speakers"].items():
    qs = sorted([q for (s, q) in flat if s == str(name)], key=lambda q: (int(q[:4]), int(q[-1])))
    full = pc.qseq(qs[0], qs[-1])
    if qs != full:
        noncontig.append((name, sorted(set(full) - set(qs))))
say(f"speakers with a GAP inside their own span: {len(noncontig)}  {noncontig}")

# --------------------------------------------------------------------------- #
# 2.  panel
# --------------------------------------------------------------------------- #
p = pd.read_parquet(f"{ES}/event_paths.parquet")
p3 = p[p.contract_rank == 3]
w = p3.pivot_table(index=["event_id", "speech_ts", "speaker"], columns="offset_min",
                   values="rate_bp").reset_index()
bt = p3[p3.offset_min.isin([-60, 240])].pivot_table(
    index="event_id", columns="offset_min", values="bar_label_ts", aggfunc="first")
bt.columns = ["t_open", "t_close"]
w = w.merge(bt.reset_index(), on="event_id", how="left")
w["move_bp"] = w[240] - w[-60]
EV = w.dropna(subset=["move_bp"]).copy()
EV["q"] = EV.speech_ts.map(pc.qkey)
EV["date"] = EV.speech_ts.dt.date
# fall back to nominal window stamps if a bar label is missing
EV["t_open"] = EV.t_open.fillna(EV.speech_ts - pd.Timedelta(minutes=60))
EV["t_close"] = EV.t_close.fillna(EV.speech_ts + pd.Timedelta(minutes=240))
EV = EV.sort_values("t_close").reset_index(drop=True)

hdr("1.  PANEL")
say(f"event_paths.parquet rank-3 events with a valid -60 -> +240 move : {len(EV)}")
say(f"span {EV.speech_ts.min()}  ->  {EV.speech_ts.max()}")
say(f"speakers in panel {EV.speaker.nunique()}   quarters {EV.q.nunique()} "
    f"({sorted(EV.q.unique())[0]}..{sorted(EV.q.unique())[-1]})")
missing = sorted(set(EV.speaker) - set(lab["speakers"]))
say(f"panel speakers with NO entry in the labels file: {missing if missing else 'none'}")
n_bar_fallback = int(w.t_open.isna().sum() + w.t_close.isna().sum())
say(f"events needing a nominal-timestamp fallback for the window stamps: {n_bar_fallback}")

# --------------------------------------------------------------------------- #
# 3.  the quarter grid
# --------------------------------------------------------------------------- #
SPEAKERS = sorted(set(lab["speakers"]) | set(EV.speaker))
rows = []
for s in SPEAKERS:
    for q in ALL_Q:
        m = meta.get((s, q), {})
        rows.append(dict(speaker=s, quarter=q, quarter_start=pc.qstart(q),
                         on_committee=(s, q) in flat,
                         stance_raw=pc.to_num(flat.get((s, q))),
                         confidence=m.get("confidence"),
                         period_start_q=m.get("start_q"), period_end_q=m.get("end_q"),
                         l1_first_evidence=m.get("first_evidence"),
                         l1_last_evidence=m.get("last_evidence"),
                         n_dates_parsed=m.get("n_dates"),
                         n_unresolved_month_tokens=m.get("n_unresolved")))
G = pd.DataFrame(rows)

# role, from the LABELS FILE role string (biography, not stance)
ROLE_STR = {s: (lab["speakers"].get(s, {}) or {}).get("role", "") for s in SPEAKERS}


def role_at(speaker: str, d: _dt.date) -> str:
    rs = ROLE_STR.get(speaker, "") or ""
    if "President (New York)" in rs:
        return "President (NY)"
    if "President (" in rs:
        return "President"
    # Board seat.  The two Chair tenures are stated in the role strings themselves
    # ("Chair (through May 2026), then Governor" / "Chair") and are public facts.
    if speaker == "Powell":
        return "Chair" if d <= _dt.date(2026, 5, 21) else "Governor"
    if speaker == "Warsh":
        return "Chair" if d >= _dt.date(2026, 5, 22) else "Governor"
    return "Governor"


G["role"] = [role_at(s, d) for s, d in zip(G.speaker, G.quarter_start)]
G["is_voter"] = [fx.is_voter(s, d) for s, d in zip(G.speaker, G.quarter_start)]

# cross-check the parsed role against fomc_extras.role_of
xr = [(s, q, r, fx.role_of(s, d)) for s, q, d, r in
      zip(G.speaker, G.quarter, G.quarter_start, G.role) if r != fx.role_of(s, d)]
hdr("2.  ROLE cross-check  (labels-file role string  vs  fomc_extras.role_of)")
say(f"disagreements: {len(xr)}")
for s, q, a, b in xr[:20]:
    say(f"   {s:10s} {q}  labels-file->{a:15s} fomc_extras->{b}")
say("role counts on-committee: " +
    str(dict(Counter(G[G.on_committee].role).most_common())))

# --------------------------------------------------------------------------- #
# L1  EVIDENCE-VINTAGE FILTER
# --------------------------------------------------------------------------- #
fe = G.l1_first_evidence
le = G.l1_last_evidence
qs = G.quarter_start
G["stance_l1"] = np.where(
    G.on_committee & fe.notna() & pd.Series([(a is not None and a < b) for a, b in zip(fe, qs)]),
    G.stance_raw, np.nan)
G["stance_l1_strict"] = np.where(
    G.on_committee & le.notna() & pd.Series([(a is not None and a < b) for a, b in zip(le, qs)]),
    G.stance_raw, np.nan)
# conservative strict: a why-block with ANY unresolved month token has an unknown true
# latest date, so treat its evidence as running to the end of the period.
cons_last = [
    (pc.qend_date(pe) if (nu and nu > 0) else l)
    for pe, nu, l in zip(G.period_end_q, G.n_unresolved_month_tokens, G.l1_last_evidence)]
G["stance_l1_strict_c"] = np.where(
    G.on_committee & pd.Series([(a is not None and a < b) for a, b in zip(cons_last, qs)]),
    G.stance_raw, np.nan)
G["l1_lag_days"] = [((b - a).days if (a is not None and a < b) else np.nan)
                    for a, b in zip(fe, qs)]

# --------------------------------------------------------------------------- #
# L2  STABILITY FILTER
# --------------------------------------------------------------------------- #
def stable_k(speaker, q, K):
    """PIT form: the value that HAS BEEN in force for the K quarters before Q.
    Uses label(Q-1)..label(Q-K) only; label(Q) is never read."""
    vals = [flat.get((speaker, pc.qshift(q, k))) for k in range(1, K + 1)]
    if any(v is None for v in vals):
        return np.nan
    if len(set(vals)) != 1:
        return np.nan
    return pc.to_num(vals[0])


for K in (2, 4, 8):
    G[f"stance_stable_{K}"] = [stable_k(s, q, K) for s, q in zip(G.speaker, G.quarter)]

# how often does the stable-history value differ from the quarter's OWN label?
# (= the size of the selection leak in the literal "label as of Q" reading)
div = {}
for K in (2, 4, 8):
    m = G[G[f"stance_stable_{K}"].notna() & G.on_committee]
    same = (m[f"stance_stable_{K}"] == m.stance_raw)
    div[K] = (int((~same).sum()), int(len(m)))

# --------------------------------------------------------------------------- #
# L3  MECHANICAL / SELF-REFERENTIAL
# --------------------------------------------------------------------------- #
hist = defaultdict(list)          # speaker -> [(t_close, move_bp)] sorted
for s, tc, mv in zip(EV.speaker, EV.t_close, EV.move_bp):
    hist[s].append((tc, float(mv)))
for s in hist:
    hist[s].sort()

NYTZ = EV.speech_ts.dt.tz


def mech_before(speaker, cutoff_ts, N):
    """sign of the mean of the speaker's last N moves whose +240 window CLOSED
    strictly before cutoff_ts.  NaN if fewer than N such speeches."""
    h = hist.get(speaker, [])
    prior = [m for t, m in h if t < cutoff_ts]
    if len(prior) < N:
        return np.nan
    return float(np.sign(np.mean(prior[-N:])))


# quarter-start arm (satisfies the umbrella rule: frozen at the first day of Q)
for N in (3, 5, 10):
    col = []
    for s, qd in zip(G.speaker, G.quarter_start):
        cut = pd.Timestamp(qd).tz_localize(NYTZ)
        col.append(mech_before(s, cut, N))
    G[f"stance_mech_q{N}"] = col

# per-speech arm (spec-faithful: strictly before THIS speech's entry bar)
for N in (3, 5, 10):
    EV[f"stance_mech_e{N}"] = [mech_before(s, t0, N) for s, t0 in zip(EV.speaker, EV.t_open)]

# --------------------------------------------------------------------------- #
# L4  ROLE + ROTATION ONLY
# --------------------------------------------------------------------------- #
# Sign fixed as a PRE-SAMPLE prior, not fitted: regional Reserve Bank presidents
# lean hawkish relative to Board appointees.  New York and the Chair are the
# committee's centre by construction.
ROLE_PRIOR = {"President": 1.0, "President (NY)": 0.0, "Chair": 0.0, "Governor": -1.0}
G["stance_role"] = [ROLE_PRIOR.get(r, np.nan) if oc else np.nan
                    for r, oc in zip(G.role, G.on_committee)]

# --------------------------------------------------------------------------- #
# C1 / C2 / C3   NOT point-in-time
# --------------------------------------------------------------------------- #
G["stance_asof"] = np.where(G.on_committee, G.stance_raw, np.nan)
G["stance_lag1"] = [pc.to_num(flat.get((s, pc.qprev(q)))) for s, q in zip(G.speaker, G.quarter)]
G["stance_highconf"] = np.where(G.on_committee & (G.confidence == "high"), G.stance_raw, np.nan)

# --------------------------------------------------------------------------- #
# join to events
# --------------------------------------------------------------------------- #
QCOLS = ["stance_l1", "stance_l1_strict", "stance_l1_strict_c",
         "stance_stable_2", "stance_stable_4", "stance_stable_8",
         "stance_mech_q3", "stance_mech_q5", "stance_mech_q10",
         "stance_role", "stance_asof", "stance_lag1", "stance_highconf"]
ECOLS = ["stance_mech_e3", "stance_mech_e5", "stance_mech_e10"]

EVJ = EV.merge(G[["speaker", "quarter"] + QCOLS + ["role", "is_voter", "on_committee"]],
               left_on=["speaker", "q"], right_on=["speaker", "quarter"], how="left")
say("")
say(f"panel events joined: {len(EVJ)}   with no (speaker,quarter) row at all: "
    f"{int(EVJ.quarter.isna().sum())}   off-committee at their own speech: "
    f"{int((~EVJ.on_committee.fillna(False)).sum())}")
oc = EVJ[~EVJ.on_committee.fillna(False)]
for _, r in oc.iterrows():
    say(f"   OFF-GRID EVENT: {r.speaker} {r.speech_ts}  quarter {r.quarter}  "
        f"(the label grid's roster ends this speaker earlier than the panel does; "
        f"every stance arm is NaN for it)")

# --------------------------------------------------------------------------- #
# report tables
# --------------------------------------------------------------------------- #
hdr("3.  L1  EVIDENCE-VINTAGE PARSE")
say(f"periods: {len(PER)}")
say(f"  with >=1 fully-specified date parsed : {int((PER.n_dates > 0).sum())}")
say(f"  with NO parseable date               : {int((PER.n_dates == 0).sum())}   "
    f"(-> every quarter of those periods is UNAVAILABLE under L1)")
nz = PER[PER.n_dates == 0]
say(f"    of those, how many DID contain a bare-year token only: "
    f"{int((nz.n_bare_years > 0).sum())}   and nothing date-like at all: "
    f"{int((nz.n_bare_years == 0).sum())}")
for _, r in nz.iterrows():
    say(f"      {r.speaker:10s} {r.start_q}-{r.end_q}  stance {r.stance:+d}  "
        f"n_q={r.n_q}  bare_years={r.n_bare_years}  unresolved_month_tokens={r.n_unresolved}")
say(f"  total dates parsed: {int(PER.n_dates.sum())}   "
    f"median per period {PER.n_dates.median():.0f}   max {int(PER.n_dates.max())}")
say(f"  UNRESOLVED month tokens (year only implied, e.g. '27 Jul', 'the September dots'): "
    f"{int(PER.n_unresolved.sum())} across {int((PER.n_unresolved > 0).sum())} periods")

av = G[G.stance_l1.notna()]
say("")
say("(quarter start - earliest cited evidence), in days, over the AVAILABLE speaker-quarters:")
say(f"  n={len(av)}  min {av.l1_lag_days.min():.0f}  q25 {av.l1_lag_days.quantile(.25):.0f}  "
    f"median {av.l1_lag_days.median():.0f}  q75 {av.l1_lag_days.quantile(.75):.0f}  "
    f"max {av.l1_lag_days.max():.0f}  mean {av.l1_lag_days.mean():.0f}")
bins = [0, 31, 92, 183, 366, 731, 10000]
lbl = ["<1m", "1-3m", "3-6m", "6-12m", "1-2y", "2y+"]
say("  " + str(dict(zip(lbl, pd.cut(av.l1_lag_days, bins, labels=lbl, right=False)
                        .value_counts().reindex(lbl).fillna(0).astype(int).tolist()))))

oncom = G[G.on_committee]
say("")
say(f"SENSITIVITY - if bare years were admitted as 1 Jan (the permissive reading), the "
    f"{int((PER.n_dates == 0).sum())} unparseable periods covering "
    f"{int(nz.n_q.sum())} speaker-quarters would mostly become available; L1 coverage is "
    f"reported on the CONSERVATIVE reading only.")

hdr("4.  L2  STABILITY divergence")
for K in (2, 4, 8):
    n_diff, n_tot = div[K]
    say(f"  K={K}: of {n_tot} speaker-quarters with a stable {K}-quarter history, "
        f"{n_diff} ({n_diff/max(n_tot,1):.1%}) have a DIFFERENT label at Q itself.")
say("  Those are exactly the quarters the literal 'label as of Q' reading would have")
say("  selected on the future.  The shipped column carries the CARRIED-FORWARD value.")

hdr("5.  L3  MECHANICAL history depth")
say(f"speakers with >=3 / >=5 / >=10 prior moves by end of sample: " +
    str([sum(1 for s in hist if len(hist[s]) >= n) for n in (3, 5, 10)]) +
    f"  of {len(hist)} speakers in the panel")
say("moves per speaker: " + str(dict(sorted(((s, len(v)) for s, v in hist.items()),
                                            key=lambda x: -x[1]))))

# --------------------------------------------------------------------------- #
# coverage table
# --------------------------------------------------------------------------- #
hdr("6.  COVERAGE PER CONSTRUCTION")
ARMS = [
    ("stance_l1", "L1  evidence-vintage (earliest cited < Q start)", "PIT*"),
    ("stance_l1_strict", "L1s LATEST cited < Q start  (parsed tokens only)", "PIT*"),
    ("stance_l1_strict_c", "L1c LATEST, unresolved months -> period end", "PIT"),
    ("stance_stable_2", "L2  unchanged the previous 2 quarters", "PIT"),
    ("stance_stable_4", "L2  unchanged the previous 4 quarters", "PIT"),
    ("stance_stable_8", "L2  unchanged the previous 8 quarters", "PIT"),
    ("stance_mech_q3", "L3  own last 3 moves, frozen at Q start", "PIT"),
    ("stance_mech_q5", "L3  own last 5 moves, frozen at Q start", "PIT"),
    ("stance_mech_q10", "L3  own last 10 moves, frozen at Q start", "PIT"),
    ("stance_role", "L4  role prior only (Pres +1 / Gov -1 / Chair,NY 0)", "PIT"),
    ("stance_asof", "C1  quarter's OWN label", "CONTAMINATED"),
    ("stance_lag1", "C2  previous quarter's label", "CONTAMINATED"),
    ("stance_highconf", "C3  own label, confidence=='high'", "CONTAMINATED"),
]
tab = []
for col, desc, pit in ARMS:
    sq = G[G[col].notna()]
    sqo = sq[sq.on_committee]
    ev = EVJ[EVJ[col].notna()]
    v = sqo[col]
    tab.append(dict(
        arm=col, pit=pit,
        sq_n=len(sq), sq_oc=len(sqo), sq_pct=f"{len(sqo)/len(oncom):.0%}",
        span=(f"{sqo.quarter.min()}..{sqo.quarter.max()}" if len(sqo) else "-"),
        ev_n=len(ev), ev_pct=f"{len(ev)/len(EVJ):.0%}",
        ev_nz=int((ev[col] != 0).sum()),
        hawk=int((v > 0).sum()), neut=int((v == 0).sum()), dove=int((v < 0).sum()),
        desc=desc))
for col in ECOLS:
    ev = EV[EV[col].notna()]
    v = ev[col]
    tab.append(dict(arm=col, pit="PIT", sq_n=-1, sq_oc=-1, sq_pct="n/a",
                    span=(f"{pc.qkey(ev.speech_ts.min())}..{pc.qkey(ev.speech_ts.max())}"
                          if len(ev) else "-"),
                    ev_n=len(ev), ev_pct=f"{len(ev)/len(EV):.0%}",
                    ev_nz=int((v != 0).sum()),
                    hawk=int((v > 0).sum()), neut=int((v == 0).sum()), dove=int((v < 0).sum()),
                    desc=f"L3  own last {col[-2:].lstrip('e')} moves, per SPEECH"))
T = pd.DataFrame(tab)
say(f"denominator: on-committee speaker-quarters = {len(oncom)}   panel events = {len(EVJ)}")
say("")
say(T[["arm", "pit", "sq_n", "sq_oc", "sq_pct", "span", "ev_n", "ev_pct", "ev_nz",
       "hawk", "neut", "dove"]].to_string(index=False))
say("")
say("  sq_n  = speaker-quarters with a usable (non-NaN) value, over the FULL 31x31 grid")
say("  sq_oc = of those, the ones where the speaker is actually on the committee that")
say("          quarter.  sq_n > sq_oc only for the two arms that are computable off the")
say("          roster - L2 (a departed member's last value stays 'stable') and L3 (a")
say("          departed member still has price history).  Neither can reach an event,")
say("          because an event only exists where somebody spoke.  sq_pct is sq_oc/476.")
say("  ev_n  = panel events (of the 1,029 with a valid rank-3 -60->+240 move) that get one")
say("  ev_nz = of those, how many carry a NON-ZERO stance, i.e. actually generate a trade")
say("  hawk/neut/dove counted over on-committee speaker-quarters (over events for *_e*)")
say("")
for _, r in T.iterrows():
    say(f"  {r.arm:20s} {r.desc}")

# voters-only view, since that is the cut that does the work
hdr("7.  COVERAGE under the VOTERS-ONLY cut, and by era")
vv = EVJ[EVJ.is_voter.fillna(False)]
e1 = EVJ[EVJ.speech_ts.dt.year <= 2023]
e2 = EVJ[EVJ.speech_ts.dt.year >= 2024]
r2 = []
for col, desc, pit in ARMS:
    r2.append(dict(arm=col,
                   all_ev=int(EVJ[col].notna().sum()),
                   all_nz=int((EVJ[col].fillna(0) != 0).sum()),
                   vot_ev=int(vv[col].notna().sum()),
                   vot_nz=int((vv[col].fillna(0) != 0).sum()),
                   vot_c2=int((vv[col].abs() >= 2).sum()),
                   e2223_nz=int((e1[col].fillna(0) != 0).sum()),
                   e2426_nz=int((e2[col].fillna(0) != 0).sum())))
for col in ECOLS:
    vvE = EV[EV.event_id.isin(vv.event_id)]
    r2.append(dict(arm=col, all_ev=int(EV[col].notna().sum()),
                   all_nz=int((EV[col].fillna(0) != 0).sum()),
                   vot_ev=int(vvE[col].notna().sum()),
                   vot_nz=int((vvE[col].fillna(0) != 0).sum()), vot_c2=0,
                   e2223_nz=int((EV[EV.speech_ts.dt.year <= 2023][col].fillna(0) != 0).sum()),
                   e2426_nz=int((EV[EV.speech_ts.dt.year >= 2024][col].fillna(0) != 0).sum())))
say(f"panel events {len(EVJ)}   voters {len(vv)}   2022-23 {len(e1)}   2024-26 {len(e2)}")
say("")
say(pd.DataFrame(r2).to_string(index=False))
say("")
say("  *_nz = tradeable events (non-zero stance).  vot_c2 = voters AND conviction |2|.")
say("  NOTE the L3 arms are +/-1 by construction so nz == ev; a zero appears only on an")
say("  exact tie in the mean of the prior N moves.")

# --------------------------------------------------------------------------- #
# hand-checks the advisor named
# --------------------------------------------------------------------------- #
hdr("8.  HAND-CHECKS against the markdown grid")


def show(sp, cols, qa="2022Q1", qb="2026Q3"):
    d = G[(G.speaker == sp) & G.quarter.isin(pc.qseq(qa, qb))]
    say(f"\n{sp}:")
    say(d[["quarter", "on_committee", "stance_raw"] + cols].to_string(index=False))


say("Jefferson is '·' in every quarter he is on the committee -> must survive K=8:")
jf = G[(G.speaker == "Jefferson") & G.on_committee]
say(f"  on-committee quarters {len(jf)}  distinct raw stances {sorted(jf.stance_raw.unique())}  "
    f"stable_8 non-NaN {int(jf.stance_stable_8.notna().sum())}")
say("\nBowman flips 2025Q2 (0) -> 2025Q3 (-2) -> must break the streak at and after the flip:")
bw = G[(G.speaker == "Bowman") & G.quarter.isin(pc.qseq("2025Q1", "2026Q1"))]
say(bw[["quarter", "stance_raw", "stance_stable_2", "stance_stable_4", "stance_stable_8",
        "stance_l1", "stance_lag1"]].to_string(index=False))
say("\nLate joiners must be mostly NaN at K=8 (honest cost, not a bug):")
for s in ["Hammack", "Musalem", "Schmid", "Miran", "Paulson", "Warsh", "Goolsbee", "Logan"]:
    d = G[(G.speaker == s) & G.on_committee]
    if not len(d):
        continue
    say(f"  {s:10s} on-committee {len(d):2d}q ({d.quarter.min()}..{d.quarter.max()})  "
        f"stable_2 {int(d.stance_stable_2.notna().sum()):2d}  "
        f"stable_4 {int(d.stance_stable_4.notna().sum()):2d}  "
        f"stable_8 {int(d.stance_stable_8.notna().sum()):2d}  "
        f"l1 {int(d.stance_l1.notna().sum()):2d}")

say("\nPowell's Chair -> Governor handover (labels role string: 'Chair (through May 2026)'):")
pw = G[(G.speaker == "Powell") & G.quarter.isin(pc.qseq("2026Q1", "2026Q3"))]
say(pw[["quarter", "quarter_start", "role", "stance_role", "on_committee"]].to_string(index=False))
wr = G[(G.speaker == "Warsh") & G.quarter.isin(pc.qseq("2026Q1", "2026Q3"))]
say(wr[["quarter", "quarter_start", "role", "stance_role", "on_committee"]].to_string(index=False))

say("\nWorked L1 example - Bowman 2023Q1-2025Q1, stance +2:")
b = PER[(PER.speaker == "Bowman") & (PER.start_q == "2023Q1")].iloc[0]
say(f"  earliest cited {b.first_evidence}   latest cited {b.last_evidence}   "
    f"dates parsed {b.n_dates}  unresolved month tokens {b.n_unresolved}")
say(G[(G.speaker == "Bowman") & G.quarter.isin(pc.qseq("2023Q1", "2025Q1"))]
    [["quarter", "stance_raw", "stance_l1", "stance_l1_strict", "l1_lag_days"]].to_string(index=False))

# --------------------------------------------------------------------------- #
# write
# --------------------------------------------------------------------------- #
KEEP = (["speaker", "quarter", "quarter_start", "on_committee", "role", "is_voter",
         "confidence", "period_start_q", "period_end_q", "stance_raw",
         "l1_first_evidence", "l1_last_evidence", "l1_lag_days",
         "n_dates_parsed", "n_unresolved_month_tokens"] + QCOLS)
OUTG = G[KEEP].copy()
OUTG["quarter_start"] = pd.to_datetime(OUTG.quarter_start)
OUTG["l1_first_evidence"] = pd.to_datetime(OUTG.l1_first_evidence)
OUTG["l1_last_evidence"] = pd.to_datetime(OUTG.l1_last_evidence)
OUTG["is_voter"] = OUTG.is_voter.astype("object")
OUTG.to_parquet(f"{OUT}/pit_labels.parquet", index=False)

EOUT = EVJ[["event_id", "speech_ts", "date", "speaker", "q", "role", "is_voter",
            "move_bp", "t_open", "t_close"] + QCOLS].copy()
EOUT = EOUT.merge(EV[["event_id"] + ECOLS], on="event_id", how="left")
EOUT = EOUT.rename(columns={"q": "quarter"})
EOUT.to_parquet(f"{OUT}/pit_labels_events.parquet", index=False)

hdr("9.  FILES WRITTEN")
say(f"{OUT}\\pit_labels.parquet          {OUTG.shape[0]} rows x {OUTG.shape[1]} cols")
say(f"{OUT}\\pit_labels_events.parquet   {EOUT.shape[0]} rows x {EOUT.shape[1]} cols")

with open(f"{OUT}/_r3_tables.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(REP))
print("\n[tables written to _r3_tables.txt]")
