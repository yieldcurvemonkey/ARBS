# Citi Velocity BONDS + SWAP SPREADS — decision log

Branch `feat/citivelo-bonds-and-swapspreads`. Running log of forks taken and why.
Written as the work happens, not reconstructed.

## D1 — Do not re-harvest the bond tag universe live

`MDP/CitiVelocityExcel/catalog/bond_tags_validated.json` already holds a validated
harvest: **2,162 ISINs × 8 values → 12,570 valid tags**, across 29 country/currency/sector
universe keys. The 8 values Citi actually serves are:

| value | ISINs serving | of 2,162 |
|---|---|---|
| PRICE | 2,105 | 97.4% |
| YIELD | 2,103 | 97.3% |
| DURATION | 2,097 | 97.0% |
| SPREAD_TSY | 1,803 | 83.4% |
| DV01 | 1,656 | 76.6% |
| OAS | 1,401 | 64.8% |
| ASW_4_USD | 1,081 | 50.0% |
| ASW_4_JPY | 324 | 15.0% |

Re-validating 12,570 tags through Excel would spend the memory budget (hard ceiling
~3,800 MB, and only a human restart clears it) to reproduce a number we already have.
**Decision: treat the harvest as the enumeration, and spend the Excel budget on
semantic calibration instead** — spot-check a sample to confirm it still serves, then
use it as the availability source of truth.

Cost if wrong: a value silently absent for some ISINs. Mitigated because the source
consults per-ISIN availability and returns an explicit "not served" rather than
falling through to a live Excel call.

## D2 — Availability is window-dependent, so mode capability is a matrix, not a flag

`bond_values2.json` records OAS as `valid_5y_only`: **empty over a 1-week window,
served over 5 years**. So "does Citi serve value V for ISIN I" is not a single boolean —
it depends on the window requested. `ASW_4_JPY` appears only in the wider probe too.

**Decision: model per-value mode capability explicitly (EOD / intraday / live) rather
than assuming all 8 values support all three modes,** and probe availability over more
than one window before recording it.

## D3 — CUSIP↔ISIN is mechanical and is now verified, not asserted

ISIN check digit = Luhn "modulus 10 double add double" over the alpha-expanded
11-char body (A=10..Z=35), doubling every **odd** position counting from the right.
CUSIP check digit doubles every **second** char 0-indexed from the left, with
`*`=36 `@`=37 `#`=38.

Verified before any of it was relied on:

- 4/4 published control ISINs (Apple, Microsoft, BAE, TCV)
- **negative control**: a deliberately corrupted ISIN is rejected — the checker can fail
- **2,162/2,162** real Citi-served ISINs across all 29 universe keys
- **349/349** CUSIP→ISIN round trips on `USA.USD.GOVT`
- **349/349** CUSIP check digits re-derived from the 8-char base

**Decision: `US` + CUSIP + check digit is the UST resolution path, and resolution does
not stop there** — the resolved ISIN is asserted to exist in Citi's universe, because a
check digit that is arithmetically right can still name a bond Citi does not quote.
That assert is what makes "the alias resolves to the SAME bond Citi is quoting" true
rather than merely likely.

## D0 — The Excel transport was unavailable this session (measured, not assumed)

The plan was to spend one Excel trip on semantic calibration. It did not happen, and
the reason is a number rather than a guess.

At session start `EXCEL.EXE` (PID 51420) was at **674 MiB**. By the time the fetch ran,
the *same* process — no connection made by this session in between — was at
**7,286 MiB / 7,639 MB, private bytes 7,776 MB**. The recorded wedge incident
(2026-08-07) was at **5,249 MB**, and the standing instruction is to stop at **3,800 MB**.
So the process was at ~2× the ceiling and ~1.45× the level that previously wedged it.

`calib_fetch.py` refused to start and said so:

```
Excel memory BEFORE: 7453 MB (ceiling 3800)
ABORT: Excel already at 7453 MB, above the 3800 MB ceiling.
```

Neither is there a cached fallback — measured directly against the tag cache at
`C:\Users\chris\AppData\Local\ARBS\ARBS\Cache\citivelo_excel`:

```
RATES.VOL 1989 · RATES.OIS 1777 · RATES.MONEY_MARKETS 9
RATES.BOND cached: 0
SWAP_SPREAD cached: 0
```

