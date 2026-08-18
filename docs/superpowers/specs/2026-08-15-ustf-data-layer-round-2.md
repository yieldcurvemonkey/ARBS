# UST futures data layer, round 2 — what the eight open items turned out to be

**Branch** `fix/ustf-data-layer-2` · **Date** 2026-08-15 · **Predecessor**
`2026-08-14-ustf-data-layer-report.md` (PRs #454, #455, #456, #458)

A handover listed eight open items and said "at least one of the unverified leads is probably
wrong". Three were wrong, and two of those were wrong in the direction that mattered: the thing the
handover was worried about was fine, and something next to it was broken. Two defects nobody had
listed were larger than anything on the list.

Every number below is a measurement. Where a number came from a subagent rather than from me, it
says so.

---

## Summary

| # | Item | Verdict | What it actually was |
|---|---|---|---|
| 1 | BarChart EOD path broken | **Fixed** | Two defects, not one; and the *reason* given for fixing it was false |
| 2 | TU / FV / UXY never panel-tested | **Fixed** | UXY was clean; **TU and FV were broken** by a rulebook clause nobody had implemented |
| 3 | `_fetch_fixings` ignores `as_of_date` | **Fixed** | 4 real lookaheads — plus a 340bp ordering bug nobody was looking for |
| 4 | Poisoned Ultra Bond rows in prod | **Fixed** | 204 in prod (18 locally); the existing rebuild tool **could not** reach them |
| 5 | Swaption cube 40-day COVID hole | **Fixed** | Real, and **recoverable offline** — the data was never missing |
| 6 | `_resolve_contract_symbol` uses IMM dates | **Fixed** | Never named an expired contract; named an **illiquid** one 25% of days |
| 7 | Fixed-principal grade unenforceable | **Refuted** | It IS enforced, and the note saying otherwise was the hazard |
| 8 | V3 arm B lacks the real swaption product | **Partly** | Cost bug fixed (**10,000×**); rewiring designed, not done |

Three findings that were on nobody's list:

- **`_fetch_fixings` returned `USD-OIS` DESCENDING** while returning `USD-SOFR-1D` ascending. So
  `.iloc[-1]` gave 7.03% for EFFR — the July-2000 fixing — and 3.62% for SOFR. **A published
  backtest family's verdict is an artifact of this.**
- **The IMM date was being used as a delivery date** in every basis report, worth up to 5.67/32 of
  net basis and a sign flip in implied repo.
- **Every Good Friday basis report had a NaN net basis, on every root, since 2018** — see §9. Found
  by asking why the rebuilt panels' residual failures were not scattered.

---

## 1 — The EOD path: two defects, and a false premise

**The premise first, because it changes what the fix is for.** The handover said minute history for
old contracts is thin, citing a 2018 probe of `UBU18` that returned one bar. `UBU18` is the
**EUR/NOK future** — the very mismapping the predecessor had just fixed — and it trades ~4 lots a
day. The real Ultra Bond has plenty:

| contract | 2018-06-12 EOD settle | volume | 1-minute bars |
|---|---|---|---|
| `UDU18` | 156.56250 | 130,617 | **993** |
| `ZBU18` | 142.90630 | 279,209 | 1,112 |
| `ZNU18` | 119.40625 | 1,236,771 | 1,153 |
| `ZTU18` | 105.85156 | 374,087 | 737 |
| `TNU18` | 127.01562 | 110,996 | 968 |

So deep history was never blocked on the EOD path. It is still worth having, for a different and
better reason — the vendor request count, which is what actually caused the rate-limit-driven gaps
the predecessor documented. Measured across six contracts spanning three eras and four roots:

```
UDU18 190 bars   ZBZ20 200   ZNM24 188   ZTU26 157   TNU26 164   ZEU26 157
1,056 settlement days retrieved in 6 requests, 1.4 seconds total.
The minute endpoint needs ONE REQUEST PER DAY -> 1,056 requests for the same coverage.
```

A **176× reduction** per contract. That is the unlock; the "thin minute history" story was not.

**Defect 1a.** `queryeod` bars are date-stamped and tz-naive. `USTFuturesMDP` localizes 00:01 and
23:59 to Chicago. Comparing them raised `Invalid comparison between dtype=datetime64[ns] and
datetime` **inside the retry loop**, so it was swallowed, re-fetched five times against a
rate-limited vendor, and returned an **empty frame** with no error reaching the caller.

**Defect 1b, and it is why a naive fix would have been worse.** Making the comparison legal is not
enough. A `00:01` start against a bar stamped `00:00` drops that day — measured before any fix, a
naive `00:01` start already lost `2026-08-03` while `00:00` kept it. Since the MDP asks for exactly
one day at a time, "fixed" would have meant every EOD request silently returning zero rows.

The window is now compared at **date granularity**, inclusive, with the date taken in the boundary's
own timezone — never via UTC, which would push a 23:59 Chicago end onto the next day. One helper
feeds the per-symbol filter, the `one_df` merge filter and the server-side URL params.

**Live acceptance**, `ZBU26` 2026-08-03 → 08-13:

| window | before | after |
|---|---|---|
| tz-aware 00:01 → 23:59 | **empty** | 9 settles, 08-03 … 08-13 |
| naive 00:01 → 23:59 | 8 settles (**08-03 lost**) | the same 9 |
| naive 00:00 → 23:59 | 9 settles | the same 9 |

### The second finding the handover asked for

It asked whether EOD settles disagree with the minute-derived prices already in the store. They do.
`get_pricer` defaults to `interval=1` and picks the bar nearest 14:00 Chicago, so **every historical
UST futures price in the store is a one-minute bar, never a settlement**. Over 59 sampled days, six
contracts, three eras:

| | median | mean abs | max abs |
|---|---|---|---|
| minute@14:00 CT − EOD settle | **0.000/32** | **0.79/32** | 4.00/32 (Oct-2020) |

Unbiased, and the median of exactly zero is itself the evidence that 14:00 CT *is* where the
settlement is struck — which is what makes it safe to stamp an EOD frame at 14:00 Chicago so the
MDP's nearest-timestamp lookup works. That lookup was the second half of the fix: `get_pricer(
interval=None)` raised `Cannot compare dtypes datetime64[ns] and datetime64[ns, America/Chicago]`
until the frame carried a timezone.

0.79/32 is small but not nothing against a net basis whose healthy range is ±11/32, and neither the
layered cache key nor the snapshot partition recorded which convention it held — so an EOD backfill
would have silently overwritten, and been served in place of, minute-derived prices. Both now carry
a `price_source` tag, **selected** rather than ordered on read. Untagged rows are one-minute bars by
definition and the default interval's cache key is unchanged, so warm caches stay warm.

**Deliberately not done:** the store's convention is left as the minute bar. Switching it to
settlement is a one-line default change that would invalidate every price in the store for a median
improvement of 0/32. It is now *possible* and *labelled*, which is the reversible half.

---

## 2 — TU, FV and UXY: the clean one was the one under suspicion

The handover's lead was that **UXY**'s `exact_original_term_months={120}` was too strict and would
silently drop an aged bond reopened as a 10-year note. The named CUSIP was `912810FT0`.

**UXY is clean.** Tied out CUSIP-for-CUSIP against CME's published Treasury Conversion Factor file
for the first time in this root's life (subagent-measured): `TNU26` 3/3, `TNZ26` 2/2, `TNH27` 1/1,
with every conversion factor matching to 4dp. `912810FT0`'s only reopening was as a *29-Year 6-Month
bond* in 2006; Treasury issued a fresh CUSIP (`91282CPZ8`) for the same Feb-2036 maturity, and CME's
own `TNU26` basket confirms its absence 3/3. `exact_120` was measured **inert** — identical baskets
across all 52 UXY contract months, because among real UST original terms only a 120-month note can
carry 113+ months remaining.

**TU and FV were broken**, by a clause the static bounds cannot express. CBOT Chapters 20 and 21:

> If the U.S. Treasury Department auctions and issues a Treasury security that meets these
> standards, such that said security is a **re-opening** of an extant Treasury issue that had not
> previously met these standards, then the extant Treasury issue shall be deemed to be a Treasury
> note meeting these standards and shall be added to the contract grade **as of the issue date** of
> said newly auctioned Treasury security.

A 7-year note reopened later as a 5-year is deliverable into ZF. Eligibility keyed off `oi`, and
`fiscaldata` collapses a CUSIP's tranches keeping the **earliest**, so `oi` read "7-Year" forever and
the 63-month cap dropped it. Against CME's published file for 2025-03-03:

| contract | CME | ours, before | missing |
|---|---|---|---|
| `ZTH25` | 11 CUSIPs | 10 | `912828Z78` (T 1½ Jan-27), CME CF **0.9229** |
| `ZFH25` | 10 CUSIPs | 9 | `91282CGQ8` (T 4 Feb-30), CME CF **0.9159** |

I verified this myself rather than inheriting it. The auction record is decisive:

```
912828Z78  Note  original 7-Year  security_term 7-Year  issued 2020-01-31  reopening No
912828Z78  Note  original 7-Year  security_term 5-Year  issued 2022-01-31  reopening Yes
91282CGQ8  Note  original 7-Year  security_term 7-Year  issued 2023-02-28  reopening No
91282CGQ8  Note  original 7-Year  security_term 5-Year  issued 2025-02-28  reopening Yes
```

and building the baskets before the fix reproduced the miss exactly.

**The obvious fix is wrong, and that was measured rather than argued.** Relaxing TU's cap from 63 to
84 months does give `ZTH25` 11/11 — and also admits `912828YX2`, `912828ZB9`, `912828ZE3`, which CME
does not list. Eligibility has to key on the **term at issue of the shortest tranche**, which is why
the repair reaches the reference-data layer and not only the spec table. That term is computed from
dates, not parsed from `security_term`: the string form runs to "29-Year 6-Month" and a parser
keeping the leading number rounds *down*, the permissive direction for a cap.

**After the fix:** `ZTH25` 11/11 with CF 0.9229, `ZFH25` 10/10 with CF 0.9159 — both matching CME to
4dp — and the three false positives stay out. Current contracts unchanged: `TUU26` 10, `FVU26` 9,
`UXYU26` 3, `TYU26` 11, all matching CME.

**Vintage-gated**, because a grade is not a constant. CBOT submission 25-099 (CFTC filing
2025-02-21, SER #9520 — confirmed verbatim from the CFTC portal by subagent, including the
`912810FT0` sentence) adds the clause to Chapters 19 (TY) and 26 (UXY) "commencing with the March
2026 contract month", and describes it as "language similar to what currently exists in … Chapter
20" — i.e. FV and TU already had it. Applying one rule to all four across all history would repeat
exactly the mistake the predecessor documented for TY's 8-year cap.

### The panels

Rebuilt with the corrected layer, every 5th business day, 2018-06-01 → 2026-08-13:

| root | contract | rows | gate pass | median deliverables | median futures px |
|---|---|---|---|---|---|
| **TU** | 2-Year | 417 | **100.0%** | 9 | 104.68 |
| **FV** | 5-Year | 417 | **99.8%** | 8 | 111.95 |
| **TY** | 10-Year | 417 | **99.8%** | 16 | 117.78 |
| **UXY** | Ultra 10-Year | 417 | **99.8%** | 2 | 125.16 |
| **US** | Classic Bond | 417 | **98.6%** | 45 | 137.19 |
| **WN** | Ultra Bond | 417 | **99.8%** | 19 | 150.34 |

**The number that matters is not the pass rate — it is that all 11 failures across 2,502 rows have
exactly two causes, and both are already named.**

| cause | rows | roots |
|---|---|---|
| **2023-02-10** — the corrupt FedInvest cash day the predecessor diagnosed | 5 | FV, TY, UXY, US, WN (TU's 2-year basket is unaffected) |
| **`USH22`, 2022-01-21 → 02-18** — the residue below | 5 | US |
| — | | |
| **false positives** | **0** | |

By year, every root is at 100% except 2023 (the one cash day) and US in 2022 (the `USH22` run):

| root | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| **TU** | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| **FV** | 100% | 100% | 100% | 100% | 100% | 98% | 100% | 100% | 100% |
| **TY** | 100% | 100% | 100% | 100% | 100% | 98% | 100% | 100% | 100% |
| **UXY** | 100% | 100% | 100% | 100% | 100% | 98% | 100% | 100% | 100% |
| **US** | 100% | 100% | 100% | 100% | **90%** | 98% | 100% | 100% | 100% |
| **WN** | 100% | 100% | 100% | 100% | 100% | 98% | 100% | 100% | 100% |

For scale, the predecessor's three roots ran 96.8% / 99.8% / 99.7% with 15 failures, of which 10
were the unresolved `USH22` run and 5 were Good Fridays nobody had identified as such.

UXY's basket of 2–3 deliverables is **correct**, not suspicious: the Ultra 10-Year grade is a
seven-month window (9y5m–10y remaining) and CME's own prose says the contract "consists of the three
most recently issued 10-Year notes".

### Z3N and TWE

Both had specs, tick specs and conversion-factor support and **no vendor root**, so nothing could
fetch them and nothing ever checked them. Both roots found — and found the way the Ultra Bond taught,
on the **tick grid**, not the price band:

| symbol | range | max volume | in 50–300 band | on tick grid | |
|---|---|---|---|---|---|
| `ZEM22` (Z3N) | 106.52–115.53 | 31,176 | 100% | **100%** (1/256) | |
| `ZEU26` (Z3N) | 104.06–107.13 | 9,690 | 100% | **100%** | |
| `ZZM22` (TWE) | 136.34–175.63 | 1,896 | 100% | **100%** (1/32) | |
| `UBU26` | 10.81–12.45 | 398 | **0%** | 2.8% | EUR/NOK — negative control |
| `TBU26` | 96.03–97.19 | 4,921 | **100%** | **4.3%** | **the trap** |

`TB` is why the controls are in the report: it sits inside the plausible band and would have passed a
band check, exactly as `UB` did.

**Z3N is live and usable** — `Z3NU26` at 2026-08-13: 104.62500, 10 deliverables, min BNOC −0.42/32,
gate passes. **TWE is wired and not usable**, which is the honest outcome:

| contract | bars | distinct closes | max volume | bars with volume |
|---|---|---|---|---|
| `ZZM22` | 75 | 70 | 1,896 | 63 |
| `ZZM23` | 189 | 149 | 212 | 72 |
| `ZZH24` | 188 | 96 | **0** | **0** |
| `ZZU26` | 164 | **1** (125.50) | **0** | **0** |

The mapping is right; a TWE panel is not buildable from this vendor.

---

## 3 — The fixings blast radius, and the bug underneath it

`_fetch_fixings`' `as_of_date` selects a cache **vintage**, never a data **window** — it feeds the
cache-accept gate and the 08:00 ET staleness re-pull, and nothing truncates. A subagent enumerated
**40 production call sites in 8 patterns**: four were defects, five legitimately want the whole
history, and the rest are benign *because the caller clips* — which is only benign given what the
next paragraph establishes.

**The framing that made this look minor is false, and that is the main result.** It was assumed a
too-long series is harmless because a curve "only consumes fixings up to its valuation date". I
measured rateslib 2.7.1 directly: on a curve anchored 2018-06-12, varying the post-anchor fixings,
a SER Sep-2018 STIRFuture returned **exactly 3.000000 / 4.000000 / 5.000000 / 6.000000%** as those
fixings were set to 3 / 4 / 5 / 6%. It priced the contract entirely off realised future fixings. A
staircase test — truncating progressively later — moves monotonically and stops exactly when the
series covers the whole accrual. So every clip in this repo is load-bearing.

Fixed:

- **`rl_usd_sofr_mt_builder_parallel` clipped nothing.** `IRSwapsMDP` clips once at max(batch) and
  the builder fanned that one series out to every snapshot, so a batch spanning a quarter priced its
  first day off fixings published months later. The dispatch loop already buckets by day; the clip
  goes there and covers every source routing through it.
- **`_make_key` hashed the raw batch-wide series**, which grows daily — so a 2018 snapshot's cache
  key changed every day and the curve cache never hit for any historical snapshot.
- **`STIRFutureMDP`** (two sites) and **`SDRUtils/analytics/fomc.py`** filtered `<= ref_date`. SOFR
  for day D publishes 08:00 ET on D+1, so that is a one-business-day peek — subagent-measured at
  0.39 bp on a front SER Jun-2018 contract, systematic and in the same direction daily. A test
  asserted the reference date's own fixing was present, i.e. it **pinned the peek**; inverted, with
  the reason in the test.
- **`IRSwapsMDP:4054`** handed the solver the series unclipped *and* in decimals while the same
  series was scaled and clipped before attaching to each output curve — the two disagreed by 100×.
  **This produced no wrong number**, and the reason matters: `_N_SER_CONTRACTS = 0` for that source,
  so `get_short_end_curve_tickers(first_n_sr1=0)` returns no SER ticker and `build_rl_stirf` attaches
  fixings to the SER leg only (the SFR line is commented out). I measured that rather than assuming
  it. Raising the constant would have activated a 100× unit error and a full-history lookahead in one
  step. Fixed as a landmine, and this report says so rather than claiming a save.

`_fetch_fixings`' *return* is deliberately unchanged: five callers genuinely want the whole history.
It now has a docstring stating the contract, plus `fixings_before()` / `fixings_asof()`.

### The bug underneath: the series was not sorted

Measured, from one call each:

```
USD-SOFR-1D : n=2183  ascending   .iloc[-1] = 0.036200  (2026-08-13)
USD-OIS     : n=6563  DESCENDING  .iloc[-1] = 0.070300  (2000-07-03)   <- should be 0.036300
```

`.iloc[-1]` reads as "the latest fixing". On EFFR it returned the fixing for **3 July 2000** — a
340 bp error, on one curve and not the other, from an identical expression. Curve-dependent and
cache-vintage-dependent, so it surfaces in one place and not the next and looks like a data problem.

`_fetch_fixings` now guarantees chronological order, because no caller can want a descending series.

### **This voids a published backtest verdict**

`notebooks/backtests/linvol_grid_common` computed its SOFR–EFFR basis with `.iloc[-1]` on both
curves. A subagent measured the published `ics_residuals.parquet` and found the basis is a
**constant −523.0 bp on all 3,230 rows** — exactly (first-ever SOFR 1.80%) minus (first-ever EFFR
7.03%).

**My own recomputation gives −520.0, and the discrepancy is worth more than the agreement would
have been.** Today's cache has SOFR *ascending* with its first row 2018-04-03 at 1.83%, because
2018-04-02 is a Good Friday whose fixing is NaN (§ the Good Friday defect below). The agent read a
vintage in which the SOFR CSV was descending too, with 2018-04-02 = 1.80% present. So the constant's
*value* moves with which cache vintage is on disk — which is the sharpest possible statement of the
defect: **the same code produces a different wrong number on different days**, and neither is a
market price.

What is invariant, and what I did verify directly: EFFR comes back descending, so its `.iloc[-1]` is
**always** the 2000-07-03 fixing of 7.03%, and the basis is wrong by roughly 340 bp on every row
regardless of vintage.

A large constant offset makes both entry thresholds no-ops (the `thr=2` and `thr=3` league rows are
byte-identical, so the published "8 configs" are really 4), pins the trade sign to one side, and
removes the convergence exit entirely (0 convergence exits; 1,056/1,056 time stops).

A subagent replayed the grid on a corrected basis — its harness first reproduced the published
`league_E.parquet` to **max abs error 0.00e+00 across 8/8 configs**, which is the calibration that
makes the rest credible — and reports the verdict **flips sign**: best `net_1x` from **−98.11 bp
(t = −2.70)** to **+704.45 bp (t = +10.68)**.

**I did not re-run that grid myself and I am not claiming a live strategy.** What is established is
that the published family-E "DEAD" verdict is an artifact of a data bug and **cannot stand as
evidence either way**. It needs re-running. This is the single most consequential thing in this
report that was on nobody's list.

---

## 4 — The Ultra Bond in production: worse than local, and out of the rebuild tool's reach

Prod held **204** unstamped WN snapshot partitions against 18 locally (subagent-measured, then
re-measured by me). They were **inert** — `_SNAPSHOT_QUARANTINE_ROOTS = {"WN"}` rejects unstamped WN
rows — proved empirically with an emptied local store and a non-WN control that was correctly served.

The finding that made a repair worth doing: **`rebuild_basis_panels --force-refresh` cannot reach
them.** That driver walks the *front* contract only, and the poisoned partitions are precisely the
post-roll **tail** of each expiring contract plus pre-2018 history — the complement of its orbit.
Re-running it, however many times, repairs zero.

Repaired with a per-(symbol, date) sweep: `force_refresh=True` refetches under the corrected `UD`
root, rewrites the partition **with** the stamp, and enqueues the re-push;
`wait_for_background_pushes()` before exit, because the push workers are daemon threads and a script
that returns early leaves prod poisoned.

**204 / 204 repaired, 0 failures, 139 seconds.** |Δ| median 10.75 points, max 75.91.

**Proof it reached prod**, with an empty local store so every byte came from Supabase:

```
prod WN blocks: 2234   stamped: 2234   UNSTAMPED: 0
prod WN blocks before 2023 priced 105-118 (impossible for the Ultra Bond then): 0

