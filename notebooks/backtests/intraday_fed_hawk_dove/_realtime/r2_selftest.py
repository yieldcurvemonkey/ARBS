"""Known-answer test for the L1 date parser and the quarter helpers.

Run BEFORE the build.  Every case here has an answer I wrote down first; the last
block deliberately mutates the parser to confirm the test can actually fail.
"""
import datetime as _dt
import re
import sys

sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_realtime")

import pit_common as pc

D = _dt.date
fails = []


def chk(name, got, want):
    ok = got == want
    if not ok:
        fails.append((name, got, want))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}\n        got  {got}\n        want {want}")


print("=" * 78)
print("A. the six formats the task names")
# every one of these appears verbatim in the corpus
chk("14 Dec 2022", pc.parse_evidence_dates("Reuters' grid updated 14 Dec 2022 filed him")[0],
    [D(2022, 12, 14)])
chk("19 Mar 2025", pc.parse_evidence_dates("his omitted 19 Mar 2025 dissent")[0],
    [D(2025, 3, 19)])
chk("30 Jul 2025", pc.parse_evidence_dates("dissented alongside Waller on 30 Jul 2025")[0],
    [D(2025, 7, 30)])
chk("Aug-2022 -> month END", pc.parse_evidence_dates("plus the Aug-2022 Jackson Hole speech")[0],
    [D(2022, 8, 31)])
chk("2 Aug 2021", pc.parse_evidence_dates("on 2 Aug 2021 he said")[0], [D(2021, 8, 2)])
chk("Sep/Oct/Dec 2025 -> 3 month-ends",
    pc.parse_evidence_dates("delivered the Sep/Oct/Dec 2025 cuts")[0],
    [D(2025, 9, 30), D(2025, 10, 31), D(2025, 12, 31)])

print("\nB. full month names and mixed text")
chk("April 2024", pc.parse_evidence_dates("in April 2024 she said")[0], [D(2024, 4, 30)])
chk("September 2019", pc.parse_evidence_dates("the September 2019 meeting")[0], [D(2019, 9, 30)])
chk("Sept-2023", pc.parse_evidence_dates("Vice Chair from Sept-2023")[0], [D(2023, 9, 30)])
chk("day beats month on the same token (14 Dec 2022 read ONCE)",
    pc.parse_evidence_dates("14 Dec 2022")[0], [D(2022, 12, 14)])

print("\nC. deliberate EXCLUSIONS (must contribute no date)")
chk("bare year excluded", pc.parse_evidence_dates("the 2019 cuts and 2022 hikes")[0], [])
chk("grid self-reference excluded", pc.parse_evidence_dates("CORRECTED for 2026Q2")[0], [])
chk("rate range not a date", pc.parse_evidence_dates("held at 4.25-4.50% and 0-0.25%")[0], [])
chk("no date at all", pc.parse_evidence_dates("She voted with the majority throughout.")[0], [])

print("\nD. UNRESOLVED month-token counter (year only implied -> counted, not used)")
chk("'27 Jul, 21 Sep, 2 Nov, 14 Dec 2022' -> 1 date + 3 unresolved",
    pc.parse_evidence_dates("unanimous on 27 Jul, 21 Sep, 2 Nov, 14 Dec 2022"),
    ([D(2022, 12, 14)], 3))
chk("'the September dots' -> 0 dates, 1 unresolved",
    pc.parse_evidence_dates("exceed the September dots"), ([], 1))
chk("'15-16 Mar' bare -> 0 dates, 1 unresolved",
    pc.parse_evidence_dates("dissented on 15-16 Mar for 50bp"), ([], 1))
chk("excluded tokens do NOT count as unresolved months",
    pc.parse_evidence_dates("the 2019 cuts; CORRECTED for 2026Q2"), ([], 0))

print("\nE. multiple dates -> min is the vintage, max is the strict bound")
ds, nu = pc.parse_evidence_dates(
    "on 11 May 2021 'Patience', 30 Jul 2021 remarks and the 27 Sep 2021 Delta speech")
chk("three dates parsed", ds, [D(2021, 5, 11), D(2021, 7, 30), D(2021, 9, 27)])
chk("min", min(ds), D(2021, 5, 11))
chk("max", max(ds), D(2021, 9, 27))

print("\nF. quarter helpers")
chk("qseq", pc.qseq("2022Q3", "2023Q2"), ["2022Q3", "2022Q4", "2023Q1", "2023Q2"])
chk("qstart 2023Q1", pc.qstart("2023Q1"), D(2023, 1, 1))
chk("qstart 2025Q4", pc.qstart("2025Q4"), D(2025, 10, 1))
chk("qend 2024Q2", pc.qend_date("2024Q2"), D(2024, 6, 30))
chk("qprev 2023Q1", pc.qprev("2023Q1"), "2022Q4")
chk("qshift 8", pc.qshift("2024Q1", 8), "2022Q1")
chk("to_num HH/D/dot", [pc.to_num(x) for x in ("HH", "D", "·", None)], [2.0, -1.0, 0.0, None] and
    [2.0, -1.0, 0.0, pc.to_num(None)])