**Decision: do not touch Excel.** Pushing risks wedging a session that only a human can
restart, and the human is away; the growth also suggests something else is driving that
process, which is a second reason to stay out of it. The autonomy granted here is over
design and implementation — the memory ceiling is a specific safety instruction given in
the same breath, and being unattended is the argument for honouring it, not for
overriding it.

**Consequence, carried honestly:** every deliverable that requires a live Citi number is
built and runnable but **not measured this session** — the quote-vs-compute calibration
table (D4), the Citi-vs-repo swap-spread comparison, and both warms. Each ships as a
committed, guarded script that produces its numbers on the first run after a human
restarts Excel. Nothing fabricates a number it could not obtain.

## D4 — Quote-vs-compute is decided by measurement, not by name

Deferred until the calibration fetch. `DURATION` is **not** assumed to be modified
duration: Macaulay and modified differ by `(1 + y/f)`, which is a measurable ratio, and
assuming is exactly the confident-wrong-number failure this repo has been bitten by.
Same for `PRICE` (clean vs dirty — discriminated with a high-accrued bond), `DV01`
(scale and sign per 100 face), and `ASW_4_USD` (which ASW variant `_4_` denotes).

## D5 — Forks taken while building the fetcher and the `FixedRateBondsMDP` branch

**Offline cannot use the chunker, so it clamps instead.** `windowed.fetch_windowed` pushes
and drops a worksheet per window, so it needs a connected client. The offline intraday path
therefore serves from the tag cache with the window held at or under `MAX_SPAN["MI01"]` —
the same measured 7-day cliff expressed as a bound rather than as a chunker. Both halves are
mutation-tested: routing intraday through one wide request makes the fake serve 10-minute
data and the test fails; removing the clamp makes the offline request span 20 days.

**`unavailable` ≠ `empty`, and both are answered from the bond's served vocabulary.** The
first version answered "was it served?" from the intersection of the request and the harvest,
which made `CAS` — never in the default value set — report as "you did not ask for it". True,
useless, and it points the reader at their request when the fix is to change their
expectation. The coverage book now carries the bond's whole served vocabulary, so the three
causes (wrong source / not served for this bond / served-but-empty-in-this-window) each get
the message whose fix can actually work.

**`DV01` is a genuine name collision and is resolved explicitly.** It is both a Citi value
token and a `FixedRateBondValue` member, and on this source they are *different numbers*:
Citi publishes its own DV01 (scale and sign unverified, D4) while `FRB_DV01` is the backend's
PV01 off the locally re-solved yield. The flat provenance book records what `FRB_DV01`
returns — computed — and Citi's own keeps its provenance under `CITI:DV01` rather than being
silently overwritten. Same reasoning for `YIELD` vs `YTM`: recording `YTM` as "quoted"
because Citi happened to publish a yield in the same response would be a false audit trail.

**The market-timezone table is convention, not measurement, and says so.** Citi stamps every
instrument in America/New_York (that part *is* measured), so an Asia/Pacific session straddles
two ET dates and an intraday stamp must be converted before it is bucketed by day. The
eighteen zones are the obvious domestic exchange zone per country; none has been checked
against a session boundary in Citi's own data the way the wire zone was. EOD deliberately
does **not** convert — an EOD row carries the label Citi assigned it, and re-deriving that
through a local zone moves it backwards for every market west of New York.

**Live is not cached.** An EOD or intraday quote is a fixed historical fact and caches
soundly. Caching "live" under today's date, which is what the sibling TradingView branch
does, serves the 09:31 print at 16:00 and still calls it live.

**Nothing here has been checked against a live Citi number.** D0 still holds: the fetcher,
the branch and the four new values are exercised end-to-end against the packaged COM fake and
the committed 2,162-ISIN harvest, and every unit interpretation they rest on is still the
unverified reading recorded in `values.py`.

## D6 — Citi's SWAP_SPREAD is a THIRD number, added alongside MMSS/SPREADOVER

New member `IRSwapValue.CITIVELO_SWAP_SPREAD` (hence `UnifiedValue.IRS_CITIVELO_SWAP_SPREAD`,
which the registry derives automatically), served from
`MDP/IRSwaps/CITIVELO_EXCEL/swap_spreads.py`.

