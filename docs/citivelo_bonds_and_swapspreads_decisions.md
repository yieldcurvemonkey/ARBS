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
