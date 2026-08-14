# UST futures data layer — what was broken, what is fixed, what is not

**Branch** `fix/ustf-data-layer` · **Date** 2026-08-14 · **Scope** the shared UST futures
market-data path (`MDP/USTFutures`, `Query/USTFutures`, `definitions/USTFutures.py`)

This started from a handover listing three measured defects that made 2 of 3 futures roots
unmeasurable. It found **six**, of which the largest was not in the handover: the Ultra Bond's
price was never a Treasury price at all. Every claim below is a measurement; where something is
inferred or unverified it says so.

---

## Summary

| # | Defect | Status | Evidence |
|---|---|---|---|
| 1 | Ultra Bond price was the **EUR/NOK exchange rate** | **Fixed** | vendor root `WN → UB`; BarChart's `UB` is the CME Euro/Krone future |
| 2 | ZN basket admitted **old 30-year bonds** and notes 6 months too short | **Fixed** | 58.5% of ZN days named a non-deliverable bond as CTD |
| 3 | ZB's 2020–21 "rejects" | **Not a defect** — the gate was wrong | carry, not corruption; net basis is ~0 there |
| 4 | Repo rate **ignored the reference date** | **Fixed** | every historical report used *today's* SOFR |
| 5 | `get_basis_report` **raised for every root** on rateslib 2.7.1 | **Fixed** | bare `"ActAct"` rejected by 2.7.1 |
| 6 | Report builder zipped **one basket's labels against another's risk** | **Fixed** | latent; fires on the first `force_refresh` after a spec change |
| — | Conversion-factor formula | **Correct as written** | 182-row tie-out; 165 Burghardt values matched |

---

## Defect 1 — the Ultra Bond was an FX rate

**The handover's framing was that UB's price was "derived, mismapped, or stale". It was none of
those: it was a different instrument.**