**Name.** Not `CITIVELO_MMSS` and not `CITIVELO_SPREADOVER`, and that is load-bearing
rather than cosmetic: `BT/signals/tfp_swap_spread.py:249` selects columns with
`"MMSS" in c`, so a name containing `MMSS` would have been silently swept into that
backtest's MMSS panel. The leading vendor token also states the actual distinction —
this one is a **quote Citi publishes**, the other two are **computed here**.

**Where it sits.** Appended at the END of the enum, not filed next to `SPREADOVER`/`MMSS`.
`auto()` renumbers every member after an insertion point; `SPREADOVER` is 10 and `MMSS`
is 11 and a test pins them. `TB/TimeseriesBuilder.py` routes on an explicit set
(`{MMSS, SPREADOVER} | _IRSWAP_ADJUSTED_SPREAD_VALUES`), so the new member goes down the
ordinary IRS value path and needs no bond pricer — checked by test, not assumed.

**The axis is ragged and per index, and is read from the catalog.** `tags.SWAP_SPREAD_LIQUID_TENORS`
is the USD axis under a generic name. USD_SOFR/USD_FEDFUND have 11 (`1M 3M 6M 1Y 2Y 3Y 5Y
7Y 10Y 20Y 30Y` — money-market tenors in, no 4Y/15Y/25Y); GBP_SONIA has a *different* 10
(no 1M–1Y, but 15Y/40Y/50Y); JPY 12, AUD 7, CHF/CAD/DKK/SEK 4, NOK 3; **EUR_EUROSTR has
no SWAP_SPREAD sub-type at all.** 13 of the 20 indices carry it. Using the USD tuple for
GBP would ask for four tenors that do not exist and miss three that do.

**Extra guard beyond `tags.ois`.** `_pick` validates trailing segments with
`allow_unrecorded=True`, which is right in general (the Function Builder walk was
depth-capped) but means a sub-type node with an EMPTY option list accepts any string.
`swap_spread_tenors` refuses an empty axis and names the indices whose axis *is* recorded.
No shipped index is in that state, so the test uses a stub catalog — otherwise the guard
would be unreachable and would rot.

**CVMETADATA is not consulted, ever.** It reports zero valid tenors for this family while
CVTSHIST serves the whole axis, and `RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y` poisons an entire
CVMETADATA batch to `#VALUE!`. The test double raises if `metadata()` is called.

**Units: UNMEASURED, and declared as such.** The served number is returned unscaled and
the module constant is literally `UNIT = "as_published"`. Consistent with D0 — zero
SWAP_SPREAD tags cached, Excel at 7,639 MB — bp-versus-decimal could not be measured this
session and is not asserted. The discriminator is magnitude (a USD 10Y swap spread is tens
of bp, so `|x| > 1` is bp) and the check that settles it is
`scripts/citivelo_swap_spread_tieout.py`, which prints Citi's raw level beside the repo's
`SPREADOVER` in bp per tenor. When it runs, `UNIT` becomes `"bp"` and the test that pins
`"as_published"` moves with it — deliberately, so that is a decision somebody makes rather
than a default that drifts.

**Why the three disagree, and why they are not reconciled.** `SPREADOVER` pairs a
round-tenor par swap with the **on-the-run** note (`10Y` → bond `CT10`, swap stays `10Y`);
`MMSS` pins the swap to a **named bond's exact maturity** (`edit_query` resolves the
CUSIP/alias and replaces the tenor with `effective = spot+2D`, `maturity = the bond's`).
Both are `(swap_rate_percent − bond_ytm_percent) × 100` — swap minus cash, in bp. Citi's
is a published quote whose Treasury leg, yield convention and swap curve are **not
documented anywhere in the harvested catalog** and are recorded here as unknown, not
inferred. Carry all three as separate columns.

## D7 — What the adversarial review found in the swap-spread track, and the fixes

D6 recorded no mutation testing. This section is that record, plus the four defects the
review found that no test could have caught. Excel was **not touched** at any point: the
one EXCEL.EXE on this box is pid 51420, started 2026-08-07 17:24:33, and its working set
was 13,222 MiB before and after every run below — **13,865 MB in the tie-out probe's own
decimal unit**, 3.6× the 3,800 MB ceiling and 2.6× the 5,249 MB that wedged it. The
standing do-not-connect constraint is more binding than when D0 recorded 7,639 MB, not
less.

