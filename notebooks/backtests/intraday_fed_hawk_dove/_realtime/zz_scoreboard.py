"""Score every stance construction. Does a genuinely point-in-time label still pay?

Trade = sign(stance) * (rate_bp[+240] - rate_bp[-60]) on SR3 rank 3.
t is DAY-CLUSTERED throughout (several speakers share a day).
Costs: SR3 ticks in 0.5bp; a round trip is ~one crossing. Quote 0.0 / 0.25 / 0.5.
"""
import numpy as np
import pandas as pd

OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_realtime"
E = pd.read_parquet(f"{OUT}/pit_labels_events.parquet")
E["speech_ts"] = pd.to_datetime(E["speech_ts"], utc=True).dt.tz_convert("America/New_York")
E["day"] = E.speech_ts.dt.date
E["q"] = E.speech_ts.dt.to_period("Q")

# structurally index-causal (a corruption test proved it), vs provenance-only, vs not PIT
ARMS = [
    ("stance_stable_2", "L2 stability >=2q", "PIT"),
    ("stance_stable_4", "L2 stability >=4q", "PIT"),
    ("stance_stable_8", "L2 stability >=8q", "PIT"),
    ("stance_mech_e5", "L3 mechanical, own last 5", "PIT"),
    ("stance_mech_e10", "L3 mechanical, own last 10", "PIT"),
    ("stance_lag1", "C2 previous quarter", "PIT"),
    ("stance_role", "L4 ROLE ONLY (floor)", "PIT"),
    ("stance_l1", "L1 evidence vintage", "provenance"),
    ("stance_l1_strict", "L1 strict", "provenance"),
    ("stance_asof", "C1 quarter's own (UPPER BOUND)", "hindsight"),
    ("stance_highconf", "C3 high-confidence only", "hindsight"),
]


def clustered_t(pnl, groups):
    x = np.asarray(pnl, float)
    n, mu = len(x), x.mean()
    g = pd.Series(x).groupby(np.asarray(groups))
    G = g.ngroups
    ssc = float(((g.sum() - g.size() * mu) ** 2).sum())
    var = (G / max(G - 1, 1)) * ssc / n ** 2
    return mu / np.sqrt(var) if var > 0 else np.nan


def book(df, col, minabs=1, cost=0.0):
    d = df[df[col].notna() & (df[col].abs() >= minabs)]
    if len(d) < 20:
        return None
    pnl = np.sign(d[col]).astype(float) * d["move_bp"].astype(float) - cost
    return {"n": len(d), "bp": pnl.mean(), "hit": (pnl > 0).mean(),
            "t": clustered_t(pnl, d["day"].values), "days": d["day"].nunique()}


def fmt(r):
    return "     -" if r is None else f"{r['bp']:+6.3f}"


def ft(r):
    return "    -" if r is None else f"{r['t']:5.2f}"


qmax = E.q.max()
last4 = E[E.q > qmax - 4]
era1 = E[E.speech_ts.dt.year <= 2023]
era2 = E[E.speech_ts.dt.year >= 2024]

print("=" * 108)
print("SCOREBOARD — bp/trade (day-clustered t).  VOTERS-ONLY cut, which is where the edge lives.")
print("=" * 108)
print(f"{'construction':<34}{'kind':<12}{'n':>5}{'gross':>8}{'t':>7}{'@0.25':>8}{'@0.50':>8}"
      f"{'hit':>7}{'22-23':>8}{'24-26':>8}{'last4q':>8}")
print("-" * 108)
rows = []
for col, name, kind in ARMS:
    v = E[E.is_voter == True]
    r = book(v, col)
    if r is None:
        print(f"{name:<34}{kind:<12}{'--- insufficient n ---':>60}")
        continue
    r25 = book(v, col, cost=0.25)
    r50 = book(v, col, cost=0.50)
    e1 = book(era1[era1.is_voter == True], col)
    e2 = book(era2[era2.is_voter == True], col)
    l4 = book(last4[last4.is_voter == True], col)
    print(f"{name:<34}{kind:<12}{r['n']:>5}{r['bp']:>+8.3f}{r['t']:>7.2f}"
          f"{fmt(r25):>8}{fmt(r50):>8}{r['hit']:>7.1%}{fmt(e1):>8}{fmt(e2):>8}{fmt(l4):>8}")
    rows.append({"construction": name, "kind": kind, "n": r["n"], "gross_bp": round(r["bp"], 4),
                 "t": round(r["t"], 3), "net_025": round(r25["bp"], 4), "net_050": round(r50["bp"], 4),
                 "hit": round(r["hit"], 4),
                 "bp_2022_23": None if e1 is None else round(e1["bp"], 4),
                 "bp_2024_26": None if e2 is None else round(e2["bp"], 4),
                 "n_2024_26": None if e2 is None else e2["n"],
                 "t_2024_26": None if e2 is None else round(e2["t"], 3),
                 "bp_last4q": None if l4 is None else round(l4["bp"], 4),
                 "n_last4q": None if l4 is None else l4["n"]})

pd.DataFrame(rows).to_csv(f"{OUT}/scoreboard.csv", index=False)

print()
print("=" * 108)
print("THE FLOOR TEST — is 'stance' worth anything over just knowing WHO is speaking?")
print("=" * 108)
fl = book(E[E.is_voter == True], "stance_role")
print(f"L4 role-only (voters)            : {fl['bp']:+.3f} bp  t {fl['t']:.2f}  n {fl['n']}")
for col, name, kind in ARMS:
    if col == "stance_role":
        continue
    r = book(E[E.is_voter == True], col)
    if r:
        print(f"  {name:<32} {r['bp']:+.3f}   increment over floor {r['bp']-fl['bp']:+.3f} bp")

print()
print("=" * 108)
print(f"LAST 4 QUARTERS ({(qmax-3)} .. {qmax}) — the decision-relevant window")
print("=" * 108)
for col, name, kind in ARMS:
    r = book(last4[last4.is_voter == True], col)
    if r:
        print(f"{name:<34}{kind:<12} n {r['n']:>4}  gross {r['bp']:+.3f}  "
              f"net@0.5 {r['bp']-0.5:+.3f}  t {r['t']:5.2f}")

print()
print("=" * 108)
print("CONVICTION |2| ONLY, voters — the notebook's strongest cut")
print("=" * 108)
for col, name, kind in ARMS:
    r = book(E[E.is_voter == True], col, minabs=2)
    if r:
        r50 = book(E[E.is_voter == True], col, minabs=2, cost=0.5)
        print(f"{name:<34}{kind:<12} n {r['n']:>4}  gross {r['bp']:+.3f}  t {r['t']:5.2f}  "
              f"net@0.5 {r50['bp']:+.3f}")
print()
print(f"wrote {OUT}\\scoreboard.csv")
