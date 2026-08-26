import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import pandas as pd, numpy as np, pyarrow.parquet as pq
from pathlib import Path

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

for f in ["event_paths.parquet", "placebo_paths.parquet"]:
    t = pq.read_schema(HERE / f)
    print("===", f)
    md = t.metadata or {}
    for k, v in md.items():
        if k.startswith(b"pandas"):
            continue
        print("  META", k.decode(), "=", v.decode()[:300])

ev = pd.read_parquet(HERE / "event_paths.parquet")
print("\nshape", ev.shape)
print(ev.dtypes.to_string())
print("\nspeech_ts dtype:", ev["speech_ts"].dtype)
print("bar_label_ts dtype:", ev["bar_label_ts"].dtype)
print(ev.head(3).T.to_string())

e = pd.read_parquet(HERE / "events.parquet")
print("\nevents.parquet cols", list(e.columns))
print("speech_ts dtype", e["speech_ts"].dtype)
print(e[["speech_ts", "clock", "title"]].head(5).to_string())
print("\nclock distribution top 20:")
print(e["clock"].value_counts().head(20).to_string())