**The silent wrong number.** `tenor_for_swap` derives a tenor from `maturity − effective`
and nothing checked that `effective` is spot. Citi's `SWAP_SPREAD` axis indexes a
*maturity* — a forward start would be the `(forward, tenor)` pair its separate `FWD`
sub-type carries, and that sub-type has no swap spread. So a 5Yx5Y forward derived `5Y`
and read the **spot** 5Y quote, byte-identical to the spot answer, with no warning: a
forward-swap RV book differencing it against its own forward rate would have carried the
entire forward/spot spread as a residual. `swap_spread_for_curve` now measures the
package's effective date against the **curve's own as-of** (not against today — the
package is rebuilt per reference date at `TB/IRSwapsTB.py:124`, so this stays a per-date
property rather than a refusal wall on a timeseries) and raises `SpotStartRequiredError`
outside `MAX_SPOT_START_LAG = 10 days`. Ten is the widest slack that still admits T+2
across a Friday-and-Monday holiday weekend (6 calendar days) and refuses the shortest
forward anybody trades (1M = 28–31 days); a ≤10-day forward is admitted, and that is
stated rather than papered over. Already-running swaps are refused for the mirror-image
reason: the derived tenor is their original span, not their remaining life.

**The gate that failed open.** `scripts/citivelo_swap_spread_tieout.py`'s memory guard
swallowed every probe exception into `None` and read `None` as "proceed". A
running-but-unreadable Excel and a machine with no Excel were the same observation, and
their correct actions are opposite. The probe now emits an explicit `NONE` from
PowerShell (`Measure-Object -Sum` over zero processes sums to `$null` and prints an empty
line, which is also what a command that never ran prints), so "no EXCEL.EXE" is an
affirmative `0.0` and everything else unreadable is `None` — and `None` **aborts**. That
matches `scripts/citivelo_bond_calibration.py`, which already fails closed on
`mem0 < 0`. Verified against a known answer rather than by reading: the probe returned
13,864.8 MB against the 13,222 MiB the independent `Win32_Process` query reported (the
same number, decimal MB vs MiB), and the gate returned `False`.

**The test that could not fail.** The abort test's only sentinel sat on `_out_path`
(tieout:226), 43 lines *after* `swap_spread_history` (tieout:183) builds a live
`CitiVeloQuotes`. Proving the gate therefore required connecting to Excel, which is why
it never was proven. The sentinel now sits on the hazard — and on the **source** module,
because `fetch` imports the name inside the function, so patching the tieout module object
would silently not take.

**Mutation sweep — 12 applied, 12 killed, sources restored byte-identical each time**
(the three files are untracked, so each was copied to scratchpad first; `git restore`
cannot recover them). The first four are the three the review ran and got `55 passed,
0 failed` from, plus the one it could not run without connecting:

| # | mutation | before | after |
|---|----------|--------|-------|
| A | MI01 cliff | `lookback = LOOKBACK_BY_MODE[request.mode]` | `lookback = timedelta(days=45)` | 
| B | live upper bound | `end = now(wire)` | `end = now(wire) + timedelta(days=1)` |
| C | as-of clamp | `if target is not None:` | `if False and target is not None:` |
| D | memory gate | (gate body) | `return True` at the top of `_memory_gate` |
| E | spot-start guard | the `_assert_spot_starting(...)` call | deleted |
| F | probe fail-open | `return False` on `mem is None` | `return True` |
| G | running-session warning | `if day < today: return` | `if True: return` |
| H | empty-history contract | empty frame, no columns | `columns=wanted` |
| I | close failure | `_logger.warning(..., exc_info=True)` | `pass` |
| I2 | close traceback | `exc_info=True` | dropped |
| J | `client_kwargs` | forwarded | dropped |
| K | probe sentinel | `if raw == "NONE"` | `if not raw` |

A–D were the surviving ones and are now killed by 2, 1, 1 and 3 tests respectively. D is
the load-bearing one: it fails at `scripts/citivelo_swap_spread_tieout.py:229` with
`AssertionError: fetch proceeded past the memory gate and reached the live-Excel path`,
**with no COM connection**, which is the property that was impossible to check before.

