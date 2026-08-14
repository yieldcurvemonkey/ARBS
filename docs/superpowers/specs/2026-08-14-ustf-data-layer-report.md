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
| 7 | The ZN grade is **vintage-dependent**; the 8-year cap starts Sept 2023 | **Fixed** | CME's own Dec-2017 basket runs to 9.67y |
| 8 | `get_ctd` was a **third, ungated** public exit | **Fixed** | calls the builder directly |
| — | Conversion-factor formula | **Correct as written** | 182-row tie-out; 165 Burghardt values matched |

Findings 7 and 8 came from a parallel adversarial audit run against this branch after the first four
commits. That audit also **independently validated** the ZN fix against a source I had not used —
CME's own published Treasury Conversion Factor basket files — reproducing `ZNU26` 11/11 and `ZNM24`
12/12 CUSIP-for-CUSIP, and tying out 128/128 overlapping conversion factors to 4dp across seven
roots. It is worth recording that the audit's most useful output was not agreement: it caught a
regression I had introduced (below) and two defects I had left standing.

### One regression I introduced, caught and fixed

Pointing the Ultra Bond at BarChart's `UD` also changed the **Schwab/thinkorswim** live-quote symbol
from `/UB` to `/UD`, because `_to_tos_symbol` resolved through `to_barchart_root`. Broker feeds speak
**CME Globex**, where the Ultra Bond genuinely *is* `UB`. The two namespaces agree for every other
root — which is precisely why conflating them went unnoticed and produced this entire class of bug
in the first place. They are now separate maps (`UST_FUTURE_GLOBEX_ROOTS` vs
`UST_FUTURE_BARCHART_ROOTS`) rather than one map doing two jobs.

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

### Defect 7 — the ZN grade is not a constant, and applying today's rule to all history is its own bug

Fixing the minimum exposed a second, opposite error that had been masked. Per CME **SER-9102**
(2022-12-06), the "less than 8 years" cap **commences with the September 2023 contract month**.
Before that the grade was original term ≤ 10y and remaining ≥ 6y6m with **no maximum** — which is why
the contract's rulebook chapter was once titled "(6½ to 10-Year)".

The decisive corroboration is CME's own worked example rather than a rule filing. *Understanding
Treasury Futures*, **Table 3 — December 2017 Ten-Year T-Note Futures Basis** — lists **17 securities
running from 6.50 to 9.67 delivery years**. Under an 8-year cap that basket would hold 4.

The pre-existing code applied `max = 96` unconditionally, dropping ~7 genuinely deliverable notes per
contract for every ZN month through June 2023. The spec is now vintage-aware
(`max_remaining_effective_period = 202309`), and the result is checked against that published basket:

> **17/17 CUSIPs reproduced exactly, and 17/17 of CME's published conversion factors match to 4
> decimal places.** `ZNM24` (post-cap) is unchanged at 10 CUSIPs.

That is an independent ground truth — a basket CME published, reproduced from the rulebook text —
and it validates the minimum, the original-term cap, the vintage rule and the CF formula in one shot.

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
| basis-report store (parquet + Supabase) | `_BASIS_REPORT_SCHEMA_VERSION` **+ `spec_fingerprint`** | **2,910 of 2,941** partitions rejected (see the proof below) |
| price-snapshot store (parquet + Supabase) | `_SNAPSHOT_SCHEMA_VERSION`, enforced only for `_SNAPSHOT_QUARANTINE_ROOTS = {"WN"}` | only WN's root was mis-mapped; requiring it everywhere would discard ~10,760 sound partitions |
| layered price cache | `_USTF_CACHE_VERSION` v2 → **v3** | key prefix change |
| basket-definition cache | `_USTF_BASKET_CACHE_VERSION` **+ `contract_specs_fingerprint()`** | any spec change now invalidates it automatically |
| BT signal panel cache | schema stamp in the **filename** | `BT/signals/_ustf_basis_cache/panel_*.parquet` had no version at all |
| rebuild checkpoints | `--fresh` on the rebuild tool | a resume onto a stale panel silently carries old rows into a "rebuilt" one |

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

### And then I made the same mistake myself

After the deliverable grade became vintage-aware, the rebuilt TY panel showed a **median basket of
10 deliverables in every year** — where pre-2023 years should hold 16–17. The spec was already
correct: a direct `build_delivery_basket_frame` call reproduced CME's published December-2017 basket
17/17. The **basket cache** was still serving baskets computed by the previous spec, because its
version constant had been bumped *before* the last spec edit rather than after.

