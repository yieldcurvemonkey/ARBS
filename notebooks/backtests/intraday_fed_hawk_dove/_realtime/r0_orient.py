"""Orientation: panel schema, label JSON shape, and what date strings live in `why`."""
import json
import re
import sys
from collections import Counter

import pandas as pd

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

BT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
ES = BT + r"\_event_study"

p = pd.read_parquet(f"{ES}/event_paths.parquet")
print("PANEL", p.shape)
print(p.dtypes.to_string())
print("\noffsets:", sorted(p.offset_min.unique().tolist()))
print("ranks:", sorted(p.contract_rank.dropna().unique().tolist()))
print("\nhead:\n", p.head(3).to_string())
print("\nn events:", p.event_id.nunique(), " n speakers:", p.speaker.nunique())
print("speakers:", sorted(p.speaker.unique().tolist()))
print("\nspan:", p.speech_ts.min(), "->", p.speech_ts.max())
print("is_voter dtype/vals:", p.is_voter.dtype, p.is_voter.value_counts(dropna=False).to_dict())

lab = json.load(open(f"{BT}/fed_quarterly_labels.json"))
print("\n\nLABELS: speakers", len(lab["speakers"]))
print("notes:", json.dumps(lab.get("notes", []), indent=1)[:3000])
k0 = list(lab["speakers"])[0]
print("\nspeaker rec keys:", list(lab["speakers"][k0].keys()))
print("period keys:", list(lab["speakers"][k0]["periods"][0].keys()))

roles = Counter(r.get("role") for r in lab["speakers"].values())
print("\nROLE field values:")
for k, v in roles.most_common():
    print(f"  {v:3d}  {k}")

conf = Counter()
nper = 0
stances = Counter()
for name, rec in lab["speakers"].items():
    for per in rec["periods"]:
        nper += 1
        conf[per.get("confidence")] += 1
        stances[per.get("stance")] += 1
print(f"\nperiods: {nper}  confidence: {dict(conf)}  stance: {dict(sorted(stances.items(), key=lambda x: str(x[0])))}")

# What date-ish tokens appear in `why`?
MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
pats = {
    "D Mon YYYY": rf"\b\d{{1,2}} {MON}[a-z]* \d{{4}}\b",
    "Mon-YYYY": rf"\b{MON}[a-z]*-\d{{4}}\b",
    "Mon YYYY": rf"\b{MON}[a-z]* \d{{4}}\b",
    "Mon/Mon/Mon YYYY": rf"\b{MON}(?:/{MON})+ \d{{4}}\b",
    "QTR": r"\b20\d{2}Q[1-4]\b",
    "bare year": r"\b(?:19|20)\d{2}\b",
}
hits = Counter()
examples = {k: [] for k in pats}
nwhy = 0
no_date = []
for name, rec in lab["speakers"].items():
    for per in rec["periods"]:
        w = per.get("why", "") or ""
        nwhy += 1
        found = False
        for k, pat in pats.items():
            m = re.findall(pat, w)
            if m:
                hits[k] += len(m)
                found = True
                if len(examples[k]) < 12:
                    examples[k].extend(m[:3])
        if not found:
            no_date.append((name, per["start_q"], per["end_q"]))
print(f"\nwhy blocks: {nwhy}   with NO date token at all: {len(no_date)}")
for k in pats:
    print(f"  {k:18s} {hits[k]:4d}   e.g. {examples[k][:8]}")
print("\nno-date periods:", no_date[:20])

# any odd formats: scan for other numeric-date shapes
odd = Counter()
for name, rec in lab["speakers"].items():
    for per in rec["periods"]:
        w = per.get("why", "") or ""
        for m in re.findall(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", w):
            odd[m] += 1
print("\nnumeric-slash dates:", dict(odd))