**Three test holes closed rather than papered over.** `_StubQuotes` pre-filtered by the
`end` it was handed, which did the as-of clamp's job for it — it now takes
`honour_bounds=False` so the clamp is the only thing standing between a 10:30 request and
an 11:00 print. The live fixture's index ended at now−3min, so there were no future rows
for the "bounded above by now" assertion to exclude — it now carries rows stamped 30
minutes into the future. And `assert module._memory_gate(3800.0) is not None` was vacuous
*and* ran a real PowerShell probe against the live EXCEL.EXE from a file whose docstring
claims "no Excel, no network"; it is gone, and every gate assertion is stubbed.

**Doc corrections.** `tags.ois_swap_spread`'s docstring claimed the catalog "carries the
full 44-tenor axis because it is shared with `PAR`". Measured against the committed
catalog it is neither shared nor 44: `USD_SOFR`'s `SWAP_SPREAD` node has 11 children
against `PAR`'s 44, a proper subset missing 4Y/15Y/25Y, and a test now pins 11-vs-44. The
repo was asserting both readings; it now asserts one. Separately, `swap_spreads.py` said
"`CVTSHIST` serves the whole axis" — measured for `USD_SOFR` only (11/11); off USD the
axis is catalog-recorded and never observed to serve, and that caveat is now carried over
from `tags.py` rather than dropped.

**Still not fixed, deliberately.** `swap_spread_for_curve` still defaults `offline=False`
and builds/tears down a `CitiVeloQuotes` per pricing call, so an N-date timeseries with no
injected `quotes` is N connect/close cycles; `client_kwargs` is now reachable (that was
the actionable half) but the default is documented rather than enforced, because forcing
`offline=True` would break the interactive case the curve fetcher's own default serves.
And `scripts/citivelo_bond_calibration.py` probes memory only *after* `quotes.client()`
has already connected — a different defect on the bonds track's file, left alone here.

## D8 — The memory guard has to run before the connection, not after

Found by adversarial review, in code written earlier in this same session, and it is
worth recording because the mistake looked exactly like the fix.

Both `scripts/citivelo_bond_calibration.py` and `daily_cache_warmer._citivelo_excel_guard`
read Excel's size like this:

```python
quotes = CitiVeloQuotes()
client = quotes.client()          # <- this is the COM connection
mem = client.excel_memory_mb()    # <- the "guard", after the fact
if mem > CEILING: raise
```

`CitiVelocityExcelClient.excel_memory_mb` is a method on a **connected** client, so
reading it requires doing the exact thing the ceiling exists to prevent. The guard ran
after the damage. It would have refused to *fetch*, having already opened a workbook
against whatever it found.

`MDP/CitiVelocityExcel/memory_guard.py` asks Windows over `Get-Process` instead — same
query, no COM — and every caller now gates before constructing anything.

The second half is subtler. The old probe returned `None` both when **no Excel was
running** and when **the probe itself failed**, and the gate read that as "fine, carry
on". Those are opposite situations: a machine with no `EXCEL.EXE` is the safest state
there is, while a probe that timed out says *nothing at all* about what is running —
and what was running, measured, was a 13,884 MB add-in. So `0.0` and `None` are now
distinct and the gate **fails closed** on `None`.

**Mutation-tested, and the first attempt was not good enough.** Seven mutations; three
survived the first pass and were closed rather than written up as passing:

- the ordering assertion matched the *name* `assert_safe_to_connect`, which first appears
  on the `from ... import` line — so it compared an import against a call and was vacuous.
  It now compares `ast.Call` line numbers, and imports are not calls.
- `>=` → `>` on the ceiling survived, because `is_safe_to_connect` has its own comparison
  and the test only exercised that one. A process sitting exactly on the limit would have
  been let through.
- the "probe must not touch COM" test searched the whole source, including the docstring
  that deliberately *names* the connected client's method to explain why it is not used.

All seven are killed now. The general lesson is the one this repo keeps relearning: a
guard is only as good as the mutation you ran against it, and the first mutation you try
is often the one your test was already shaped to survive.

## D9 — Excel came back mid-session, so everything blocked got measured after all