Nothing in a cached basket recorded which spec built it, and 10 deliverables is a perfectly
plausible number — only a by-year sanity check on basket size caught it.

So the hand-maintained version is gone. `contract_specs_fingerprint()` is a short stable hash of the
whole `_CONTRACT_SPECS` table, and it is now part of both the basket cache key and every basis
report (a `spec_fingerprint` column the read path requires alongside `schema_version`). **Any change
to a deliverable grade invalidates the derived data automatically, with no step left to forget.**

After invalidation, measured through the MDP rather than the spec function:

| contract | before | after |
|---|---|---|
| `TYU18` @ 2018-06-12 | 10 | **16** |
| `TYZ20` @ 2020-10-15 | 10 | **17** |
| `TYM24` @ 2024-04-15 | 10 | 10 (post-cap, unchanged) |
| `TYU26` @ 2026-08-13 | 10 | **11** — matches CME's published `ZNU26` basket |

I am recording this at length because it is the most transferable finding here. The original defects
were exotic; this one is ordinary, and it is the reason "fixed the code" and "fixed the data" are
different claims.

### Proof the invalidation reaches everything

Scanning the whole local basis-report store against the current stamp *and* fingerprint:

```
2,941 basis-report partitions on disk
  WOULD BE SERVED : 31      <- all TY partitions the in-flight rebuild had just written
  treated as stale: 2,910
  implausible futures price among served: 0
```

The 31 servable partitions are precisely the ones written by the running rebuild under the current
spec. Nothing built by older code can reach a consumer.

One residue worth naming: some reports written during this session's own pilot runs were pushed to
Supabase before the "never persist a failing report" fix landed. They are **inert** — the fingerprint
no longer matches, so they can never be served — but they are still sitting there as junk. Cleaning
them up is housekeeping, not correctness.

---

## The gate, and the fact that it is read

`MDP/USTFutures/basis_report_quality.py`, applied inside `get_basis_report` on **both** the freshly
built and the cached path, and before any write.

- **Raises by default.** A caller that does nothing still cannot consume a broken report.

  A correction to the handover's framing here, since I originally repeated it: the previous
  `data_ok` flag **was** read — `RVUtils/BasisVsVol/run_v1_results.py:51` and the v1 notebook
  builder both call `filter_data_ok`. The failure was not an unread flag. **The rule was wrong**: it
  gated on *gross* basis, so it rejected healthy high-carry data and passed nothing that would have
  caught the Ultra Bond. A gate that is read but wrong is not better than one that is unread, and it
  is more dangerous, because its output looks like diligence.
- `on_bad_data="warn"/"ignore"` for backfills, and the verdict is attached as `data_ok` /
  `data_quality_reason` columns, so a caller that chose `"warn"` has it *in the data*, not only in a
  log line.
- **Carry-adjusted by construction** — net basis and implied repo, never gross basis. See defect 3.
- Implied repo is checked only ≥21 days from delivery, because it annualises a shrinking horizon and
  is legitimately wild near expiry.

- **An empty report is absence, not corruption.** A holiday, an unlisted contract or a symbol with
  no basket produces no rows; there is nothing there to contradict itself. Failing those would make
  every such day look like a feed break. (The gate got this wrong initially and the audit caught it.)
- **`get_ctd` is gated too.** It calls the builder directly and was the one remaining way to read a
  corrupt basis report without being told.
- **A failing report is never persisted**, whatever `on_bad_data` says. A backfill saying "carry on
  past a bad day" is not saying "cache it for everyone else".

Calibrated so ZB passes the Feb–Jun 2020 dislocation cleanly. A gate that cannot tell a stressed
market from a broken feed makes the most interesting period in the sample unusable — which is what
happened last time.

**Operational consequence, stated plainly:** `MDP/cache_populator.py`'s nightly warmer calls
`get_basis_report` and will now surface a **FAILED** status on gate-rejected days (~0–6% per root
per year on healthy roots, concentrated in 2021–23 for ZB). Because a failing report is deliberately
not persisted, those days re-fail on every run rather than being silently cached. That is the
intended trade — a recurring visible failure beats a one-time silent one — but an operator who wants
the warmer quiet should pass `on_bad_data="warn"`, which records the verdict in `data_ok` instead of
raising.

### The gate immediately earned its keep on a defect nobody was looking for

Rebuilding the panels, the gate flagged **2023-02-10 on two roots at once** — `USH23` net basis
−293/32 with implied repo +113.6%, and `WNH23` −355/32 with +169.9%. A defect hitting the classic
bond and the Ultra Bond on the same day is a **cash**-side problem, not a futures one. The basket
yields say so plainly:

| date | ZB basket YTM (min–median–max) |
|---|---|
| 2023-02-03 | 3.598 – 3.790 – 3.826 |
| **2023-02-10** | **4.571 – 4.738 – 4.772** |
| 2023-02-17 | 3.896 – 4.053 – 4.087 |

The long bond did not yield 95bp more on one Friday and 69bp less the next. The **futures** prices
across those three days (130.06 → 126.94 → 125.81) move smoothly, so the futures leg is fine and the
FedInvest cash prints for 2023-02-10 are wrong — the same class as the recorded FedInvest
degenerate-price days. Nothing in this branch was aimed at the cash leg; the gate caught it because
"a 113% implied repo against 4.55% funding is not a market" is true regardless of which leg broke.

### An honest caveat on the thresholds

They were calibrated against panels built with the **old** repo rate, because that was the data
available at the time. With the repo fix in, healthy net basis is much tighter than the calibration
assumed (|min net basis| ≤ 11/32 across every root and era spot-checked, against a 96/32 limit). The
thresholds are therefore **looser than they need to be** — they will catch gross corruption of the
kind found here and will not catch something subtler. That is the safe direction to err for a gate
that raises by default, but it is a known slack, not a tuned value. Re-deriving them from the rebuilt
panels is the obvious next step and is deliberately left undone rather than done hastily.

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
- **Did not fix the BarChart EOD path.** Every `interval=None` call fails with
  `Invalid comparison between dtype=datetime64[ns] and datetime`, so only the minute/intraday
  endpoint works. That matters here because minute history for old contracts far from delivery is
  thin — the very first probe found essentially no `UBU18` minute data — and the EOD endpoint is
  what would serve settlement prices for those days. Out of scope for a mapping fix, but it is the
  reason a `force_refresh` backfill over deep history has holes, and it is the highest-value
  follow-up for anyone wanting a complete panel.
- **Did not fix `_resolve_contract_symbol`'s use of IMM dates** (handover Lead C). Confirmed as a
  latent bug — Treasury futures' last trading day is not the IMM date — but it only fires for
  callers passing a bare root, and the roll convention a caller wants there is genuinely ambiguous
  (last trade? first notice? seven days before?). Picking one silently would be worse than leaving a
  known, documented sharp edge. **This is the one item I would most want a human decision on**;
  it is also the most reversible, being a single function.

---

## Verification

- **Regression tests**: `tests/test_ustf_data_layer.py` + a rewritten
  `tests/test_ust_futures_price_normalization.py`, plus the two pre-existing UST-futures modules —
  **56 passing**.

  On the *first* batch of tests I built a scratch worktree at the unfixed commit `f42e9c14` and ran
  them there: **8 of 8 that could import against base failed**. The rest could not import at all,
  because the modules they exercise are new — which is proof of novelty rather than of redness, and
  is worth stating as such. The later tests (the ZN grade vintage, the spec fingerprint) were added
  after that exercise and were **never run against base**; on base their file fails at import, for
  the same reason. So: per-test red evidence exists for the first batch, not for all of them.
- The old test file asserted `11.13 → 111.40625` outright. It now asserts the opposite and says so
  in its docstring — a test can lock in a bug as effectively as it can prevent one.
- **Every test module that touches the changed code** — all 25 of them, found by grepping `tests/`
  for `USTFutures`, `USTFuture`, `ustf_basis` and `treasury_conversion`:
  **285 passed, 1 skipped, 23 deselected.**
- **Full fast gate**: started, and *not* finished — it paces to roughly nine hours in this
  environment (~6 s/test; `tests/test_citivelo_excel_supervisor.py` alone takes 3m37s). At the point
  of writing it had run 823 tests with exactly one failure:
  `test_citivelo_excel_supervisor.py::test_not_signed_in_means_keep_waiting`. That is the known
  pywinauto hazard — the intended deselect used the wrong path (`tests/test_excel_supervisor.py`
  rather than `tests/test_citivelo_excel_supervisor.py`), so it ran. It hangs on `main` too, the
  other 13 tests in its module pass, and it touches nothing in this branch. **I am reporting this
  as an incomplete verification rather than a green one**, because it is.
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

## Panels rebuilt, and the improvement measured

Rebuilt with `python -m MDP.USTFutures.rebuild_basis_panels --roots US TY WN --start 2018-06-01
--end 2026-08-13`, same date span as the original panels.