print("\nG. the STRICTNESS boundary: 'predates Q start' must be STRICT")
# a label whose only evidence is 1 Jan 2023 must NOT be available in 2023Q1
ev = pc.parse_evidence_dates("said on 1 Jan 2023 that")[0]
chk("1 Jan 2023 vintage", ev, [D(2023, 1, 1)])
chk("NOT available in 2023Q1 (strict <)", min(ev) < pc.qstart("2023Q1"), False)
chk("available in 2023Q2", min(ev) < pc.qstart("2023Q2"), True)
# month-end resolution is what stops 'Aug 2022' manufacturing availability in 2022Q3
ev2 = pc.parse_evidence_dates("the Aug 2022 Jackson Hole speech")[0]
chk("Aug 2022 NOT available in 2022Q3 (month-END rule)", min(ev2) < pc.qstart("2022Q3"), False)
chk("  ... and IS available in 2022Q4", min(ev2) < pc.qstart("2022Q4"), True)

print("\n" + "=" * 78)
print("H. WHAT THE MONTH-END RULE DOES AND DOES NOT BUY  (a null result, stated)")
# A quarter start is ALWAYS the 1st of a month.  So for a month-precision token,
# month_start < qstart  <=>  month_end < qstart : the resolution choice cannot
# change AVAILABILITY at any quarter boundary.  Demonstrate it rather than claim it.
_orig = pc._month_end
pc._month_end = lambda y, m: _dt.date(y, m, 1)
flipped = []
for yy in range(2019, 2027):
    for mm in range(1, 13):
        for qq in [f"{y2}Q{n2}" for y2 in range(2019, 2027) for n2 in (1, 2, 3, 4)]:
            a = _dt.date(yy, mm, 1) < pc.qstart(qq)
            b = _orig(yy, mm) < pc.qstart(qq)
            if a != b:
                flipped.append((yy, mm, qq))
pc._month_end = _orig
print(f"  month-start vs month-end disagree on availability in {len(flipped)} of "
      f"{12*8*32} (month x quarter) pairs")
chk("month-end rule changes NO availability decision (quarter starts are month starts)",
    len(flipped), 0)
assert pc.parse_evidence_dates("Aug 2022")[0] == [D(2022, 8, 31)], "restore failed"

print("\nI. MUTATION CHECKS on the predicates that ARE load-bearing")


def _avail(why, q, strict=True):
    ds, _ = pc.parse_evidence_dates(why)
    if not ds:
        return False
    return (min(ds) < pc.qstart(q)) if strict else (min(ds) <= pc.qstart(q))


# I.1 the STRICT '<'.  Non-strict would hand you a label on the day it was learned.
print(f"  strict   : '1 Jan 2023' available in 2023Q1 -> {_avail('on 1 Jan 2023', '2023Q1', True)}")
print(f"  MUTATED  : with '<=' instead            -> {_avail('on 1 Jan 2023', '2023Q1', False)}")
chk("strict '<' is load-bearing (mutation flips the answer)",
    _avail("on 1 Jan 2023", "2023Q1", True) != _avail("on 1 Jan 2023", "2023Q1", False), True)

# I.2 the bare-year EXCLUSION.  Including bare years as 1 Jan would create availability.
_bare = re.compile(r"\b((?:19|20)\d{2})\b")


def _avail_with_bare_years(why, q):
    ds, _ = pc.parse_evidence_dates(why)
    ds = list(ds) + [_dt.date(int(y), 1, 1) for y in _bare.findall(why)]
    return bool(ds) and min(ds) < pc.qstart(q)


w = "Through 2022 she was hawkish; Reuters' 14 Dec 2022 grid placed her in the HAWKISH bucket."
print(f"  excluded : bare years off, available in 2022Q3 -> {_avail(w, '2022Q3')}")
print(f"  MUTATED  : bare years on                       -> {_avail_with_bare_years(w, '2022Q3')}")
chk("bare-year exclusion is load-bearing (mutation flips the answer)",
    _avail(w, "2022Q3") != _avail_with_bare_years(w, "2022Q3"), True)

# I.3 day-precision parsing itself
_savedeeper = pc._PATTERNS
pc._PATTERNS = [p for p in pc._PATTERNS if p[0] != "day"]
got_mut = pc.parse_evidence_dates("Reuters' grid updated 14 Dec 2022 filed him")[0]
pc._PATTERNS = _savedeeper
got_ok = pc.parse_evidence_dates("Reuters' grid updated 14 Dec 2022 filed him")[0]
print(f"  MUTATED  : day pattern removed -> {got_mut}   (restored -> {got_ok})")
chk("removing the day pattern degrades 14 Dec 2022 to a month-end", got_mut, [D(2022, 12, 31)])
chk("parser restored after mutation", got_ok, [D(2022, 12, 14)])

print("\n" + "=" * 78)
if fails:
    print(f"{len(fails)} FAILURES:")
    for f in fails:
        print("  ", f)
    raise SystemExit(1)
print("ALL KNOWN-ANSWER CASES PASS")