`EXCEL.EXE` pid 51420 was restarted by a human at **07:28**, arriving fresh at
**1,944 MB** — under the 3,800 MB ceiling. The standing instruction was never "do not
touch Excel", it was "stop at the ceiling"; under the ceiling, the correct action is to
proceed. So D0's consequences were retired rather than handed off, and everything below
is measured rather than deferred.

Excel went 1,967 → 1,945 MB across the whole session's work. The cost was never the
concern; the ceiling was.

### D4 settled — quote-vs-compute, decided by measurement

`scripts/citivelo_bond_calibration.py fetch build`, 2026-08-07, 7 US Treasuries chosen
so accrued spans **0.095 to 2.188** price points. **57/57 tags served.**

| value | verdict | margin |
|---|---|---|
| `PRICE` | **clean**, per 100 face | 0.0186 bp median error vs Citi's own YIELD, against **57.43 bp** if read as dirty |
| `YIELD` | percent, semi-annual | reproduced to 0.0001–0.0008 bp on the four bonds that reconstruct cleanly |
| `DURATION` | **modified** | 1.9e-05 yr median error, against **0.0500 yr** as Macaulay |
| `DV01` | **per 1mm face, positive for a long** | ratio to local per-100 dv01 = 10000.06 median; 9999.997 / 10000.03 / 10000.06 / 10000.09 on the clean four |

Each was settled by asking which reading of one Citi number reproduces **another Citi
number** — never by repricing Citi's figure with our own model and noting that it agrees,
which is a tautology. The margins are factors of 2,600–3,000, so none is a close call.

**Reported against my own interest:** three of the seven bonds do *not* reconstruct
cleanly — yield errors −12.44, +25.70 and +0.62 bp. On the 0.5Y bond that is ~0.006 price
points, i.e. sub-tick rounding; on `US91282CLF67` it is 1.71 price points, which is real
and unexplained. The coupon and schedule come from parsing Citi's description text, and a
wrong first coupon shows up exactly this way. It does not touch the three verdicts, which
turn on ratios far larger than any schedule error can produce, but it is an open question
and not a rounding story.

`ASW_4_<CCY>` is still **unmeasured**: which asset-swap variant `_4_` denotes is open.

### Citi's SWAP_SPREAD is in basis points, and agrees with the repo sub-bp

`scripts/citivelo_swap_spread_tieout.py`, USD_SOFR, 2026-07-08..08-07, 23 daily
observations per tenor. Citi publishes 2Y −14.56, 10Y −41.78, 30Y −75.11 — right
magnitude, sign and term structure for USD swap spreads, three orders of magnitude from a
decimal reading. `UNIT` moved from `"as_published"` to `"bp"`, and the served value did
not move, because Citi was publishing bp all along.

Against the repo's independently computed `SPREADOVER`, median difference per tenor:

| 2Y | 3Y | 5Y | 7Y | 10Y | 20Y | 30Y |
|---|---|---|---|---|---|---|
| +0.036 | +0.386 | +0.015 | +0.067 | −0.002 | −0.069 | −0.156 |

Two different constructions from two different data sources landing under 0.4 bp on all
seven tenors, and under 0.1 bp on five of them. **The mean difference over the same days is ~150,000 bp and is
meaningless** — the repo's own `SPREADOVER` failed to price on **9 of 23 days** and
returns values like −151,276 bp when it does. That is a repo-side gap, not a disagreement
with Citi, and the script now excludes those days from the median, counts them in the
output, and persists the per-day series so nobody can quote the mean by accident. The
first run of this table reported a median of 0.85 bp precisely because the broken days
were still inside the median; excluding them moved it to ~0.05 bp.

### `bulk_get_data` needed a real branch, not a documented gap

The timeseries warm raised `NotImplementedError: Unsupported source USTS_CITIVELO-RL` —
`TimeseriesBuilder` goes through `bulk_get_data`, which had no Velocity branch. It had
been written up as a known gap; it was actually a blocker for the whole timeseries
deliverable. `_citivelo_prefetch_range` now issues **one** `CVTSHIST` over the full date
range and every per-date build is a tag-cache read that opens no workbook. That is not
just speed: N workbook round-trips for one backfill is the growth the ceiling exists to
bound.

