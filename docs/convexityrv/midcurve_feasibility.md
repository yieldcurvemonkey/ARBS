# SOFR mid-curve vol: obtainable?

**VERDICT: OBTAINABLE.** Not via `qs_timeseries` — via the Barchart per-strike EOD path,
at **~1 HTTP call per (contract, strike, right) for that leg's ENTIRE daily history**.
A 2-root × 8-quarterly panel is **~1–2 hours**, not days. A proof panel covering
1Y/2Y/3Y mid-curves is built and verified at
`notebooks/data/convexity_rv/sofr_midcurve_probe.parquet`.

The prior conclusion — "the Barchart raw-EOD cache holds 682 mid-curve keys and every
one is EMPTY" — **is wrong**. 55 of those 682 already held real daily frames before
this task made a single network call. The count was of keys, not of contents, and the
majority of keys are `no_data` *markers*, most of which turned out to be **poisoned
cache entries**, not vendor absence: 8 of 8 near-money `MMAZ26` legs marked `no_data`
returned 231 clean daily bars each on a forced refetch.

---

## 1. What was tried, and what came back

### 1.1 `qs_timeseries` — dead end, unchanged
Not re-measured. The prior finding stands and is dangerous: bare mid-curve roots raise,
and `root_globex="S0"` / `product="S0"` **silently return the standard SR3 series**
(S0, S2, S3 all hand back the identical `SR3M26` column). Never trust a mid-curve hint
on that endpoint.

### 1.2 Barchart per-strike EOD — works
Endpoint: `https://www.barchart.com/proxies/timeseries/historical/queryeod.ashx?symbol=<SYM>`
reached through `STIRFutureOptionMDP._fetch_barchart_eod_series`, symbol form
`<BARCHART_ROOT><CODE>|<STRIKE4><C|P>`, e.g. `MMCZ26|9700C`.

Root map (already in `MDP/STIRFutures/_sofr_option_contracts.py`):
`0Q→MMA (1Y)`, `2Q→MMB (2Y)`, `3Q→MMC (3Y)`, `4Q→MMD (4Y)`, `5Q→MME (5Y)`.

**Found on disk before any network call** (`STIRFutureOptionRawEOD_Cache`, 8,797 keys):

| contract | root | requested legs | with data | strike range with data |
|---|---|---|---|---|
| `MMCZ26` | 3Q (3Y) | 58 | **29** | 94.375–98.125, contiguous 0.125 grid |
| `MMAZ26` | 0Q (1Y) | 206 | 11 | 90.25–92.75 (far-OTM junk only) |
| `MMBZ26` | 2Q (2Y) | 204 | 9 | 90.50–93.00 (far-OTM junk only) |
| `MMAU26` | 0Q (1Y) | 214 | 6 | 90.25–91.50 (far-OTM junk only) |

`MMCZ26` alone was already a complete 28-strike × 218-day panel with coherent prices
(96.00C = 0.7750 with `SQZ29` at 96.645 on 2025-09-15, decaying to 0.2050 by
2026-07-28, with live open interest of 6,208).

**Scope note.** `option_snapshot` / `option_timeseries` were **not** run end-to-end for
mid-curves. What is proven here is the raw-EOD layer those endpoints consume: both
resolve their legs through `_fetch_barchart_eod_series`, so mid-curve data is reachable
by them — but their ATM/delta alias resolution generates candidate strikes from the
stale 1/16 rule (caveat 3), so expect the same miss rate and backoff cost until that
rule is fixed. Explicit-strike requests are unaffected.

### 1.3 The cache-poisoning finding
`_fetch_barchart_eod_series` writes a **permanent** `no_data` marker for any symbol a
batch failed to return, gated only on *some other* symbol in that batch succeeding
(`STIRFutureOptionMDP.py:5335`). Nothing but `force_refresh=True` ever retries it. So a
partially-degraded batch bakes in permanent misses for legs the vendor really serves.

Before/after on the smallest possible unit — 8 near-money `MMAZ26` legs, every one
marked `no_data`:

```
HTTP calls 13 in 4.43s (0.341s/call); 8/8 legs now have data (8 healed from no_data)
   HEALED MMAZ26|9600C   no_data -> data  n=231  2025-09-15..2026-08-14
   HEALED MMAZ26|9587C   no_data -> data  n=231  2025-09-15..2026-08-14
   ... (8/8)
```

This reproduced live: a second `0QZ26` ladder run healed 3 further legs that the first
run had just re-marked `no_data`. The flakiness is in the fetch, not the vendor.

### 1.4 Expired contracts are served — so a multi-year backfill is real
`0QZ24` (expired 2024-12-13), 6 legs, none previously requested:

```
HTTP calls 11 in 3.8s (0.345s/call); 6/6 legs now have data
   MMAZ24|9600C  absent -> data  n=314  2023-09-18..2024-12-13
```