WNH16 2016-01-25  old 110.453125 -> served 164.68750
WNM15 2015-05-04  old 109.684375 -> served 161.34380
WNH19 2019-01-02  old 111.903125 -> served 161.62500
WNH20 2019-12-26  old 111.873437 -> served 182.96880
WNH23 2022-12-27  old 111.556250 -> served 134.53125
```

Not one served value could have come from the old data.

The basis-report table needs no repair: 3,012 of 3,157 blocks are self-invalidating by version or
fingerprint, the 145 current ones carry plausible prices, and **zero blocks anywhere carry
`data_ok = False`**. Deleting the inert junk would reclaim ~37 MB and is housekeeping, not
correctness — deliberately not done, because a `DELETE` against production for tidiness is a worse
trade than 37 MB.

**Unresolved, and stated rather than buried:** 40 unstamped WN blocks carry a prod write timestamp
of 2026-08-14, 02:40–04:06. The likeliest explanation is simply the predecessor's own pilot runs,
before its vendor-root fix landed in that session — but I measured *what* landed, not *how*, and two
other mechanisms are consistent with it: the background pusher re-reads `pq_files[-1]` rather than
the bytes it just wrote, and `_pull_day` deletes sibling parquets under a concurrent write. That
writer is quiescent (no unstamped row touched since) and the quarantine made the residue inert, so
this is a loose end rather than an active risk — but it is not identified, and a stamp-based defence
only works against roots someone has thought to quarantine.

---

## 5 — The swaption cube: real, bigger than reported, and recoverable offline

Confirmed by direct store scan, and it is worse than the claim: **60 of 2,702 days degraded**, 59 of
them contiguous, in two phases because the rectangle search maximises area over a sparse mask and the
orientation flips:

| window | days | shape |
|---|---|---|
| 2020-01-24 → 2020-03-24 | 40 | expiries amputated — **no expiry shorter than 4Y** |
| 2020-03-25 → 2020-04-21 | 19 | tenors amputated — down to 2–4 tenors |
| 2020-03-09 | *(within the 40)* | the worst: **1 expiry × 5 tenors**, minimum expiry 15Y |
| 2026-08-12 | 1 | a 1×2 rectangle kept over the full 17×9 |

**The diagnosis in the handover was wrong.** It is not a warm-config artifact and the source tag flip
is a symptom, not a cause. `scripts/citivelo_swaption_vol_warm.py::build` tried the full 13-offset
grid first and took the **first build that succeeded, whatever survived** — ranking a day by smile
richness when what matters is which part of the curve you can price. The cause is structural, not a
run of bad days: `_largest_rectangle` requires **every** offset present, and a 1Y option has no
−200bp strike when rates are ~1.5%, so one structurally unquotable wing amputates a whole expiry row.

Ranking is now **ATM axis coverage** (expiries × tenors), smile richness only as a tie-break. The
distinction decides every degraded day: an 8×9×13 cube is 936 numbers against the ATM surface's 153,
so ranking by total quote count would have changed nothing. That is asserted in the tests, because
my first version of those tests got it wrong and would have locked in the misunderstanding.

**The data was never missing upstream**, so the repair needed no Excel, no Citi and no sign-in — the
recorded blocker does not apply. After an offline rebuild over the affected days (`--start`/`--end`
added for this):

```
before: 2,702 stored days, 60 degraded
after : 2,702 stored days,  0 degraded

