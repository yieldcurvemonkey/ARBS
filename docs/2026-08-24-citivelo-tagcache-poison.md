# Swaption vol under the OIS par tags: a merged Excel region

**Status: root cause found, demonstrated and fixed; data repaired and validated.**
Branch `fix/citivelo-tagcache-poison`.

## The defect

`CitiVeloTagCache` served swaption normal volatility under the OIS par-rate tags.
`RATES.OIS.USD_SOFR.PAR.2Y` returned ~102 on a day the 2y SOFR OIS was 4.2361%.

Three families were affected, not one:

| family | rows | poisoned | first | last |
|---|---:|---:|---|---|
| `RATES.OIS.USD_SOFR.PAR` (36 of 44 tags) | 187,383 | 93,600 (50.0%) | 2015-10-08 | 2026-07-29 |
| `RATES.OIS.CAD_CORRA.PAR` (44 of 44) | 167,876 | 41,228 (24.6%) | 2015-10-08 | 2019-07-16 |
| `RATES.OIS.JPY_TONAR_LCH.PAR` (44 of 44) | 62,611 | 31,591 (50.5%) | 2015-10-08 | 2019-07-16 |

2015-10-08 is the USD swaption tags' own first day, in every family. The `MI01`
and `HOURLY` copies of these OIS tags are clean — but `MI01` is **not** clean in
general: 57 bond PRICE/YIELD tags carry the same vol and are covered below.

It survived because the poisoned days are **interleaved** with good ones — the
cache merges rather than replaces — so the series still plotted as a plausible
line and only ever failed a value check, never a shape check.

## The mechanism

Measured, and reproduced offline in
`tests/test_citivelo_tagcache_poison.py`.

1. **`_write_and_read` left the sheet cursor inside a live spill.** It reserves
   `rows_needed + gap` = 8 + 30 = 38 rows per anchor and then corrects the cursor
   from the block's real extent, `_advance_past(_extent(anchor))`. Both early
   returns — a poll timeout and an Excel error int — returned **before** that
   correction. A `CVTSHIST` that timed out therefore left the cursor 38 rows
   below a formula that goes on to spill 2,700–5,500 rows.

2. **The next formula was planted inside that block**, so `_extent` handed back
   ONE region holding TWO blocks. `_extent`'s own docstring already says
   `CurrentRegion` "absorbs adjacent cells"; so does `find_header_row`'s.

3. **`parse_tshist_block` read the second block as the first block's data.** It
   located the FIRST `Date` header — the par block's — and then walked *every*
   body row below it, mapping by column position. The header location was
   defended against exactly this hazard. The **body was not**.

4. **The columns lined up one-for-one.** `DEFAULT_CHUNK_SIZE` is 44 and so is a
   par grid — `ois_par_grid`'s own docstring says the chunk size comes from the
   add-in's 44-tenor curve export. Column *j* of the vol block was column *j* of
   the par block.

5. **`keep="first"` kept the upper block's rows**, so a short nightly-tail par
   request kept its own few days and took ~2,700 historical days from the vol
   block below. `cache.get` writes the whole returned series unclipped, so a
   7-day request banked an 11-year vol history.

### The fingerprint that identifies it

Every poisoned value is **bit-exact** (max |diff| = 0.0) against that same day's
`RATES.VOL.USD.ATM_RFR.NORMAL` series. 100% of them, in all three families.

**For USD_SOFR**, par slot *i* maps to `cube_tags('USD')` ATM position *i* for
all 44, on every one of 2,600 poisoned days — and the decisive detail is the
**8 clean tenors** (3W, 4M, 11M, 21M, 8Y, 12Y, 19Y, 35Y at positions
3, 7, 14, 18, 25, 29, 36, 40). Those are exactly the requested vol tags whose
tenor is 4Y or 12Y, which Citi does not quote. Their columns came back empty,
`coerce_float(None)` returned `None`, and the row was skipped — leaving that par
tag untouched **at its exact position**. A Python `zip` of the *served* series
would have compacted those 8 away and shifted every later tenor.