Each mid-curve leg's history begins **~15 months before its expiry** (`MMAZ26` from
2025-09-15 for a 2026-12-11 expiry; `MMAZ24` from 2023-09-18 for 2024-12-13). Quarterly
expiries at 3-month spacing therefore overlap ~5 deep, and ~8 quarterlies per root span
well over 2 years.

---

## 2. Cost, measured

| run | legs planned | HTTP calls | wall | s/call |
|---|---|---|---|---|
| probe `0QZ26` near-money | 8 | 13 | 4.43 s | 0.341 |
| probe `0QZ24` (expired) | 6 | 11 | 3.80 s | 0.345 |
| harvest `0QZ26` ladder | 74 | *not captured* (cap 120) | ~90 s | — |
| harvest `0QZ26` re-run | 19 | 24 | 7.62 s | 0.318 |
| harvest `2QZ26` ladder | 82 | 121 | 281.45 s | 2.326 |

**Total live HTTP: ~278**, bounded above by 289 — inside the 400 cap. (Four of five runs
were counted exactly, totalling 169; the uncaptured `0QZ26` harvest planned 74 legs and
is estimated at ~109 from the measured 121/82 = **1.48 calls per planned leg**, which
covers session-token fetches and retries.)

Two rates matter, and the gap between them is the whole cost story:
- **legs that exist**: ~0.32 s/call.
- **legs that do not exist**: the 5-attempt exponential backoff fires, dragging the
  `2QZ26` batch (16 of 82 legs absent) to 2.33 s/call. **Ladder accuracy, not call
  count, is what costs time.**

**Extrapolation.** Cost is per-LADDER, not per-date — one call buys a leg's whole
history, so adding years to an existing ladder is free. At the measured 3.43 s per
planned leg (worst case, misses included):

> **2 roots × 8 quarterlies × ~80 legs ≈ 1,280 legs ≈ 1,900 calls ≈ 73 minutes.**

Call it **1–2 hours** for a 2-year, 2-root panel. Halve it with a 0.25-step OTM-only
ladder. This is comfortably an attended-job, not an overnight crawl.

---

## 3. The proof panel

`notebooks/data/convexity_rv/sofr_midcurve_probe.parquet` — 3,873 rows, 7 contracts.
Columns: `date, contract, barchart_root, underlying, is_midcurve, expiry, forward,
strike, right, price, tau_yrs, atm_bpvol`. Coverage/provenance in
`sofr_midcurve_probe_coverage.json`.

ATM normal vol is a Bachelier inversion of the nearest-OTM listed settle. Since
SR3 price = 100 − rate, a normal vol on the futures **price** in price-points/yr is
numerically the yield vol; ×100 gives bp/yr, directly comparable to QuikStrike ABPV.

### 3.1 The method is validated against QuikStrike, not asserted
Two independent contracts spanning a 50% level difference, 2026-01-02..2026-03-31,
flat 4% discount factor:

| contract | this engine | QuikStrike ABPV | error |
|---|---|---|---|
| `SFRM26` | 45.01 | 44.74 | **+0.6%** |
| `SFRZ26` | 69.08 | 68.45 | **+0.9%** |

Mutation-tested, so the match is not a coincidence of a broken pipeline:
τ×1.2 → −7%; τ×0.8 → +12%; τ in months → −60%; price×1.1 → +10%. All far outside ±1%.

*(A first negative control — repricing against the wrong underlying — moved the answer
only 3% and is reported here as uninformative rather than passing: ATM vol is
first-order insensitive to small forward shifts. The τ and price mutations are the
tests that actually bite.)*

### 3.2 Result: a clean forward-vol term structure at ONE expiry
All four contracts below expire **2026-12-11**; only the underlying differs. This is
precisely the listed analogue of a swaption on a forward rate, and the thing the
constant-maturity `ust_listed_vol.parquet` panel cannot express.

| contract | underlying | forward | ATM bp/yr | vs `SFRZ26` | corr |
|---|---|---|---|---|---|
| `SFRZ26` | SFRZ26 | spot | 75.04 | 1.000 | 1.000 |
| `0QZ26` | SFRZ27 | +1y | 91.60 | **1.263** | 0.706 |
| `2QZ26` | SFRZ28 | +2y | 88.24 | **1.206** | 0.791 |
| `3QZ26` | SFRZ29 | +3y | 85.49 | **1.138** | 0.850 |

(medians on common days; 218–231 days each)

Sane on every axis: forward vol exceeds spot vol at every point; the curve is humped,
peaking at the 1y-forward belly where policy uncertainty concentrates, then declining
monotonically; correlation with the standard option rises monotonically with forward
distance; and the series get *smoother* further out (max 1-day move 16.5 → 11.7 → 9.0 bp
vs 21.2 for the standard). The independently-harvested `0QZ24`/`SFRZ24` pair reproduces
the same sign in the 2023-24 hiking-cycle regime at a much higher level (137.05 vs
93.34, ratio 1.438).