1M x 10Y ATM vol, previously absent:
  2020-01-23   60.9 bp        2020-03-09  168.2 bp
  2020-03-20  152.7 bp        2020-04-22   83.4 bp
```

That 168 bp print on 2020-03-09 is the COVID vol spike — the most valuable observation in the
sample, and it was not there. Recovered days carry `citivelo_excel_warm/DAILY/atm_only` in `source`,
so a consumer can tell an ATM surface from a full smile without inspecting axes.

**Pushed to L2 and verified**, applying item 4's standard: 59 + 3 days rewritten,
`verify` returns 65 and 8 days checked, **0 problems**. A local-only repair would have been undone by
the next machine's `prefetch_range`.

---

## 6 — The roll: the suspicion was backwards

**Four** sites resolved a bare root with IMM-date arithmetic, not two. They agreed only because all
four were written identically — so fixing one would have made `warm_ustf_cache` warm `TYU26` while
`usd_swaps` read `TYZ26`, with no error anywhere.

The handover's concern was that the IMM rule names **expired** contracts. Over 2,168 CME business
days, 2018-2026, it never does — the IMM date always falls before the last trading day
(subagent-measured, from 88 BarChart frames / 16,431 bars). The real defect is the opposite: it holds
the expiring contract a **median 16 business days** past the liquidity roll.

Against the contract actually carrying the most open interest:

| rule | TY | TU | WN |
|---|---|---|---|
| IMM (previous) | 25.3% wrong | 25.4% | 26.9% |
| last trading day | 28.8% wrong | **39.9%** | 29.4% |
| **first position day** | **3.7%** | **3.8%** | **4.4%** |

On the days the IMM rule was wrong, the contract it named held a **median 0.8–1.2%** of the liquid
contract's open interest, and under 10% of it on 88% of them — 56–60 days a year, per root, of
quoting a contract nobody trades. The price was never garbage, which is exactly why this was
invisible.

**The obvious fix is worse than the bug.** Rolling at the last trading day is the delivery-correct
answer and measurably the worst quoting answer, above all for TU (100.5 days a year wrong vs 9.5).
Every implicit caller in the repo feeds a quote path; every delivery caller already passes an
explicit symbol. `ust_deliverable_contract()` now exists for the other question so the next person
does not reach for `front_month`.

**The calendar is the discriminator, so I validated it myself.** CME closes Good Friday, **trades**
Columbus Day and Veterans Day, and observes New Year `sunday_to_monday` — it traded 2021-12-31.
Against the last bar BarChart holds for every expired contract, six roots, 2018-2025:

| calendar | exact |
|---|---|
| CME interest-rate | **192 / 192** |
| `pandas.USFederalHolidayCalendar` | 174 / 192 |

The 18 it misses are Good Friday 2018 and 2024 and the 2021 New Year. Both the fixture and that
mutation check are in the test file, because a golden table any calendar passes proves nothing.

**The one place this could make production worse**, closed by construction rather than left
unmeasured: `usd_swaps._build_invoice_swap_lookup` resolves from a bare root, and rolling ~16 bd
earlier would drop the expiring contract while SDR invoice swaps still reference it. The lookup now
takes the union `{front, back, still-deliverable}` — two symbols outside the roll, three inside — a
strict superset of either rule's coverage.

### The adjacent defect, which was larger than the roll

`RLUSTFuturePricer._resolve_delivery` fell back to the contract's **IMM date**, and
`_build_basis_report_frame` calls that fallback directly — so **every basis report carried to the
third Wednesday instead of a delivery day**. The pricer already knew better: `_delivery_dates` holds
the `(first, last)` business-day window the MDP computed, and the method ignored it.

| symbol | date | min net basis @ IMM | @ last delivery | Δ | max IRR @ IMM | @ last delivery |
|---|---|---|---|---|---|---|
| `USZ20` | 2020-10-15 | +4.03/32 | −1.64/32 | **−5.67** | −39.23% | **+26.04%** |
| `TYZ20` | 2020-10-15 | +2.20/32 | −0.58/32 | −2.79 | −26.22% | **+17.69%** |
| `USU26` | 2026-08-13 | +2.80/32 | +1.44/32 | −1.36 | 261.34% | 326.17% |
| `WNU18` | 2018-06-12 | −1.57/32 | −3.01/32 | −1.44 | 183.06% | 195.22% |

`_BASIS_REPORT_SCHEMA_VERSION` 3 → 4 accordingly. **Operational consequence:** every stored basis
report is now a miss, so the nightly warmer rebuilds the lot once.

#### It partly explains the residue the predecessor could not resolve

The 2026-08-14 report left 10 `USH22` rows failing over Nov-2021 → Feb-2022 — net basis +80 to
+100/32 against 0.05% funding — and said "I did not resolve which" between a delivery-option-rich
period and the overnight-vs-term repo deviation. The delivery-date fix is a third candidate nobody
had, and it is a real contributor but not the answer. Comparing all 410 US rows, before and after:

| | value |
|---|---|
| Δ min net basis | median **−1.23/32**, mean −1.93, range −6.51 … +1.53 |
| Δ deliverable count | **0 on all 410 rows** |
| futures price identical | **100.0%** of rows |
| `USH22` failures cleared | **5 of 10** (−5.7/32 on each) |

The basket and the price are untouched — only the carry moved, which is exactly what changing the
delivery date should do, and is the check that the change is what it claims to be. The shift is
systematic and one-signed.

The five `USH22` rows that remain are the ones closest to delivery, still at +75 to +95/32 with
implied repo from −1020% to −1807%. So **the hypothesis survives as a contributor and dies as an
explanation**: the predecessor's overnight-versus-term repo reading — a CTD on special, funded far
below the overnight fixing — remains the live candidate for the residue.

The test that asserted the delivery date *was* the IMM date had pinned the defect. Inverted and
renamed, with the reason in its docstring — the same treatment the predecessor gave the
`11.13 → 111.40625` assertion.

---

## 7 — Refuted: the fixed-principal grade is enforced

The module note said the "no TIPS, no FRNs" leg was unenforced because the frame has no
security-type column, and recorded it as latent. **That was wrong in the direction that invites
damage.** The rule is enforced — at *fetch* time, by `inflation_index_security:eq:No` in the auctions
query plus the FRN drop — and by nothing else. A reader who believed the note could delete that
filter as redundant.

Measured by re-fetching with the filter removed (subagent): 106 TIPS CUSIPs enter the frame and
contaminate the December-2026 basket of **all six roots** — TYZ26 3, TUZ26 1, FVZ26 1, USZ26 10,
WNZ26 5, TNZ26 1. I reproduced the mechanism directly: injecting `91282CJY0` (TII 1¾ Jan-34) into the
reference frame puts it in the `TYZ26` basket, because a 10-year TIPS is `security_type='Note'` with
a fixed `int_rate` and semi-annual payments — so `oi` reads "10-Year" and every filter passes it.

`security_type` is genuinely redundant: measured, the API returns the identical 2,375 rows with and
without it, *because* TIPS ride as Note/Bond. `inflation_index_security` is not.

Changes: the note now says what is true with the counts attached; `_prepare_reference_data` drops
flagged rows so the grade is enforced where the basket is **built**; and the loader keeps the two
markers. Frames lacking them pass through unchanged rather than failing closed — a legacy cached
parquet has neither — and `test_the_guard_calibrates_against_an_unflagged_tips` asserts that limit
rather than describing it.

---

## 8 — V3 arm B: the cost bug fixed, the rewiring not

`v3.py` charged the swaption round trip as `ann * (swaption_cost_vol_bp / 1e4) * sqrt(T/2π)`. The
module is bp-native **by declaration** and `swaption_annuity` is "$ per bp on $1mm", so the `/1e4`
divides by ten thousand a second time. Verified against the module's own `normal_receiver_price`:
the ATM value is exactly `ann * vol_bp * sqrt(T/2π)`, **ratio 1.00000000**.

| root | charged | should have been | vs that arm's basis fees |
|---|---|---|---|
| UB | $0.63 | **$6,332** | 1.4% |
| ZB | $2.39 | **$23,948** | 2.3% |
| ZN | $2.22 | **$22,203** | 1.5% |

The pre-registration's "a separate swaption round-trip cost in normal-bp of vol — an RV trade costed
on one leg only flatters itself" was therefore **not met** until now. The published "arm B agrees to
within $2.40 on $1.5m" was measuring exactly this: the QDB path folded in the swaption's *marks* and
never charged its *cost*, so the residual **was** the uncharged cost, to the cent. Both statements
in the results doc now carry addenda.

The verdict does not move — the correction is strictly negative-going against 0 of 198 profitable
cells, best Sharpe −0.230 vs E[max | null] 0.638.

**Not done:** arm B still books the swaption as a cash adjustment at unwind rather than through the
registered `Query/IRSwaptions` product, so its intraday marks are wrong by up to **$121,703 on ZB**
(subagent-measured). The full wiring design exists — API contract, the two-clock marking rule
(`qdb[t] = B[t if exit else t−1] + S[t] − fees`), the roll/gap early-unwind case affecting 36 of
2,783 arm-B trades, and the legitimate residuals — and is deliberately not implemented here: it needs
the Citi cube context for its slow test (~166 s first call), and it cannot change a verdict that is
already 0/198.

---

## 9 — The one the panels found: every Good Friday, every root, since 2018

This was not on the list, and it is the clearest argument for rebuilding a panel rather than
trusting a spot check. The rebuilt panels' residual failures were not scattered — they were **the
same five dates on every root**: 2021-04-02, 2023-04-07, 2024-03-29, 2025-04-18, 2026-04-03. All
Good Fridays.

It reads as a market-holiday data gap, and it is not one. On those days the cash prices, yields,
gross basis and implied repo are all present and finite; only `bnoc` and `repo_rate` are NaN. SOFR
does not publish on Good Friday — SIFMA closes — and the NY Fed series says so with an **explicit
NaN row** rather than an absent one:

```
2021-04-01  0.0001
2021-04-02     NaN   <- .iloc[-1] of a slice ending here
2021-04-05  0.0001
```

`_resolve_repo_rate` slices `<= as_of` and takes the last element, which lands on that NaN. So the
repo rate is NaN, so every net basis on the day is NaN, so the whole day fails the gate. One day a
year, per root, on all six, for the entire sample.

`_chronological` now drops non-finite rows as well as sorting — a NaN is not a published fixing, and
no caller can want one. Those days now price and pass:

| contract | date | repo | min net basis |
|---|---|---|---|
| `TUM21` | 2021-04-02 | 0.010% | +0.14/32 |
| `FVM23` | 2023-04-07 | 4.810% | +2.57/32 |
| `UXYM24` | 2024-03-29 | 5.340% | +3.98/32 |
| `TUM26` | 2026-04-03 | 3.660% | −1.44/32 |

The transferable part is not the bug, it is how it was found: a gate that rejects a *pattern* of
dates is telling you about itself, not about the market. The predecessor's report had already
recorded Good Friday days as "no cash data — correct behaviour"; they had cash data all along.

---

## What I did not do

- **Did not re-run the linvol family-E grid.** The published verdict is void; establishing what
  replaces it is a research task, not a data-layer repair.
- **Did not implement arm B's product wiring** (above).
- **Did not switch the price store to settlement prices.** Possible and labelled; a full
  re-derivation for a median 0/32 is not worth it today.
- **Did not delete the inert junk** in `arbs_ustf_basis_report_blocks_v1`. ~37 MB, entirely
  unreachable.
- **Did not identify the writer** that put 40 unstamped WN blocks into prod on 2026-08-14.
- **Did not read CBOT Chapters 20, 21, 17, 26 or the 3-Year chapter directly** — cmegroup.com blocks
  this host. Chapters 19 and 26 are verbatim from the CFTC copy of 25-099; the others are validated
  empirically against CME's published conversion-factor files instead, which is a weaker citation and
  a stronger test.

## Verification

- **Regression tests added:** `test_barchart_eod_window`, `test_ustf_price_source`,
  `test_fixings_asof`, `test_ustf_fixed_principal_grade`, `test_ustf_roll_convention`,
  `test_ustf_reopening_clause`, `test_ustf_vendor_roots`, `test_swaption_cube_warm_choice`,
  `test_bvv_v3_swaption_cost`.
- **Red against `main`**, in a scratch worktree, on *behaviour* rather than import: the tz-aware EOD
  window returns empty (`assert not True`); the curve-cache key differs by hash; the early snapshot
  in a two-day batch receives the full 2019-12-31 series; the STIR pricer keeps the reference date's
  own fixing; the marked TIPS and FRN are both in the basket. Tests whose *modules* are new fail on
  import there, which is proof of novelty and not of redness — stated as such.
- **Tests that pinned defects, inverted with the reason in the docstring:** the STIR inclusive
  fixings filter, the IMM-date delivery assertion, and the UXY exact-original-term row.
- **Full fast gate: 8,393 passed, 1 failed, 81 skipped, in 35 minutes.** The failure is
  `test_citivelo_read_path_perf.py::test_fixings_kwargs_resolve_once_per_wrapper` — the same
  full-suite state effect the predecessor recorded, and it **passes in isolation on this branch**
  (checked, not assumed). `test_citivelo_excel_supervisor.py::test_not_signed_in_means_keep_waiting`
  is deselected per the recorded pywinauto hang. For comparison the predecessor's run was 7,973
  passed / 2 failed.
- **Two production data repairs, both verified by reading the data back rather than by trusting the
  writer:** 204/204 Ultra Bond snapshot partitions in Supabase (read back through the gated path
  with an emptied local store, so every byte came from prod), and 62 swaption cube days pushed to
  L2 (`verify` → 65 and 8 days checked, 0 problems). Neither deleted anything; both were
  content-diffed rewrites of data already known to be wrong.

## Panels and data

Committed at `docs/superpowers/specs/_data/2026-08-15-ustf-panels/`.