**That gap-preserving argument applies to USD only — 36 of the 124 tags.** CAD
and JPY are **compacted**: their par slots walk the *served* index contiguously
(CAD 44–87, JPY 132–152 then 109–131) with no gaps at all. Both patterns are the
same mechanism in two different cache states, and `cache.get`'s span grouping is
what produces them:

`get` groups tags by identical missing span. On a **cold** cache all 187
requested vol tags share one span and chunk at 44 into requested 0–43, 44–87, …,
so a victim sees the *request* grid with its dead 4Y/12Y slots preserved — event
A, USD. Once the 153 real tags are banked, the 34 never-banked 4Y/12Y tags have
`coverage() is None` and form their **own** span group, leaving a 153-tag group
that chunks into **served** 0–43 / 44–87 / 88–131 / 132–152. That last chunk is
ragged, 21 wide — and JPY's slots 21–43 are empty for event B, exactly as a
21-wide chunk predicts. CAD took chunk 1; JPY event C took chunk 2 at column
position (par slot 21 ← served 88+21 = 109).

All three carry **USD** vol, which is why no per-currency explanation works.

### It was at least 18 separate events, not one

Poisoned-date sets are bit-identical within an event and distinct between them:

- **A** — 2,600 days, 2015-10-08 … 2026-07-29: USD_SOFR, 36 tags, request grid 0–43.
- **B** — 937 days, 2015-10-08 … 2019-07-16: CAD_CORRA 44 tags (served 44–87) *and* JPY 21 tags (served 132–152), on the *same* 937 dates.
- **C** — 518 days, 2015-10-08 … 2017-11-08: JPY 23 tags, served 109–131.
- **plus 15 more** in the MI01 bond families (below).

Every one of the 124 daily tags has exactly one donor; none has two. The same
donor node serves two different bonds with different day counts, which a single
merged region cannot do — so these are independent recurrences of one defect, not
one catastrophic run.

## What was ruled out

- **A positional `zip` in Python.** Falsified, and by exhaustion rather than by
  the gap argument alone — the gaps only speak for USD. Across 3,131 worktree
  `.py` files there are exactly **3** production `cache.write` sites and **8**
  `cache.get` fetcher sites, and every one keys the tag from a dict's `.items()`
  or delegates the tag list verbatim to the wire. Extended to all 90 top-level
  directories of `clee`, every branch, deletion and stash, 54 checkouts'
  uncommitted diffs, and the entire 48,906-line IPython history spanning the
  cache's whole life: **zero** occurrences of `ois_par_grid`, `cube_tags`,
  `cache.write(` or any `RATES.OIS.*.PAR.` literal. There is no such code.
- **A stale or wrong-anchor block read on its own.** `_column_for_tag` matches by
  header text with three textual fallbacks and no positional one, so a foreign
  block's headers produce "no column" failures — loud, not silent.
- **The vendor / the add-in.** The CurveStore reprices the same curve correctly
  from data written by a path the poison never touched.
- **A read triggering a write.** Settled by test, not inspection: `read()`,
  `coverage()`, `get(fetcher=None)` and `get(fetcher→{})` each leave the cache
  byte-identical with an unchanged `st_mtime_ns`.
- **`fetched_at` as evidence of when the poison landed.** `write()` rewrites it
  on every write. The 2026-08-24 15:46 stamps on all 44 tags were a live VS Code
  Jupyter kernel doing an ordinary tail refresh.

### Reproduced end to end, on pinned code

Not just at the parser. A 17-day PAR request driven through the real
`fetch_timeseries → parse_tshist_block → cache.get` chain, on a `git archive` of
the **pre-fix** commit, banked 2,709 rows reaching back to 2015-10-08 and
poisoned exactly 36 of 44 tenors — and **92,820 of 92,820 values are bitwise
identical float64 to the pre-repair production parquets** on their own poisoned
days, with the 8 clean tenors exactly right. The identical script on the fixed
code writes 17 rows per tag, the requested window, zero poisoned tenors.