`--verify` runs 20 tie-out asserts (levels, τ, OTM side, ATM proximity ≤ 0.60,
continuity < 40 bp/day, ratio > 1 on same-expiry common days). **All pass.**

One honest note on levels: the panel's minimum is 16.8 bp/yr, all `SFRM26` in May 2026.
That is real, not a defect — a front SR3 collapses toward zero vol once most of its
reference quarter has already fixed. No mid-curve prints below 73 bp/yr.

---

## 4. Caveats and hazards

1. **`cache_only()` does not block this path — measured, not suspected.**
   `RVUtils/ConvexityRV/listed_cache_guard.py` patches `requests`; the Barchart EOD data
   plane is **httpx** (`BarchartFetcher._fetch_eod_timeseries` → `client.get`). Verified
   directly: inside `cache_only()`, `requests.get` and `requests.Session.request` are
   blocked while `httpx.AsyncClient.send` and `httpx.Client.send` are **not**. Session
   tokens are cached at class level, so the requests-level block on token fetches does
   not reliably stop a warm process either.
   **`network_calls_blocked()` reports 0 for this task, and that number is meaningless
   here** — it cannot see the transport that was actually used. All counts in §2 come
   from `NetGuard` in the harvest script, which patches httpx *and* requests.
   *Recommended follow-up (deliberately not done here): extend `cache_only()` to patch
   `httpx.AsyncClient.send` / `httpx.Client.send`. Until then, no unattended job on this
   path is actually guarded.*
2. **Never trust a `no_data` marker on this cache.** It conflates "vendor has nothing"
   with "one batch flaked". The harvester defaults to `force_refresh=True` for legs
   marked `no_data`; `--no-force` trusts the cache and is the wrong default.
   Corollary: re-running a harvest is **not** free, because genuinely-absent strikes are
   re-paid for (with backoff) every time. Use `--no-force` only once a ladder is known good.
3. **Strike-ladder rules are stale for 1Y/2Y roots.** `_cme_listed_strike_rule_for_contract`
   uses a 1/16 fine step for `0Q`/`2Q` within 5 months; 95 of 189 historical `MMAU26`
   misses were 1/16-grid requests that never list. `MMC` (1/8 step) hit 50%. Harvest on
   the **0.125/0.25 grid only** — the 1/16 grid is pure waste.
4. **4Q/5Q (`MMD`/`MME`) untested.** CME lists them; no leg of either was requested here.
5. **Weekly mid-curves (`S01`…`S35`, `MMI`…`MMV`) out of scope** and have no last-trade-date
   rule (`sofr_option_last_trade_date` returns `None`), so `atm_vol_series` will refuse them.
6. **Modelling shortcuts, adequate for feasibility, not for a book:** European Bachelier on
   an American-exercise option; flat 4% discounting rather than the SOFR curve; ATM taken
   as the nearest OTM listed strike (median |K−F| = 0.030) rather than a smile-interpolated
   ATMF. The <1% ABPV tie-out bounds the combined error at these maturities.
7. `Volume = 0` rows are CME settlement prices, not missing data, and are used deliberately.

---

## 5. Reproducing

```bash
# rebuild the panel from cache, zero network, with asserts
python scripts/harvest_sofr_midcurve_vol.py --mode offline \
    --contracts 0QZ26 2QZ26 3QZ26 0QZ24 --controls SFRZ26 SFRZ24 SFRM26 --verify

# see what a harvest would cost before paying for it
python scripts/harvest_sofr_midcurve_vol.py --mode harvest --contracts 0QU26 \
    --step 0.125 --half-width 0.25 --max-calls 999 --dry-run

# smallest live test: near-money legs of one contract, hard-capped
python scripts/harvest_sofr_midcurve_vol.py --mode probe --contracts 0QZ26 \
    --plan-limit 8 --max-calls 40
```

`--max-calls` is a hard cap enforced by `NetGuard`; the run aborts past it. Leave
headroom over `--plan-limit` — token fetches and retries count too (measured 1.48
calls per planned leg).

**Each run rewrites the parquet with only the contracts named on that command line** —
unlike `harvest_ust_listed_vol.py`, this one does not resume. So the probe example above
will shrink the delivered panel to `0QZ26` + controls. That is safe and reversible:
every leg is now cached, so the first (offline) command restores the full panel in ~4 s
at zero network cost. The parquet is a regenerable artefact, not a source of truth.

---

## 6. Bottom line

SOFR mid-curve vol **is obtainable**, the data was **partly already on disk**, and the
blocker was a **poisoned cache plus a stale strike rule**, not vendor absence. The
resulting 1Y/2Y/3Y forward-vol curve at a single expiry is exactly the listed instrument
the forward-curve comparison needs. No strategy has been built on this, by design.
