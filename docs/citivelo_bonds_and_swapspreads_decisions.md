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
