"""Probe 7: do the two headline checks actually have teeth?

A checking tool that is itself wrong reports success and hides the thing it was
built to find. The blackout check and the FOMC-move check are the two results the
whole panel is being certified on, so both are re-run against inputs whose answer
is known IN ADVANCE:

  M1  blackout flag randomly permuted, count preserved  -> ratio must go to ~1.0
  M2  FOMC dates shifted +180 days                      -> both checks must collapse
  M3  speaker/date join broken by shifting events +3d   -> blackout ratio must rise
  M4  extract_speaker on the four known title families  -> exact string answers

If a mutated input still "passes", the check is vacuous and its PASS on the real
data means nothing.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import QuantLib as ql

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def blackout_ratio(p, flag) -> float:
    b, nb = p["n_speakers"][flag], p["n_speakers"][~flag]
    return float(b.mean() / nb.mean())


def fomc_ratio(p, flag) -> float:
    return float(p["abs_d_rate_bp"][flag].median() / p["abs_d_rate_bp"].median())


def build_blackout(meetings, idx) -> np.ndarray:
    s = set()
    for m in meetings:
        q = ql.Date(m.day, m.month, m.year)
        for _ in range(10):
            q = CAL.advance(q, ql.Period(-1, ql.Days), ql.Preceding)
            s.add(dt.date(q.year(), q.month(), q.dayOfMonth()))
    return np.array([d.date() in s for d in idx])


def main() -> None:
    p = pd.read_parquet(OUT / "panel_daily.parquet")
    p.index = pd.to_datetime(p.index)
    idx = p.index

    from fomc_extras import fomc_decision_dates
    from global_hawk_dove_common import _PRE2023_DECISIONS
    meetings = sorted(set(fomc_decision_dates()) | set(_PRE2023_DECISIONS["FED"]))

    real_bo = p["is_blackout"].to_numpy()
    r0 = blackout_ratio(p, real_bo)
    f0 = fomc_ratio(p, p["is_fomc_day"].to_numpy())
    print(f"REAL DATA   blackout ratio {r0:.3f}   FOMC |move| ratio {f0:.2f}x")
    print("            (a ratio near 1.0 means the flag carries no information)\n")

    print("--- M1: blackout flag randomly permuted, count preserved ---")
    rng = np.random.default_rng(0)
    rs = []
    for _ in range(200):
        rs.append(blackout_ratio(p, rng.permutation(real_bo)))
    print(f"  permuted ratio: mean {np.mean(rs):.3f}  "
          f"2.5-97.5pct [{np.percentile(rs, 2.5):.3f}, {np.percentile(rs, 97.5):.3f}]")
    m1 = r0 < np.percentile(rs, 2.5)
    print(f"  real {r0:.3f} sits BELOW the permuted 2.5th pct? {m1}  "
          f"-> {'the check has teeth' if m1 else 'VACUOUS'}\n")

    print("--- M2: FOMC dates shifted +180 days ---")
    sh = [m + dt.timedelta(days=180) for m in meetings]
    bo_sh = build_blackout(sh, idx)
    fo_sh = np.array([d.date() in set(sh) for d in idx])
    r2, f2 = blackout_ratio(p, bo_sh), fomc_ratio(p, fo_sh) if fo_sh.sum() else np.nan
    print(f"  blackout ratio {r2:.3f} (real {r0:.3f})   "
          f"FOMC |move| ratio {f2:.2f}x (real {f0:.2f}x), n_fomc={int(fo_sh.sum())}")
    m2 = r2 > r0 * 1.3 and (np.isnan(f2) or f2 < f0 * 0.8)
    print(f"  both collapse toward no-signal? {m2}  "
          f"-> {'the checks track the real calendar' if m2 else 'INVESTIGATE'}\n")

    print("--- M3: events shifted +3 business days (a broken date join) ---")
    fed = pd.read_parquet(OUT / "fed_calendar_raw.parquet")
    fed["Date"] = pd.to_datetime(fed["Date"])
    shifted = fed["Date"] + pd.offsets.BDay(3)
    n_sh = shifted.dt.normalize().value_counts().reindex(idx).fillna(0)
    q = p.copy()
    q["n_speakers"] = n_sh.to_numpy()
    r3 = blackout_ratio(q, real_bo)
    print(f"  blackout ratio with a +3bd-misaligned join: {r3:.3f} (real {r0:.3f})")
    m3 = r3 > r0 * 1.2
    print(f"  misalignment degrades the separation? {m3}  "
          f"-> {'the check is sensitive to date alignment' if m3 else 'INVESTIGATE'}\n")

    print("--- M4: extract_speaker known answers ---")
    strip = re.compile(r"\b(Speaks?|Testifies|Testimony)\b")

    def ex(t):
        return (strip.sub("", t or "").strip().split() or [""])[-1]

    cases = [("FOMC Member Cook Speaks", "Cook"),
             ("Fed Chair Powell Speaks", "Powell"),
             ("Fed Chairman Powell Testifies", "Powell"),
             ("Fed Chair Yellen Testimony", "Yellen"),
             ("FOMC Member Williams Speaks", "Williams")]
    m4 = True
    for t, want in cases:
        got = ex(t)
        ok = got == want
        m4 &= ok
        print(f"  {'OK ' if ok else 'FAIL'}  {t!r} -> {got!r} (want {want!r})")

    print("\n--- M5: the Chair regex must catch 'Chairman', not just 'Chair' ---")
    naive = re.compile(r"\bChair\b", re.I)
    fixed = re.compile(r"\bChair(?:man|woman|person)?\b", re.I)
    t = fed["Title"].astype(str)
    n_naive = int(t.str.contains(naive).sum())
    n_fixed = int(t.str.contains(fixed).sum())
    print(f"  naive r'\\bChair\\b' matches {n_naive};  "
          f"fixed r'\\bChair(?:man)?\\b' matches {n_fixed}")
    m5 = n_fixed > n_naive
    print(f"  the fixed regex catches {n_fixed - n_naive} more (the 'Fed Chairman' "
          f"form) -> {'the fix was necessary' if m5 else 'no difference'}")

    print("\n" + "=" * 60)
    allok = m1 and m2 and m3 and m4
    print(f"MUTATION SUITE: {'ALL CHECKS HAVE TEETH' if allok else 'SOMETHING IS VACUOUS'}")
    print(f"  M1 permuted-blackout {m1}   M2 shifted-FOMC {m2}   "
          f"M3 misaligned-join {m3}   M4 speaker-extract {m4}")


if __name__ == "__main__":
    main()
