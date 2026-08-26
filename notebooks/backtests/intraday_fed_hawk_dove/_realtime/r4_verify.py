"""Independent recompute + a decisive leakage test for the PIT label build.

Two things happen here.

1. REINDEPENDENT RECOMPUTE.  Every column in pit_labels.parquet is rebuilt from the
   raw JSON and the raw panel by a second, differently-structured code path and
   asserted equal.  A shared helper bug would survive this; a build-script bug will not.

2. THE PERTURBATION TEST.  Pick a cutoff T.  Corrupt EVERYTHING dated on or after T -
   every label value, every confidence tier, every cited evidence date, every price
   move - and rebuild.  Any column value for a quarter that starts strictly before T
   must be bit-identical, because by the umbrella rule it was computable from
   information dated before its own quarter start, and its quarter start is before T.
   Rows whose quarter starts exactly AT T are reported separately: that is where the
   arms separate into "the value itself is indexed before Q" and "the value is indexed
   at Q but argued from pre-Q evidence".

   WHAT THIS CAN AND CANNOT PROVE.  It proves the CODE is causal - that no construction
   reads a cell indexed at or after the quarter it trades.  It cannot prove the 2026
   human assigner was causal.  That is the residual L1 addresses by argument and no
   test can close.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from collections import defaultdict

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


ALL_Q = pc.qseq("2019Q1", "2026Q3")
QCOLS = ["stance_l1", "stance_l1_strict", "stance_l1_strict_c",
         "stance_stable_2", "stance_stable_4", "stance_stable_8",
         "stance_mech_q3", "stance_mech_q5", "stance_mech_q10",
         "stance_role", "stance_asof", "stance_lag1", "stance_highconf"]

# --------------------------------------------------------------------------- #
# inputs, as three plain dictionaries the builder below is a pure function of
# --------------------------------------------------------------------------- #
lab = json.load(open(f"{BT}/fed_quarterly_labels.json"))

CELL = {}     # (speaker,q) -> dict(stance, confidence, first_ev, last_ev, n_unres, end_q)
for name, rec in lab["speakers"].items():
    for per in rec["periods"]:
        ds, nu = pc.parse_evidence_dates(per.get("why", "") or "")
        for q in pc.qseq(per["start_q"], per["end_q"]):
            CELL[(str(name), q)] = dict(
                stance=float(per["stance"]), confidence=per.get("confidence"),
                dates=list(ds), n_unres=nu, end_q=per["end_q"])

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
EV["t_open"] = EV.t_open.fillna(EV.speech_ts - pd.Timedelta(minutes=60))
EV["t_close"] = EV.t_close.fillna(EV.speech_ts + pd.Timedelta(minutes=240))
NYTZ = EV.speech_ts.dt.tz
MOVES = [(str(s), pd.Timestamp(tc), float(m))
         for s, tc, m in zip(EV.speaker, EV.t_close, EV.move_bp)]

SPEAKERS = sorted(set(lab["speakers"]) | set(EV.speaker))
ROLE_STR = {s: (lab["speakers"].get(s, {}) or {}).get("role", "") for s in SPEAKERS}
ROLE_PRIOR = {"President": 1.0, "President (NY)": 0.0, "Chair": 0.0, "Governor": -1.0}

# --------------------------------------------------------------------------- #
# the independent builder - a pure function of (CELL, MOVES)
# --------------------------------------------------------------------------- #
LEAK_STABLE = False      # mutation switches, flipped only by the mutation checks
LEAK_MECH_DAYS = 0


def role_at(sp, d):
    rs = ROLE_STR.get(sp, "") or ""
    if "President (New York)" in rs:
        return "President (NY)"
    if "President (" in rs:
        return "President"
    if sp == "Powell":
        return "Chair" if d <= _dt.date(2026, 5, 21) else "Governor"
    if sp == "Warsh":
        return "Chair" if d >= _dt.date(2026, 5, 22) else "Governor"
    return "Governor"


def build(cell, moves):
    by_sp = defaultdict(list)
    for s, tc, m in moves:
        by_sp[s].append((tc, m))
    for s in by_sp:
        by_sp[s].sort()

    out = []
    for sp in SPEAKERS:
        for q in ALL_Q:
            c = cell.get((sp, q))
            d0 = pc.qstart(q)
            r = {"speaker": sp, "quarter": q}
            raw = c["stance"] if c else np.nan

            # ---- L1 family -------------------------------------------------
            if c and c["dates"]:
                r["stance_l1"] = raw if min(c["dates"]) < d0 else np.nan
                r["stance_l1_strict"] = raw if max(c["dates"]) < d0 else np.nan
                lastc = pc.qend_date(c["end_q"]) if c["n_unres"] > 0 else max(c["dates"])
                r["stance_l1_strict_c"] = raw if lastc < d0 else np.nan
            else:
                r["stance_l1"] = r["stance_l1_strict"] = np.nan
                lastc = pc.qend_date(c["end_q"]) if (c and c["n_unres"] > 0) else None
                r["stance_l1_strict_c"] = raw if (lastc is not None and lastc < d0) else np.nan

            # ---- L2 --------------------------------------------------------
            for K in (2, 4, 8):
                hist = []
                qq = q
                for _ in range(K):
                    qq = pc.qprev(qq)
                    hist.append(cell.get((sp, qq)))
                if LEAK_STABLE:
                    hist.append(c)                      # <-- the injected leak
                vals = [h["stance"] if h else None for h in hist]
                r[f"stance_stable_{K}"] = (vals[0] if (None not in vals and
                                                      len(set(vals)) == 1) else np.nan)

            # ---- L3 --------------------------------------------------------
            cut = pd.Timestamp(d0).tz_localize(NYTZ) + pd.Timedelta(days=LEAK_MECH_DAYS)
            prior = [m for tc, m in by_sp.get(sp, []) if tc < cut]
            for N in (3, 5, 10):
                r[f"stance_mech_q{N}"] = (float(np.sign(np.mean(prior[-N:])))
                                          if len(prior) >= N else np.nan)

            # ---- L4 --------------------------------------------------------
            r["stance_role"] = ROLE_PRIOR.get(role_at(sp, d0), np.nan) if c else np.nan

            # ---- C1 / C2 / C3 ---------------------------------------------
            r["stance_asof"] = raw if c else np.nan
            cp = cell.get((sp, pc.qprev(q)))
            r["stance_lag1"] = cp["stance"] if cp else np.nan
            r["stance_highconf"] = raw if (c and c["confidence"] == "high") else np.nan
            out.append(r)
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- #
# 1. independent recompute vs the shipped parquet
# --------------------------------------------------------------------------- #
hdr("V1.  INDEPENDENT RECOMPUTE vs pit_labels.parquet")
SHIP = pd.read_parquet(f"{OUT}/pit_labels.parquet")
MINE = build(CELL, MOVES)
A = SHIP.sort_values(["speaker", "quarter"]).reset_index(drop=True)
B = MINE.sort_values(["speaker", "quarter"]).reset_index(drop=True)
assert (A.speaker.tolist() == B.speaker.tolist()) and (A.quarter.tolist() == B.quarter.tolist())
say(f"rows compared: {len(A)}")
bad = 0
for c in QCOLS:
    same = ((A[c].isna() & B[c].isna()) | (A[c] == B[c]))
    n = int((~same).sum())
    bad += n
    say(f"  {c:20s} mismatches {n}")
assert bad == 0, f"{bad} mismatches between the shipped parquet and the independent rebuild"
say("ALL COLUMNS MATCH - the build is reproducible from a second code path.")

# --------------------------------------------------------------------------- #
# 2. the perturbation test
# --------------------------------------------------------------------------- #
T = _dt.date(2024, 1, 1)
rng = np.random.default_rng(20260826)


def corrupt(cell, moves, T):
    """corrupt every input dated on or after T"""
    c2 = {}
    for (sp, q), c in cell.items():
        if pc.qstart(q) >= T:
            c2[(sp, q)] = dict(
                stance=(2.0 if c["stance"] != 2.0 else -2.0),      # always a real change
                confidence=("high" if c["confidence"] != "high" else "low"),
                dates=[(d + _dt.timedelta(days=1000) if d >= T else d) for d in c["dates"]],
                n_unres=c["n_unres"], end_q=c["end_q"])
        else:
            c2[(sp, q)] = dict(c, dates=[(d + _dt.timedelta(days=1000) if d >= T else d)
                                         for d in c["dates"]])
    Tts = pd.Timestamp(T).tz_localize(NYTZ)
    m2 = [(s, tc, (-3.0 * m if tc >= Tts else m)) for s, tc, m in moves]
    return c2, m2


C2, M2 = corrupt(CELL, MOVES, T)
PERT = build(C2, M2).sort_values(["speaker", "quarter"]).reset_index(drop=True)

qstarts = B.quarter.map(pc.qstart)
pre = qstarts < T
at = qstarts == T
post = qstarts > T
say("")
say(f"cutoff T = {T}.  Corrupted on/after T: every label value, every confidence tier,")
say(f"every evidence date, every price move.  rows before T {int(pre.sum())} | "
    f"at T {int(at.sum())} | after T {int(post.sum())}")


def ndiff(mask, col):
    a, b = B.loc[mask, col], PERT.loc[mask, col]
    return int((~((a.isna() & b.isna()) | (a == b))).sum())


say("")
say(f"{'arm':22s} {'before T':>9s} {'at T':>6s} {'after T':>8s}   verdict")
say("-" * 92)
verdict = {}
for c in QCOLS:
    nb, na, np_ = ndiff(pre, c), ndiff(at, c), ndiff(post, c)
    if nb > 0:
        v = "*** LEAK: changes BEFORE the cutoff ***"
    elif na == 0:
        v = "index-causal: value comes from strictly before its own quarter"
    else:
        v = "value is indexed AT its own quarter (see note)"
    verdict[c] = (nb, na, np_, v)
    say(f"{c:22s} {nb:9d} {na:6d} {np_:8d}   {v}")
say("-" * 92)
leaks = [c for c in QCOLS if verdict[c][0] > 0]
assert not leaks, f"FUTURE LEAKAGE in {leaks}"
say("No column changes for any quarter starting before the cutoff.  "
    "No construction reads the future.")

say("")
say("The 'at T' column is the informative one.  It separates:")
say("  INDEX-CAUSAL  (0 at T) - L2, L3, L4 and C2.  Corrupting quarter T's own label")
say("     leaves them untouched, because the value they carry is literally a pre-T cell")
say("     (L2/C2), a pre-T price (L3) or a public roster fact (L4).")
say("  INDEXED AT Q  (>0 at T) - L1, L1s, L1c, C1, C3.  These carry quarter Q's OWN")
say("     assigned value.  L1's claim is not that the value is indexed earlier; it is")
say("     that the EVIDENCE the assigner cited for it is.  That is an argument about")
say("     provenance and this test cannot adjudicate it - only the prose can, and only")
ast = "     as far as the assigner's citations are complete."
say(ast)

# Sanity: the perturbation must actually bite, or "no change before T" proves nothing.
# stance_role is the ONE exception and it is the point of L4: it is a pure function of
# the role string and the calendar, so corrupting every stance and every price moves it
# by exactly zero rows anywhere.  It gets its own vacuity check below.
biting = {c: verdict[c][2] for c in QCOLS if c != "stance_role"}
say("")
say(f"perturbation bites after T (non-zero changes required): {biting}")
assert all(v > 0 for v in biting.values()), \
    "perturbation did not change anything after the cutoff - the test is VACUOUS"
say(f"stance_role changes: before T {verdict['stance_role'][0]}, at T "
    f"{verdict['stance_role'][1]}, after T {verdict['stance_role'][2]} - ZERO everywhere.")
say("That is L4's defining property, not a dead column: it is a pure function of the")
say("role string and the calendar, so no stance and no price can move it.  Its own")
say("vacuity check (perturb the ROLE strings) follows.")

_save_roles = dict(ROLE_STR)
for k in ROLE_STR:
    ROLE_STR[k] = "President (Atlanta)" if "President" not in (_save_roles[k] or "") else "Governor"
ROLEPERT = build(CELL, MOVES).sort_values(["speaker", "quarter"]).reset_index(drop=True)
ROLE_STR.update(_save_roles)
_nrp = int((~((B.stance_role.isna() & ROLEPERT.stance_role.isna()) |
              (B.stance_role == ROLEPERT.stance_role))).sum())
say(f"  swapping every role string moves stance_role on {_nrp} rows - the column is live.")
assert _nrp > 0, "stance_role does not respond to role - the column is dead"
_restored = build(CELL, MOVES).sort_values(["speaker", "quarter"]).reset_index(drop=True)
assert _restored[QCOLS].equals(B[QCOLS]), "role strings not restored"

# --------------------------------------------------------------------------- #
# 3. mutation checks - prove the perturbation test can fail
# --------------------------------------------------------------------------- #
hdr("V2.  MUTATION CHECKS - can the leakage test actually catch a leak?")

say("M1  make L2 read quarter Q's own label as well (the literal 'label as of Q' reading)")
LEAK_STABLE = True
MUT = build(C2, M2).sort_values(["speaker", "quarter"]).reset_index(drop=True)
CLEAN = build(CELL, MOVES).sort_values(["speaker", "quarter"]).reset_index(drop=True)
m_at = int((~((CLEAN.loc[at, "stance_stable_2"].isna() & MUT.loc[at, "stance_stable_2"].isna()) |
              (CLEAN.loc[at, "stance_stable_2"] == MUT.loc[at, "stance_stable_2"]))).sum())
LEAK_STABLE = False
say(f"    stance_stable_2 changes at T under the mutation: {m_at}  "
    f"(clean build: {verdict['stance_stable_2'][1]})")
assert m_at > 0 and verdict["stance_stable_2"][1] == 0, \
    "MUTATION NOT DETECTED - the 'at T' test is vacuous for L2"
say("    DETECTED.  The shipped L2 reads Q-1..Q-K only; the leaky variant does not.")

say("")
say("M2  give L3 a 180-day FORWARD window instead of a backward one")
LEAK_MECH_DAYS = 180
MUT2 = build(C2, M2).sort_values(["speaker", "quarter"]).reset_index(drop=True)
CLEAN2 = build(CELL, MOVES).sort_values(["speaker", "quarter"]).reset_index(drop=True)
m_pre = int((~((CLEAN2.loc[pre, "stance_mech_q5"].isna() & MUT2.loc[pre, "stance_mech_q5"].isna()) |
               (CLEAN2.loc[pre, "stance_mech_q5"] == MUT2.loc[pre, "stance_mech_q5"]))).sum())
LEAK_MECH_DAYS = 0
say(f"    stance_mech_q5 changes BEFORE T under the mutation: {m_pre}  "
    f"(clean build: {verdict['stance_mech_q5'][0]})")
assert m_pre > 0 and verdict["stance_mech_q5"][0] == 0, \
    "MUTATION NOT DETECTED - the 'before T' test is vacuous for L3"
say("    DETECTED.  A forward-looking window shows up as a pre-cutoff change.")

# restore check
FIN = build(CELL, MOVES).sort_values(["speaker", "quarter"]).reset_index(drop=True)
assert FIN[QCOLS].equals(B[QCOLS]), "builder not restored after mutations"
say("")
say("builder restored to the shipped definition after both mutations.")

# --------------------------------------------------------------------------- #
# 4. per-arm property assertions
# --------------------------------------------------------------------------- #
hdr("V3.  PER-ARM PROPERTY ASSERTIONS")
S = SHIP.copy()
S["qs"] = S.quarter.map(pc.qstart)

n = 0
for _, r in S[S.stance_l1.notna()].iterrows():
    assert r.l1_first_evidence.date() < r.qs, f"L1 vintage not before Q start: {r.speaker} {r.quarter}"
    assert r.stance_l1 == r.stance_raw
    n += 1
say(f"L1   : {n} available rows, every one has earliest cited evidence STRICTLY before "
    f"its quarter start, and carries the period's own stance.")

n = 0
for _, r in S[S.stance_l1_strict.notna()].iterrows():
    assert r.l1_last_evidence.date() < r.qs
    n += 1
say(f"L1s  : {n} rows, LATEST cited evidence strictly before quarter start.")
sub = set(zip(S[S.stance_l1_strict.notna()].speaker, S[S.stance_l1_strict.notna()].quarter))
sup = set(zip(S[S.stance_l1.notna()].speaker, S[S.stance_l1.notna()].quarter))
assert sub <= sup, "L1-strict is not a subset of L1"
say(f"       L1-strict is a strict SUBSET of L1 ({len(sub)} of {len(sup)}) - as it must be.")

flat = {k: v["stance"] for k, v in CELL.items()}
for K in (2, 4, 8):
    n = 0
    for _, r in S[S[f"stance_stable_{K}"].notna()].iterrows():
        vals = [flat.get((r.speaker, pc.qshift(r.quarter, k))) for k in range(1, K + 1)]
        assert all(v is not None for v in vals) and len(set(vals)) == 1
        assert r[f"stance_stable_{K}"] == vals[0]
        n += 1
    say(f"L2 K={K}: {n} rows, each equal to a value held unchanged across Q-1..Q-{K}; "
        f"Q's own label never read.")
    a = set(zip(S[S[f"stance_stable_{K}"].notna()].speaker, S[S[f"stance_stable_{K}"].notna()].quarter))
    if K > 2:
        assert a <= prev_set, f"stable_{K} not nested inside stable_{K//2}"
    prev_set = a
say("       nesting stable_8 subset stable_4 subset stable_2 holds.")

byspk = defaultdict(list)
for s, tc, m in MOVES:
    byspk[s].append((tc, m))
for s in byspk:
    byspk[s].sort()
n = 0
for _, r in S[S.stance_mech_q5.notna()].iterrows():
    cut = pd.Timestamp(r.qs).tz_localize(NYTZ)
    prior = [m for tc, m in byspk[r.speaker] if tc < cut]
    assert len(prior) >= 5
    assert r.stance_mech_q5 == float(np.sign(np.mean(prior[-5:])))
    assert max(tc for tc, _ in byspk[r.speaker] if tc < cut) < cut
    n += 1
say(f"L3   : {n} rows for N=5; every input move's +240 bar closed strictly before the "
    f"quarter start.")

EE = pd.read_parquet(f"{OUT}/pit_labels_events.parquet")
n = 0
for _, r in EE[EE.stance_mech_e5.notna()].iterrows():
    prior = [m for tc, m in byspk[r.speaker] if tc < r.t_open]
    assert len(prior) >= 5 and r.stance_mech_e5 == float(np.sign(np.mean(prior[-5:])))
    n += 1
say(f"L3e  : {n} events; every input move's +240 bar closed strictly before THIS event's "
    f"-60 entry bar (no same-day self-reference).")

assert set(S[S.stance_role.notna()].role) <= set(ROLE_PRIOR)
assert S[S.stance_role.notna()].groupby("role").stance_role.nunique().max() == 1
say("L4   : stance_role is a function of role alone (one value per role, no exceptions).")

assert (S[S.stance_highconf.notna()].confidence == "high").all()
say("C3   : every stance_highconf row has confidence == 'high'.")
n = int((S.stance_lag1.notna()).sum())
chk = [flat.get((r.speaker, pc.qprev(r.quarter))) for _, r in S[S.stance_lag1.notna()].iterrows()]
assert all(a == b for a, b in zip(chk, S[S.stance_lag1.notna()].stance_lag1))
say(f"C2   : {n} rows, each exactly the previous quarter's label.")

say("")
say("ALL PROPERTY ASSERTIONS PASS.")

with open(f"{OUT}/_r4_verify.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(REP))
print("\n[written to _r4_verify.txt]")
