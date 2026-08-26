"""Exhaustive census of date-like tokens in the `why` corpus, so the L1 parser cannot
silently miss a format. Strategy: strip out every token the parser WILL handle, then
show what month-name / year-bearing text is left over."""
import json
import re
from collections import Counter

BT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"
lab = json.load(open(f"{BT}/fed_quarterly_labels.json"))

whys = []
for name, rec in lab["speakers"].items():
    for per in rec["periods"]:
        whys.append((name, per["start_q"], per["end_q"], per.get("why", "") or ""))
corpus = "\n".join(w for _, _, _, w in whys)
print(f"{len(whys)} why blocks, {len(corpus)} chars")

MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"

# Known formats we intend to parse
KNOWN = [
    (rf"\b\d{{1,2}}\s+{MON}\s+\d{{4}}\b", "D Mon YYYY"),
    (rf"\b{MON}\s+\d{{1,2}},\s*\d{{4}}\b", "Mon D, YYYY  (US style)"),
    (rf"\b{MON}(?:\s*/\s*{MON})+[\s-]\d{{4}}\b", "Mon/Mon/Mon YYYY"),
    (rf"\b\d{{1,2}}\s*/\s*\d{{1,2}}\s+{MON}\s+\d{{4}}\b", "D/D Mon YYYY"),
    (rf"\b{MON}[-\s]\d{{4}}\b", "Mon YYYY / Mon-YYYY"),
]
work = corpus
for pat, nm in KNOWN:
    found = re.findall(pat, work)
    print(f"  {nm:26s} {len(found):4d}  e.g. {sorted(set(found))[:6]}")
    work = re.sub(pat, " <<PARSED>> ", work)

# also strip grid self-references and bare years (deliberately EXCLUDED, not unparsed)
q = re.findall(r"\b20\d{2}Q[1-4]\b", work)
work = re.sub(r"\b20\d{2}Q[1-4]\b", " <<QTR>> ", work)
print(f"  {'YYYYQn (excluded)':26s} {len(q):4d}  e.g. {sorted(set(q))[:6]}")

# What month-name text survives?  (i.e. a month name NOT part of a parsed token)
left_mon = re.findall(rf".{{0,40}}\b{MON}\b.{{0,40}}", work)
print(f"\nLEFTOVER month-name contexts: {len(left_mon)}")
c = Counter()
for s in left_mon:
    c[re.sub(r"\s+", " ", s.strip())] += 1
for s, n in c.most_common(60):
    print(f"   {n:2d}  ...{s}...")

# What bare years survive?
left_yr = re.findall(r"\b(?:19|20)\d{2}\b", work)
print(f"\nLEFTOVER bare years (excluded by design): {len(left_yr)}  {Counter(left_yr).most_common(10)}")

# any other numeric date shape at all
print("\nnumeric dd/mm/yy shapes:", Counter(re.findall(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b", work)))
print("ISO shapes:", Counter(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", work)))