Each guard was then shown to stop it *independently*: the parser returns
`foreign_rows=2710` and a 17-row series; `cache.write` refuses the vol series
under a par tag; `cache.get` refuses the unrequested key. No COM, temp cache only.

**Refuted along the way — the block ordering first written in commit `da132c54`.**
"Vol block first, par planted second" does **not** produce it: `CurrentRegion`
floods *upward* as well as down, so the first `Date` header found is the vol
block's and all 44 par tags come back "no column" — loud, not silent. The order
must be par block first with the older block's rows continuing below it, which is
the layout the window guard models.

**Not established:** *which historical run* delivered it, and by which of the
overlap routes. The mechanism is proven and reproducible from the point the
client reads a merged region; what was never observed live is the sheet event
that creates one, because driving Excel over COM is a measured hazard here and
was out of budget. The remaining live check is small and specific: write a tall
`CVTSHIST` at an anchor, let it settle, re-issue a short one at the *same* anchor
and see whether the add-in republishes `CvFunction_<row>_<col>` exactly or leaves
it stale — if it always republishes, `_extent` never falls back to
`CurrentRegion` at a reused anchor and the merged region must arise another way.

A separate exhaustive negative supports the mechanism by elimination: across
3,131 worktree `.py` files (3 production `cache.write` sites, 8 `cache.get`
fetcher sites, all dict-keyed), all 90 top-level directories of `clee`, every
branch, deletion and stash, 54 checkouts' uncommitted diffs, and the **entire
48,906-line IPython history spanning the cache's whole life** — there is **no**
Python code anywhere that pairs a par tag list with vol values.

## The fix

Four guards, outermost first. Each was mutated out and its tests confirmed red.

