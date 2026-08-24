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

`DAILY`/`CLOSE` only. The `MI01` and `HOURLY` copies of the same tags are clean.
2015-10-08 is the USD swaption tags' own first day, in every family.

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

Par slot *i* maps to `cube_tags('USD')` ATM position *i*, for all 44, on every
one of 2,600 poisoned days, **bit-exact** (max |diff| = 0.0 against the
`RATES.VOL` parquets).

The decisive detail is the **8 clean tenors**: 3W, 4M, 11M, 21M, 8Y, 12Y, 19Y,
35Y — positions 3, 7, 14, 18, 25, 29, 36, 40. Those are exactly the requested vol
tags whose tenor is 4Y or 12Y, which Citi does not quote. Their columns came back
empty, `coerce_float(None)` returned `None`, and the row was skipped — leaving
that par tag untouched **at its exact position**. A Python `zip` of the served
series would have compacted those 8 away and shifted every later tenor. It is
that gap-preserving signature that proves the mapping happens at column position
inside one region, and not in any Python re-keying.

CAD_CORRA took served vol tags 44–87 and JPY_TONAR_LCH 132–152 then 109–131 —
the same defect on other chunks in other runs. All three carry **USD** vol, which
is why a per-currency explanation cannot be right.

## What was ruled out

- **A positional `zip` in Python.** Falsified. Every `zip(`, `dict(zip(`,
  `.columns =` and `.write(` site was searched; nothing renames a vol series to a
  par tag, and the 8 gaps disprove compaction.
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

**Not established:** *which historical run* delivered it. The mechanism is proven
and reproducible; the vehicle is ranked (`harvest_curve_modes.fetch_and_bank` for
the deep history, `citivelo_swaption_vol_warm.fetch` as the vol side) but the
wire-level overlap was never observed live, because driving Excel over COM is a
measured hazard in this repo and was out of budget. Confirming it live would mean
forcing a `CVTSHIST` timeout, writing the next chunk 38 rows below, and dumping
`_extent(anchor).Value`.

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

**2,892 removed rows were INSIDE the plausibility band** and would have survived
a value check; `RATES.OIS.USD_SOFR.PAR.1D` alone had 471. A short-expiry normal
vol dips under 25 in a quiet regime, so a poisoned row can wear a par rate's
clothes. The donor is *searched for*, not assumed, and must explain ≥90% of the
out-of-band rows; one was identified for all 124 tags, and the map recovered is
the expected one.

Applied to `DAILY`/`CLOSE`: **166,419 rows removed across 124 tags.**

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

## The rest of the cache

16,678 parquets (14,535 `DAILY`/`CLOSE`, 1,850 `MI01`, 293 `HOURLY`),
~144.9M rows. `MI01` and `HOURLY` were swept with the same tool and the same
donor search: **no foreign rows**. The three OIS PAR families above are the whole
of this defect.

**One unrelated finding, reported not repaired.** 58 `MI01` `RATES.BOND.*`
YIELD/PRICE tags carry exact-midnight rows with impossible values — e.g.
`US91282CHT18.YIELD` maxes at 146.99% with 2,687 midnight rows, against a
non-midnight range that is ordinary. These are **not** this defect: an exhaustive
donor search over every tag in the cache found **no** match to the swaption vol
family, to the tag's own PRICE sibling, or to its own DAILY series. Two facts are
solid — the values are impossible, and 100% of them are 00:00:00-stamped, which
contradicts `cache.py`'s "daily and intraday are never mixed". The source is
unidentified and it deserves its own investigation. It was not repaired, because
without an identified donor the tier-2 criterion cannot run and a band-only
deletion would be a guess.

**One genuinely isolated print:** `RATES.OIS.DKK_TNDKK.PAR.5Y` at
2026-08-05 07:27 reads 17.7948 between neighbours of 2.46595 and 2.46300. A
single-minute spike with no donor — a bad tick, not this defect. It sits inside
the band and is left alone.

## Blast radius

`notebooks/rv/fed_sentiment_lead.py:1075` and
`notebooks/rv/fedlock_sentiment_lead.py:724` read `RATES.OIS.USD_SOFR.PAR.2Y`
with no sanity check.

**They were not re-run here**, and that is a deliberate call. The series they read
now has 2,600 interior holes rather than 2,600 lies, so re-running today would
regress a silently shorter sample and answer a different question than either the
original or the repaired-data version. The right sequence is: deep re-harvest,
then re-run. Both studies concluded the relationship "does not reach the price",
and spurious variance biases a regression toward zero, so the conclusion is very
likely to survive — but it survived by accident and still needs the re-run to
have been earned. `fed_detachment_prices.curve_store_par_rate(2)` is a drop-in
clean source that needs no re-harvest and no COM.

## Operational note

The fix is on a branch. Until it merges and long-lived processes restart, the
repaired data can be re-poisoned: the nightly par refresh runs from the primary
checkout, and the VS Code Jupyter kernel that wrote at 15:46 today is still
running the old code in memory. **Merge, then restart that kernel.**