### The warms ran

| job | result |
|---|---|
| 7 · bond tags (store) | OK 56.9s — `RATES.BOND` cached **0 → 131** |
| 8 · swap-spread tags (store) | all **11** USD_SOFR tenors cached |
| 9 · FRB values EOD | OK 55.8s — **15 rows × 42 cols** |
| 10 · swap spreads EOD | OK 23.2s — **15 rows × 11 cols** |

Job 8 also raised `OLE error 0x800AC472` on a follow-up call — Excel busy or in cell-edit
mode, consistent with a human using it minutes after restarting it. The tags it was
fetching all landed, which is why it is recorded as an interruption rather than a failure.

### A claim I made and then disproved

I wrote in the hand-off notes that running `--jobs 9,10` without the store warms "warns
and is refused". It warns and **proceeds** — `assert_ordered` deliberately skips a
requirement no *selected* job provides, so a subset that omits the producer entirely is
unconstrained. Checking it is what found it. The warning names the missing warm and the
consequence, which is the behaviour that matters; the doc claim was wrong and is corrected
rather than quietly dropped.

## D10 — "349 seems low" — it isn't, but the universe still moves

Asked directly whether 349 ISINs was too few given new issuance and maturities. It is a
fair challenge and the answer took measuring, because the first check I ran was wrong: I
printed the catalog's maturity range by sorting date **strings** in `M/D/YYYY`, which
gave a meaningless "1/15/2027 .. 9/30/2032". Parsed properly the range is
**2026-08-15 .. 2056-05-15** — 0.02y to 29.8y, the whole curve.

**349 is right.** Measured against the repo's own `fiscaldata` reference table:

| | count |
|---|---|
| Citi `USA.USD.GOVT` | **349** |
| fiscaldata live nominal coupon USTs | **352** |

All 349 carry ticker `T`, real coupons 0.375–6.75, and **zero** zero-coupon
instruments — so this is the nominal coupon note/bond universe, with bills, TIPS, FRNs
and STRIPS excluded as separate instrument classes. Buckets: 106 under 2y, 43 2-3y, 57
3-5y, 31 5-7y, 13 7-10y, 59 10-20y, 40 20-30y. That is the complete curve, not a liquid
subset.

**But the moving-universe concern is real, and it bites in two directions.**

*New issues.* The six live USTs Citi lacks are three when-issued (settling 2026-08-17,
correctly not quoted) and **three issued 2026-07-31 that Citi had still not picked up
eight days later** — `91282CRB9`, `91282CRA1`, `91282CRC7`, which are the on-the-run 2Y,
5Y and 7Y. So `UnifiedQuery(cusip="CT2")` resolves to a real bond this source cannot
quote. That is a property of the vendor, not a bug here, and resolution says so by name.

*Maturities.* This is the one that changes the design. `CVCURVEBOND` is date-stamped, so
it looks like you can ask for a historical constituent list. Measured across five as-of
dates it returns 115 / 150 / 235 / 296 / 349 ISINs for 2021-08-09 through 2026-08-07 —
and their **union is exactly the 349 live today**. Not one matured bond came back. Citi
does not serve the universe as it stood; it serves today's set filtered to what already
existed.

**Decision: the catalog becomes an accumulating union.** `bonds/refresh.py` merges each
refresh into `bond_isins.json` and **never removes**, recording `first_seen`/`last_seen`.
If a matured bond cannot be recovered from Citi, the only way to ever hold its history is
to have seen it while it was live — so run the refresh regularly and the universe grows
into the full picture; run it never and it decays back into a snapshot. New bonds also
get their values probed on discovery, because a bond with no validated tags resolves fine
and then has nothing requested for it.

A guard came straight out of this: the first refresh ran on a **Saturday**, `CVCURVEBOND`
returned nothing, and it logged a cheerful "0 new". Zero served is a publication gap, not
an empty universe, so it now rolls weekends back to Friday and **raises** on an empty
result rather than recording a no-op that looks like success.

## D11 — The intraday warm succeeded and cached nothing

The first full intraday warm reported **349/349 bonds, 698 tags, 134 s** and wrote
**zero** MI01 files. The manifest recorded it as done.