| where | guard |
|---|---|
| `block_parser._one_block_only` | Bounds the body to ONE block: a second `Date` header, a formula row, or the dates ceasing to be monotone. Direction is **measured** from the first two dated rows, so an oldest-first block is not truncated at row two, and a stamp repeated across a chunk seam is not a reversal. |
| `block_parser` window guard | Rows outside the window the caller actually asked for are not this block's data. This catches the layout the three markers cannot see — see below. |
| `com_client._write_and_read` | Advances the cursor past the measured extent on **both** early-return paths, and skips a worst-case 6,000 rows when the extent cannot be trusted (a pending block's extent is a floor, not the truth). `_anchor` also re-reads `_next_free_row` before every formula, because `EXCEL_LOCK` is per-process while the scratch workbook is deliberately shared between processes. |
| `cache.get` / `cache.write` | `get` writes only tags the span asked for; `write` refuses a series whose values cannot belong to its family (`MDP/CitiVelocityExcel/sanity.py`). |

### A hole the first three guards missed

The three structural markers cover two complete stacked blocks. They do **not**
cover a *short* request planted inside a *taller* spill: what follows the par
block is then that spill's continuation rows — no second header, no formula row,
and, because the vol rows at that sheet depth carry dates months older than the
par block's oldest, the sequence never stops descending. Measured: 40 of 43 rows
poisoned, `foreign_rows` reported as 0.

That is precisely the nightly-tail shape — the one that kept re-poisoning the par
tags after every heal — which is why the window guard exists. A *wide* request
cannot be defended that way, but a wide request produces a block taller than the
spill it was planted in, which leaves no continuation rows and lands back in the
three markers.

**Residual, stated plainly:** a request made with a relative `period=` has no
window to check against, so for that call shape the defence is the three markers
plus the family band. The band is the last line, not the fix — a wrong series
whose numbers land inside the band still gets through, and the vol family reaches
down to 8.69, which is inside the par band.

## The repair

`scripts/citivelo_tagcache_repair.py` — `report` is the default and read-only;
`repair --apply` backs every file up first.

Two criteria, and the second is the one that matters:

- **Tier 1, out of band** — the value cannot belong to the family at all.
- **Tier 2, an exact match to the donor** — the value equals, to the last bit,
  what the donor tag carried that same day.

**71,131 of the 283,936 removed rows — a quarter of the damage — were INSIDE the
plausibility band** and would have survived a value check: 2,892 in the daily par
families (`PAR.1D` alone had 471, because a short-expiry normal vol dips under 25
in a quiet regime) and 68,239 in MI01, where the bond PRICE tags have *no*
out-of-band rows at all. Tier 1 alone is not a repair; it is the half of the
repair that is easy to see.

The donor is *searched for*, not assumed, and must explain ≥90% of a tag's
suspect rows. One was identified for every affected tag bar five, and those five
held a single impossible tick each, where only tier 1 fired.

Applied to `DAILY`/`CLOSE`: **166,419 rows removed across 124 tags** — plus
117,509 more in `MI01` and 8 isolated ticks, for **283,936 across 186 tags**.

Rows are **deleted, not rebuilt**. The clean par rate is recomputable from the
CurveStore's discount factors, but it is a derived number ~0.2bp off the quoted
one, and writing it into a cache whose contract is "what the vendor quoted" would
leave the next reader no way to tell. A missing row is an honest cache miss.

### Validation, against a source the removal never consulted

| | median \|diff\| | p95 | corr |
|---|---:|---:|---:|
| USD 2Y before | 0.31bp | 10,724.88bp | 0.161 |
| USD 2Y after | **0.00bp** | 0.36bp | **1.0000** |
| USD 5Y after | 0.23bp | 0.70bp | 1.0000 |
| USD 10Y after | 0.17bp | 0.48bp | 1.0000 |
| JPY 2Y before | 1.97bp | 53.75bp | 1.0000 |
| JPY 2Y after | 1.20bp | **2.44bp** | 1.0000 |

CAD is unchanged before and after (median 1.35bp, corr 1.0000, n=2,825 both) —
its 937 removed rows were on dates the CAD curve never had, i.e. days the vol
block *inserted*. No genuine CAD observation was touched. The residual 1.2–1.8bp
on CAD/JPY is day-count and roll convention between the quoted par rate and the
repricing, and it is the same before and after.

Residual out-of-band rows across every banded tag in the daily cache: **0**.

The tool was verified against a synthetic cache whose answer was known — 200
planted rows including 48 inside the band, plus a decoy donor — before it was
pointed at the real one. It named exactly the planted set.

**Holes left behind.** Each repaired USD tag has 2,600 interior holes
(2015-10-08 … 2026-07-29). `missing_spans()` reasons about head and tail only and
cannot see an interior hole, so a **deep re-harvest** is what refills them, not
the nightly. The sidecars were rewritten to match (`n_rows`, `first`, `last`);
`first`/`last` were in fact unchanged, so the nightly's `_sidecar_last` was never
reading a wrong date.

## The rest of the cache — and the part that also had to be repaired

16,678 parquets (14,535 `DAILY`/`CLOSE`, 1,850 `MI01`, 293 `HOURLY`),
~144.9M rows.

**`MI01` is NOT clean, and an earlier draft of this note said it was.** 57
`MI01` `RATES.BOND.*` PRICE/YIELD tags carry the same USD ATM swaption vol, on
exact-midnight rows, reaching **2026-08-20/21** — much more recent than the daily
damage. **117,509 further rows, 57 tags, now repaired.**

Two things make this the sharpest illustration in the whole investigation:

- **58% of those rows (68,239) are INSIDE any plausible band**, and every one of
  the PRICE tags is *entirely* in-band — `out_of_band = 0` for all of them. A
  value check finds **nothing** there. Only the donor match does. A bond price of
  89.9 and a normal vol of 89.9bp are the same float.
- **Each bond's PRICE and YIELD take ADJACENT vol nodes** — `CQE48.PRICE ← vol
  3Y.1Y` and `CQE48.YIELD ← vol 3Y.2Y`, `CQG95.PRICE ← 3Y.5Y` and
  `.YIELD ← 3Y.7Y`, and so on down the list. Adjacent columns in the victim block
  take adjacent columns in the foreign one. That is the column-position signature
  again, on a different family.

It is also a **frequency** mix: 100% of the poisoned rows are `00:00:00`-stamped
DAILY rows sitting in a minute-frequency key, which `cache.py`'s docstring says
never happens ("daily and intraday ... are **never** mixed"). The blocks shared a
worksheet, so a DAILY vol block could merge into an `MI01` region — which is why
the repair tool searches for donors **across** frequencies. Searching only the
victim's own frequency finds nothing and reports the tag clean, which is exactly
the false negative that produced the earlier wrong claim.

That makes the total **at least 18 separate poison events**: 3 daily and 15 more
in the bond families, distinguished by bit-identical poisoned-date-set hashes and
by donor runs starting at served indices 36, 72, 108 and 144.

`HOURLY` was swept the same way and is clean.

**8 isolated bad prints, also removed.** Five `RATES.BOND.*.YIELD` tags each held
one or two impossible values with no donor at all — 1,460% and 1,463% on
`US91282CQY02` against a 4.20% median, 10,040% on `CND10008R1W1` against 1.65%,
-6.52% on `US9128284X55`. Bad ticks rather than this defect, but a yield that
cannot be a yield does not get to stay just because its cause is different.

### Validating the MI01 survivors

A bond's price and yield must move opposite ways, and after the repair they do:
`corr(dY, dP)` on true consecutive-minute changes is **−0.9994** for
`US91282CHT18` and **−0.9993** for `US91282CQE48`. Yields land at 3.82–4.58% and
prices at 95.8–100.3 — ordinary UST numbers where the max was 146.99% before. A
handful of midnight rows survive in each (26, 11, 21), which is the guard working
as designed: they matched no donor, so they were left alone.

### Two things left alone, and named

**`RATES.OIS.DKK_TNDKK.PAR.5Y`** at 2026-08-05 07:27 reads 17.7948 between
neighbours of 2.46595 and 2.46300. A single-minute spike, no donor, inside the
band — nothing about it is provably foreign.

**`RATES.BOND.US912810EX29`** is internally inconsistent and **that is
pre-existing, not the repair**: 1,890 minutes between 2026-08-07 08:30 and
2026-08-14 19:59 carry yields of 2.56–3.5% while the price sits pinned at
100.009–100.044 — a stuck price against a moving yield, which no bond does. The
count is *identical* in the pre-repair backup, and `corr(dY, dP)` is −0.46 here
against −0.999 for its healthy siblings. It is a different data-quality problem in
the same family and it deserves its own look; the repair neither caused it nor
touched it.

### Totals

| | tags | rows removed |
|---|---:|---:|
| `DAILY` OIS PAR (3 currencies) | 124 | 166,419 |
| `MI01` bond PRICE/YIELD | 57 | 117,509 |
| `DAILY` bond YIELD, isolated ticks | 5 | 8 |
| **total** | **186** | **283,936** |

Re-run of the sweep after the repair: `DAILY`, `MI01` and `HOURLY` all report
**no foreign rows**.

### A band-free confirmation

The sweep above can only speak for families whose unit is known, and only five
tag patterns have a band. So the whole cache was also checked a second way, which
needs no band at all: build a reverse index from *value* to *vol tag* on four
probe dates, then ask of every other tag whether its value on those dates equals
some vol series' value to the last bit.

**14,689 non-vol parquets across every frequency. Zero matches on two or more
probe dates.** No tag in any family, banded or not, still carries the vol series.

Its limit, stated: four probe dates with a two-hit threshold would miss a tag
poisoned only on a date set disjoint from all four. It is a cross-check on the
band-and-donor sweep, not a replacement for it — but the two disagree nowhere.

### Getting the old bytes back

Every file the repair touched was copied before it was touched, parquet and
sidecar both, under
`%LOCALAPPDATA%\ARBS\ARBS\Cache\citivelo_excel_prerepair\<UTC stamp>\`:

| stamp | files | what |
|---|---:|---|
| `20260824T213134Z` | 248 | the 124 daily OIS PAR tags |
| `20260824T223941Z` | 114 | the 57 MI01 bond tags |
| `20260824T224814Z` | 10 | the 5 isolated-tick tags |

A second copy of the 132 daily PAR parquets, taken before anything at all
happened, is committed to this branch under `_snapshot/DAILY_CLOSE_PAR/` — that
one is the reference for "what did it look like before you started", because it
predates even the first report.

## Blast radius

`notebooks/rv/fed_sentiment_lead.py:1075` and
`notebooks/rv/fedlock_sentiment_lead.py:724` read `RATES.OIS.USD_SOFR.PAR.2Y`
with no sanity check.

**They were not re-run here**, and that is a deliberate call. The series they read
now has 2,600 interior holes rather than 2,600 lies, so re-running today would
regress a silently shorter sample and answer a third question — neither the
original's nor the repaired-data one. The right sequence is: deep re-harvest,
then re-run. `fed_detachment_prices.curve_store_par_rate(2)` is a drop-in clean
source that needs neither, if the owner prefers not to wait.

**Why the conclusion probably survives, stated correctly.** The poisoned series
was the **dependent** variable — a forward change in the rate, regressed on a
sentiment index. Noise in *Y* does not attenuate the coefficient the way noise in
a regressor does; the estimate stays unbiased and the standard error inflates. At
roughly 84x the true volatility (sd 1,887bp against 22.5bp at four weeks) the
power is destroyed, so "we found nothing" is what that regression had to say
regardless of whether anything was there. That is a weaker statement than
attenuation would give: it means the studies could not have detected a real
effect, not that a real effect would have shown up smaller. Both concluded the
relationship does not reach the price, and both are still owed an honest test.

## Test state

`tests/test_citivelo_tagcache_poison.py` — 23 cases. Every guard was mutated out
in turn and its tests confirmed red, each one **isolated**: two of them initially
overlapped (a 2,700-row spill is cleared by the constant floor whether or not
`_advance_past` runs), so the cases were split — a 12,000-row spill isolates
`_advance_past`, an `_extent` that raises isolates the constant.

Fast gate on the merged tree: **9,993 passed, 4 failed, 122 skipped**, 39m06s.
All four are accounted for and none is this branch's:

| failure | verdict |
|---|---|
| `test_a_batch_of_matured_bonds_…` | **was mine** — fixture fed a price to a YIELD tag; fixed, file passes 8/8 |
| `test_fixings_kwargs_resolve_once_per_wrapper` | the known flake; passes in isolation, verified |
| `…default_base_dir_is_repo_root_relative` | pre-existing — verified failing on unmodified code in another worktree |
| `test_252_dates_200_tenors_under_5s` | a 5s budget measured under my own concurrent jobs; passes alone, verified |

The gate caught **three** fixtures that fed convenience sentinels to tags whose
units now matter — a 39% par rate, a 111% par rate and a 100% bond yield. In each
case the guard was right and the fixture was fixed, never the other way round.

## Operational note

**The nightly still works.** The repair rewrote 186 sidecars, and
`citivelo_daily_par_refresh._sidecar_last` reads the sidecar rather than the
parquet — its docstring calls it authoritative — so this was worth checking
rather than assuming. All five curves plan `refresh` from 2026-08-14, a 10-day
span, with no tag reporting "never banked" and no 21-year re-request:

```
USD-SOFR-1D       tags=44  sidecar-None=0  banked_to=2026-08-21  refresh  span=10d
CAD-CORRA-1D      tags=44  sidecar-None=0  banked_to=2026-08-21  refresh  span=10d
JPY-TONAR-1D-LCH  tags=44  sidecar-None=0  banked_to=2026-08-21  refresh  span=10d
EUR-ESTR-1D       tags=44  sidecar-None=0  banked_to=2026-08-21  refresh  span=10d
GBP-SONIA-1D      tags=44  sidecar-None=0  banked_to=2026-08-21  refresh  span=10d
```

**But the fix is on a branch, and the repaired data can be re-poisoned until it
lands.** The nightly par refresh runs from the primary checkout, and the VS Code
Jupyter kernel that wrote at 15:46 today is still holding the old code in memory.
**Merge, then restart that kernel.** Nothing else needs doing — the interior
holes are the only lasting cost, and only a deep re-harvest fills those.