`definitions/USTFutures.py` mapped internal root `WN` to BarChart root `UB`. BarChart's `UB` is the
**CME Euro/Krone (EUR/NOK) FX future** — confirmed directly on
[barchart.com/futures/quotes/UBU26](https://www.barchart.com/futures/quotes/UBU26), which renders as
"Euro/Krone Sep '26 Futures", contract size EUR 125,000, last 10.945. BarChart's Ultra 30-Year
Treasury-Bond is root **`UD`**
([UD*0/profile](https://www.barchart.com/futures/quotes/UD*0/profile), CBOT, $100,000).

Measured over four eras, `UD` vs `UB` with `ZB` as a control:

| window | UD (Ultra Bond) | UB (Euro/Krone) | ZB control |
|---|---|---|---|
| 2018-06 | 155.13 – 160.13, **vol 11,992** | 9.46 – 9.54, vol 4 | 142.09 – 145.38 |
| 2020-10 | 212.78 – 222.72, **vol 18,350** | 10.85 – 11.08, vol 2 | 171.91 – 176.78 |
| 2024-04 | 118.78 – 127.34, **vol 43,087** | 11.59 – 11.85, vol 6 | 113.13 – 119.44 |
| 2026-08 | 109.75 – 111.72, **vol 54,285** | 10.94 – 11.04, vol 6 | 108.44 – 110.22 |

`UD` lands on the contract's 1/32 tick grid **100%** of the time; `UB` lands on it ~5% of the time,
i.e. by chance. Independent corroboration: Yahoo `UB=F` on 2026-08-14 is 110.41, matching `UD`. On
2024-04-15, `UDM24` is 119.66 — just under the 120.7 minimum CF-adjusted forward in its own basket,
which is exactly what "cheapest to deliver" means, and precisely the contradiction the handover
flagged.

### Why it went unnoticed for so long: a decoder built on a false premise

Commit `32be9d58` ("wn vol bug fix", 2026-03-12) added a "compact 32nds" decoder that reinterpreted
any sub-100 `UB` quote as `100 + whole + frac*100/32`. It turned an obviously-wrong `11.13` into a
plausible-looking `111.40625`.

Its premise was measurably false. A quote's fractional part cannot exceed 32 thirty-seconds, and
these routinely did — a raw `9.465` implies "46.5 thirty-seconds". The decoder also ran over
BarChart **option premium** fields, mapping a 1.25 premium to 101.78.

The decoder is gone. In its place is a wrong-instrument guard that returns `NaN` and logs, so a bad
feed stays *absent* rather than becoming *plausible*. This is the repo's own recorded lesson —
"the branch that says nothing is the one that rewrites what your numbers mean" — with a price tag
attached.

`UB` is still accepted on **input** (it is the CME Globex spelling); it is simply never emitted as a
vendor root again.

---

## Defect 2 — ZN's basket, and why the bias was monotone

Lead B in the handover was right about the minimum and **understated the problem**. CBOT Rulebook
Chapter 19 (U.S. Treasury Note Futures, 6½ to 8-Year),
[rulebook/CBOT/II/19.pdf](https://www.cmegroup.com/content/dam/cmegroup/rulebook/CBOT/II/19.pdf):

> The contract grade for delivery on futures made under these Rules shall be U.S. Treasury
> fixed-principal notes which have fixed semi-annual coupon payments, and which have: (a) an
> original term to maturity (i.e., term to maturity at issue) of **not more than 10 years**; and
> (b) a remaining term to maturity of **not less than 6 years 6 months and less than 8 years**.

The code had `min_remaining_months_from_first=72` (6y0m, should be 78) **and no original-term limit
at all**. Two leaks:

1. notes 6 months too short;
2. **old 30-year bonds** with 6.5–8 years left to run — which are bonds, not notes.

The second dominated. Those bonds carry 5.5–7.625% coupons, which makes them look cheapest to
deliver whenever yields sit below the 6% notional coupon. They were named CTD on **1,103 of 1,886
ZN panel days (58.5%)**, from 2018-06 to 2024-11, with a **median implied repo of 14.58% against
actual funding of 0.05–5.30%**. The named bonds were `T 7⅝ Feb 25`, `T 6⅞ Aug 25`, `T 6 Feb 26`,
`T 6¾ Aug 26`, `T 6½ Nov 26`, `T 6⅜ Aug 27`, `T 6⅛ Nov 27`, `T 6⅝ Feb 27`, `T 5½ Aug 28`,
`T 5¼ Nov 28`, `T 6⅛ Aug 29`, `T 5¼ Feb 29`, `T 5⅜ Feb 31` — every one a 1995–2001 vintage long
bond.

**A 14% implied repo against 0.05% funding is not a market.** That single number is the whole
diagnosis, and it is why the fix does not depend on resolving a documentation ambiguity.

This also explains the **monotone decay** the handover flagged (median `min_gross32` −149/32 in 2020
→ −16/32 in 2026) and which it correctly identified as "a bias, not noise": the mispricing from a
high-coupon interloper shrinks as market yields converge on the 6% notional coupon. It is a
thermometer for the gap between yields and 6%, not a market signal.

Measured basket effect:

| contract | before | after |
|---|---|---|
| `ZNU18` @ 2018-06-12 | 21 bonds (4× 30-Year) | 9 bonds, notes only |
| `ZNU20` @ 2020-08-04 | 24 bonds (5× 30-Year) | 11 bonds, notes only |
| `ZNM24` @ 2024-04-15 | 19 bonds (1× 30-Year) | 10 bonds, notes only |
| `ZBM24`, `WNM24` | 56 / 19 | **unchanged** — no collateral damage |

### A handover suspicion that does not survive: UB's `n_deliverable = 19`

The handover flagged UB's basket size being "identical for nine consecutive years" as suspicious.
It is not. Treasury auctions four distinct 30-year CUSIPs a year (Feb/May/Aug/Nov new issues, with
the intervening months reopening them), so the set with ≥25 years remaining is roughly
4 × 5 years ≈ 19–20 at any time. The post-fix `WNM24` basket is 19 bonds maturing 2049-08-15 through
2054-02-15 — a 4.5-year span at ~4 per year. **The number was right all along; only the price
attached to it was wrong.** Worth recording because it is the one place where the handover's
instinct pointed at a healthy part of the system.

### The rest of the table was audited too

Every root was checked against the rulebook and CME's *Understanding Treasury Futures* Table 2.
**TU, Z3N, FV, UXY, TWE, US and WN all already matched**; only TY was wrong. Citations are now in
`treasury_conversion_factors.py`, and the values are pinned by test so the TY fix cannot drift into
its neighbours.

---

## Defect 3 — ZB 2020–21 was never a data problem

The handover called this an open question and flagged that resolving it would let the repo claim a
result tested through the COVID stress. **It resolves in favour of the data: the gate was wrong.**

Gross basis contains carry. In 2020–21, repo near zero against 2–3% coupons makes carry large, so a
**gross**-basis rule flags perfectly good ZB data as broken. The old rule
(`abs(min_gross32) < 32.0`, `build_basis_panel.py:197`) rejected 58% of healthy ZB in 2021.

Once the repo rate is correct (defect 4), the carry-adjusted number is small everywhere:

| contract | date | min gross basis | min **net** basis |
|---|---|---|---|
| `ZBZ20` | 2020-10-15 | +27.1/32 | **+4.0/32** |
| `ZNZ20` | 2020-10-15 | +13.5/32 | **+2.2/32** |
| `WNZ20` | 2020-10-15 | +18.3/32 | **+3.1/32** |
| `ZBU18` | 2018-06-12 | +20.1/32 | **−1.0/32** |

A large gross basis with a near-zero net basis is a high-carry regime, not a feed break. The new
gate is carry-adjusted for exactly this reason, and March 2020 now passes 100% on all three roots.

---

## Defect 4 — the repo rate ignored the date (found here, not in the handover)

`_fetch_fixings` **ignores its `as_of_date` argument** and returns the whole series — measured:
`as_of=2018-06-12` still returns `2018-04-02 .. 2026-08-13`. `_resolve_repo_rate` then took
`.tail(1)`, i.e. **today's** overnight rate, for every historical date: 3.62% for a June-2018 report
whose real fixing was 1.67%, and for an October-2020 report whose real fixing was 0.10%.

Every net basis, BNOC and implied repo in this path, across all history, was computed with the wrong
funding rate. The correct fixing was in the same series the whole time.

Fixed in the consumer by slicing to the last fixing on or before the reference date. **`_fetch_fixings`
itself is left alone** — it has callers outside this path that want the full series, and changing it
is a wider blast radius than this branch should take. That is a deliberate, reversible choice; the
wider fix is worth doing separately.

---

## Defect 5 — the path did not run at all on `main`

rateslib 2.7.1 rejects a bare `"ActAct"` ("must be directly specified as `ActActICMA` … or
`ActActISDA`"). `net_basis`, `bnoc` and `implied_repo` all defaulted to it, so **`get_basis_report`
raised for every root on `main`**. The fix (`Act360`, which is also the right convention for US
repo) existed on `feat/basis-vs-vol` and was never merged. Ported here.

---

## Defect 6 — the report builder mixed two baskets

`_build_basis_report_frame` fetched a **second** delivery basket with `ignore_cache=force_refresh`,
then zipped its cusips, labels, prices and CFs against `gross_basis`/`bnoc`/`irr` vectors computed
from the pricer's own (cached) basket. When the two disagree — exactly what happens on the first
`force_refresh` after a deliverable-window change, when the cache still holds the old basket — every
risk number lands on the wrong bond, silently.

This was latent, and it was about to fire: fixing defect 2 changes the ZN basket. The report is now
built from the pricer's own basket with explicit length assertions, which also removes a duplicate
`FixedRateBondsMDP` round-trip per report. `get_pricer` additionally threads `force_refresh` into the
basket cache, which it previously never invalidated.

---

## The conversion-factor question: resolved by measurement, no change needed

`calculate_conversion_factor` implements CME's published formula correctly. Verified by a 182-row
numerical tie-out and against 165 published values from Burghardt & Belton Exhibit 1.3 — **all 165
matched to 4 decimal places**. rateslib's internally-computed factors also agree with ours: the
report's `gross_basis` ties out to `clean_price − futures_price × invoice_cf` on **100.0% of rows**
across all three panels, median absolute difference 0.0000/32. So the "two CF sources in one report"
hazard is real in principle but **not realised** — they agree.

`basket_source="RL_CME_TCF"` does indeed read no CME file; factors are computed. Given the tie-out,
**wiring in CME's published tables would buy nothing measurable**, so it was deliberately not done.
The recorded gap is accurate as a description and immaterial as a defect.

One divergence channel is dormant rather than absent: ARBS uses `min(maturity, call_date)` as the CF
reference end date and rateslib has no call input. The last callable UST matured 2014-11-15, so this
cannot bite on modern dates, but a pre-2015 ZB/UB backtest would need it checked.

---

## Caches: why deleting files does not work here

This repo has a recorded case of four caches serving one value with a code fix reaching none. The
same trap is live here, and it was measured rather than assumed:

> After removing all **1,855** local Ultra Bond snapshot partitions, `USTFutureStore` pulled
> `WNM20` straight back **from Supabase** still carrying `price=112.496875` — the EUR/NOK-derived
> value.

`_read_partition` falls back to a remote pull whenever local files are missing, so `rm -rf` is
silently undone by the next read. A plausibility band cannot catch these either, because the old
decoder mapped the FX rate *into* the range of a real bond price.

So invalidation is done with **stamps the read path requires**:

| layer | mechanism | effect |
|---|---|---|
| basis-report store (parquet + Supabase) | `_BASIS_REPORT_SCHEMA_VERSION = 2` | **1,988 of 1,991** partitions carry no stamp → cache miss |
| price-snapshot store (parquet + Supabase) | `_SNAPSHOT_SCHEMA_VERSION = 2`, enforced only for `_SNAPSHOT_QUARANTINE_ROOTS = {"WN"}` | only WN's root was mis-mapped; requiring it everywhere would discard ~10,760 sound partitions |
| layered price cache | `_USTF_CACHE_VERSION` v2 → **v3** | key prefix change |
| basket-definition cache | new `_USTF_BASKET_CACHE_VERSION` | the TY window change invalidates every cached ZN basket |
| panel checkpoints | `--fresh` on the rebuild tool | a resume onto a stale panel silently carries old rows into a "rebuilt" one |

Two further defects surfaced **while proving the invalidation works** — both are the kind that only
appear when you actually check:

- `force_refresh=True` skipped the cache **write** as well as the read, so there was no way to
  repair a poisoned entry through this API. The store, and Supabase behind it, would serve the old
  value forever. It now skips only the read.
- A report that **failed the gate was still persisted** when the caller passed `on_bad_data="warn"`.
  A backfill saying "carry on past a bad day" is not saying "cache it for everyone else". This bit
  during development: a pilot run wrote failing reports into the store, they synced to Supabase, and
  the next run served them back *with a fresh stamp*, so they looked current.

`MDP/USTFutures/purge_ustf_cache.py` handles the cases stamps cannot.

---

## The gate, and the fact that it is read

`MDP/USTFutures/basis_report_quality.py`, applied inside `get_basis_report` on **both** the freshly
built and the cached path, and before any write.

- **Raises by default.** A caller that does nothing still cannot consume a broken report. That is
  the whole point: the historic failure was a `data_ok` flag that a builder computed and no consumer
  applied.
- `on_bad_data="warn"/"ignore"` for backfills, and the verdict is attached as `data_ok` /
  `data_quality_reason` columns, so a caller that chose `"warn"` has it *in the data*, not only in a
  log line.
- **Carry-adjusted by construction** — net basis and implied repo, never gross basis. See defect 3.
- Implied repo is checked only ≥21 days from delivery, because it annualises a shrinking horizon and
  is legitimately wild near expiry.

Calibrated so ZB passes the Feb–Jun 2020 dislocation cleanly. A gate that cannot tell a stressed
market from a broken feed makes the most interesting period in the sample unusable — which is what
happened last time.

---

## What I did **not** do, and why

- **Did not touch `_fetch_fixings`.** It ignores `as_of_date` for everyone, not just this path. The
  UST-futures consumer is fixed; the shared function is not. Wider blast radius than this branch
  warrants — but it is a real bug and someone should own it.
- **Did not enforce the "fixed-principal" leg of the ZN grade.** The rulebook excludes TIPS and
  FRNs; the fiscaldata reference frame has **no security-type column** (its only descriptor is `oi`,
  whose values are just `2/3/5/7/10/20/30-Year`). A TIPS issued as a 10-year would pass the filters.
  Documented in the code as unenforced rather than silently assumed. Not observed to bite — no TIPS
  appeared in any basket inspected — but unproven.
- **Did not wire in CME's published conversion factors.** The computed ones tie out exactly; there
  is nothing to gain. Argued from measurement above rather than left open.
- **Did not revive the basis-vs-vol strategy.** Out of scope and correctly concluded dead.
- **Did not modify `ARBS-bvv`/PR #454.** Its `build_basis_panel.py:197` still uses the old
  gross-basis rule `abs(min_gross32) < 32.0`. If that branch is ever revived, that line should call
  the shared gate instead. Flagged, not changed.
- **Did not fix `_resolve_contract_symbol`'s use of IMM dates** (handover Lead C). Confirmed as a
  latent bug — Treasury futures' last trading day is not the IMM date — but it only fires for
  callers passing a bare root, and the roll convention a caller wants there is genuinely ambiguous
  (last trade? first notice? seven days before?). Picking one silently would be worse than leaving a
  known, documented sharp edge. **This is the one item I would most want a human decision on**;
  it is also the most reversible, being a single function.

---

## Verification

- **Regression tests**: `tests/test_ustf_data_layer.py` + a rewritten
  `tests/test_ust_futures_price_normalization.py`, **35 passing**. Each was run against the unfixed
  tree at `f42e9c14` in a scratch worktree first: **8 of 8** that could import there **failed**; the
  rest could not import at all, because the modules are new. A test that passes on both sides of a
  change is not a regression test.
- The old test file asserted `11.13 → 111.40625` outright. It now asserts the opposite and says so
  in its docstring — a test can lock in a bug as effectively as it can prevent one.
- **Fast gate**: see `PANEL_AND_GATE_RESULTS` below.
- **End-to-end**, `force_refresh=True`, so no value can have come from a cache:

| symbol | date | futures px | min clean/CF | min net basis | max IRR | repo |
|---|---|---|---|---|---|---|
| `WNU18` | 2018-06-12 | 156.531 | 157.152 | −1.6/32 | 1.83% | 1.67% |
| `WNZ20` | 2020-10-15 | 219.688 | 220.628 | +3.1/32 | −0.32% | 0.10% |
| `WNM24` | 2024-04-15 | 120.406 | 120.685 | +11.0/32 | 2.33% | 5.32% |
| `ZBZ20` | 2020-10-15 | 175.188 | 176.180 | +4.0/32 | −0.39% | 0.10% |
| `ZNZ20` | 2020-10-15 | 139.094 | 139.622 | +2.2/32 | −0.26% | 0.10% |

Every futures price now sits at or just below the cheapest CF-adjusted forward in its own basket,
on the contract's tick grid, at a level consistent with the instrument.

---

## PANEL_AND_GATE_RESULTS

_(filled in below when the rebuild completes)_