`CitiVeloBondFetcher.fetch` is the right way to *read* an intraday quote — it routes
through `windowed.fetch_windowed`, which chunks under the six-day cliff and verifies
each window's spacing — but it talks to `quotes.client()` **directly**, so nothing it
fetches reaches the tag cache. Driving `CitiVeloQuotes.frame` in sub-cliff windows caches
properly, and is also **5.7× cheaper**: 48 s and +170 MB against 134 s and +971 MB,
because one batched `CVTSHIST` per window beats a worksheet pushed and dropped per batch.

The structural fix matters more than the bug: `warm()` now asks the **cache** whether the
tags actually landed and refuses to mark a batch done when none did. A warm that reports
success and caches nothing is worse than one that fails, and nothing in the previous
design could tell the difference.

Verifying the result then caught my *checker* being wrong rather than the data. The
cached MI01 series has a median gap of 2 minutes, which looks like downsampling — it is
not. A bond does not print every minute: 1,227 of 2,765 gaps are exactly one minute, the
minimum gap is one minute, and every stamp sits on a 1-minute boundary. Median measures
liquidity; only the **minimum** gap measures resolution, because a 10-minute grid cannot
produce a 1-minute gap.

## D12 — A pre-existing bug that blocked every intraday FRB timeseries

`TB/FixedRateBondsTB.py` guarded with `hasattr(cache_map, "_l2_read")`. The row cache is a
`diskcache.FanoutCache`, whose `__getattr__` uses a bare `assert`, and `hasattr` only
swallows `AttributeError` — so the `AssertionError` propagated and killed the call:
`AssertionError: cannot access _l2_read in cache shard`.

It fires whenever the run is large enough to trip `_should_suppress_row_cache_l2`, which
is every intraday request (a two-day 1-minute range is thousands of reference points) and
no small daily one — which is why it survived. Unchanged by this branch, confirmed
against `main`. Fixed in both places with a probe that catches what is actually raised.

## Status at hand-off

Built, tested, **measured**, and both caches warmed. Excel was under the ceiling for the
second half of the session and every deferred item was retired — see D9.

**Done and measured:** the eight values Citi serves per bond, reachable through
`FixedRateBondValue`; alias -> CUSIP -> ISIN resolution verified on 2,162 real ISINs and
349 round trips; Citi's swap spread as `IRSwapValue.CITIVELO_SWAP_SPREAD` alongside the
computed MMSS/SPREADOVER; all three modes; the quote-vs-compute semantics for PRICE,
YIELD, DURATION and DV01; Citi's swap-spread unit and its sub-bp agreement with the
repo's own number; and both warms (pricer cache 0 -> 131 bond tags + 11 swap-spread
tenors; timeseries 15x42 and 15x11).

**Open, and stated rather than buried:**

- `ASW_4_<CCY>` — which asset-swap variant `_4_` denotes is unmeasured. `ql_asset_swap_spread`
  computes par-par and is reconciled to `ql.AssetSwap.fairSpread()` at 4.8e-14 bp, so the
  comparison is one fetch away; it was not run.
- Three of seven calibration bonds reconstruct with yield errors of −12.44, +25.70 and
  +0.62 bp. Sub-tick on the short one, real on `US91282CLF67`. Most likely the coupon or
  first-coupon date parsed from Citi's description text. Does not affect the D4 verdicts,
  which turn on factors of 2,600–3,000.
- The repo's `SPREADOVER` fails to price on 9 of 23 days in the tie-out window and returns
  values like −151,276 bp when it does. Pre-existing, surfaced here, not fixed here.
- `SWAP_SPREAD` off USD is catalog-recorded but never observed to serve. `EUR_EUROSTR` has
  no such node at all; `GBP_SONIA`'s axis is a different ten.
- `USTS_TRADINGVIEW-*` still has no `bulk_get_data` branch; only the Velocity one was added.

**To re-run any of it:**

```
python scripts/citivelo_bond_calibration.py fetch build      # D4 verdicts
python scripts/citivelo_swap_spread_tieout.py fetch compare  # units + agreement
python scripts/daily_cache_warmer.py --jobs 7,8,9,10         # store warms, then values
```

Each aborts on its own if Excel is at or above 3,800 MB, checked **before** anything
connects, so none of them can be the thing that wedges it.
