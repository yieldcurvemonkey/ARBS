"""Is the configurable backtest's +0.86 bp/trade real, or is it the hindsight in the labels?

The manual quarterly labels (FED_SPEAKER_QUARTERLY_LABELS.md) say of themselves:
  "These labels are not point-in-time. They were assigned in 2026 from commentary covering the
   whole period ... an *upper bound* ... not a tradeable strategy."

DECISIVE TEST, on the SAME price data (my event panel, which carries 2022 unlike the JPM-scored
subset): trade the quarter's OWN label (hindsight, = what the backtest does) versus the PREVIOUS
quarter's label (knowable at the time, = what a desk reassessing the committee each quarter would
actually have had). Same events, same window, same bars. The gap between them IS the hindsight.
"""
import json

import numpy as np
import pandas as pd

ES = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
BT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"

lab = json.load(open(f"{BT}/fed_quarterly_labels.json"))


def qseq(a, b):
    """every 'YYYYQn' from a to b inclusive"""
    y, n = int(a[:4]), int(a[-1])
    Y, N = int(b[:4]), int(b[-1])
    out = []
    while (y, n) <= (Y, N):
        out.append(f"{y}Q{n}")
        n += 1
        if n == 5:
            y, n = y + 1, 1
    return out


# speakers -> {name: {full_name, role, periods:[{start_q,end_q,stance,...}]}}
flat = {}
for name, rec in lab["speakers"].items():
    for per in rec.get("periods", []):
        for q in qseq(per["start_q"], per["end_q"]):
            flat[(str(name), q)] = per["stance"]
print(f"speakers: {len(lab['speakers'])}   speaker-quarter labels: {len(flat)}")
print(f"sample: {list(flat.items())[:4]}")


def qkey(ts):
    ts = pd.Timestamp(ts)
    return f"{ts.year}Q{(ts.month - 1)//3 + 1}"


def qprev(q):
    y, n = int(q[:4]), int(q[-1])
    return f"{y-1}Q4" if n == 1 else f"{y}Q{n-1}"


def to_num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    return {"HH": 2.0, "H": 1.0, "·": 0.0, ".": 0.0, "": np.nan,
            "D": -1.0, "DD": -2.0}.get(s, np.nan)


p = pd.read_parquet(f"{ES}/event_paths.parquet")
p = p[p.contract_rank == 3]
wide = p.pivot_table(index=["event_id", "speech_ts", "speaker"],
                     columns="offset_min", values="rate_bp").reset_index()
need = [c for c in (-60, 240) if c in wide.columns]
if len(need) < 2:
    raise SystemExit(f"missing offsets, have {sorted([c for c in wide.columns if isinstance(c,(int,float))])[:30]}")
wide["move_bp"] = wide[240] - wide[-60]
wide = wide.dropna(subset=["move_bp"])
wide["q"] = wide.speech_ts.map(qkey)
wide["qprev"] = wide.q.map(qprev)
wide["lab_now"] = [to_num(flat.get((s, q))) for s, q in zip(wide.speaker, wide.q)]
wide["lab_lag"] = [to_num(flat.get((s, q))) for s, q in zip(wide.speaker, wide.qprev)]
wide["year"] = wide.speech_ts.dt.year

print(f"\nevents with a rank-3 -60->+240 move: {len(wide)}  "
      f"{wide.speech_ts.min().date()} -> {wide.speech_ts.max().date()}")


def book(df, col, name, minabs=1):
    d = df[df[col].notna() & (df[col].abs() >= minabs)].copy()
    d["pnl_bp"] = np.sign(d[col]) * d["move_bp"]
    if len(d) < 20:
        return {"book": name, "trades": len(d)}
    day = d.groupby(d.speech_ts.dt.date)["pnl_bp"].mean()
    return {"book": name, "trades": len(d), "avg_bp": round(d.pnl_bp.mean(), 4),
            "hit": round((d.pnl_bp > 0).mean(), 4),
            "t_naive": round(d.pnl_bp.mean() / (d.pnl_bp.std(ddof=1) / np.sqrt(len(d))), 3),
            "t_byday": round(day.mean() / (day.std(ddof=1) / np.sqrt(len(day))), 3),
            "n_days": len(day)}


rows = [
    book(wide, "lab_now", "HINDSIGHT  quarter's own label  (= the backtest)"),
    book(wide, "lab_lag", "REAL-TIME  previous quarter's label"),
    book(wide, "lab_now", "  hindsight, conviction |2|", minabs=2),
    book(wide, "lab_lag", "  real-time, conviction |2|", minabs=2),
]
print("\n" + "=" * 78)
print(pd.DataFrame(rows).set_index("book").to_string())

# where does the hindsight book earn it?
print("\n" + "=" * 78)
print("BY YEAR (avg bp/trade)")
yr = []
for y, g in wide.groupby("year"):
    a = book(g, "lab_now", "now")
    b = book(g, "lab_lag", "lag")
    yr.append({"year": y, "n_now": a.get("trades"), "avg_now": a.get("avg_bp"),
               "n_lag": b.get("trades"), "avg_lag": b.get("avg_bp")})
print(pd.DataFrame(yr).set_index("year").to_string())

# how often does the label actually CHANGE quarter to quarter? that is where hindsight lives
chg = wide.dropna(subset=["lab_now", "lab_lag"])
same = (chg.lab_now == chg.lab_lag)
print(f"\nevents where the label is UNCHANGED from the prior quarter: "
      f"{same.mean():.1%} ({same.sum()}/{len(chg)})")
if (~same).sum() > 20:
    print("  on CHANGED-label events only:")
    print("   ", book(chg[~same], "lab_now", "hindsight"))
    print("   ", book(chg[~same], "lab_lag", "real-time"))
