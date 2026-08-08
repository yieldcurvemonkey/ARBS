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
