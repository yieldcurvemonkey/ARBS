"""Follow-ups on stage 1: where the two score CSVs disagree, and the publication lag."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import numpy as np
import pandas as pd

import global_hawk_dove_common as G

GLOB = r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\global_hawk_dove_scores.csv"
FED = r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv"
M = "trailing_5_avg"

s = G.load_global_scores(GLOB, M)
f = s[s["central_bank"] == "FED"].copy()
lag = np.array([(a - b).days for a, b in zip(f["pub_date"], f["date"])])
print(f"FED score rows: {len(f)}")
print(f"published AFTER the speech: {(lag>0).mean():.1%}")
print(f"median lag over ALL rows            : {np.median(lag):.0f} d")
print(f"median lag over LATE rows only      : {np.median(lag[lag>0]):.0f} d")
print(f"lag percentiles (late only) 25/50/75/90: "
      f"{np.percentile(lag[lag>0], [25,50,75,90]).round(0)}")
print(f"rows with pub_date == date (no parseable pub, treated as same-day): "
      f"{(lag==0).sum()}")

fo = pd.read_csv(FED)
fo["date"] = pd.to_datetime(fo["date"]).dt.date
m = f.merge(fo[["date", "speaker", M, "hawk_dove_score"]], on=["date", "speaker"],
            suffixes=("_glob", "_fed"))
bad = m[~np.isclose(m[f"{M}_glob"].astype(float), m[f"{M}_fed"].astype(float),
                    equal_nan=True)]
print(f"\nshared (speaker,date) rows: {len(m)}; disagreeing on {M}: {len(bad)}")
if len(bad):
    print(bad[["date", "speaker", f"{M}_glob", f"{M}_fed",
               "hawk_dove_score_glob", "hawk_dove_score_fed"]].to_string(index=False))
    print("\nwould the disagreement change the SIGN of the stance?")
    sg = np.sign(bad[f"{M}_glob"].astype(float))
    sf = np.sign(bad[f"{M}_fed"].astype(float))
    print(f"  sign differs on {int((sg != sf).sum())} of {len(bad)} rows")

ev = pd.read_parquet(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
                     r"\_event_study\events.parquet")
print("\nthe one speech on an FOMC decision day:")
print(ev[ev["is_fomc_day"]][["date", "speech_ts", "speaker", "title",
                             "stance_score_exante", "stance_sign"]].to_string(index=False))
print("\nweekend speeches (no bars will serve):")
wk = ev[ev["speech_ts"].apply(lambda t: pd.Timestamp(t).weekday()) >= 5]
print(f"  n = {len(wk)}")
print(wk[["date", "speech_ts", "speaker"]].head(10).to_string(index=False))
print("\nspeech-hour distribution (NY):")
print(ev["speech_ts"].apply(lambda t: pd.Timestamp(t).hour).value_counts().sort_index().to_string())