**Two deviations from the original build, stated rather than buried:**
1. the rebuild samples **every 5th business day** (~50 rows/year/root) rather than daily — enough
   for a pass-rate table, and it is what fits in the time available;
2. it uses the **overnight SOFR fixing at the reference date** as the repo rate, where the original
   used a term financing rate from a module that exists only on the PR #454 branch. This is the
   likeliest source of the residual ZB flags (below), since an overnight rate is weakest exactly
   where term repo and specials matter.

### Consistency-gate pass rate, before vs after

"Before" is the original panels under the old gross-basis rule (`abs(min_gross32) < 32`); "after" is
the rebuilt panels under the shared carry-adjusted gate.

| root | year | before | after | | root | year | before | after |
|---|---|---|---|---|---|---|---|---|
| ZB→US | 2018 | 100.0% | 100.0% | | ZN→TY | 2018 | 8.3% | **100.0%** |
| | 2019 | 100.0% | 100.0% | | | 2019 | 0.0% | **100.0%** |
| | 2020 | **62.1%** | **100.0%** | | | 2020 | 0.0% | **100.0%** |
| | 2021 | **41.9%** | **94.1%** | | | 2021 | 13.3% | **100.0%** |
| | 2022 | 83.7% | 85.7% | | | 2022 | 0.5% | **100.0%** |
| | 2023 | 88.9% | 94.2% | | | 2023 | 28.8% | 98.1% |
| | 2024 | 100.0% | 100.0% | | | 2024 | 63.4% | 100.0% |
| | 2025 | 100.0% | 100.0% | | | 2025 | 97.2% | 100.0% |
| | 2026 | 98.7% | 100.0% | | | 2026 | 99.4% | 100.0% |

| root | before | after |
|---|---|---|
| **ZB → US** | 85.4% of 1,905 rows | **96.8%** of 410 rows |
| **ZN → TY** | 35.1% of 1,886 rows | **99.8%** of 416 rows |
| **UB → WN** | **1.9%** of 1,669 rows | **99.7%** of 365 rows |

ZB 2020 goes 62.1% → 100% and 2021 goes 41.9% → 94.1% **without any change to ZB's data** — the
whole difference is a gate that subtracts carry before judging. That is the COVID window becoming
claimable, which was the point.

### The Ultra Bond is a bond again

Median futures price per year — the clearest single picture of what was wrong:

| year | before (EUR/NOK) | after (Ultra Bond) |
|---|---|---|
| 2018 | 110.71 | **156.92** |
| 2019 | 111.24 | **175.62** |
| 2020 | 112.09 | **218.03** |
| 2021 | 110.83 | **196.31** |
| 2022 | 111.09 | **152.28** |
| 2023 | 112.57 | **134.80** |
| 2024 | 113.13 | **126.11** |
| 2025 | 113.35 | **118.59** |
| 2026 | 112.00 | **118.00** |

The "before" column is flat because an exchange rate does not care about the Fed. The "after" column
is the rate cycle: the 2020 low-yield peak at 218, the 2022–23 selloff, the 2024–26 range.

### ZN's basket size, both eras

| era | before | after |
|---|---|---|
| pre-Sept-2023 | 21–23 | **17** |
| post-Sept-2023 | 18–19 | **10** |

Both move down, for different reasons: pre-2023 the old basket admitted short notes *and* old
30-year bonds while wrongly capping at 8 years; post-2023 the cap is real and the short notes and
bonds are gone.

### What still fails, honestly

- **ZB 2021–22 (13 of 410 rows).** Ten are one contract, `USH22` over Nov-2021–Feb-2022: net basis
  +80 to +100/32 with implied repo −7% to −33% against 0.05% funding. That signature is consistent
  with either a genuinely delivery-option-rich period or with the overnight-vs-term repo deviation
  above; **I did not resolve which**, and net basis excludes the delivery option by construction, so
  a large value there is not automatically wrong.
- **2023-02-10 on ZB and WN** — a corrupt FedInvest cash day, diagnosed above. A true positive.
- **WN and TY 2023 (one row each)** — the same 2023-02-10 cash day.
- Gaps in the WN panel are a mix of **market holidays** (Good Friday 2019-04-19 and 2022-04-15 raise
  "No deliverable bond pricers resolved" because there is no cash data — correct behaviour) and
  **transient BarChart failures** under `force_refresh`; the latter succeed on retry
  (2018-08-31 → 159.34, 2019-07-19 → 176.00) and the tool's resume picks them up on a second pass.
  Both are counted and printed, never silently dropped.
