# Convexity RV, block 2 — the CA data layer repaired, and three strategies measured dead

Four workflows were asked for. All four were built. **Three of them are dead, and
the fourth was a data-and-correctness repair that is the reason the other three
can now be trusted to be dead rather than merely unmeasured.**

---

## W1 — the convexity-adjustment data layer

"Fix the CA data" turned out to be two problems wearing one name.

### Three silent correctness defects in the *shared* path

`RVUtils/ConvexityRV` computes its own adjustment and ties out to Citi. The
repo-wide path — `IRSwapValue.CVX_ADJ`, reached by `TB.IRSwapsTB.sfr_cvx_adj` —
is a second, independent implementation that nothing external had ever graded.

| defect | measured error |
|---|---|
| matched swap built **annual/annual**, not Citi's quarterly/quarterly | **−4.585 / −5.816 / −5.884 bp** on three dates 2023–2025 |
| `_as_percent` magnitude heuristic applied to a percent quantity | up to **+9,405 bp**, on every SR3 priced above 99.00 |
| price panel unconditionally `bfill().ffill()`-ed | **look-ahead inside the price series** |

Defect 1 is larger than the quantity it corrupts — Whites/Reds run 1.3–6.8 bp, so
a −5 bp bias flips the sign. Defect 2 trips on any SR3 above 99.00, i.e. the whole
ZIRP window 2020-03 → 2022-06. All three are now pinned to **Citi's Figure 58**
(13 rows, close 6/9/2023), with the annual variant retained as a negative control
that must fail. Mutation-checked 4/4.

Also fixed: `Q12STIRT` / `Q16STIRT` node horizons (the defect `db95871d` fixed for
Q20 and flagged elsewhere — these are the curves the nightly builds into the
production store), and three defects in the recurring SR3 warm.

### Coverage

A 486-date warm (456 gained depth, 451 reached depth 20, 0 failures, 1.66 h) plus
a panel rebuild. Dates on which each colour is **usable**, gate applied:

| colour | year | before | after |
|---|---|---:|---:|
| Blues | 2023 | 49 | **229** |
| Golds | 2023 | 28 | **244** |
| Golds | 2025 | 20 | **241** |
| Golds | 2026 | **0** | **159** |

The Golds settle gate moved **2.239 → 0.669 bp** median at a **0.446 → 0.990**
pass rate, while ranks 1–13 stayed identical to three decimals — the node-grid fix
moved only what it should.

**The 2018–19 tail is not recoverable**, and that is measured rather than assumed:
302 dates, 313 cells, **0 gained depth**, every request "no data". The deep end of
a 2018–19 strip reaches quarterlies that have since expired. The job's own
acceptance check refused to report success.

---

## W2a — intraday convexity adjustment

The premise turned out to be wrong in our favour. A scout reported that
`build_mdp_request` date-truncates `CVX_ADJ` and that reaching an instant needed a
code change. Measured: `market_request={"timestamp": "now"}` **already** delivers a
full datetime. No Query-layer change is needed; the transport is an existing,
unused feature. Six tests pin it.

---

## W2b — CA against a swap fly: **DEAD**

45 epochs, ranks 2–17 so Blues and Golds are inside the fitted range for the
first time.

| arm | terminal | ann Sharpe | max DD |
|---|---:|---:|---:|
| unhedged, zero cost | +$2,483,251 | **0.130** | −$2.62M |
| unhedged, 0.5 bp | +$233,251 | 0.012 | −$2.87M |
| unhedged, 1.0 bp | −$2,016,749 | −0.105 | −$3.61M |

Mean hold 26 bdays over 5.62 y ≈ **54 independent observations**, and
`E[max SR | null]` at n_obs = 54 is **0.177 at six trials**. The best *gross*
Sharpe is 0.130. It fails the null before costs; costs then take 90 % of gross.
The fly hedge is **worse than no hedge at every cost level**.

**The repaired data made this worse, and that is the point.** Block 1 quoted 0.470
on a panel whose deep end was missing and whose window was chosen by where the
data happened to exist. On a complete panel over a fixed window it is 0.130. A
Sharpe that falls by two thirds when you supply the missing data was never
measuring what it appeared to.

### What *did* reproduce: the economics

Citi's published regression — *Sell Eurodollar convexity in Blues*, Fig 4, monthly
2013–2017, `d(Blues CA − model)` on `d(dealer positioning)`, slope `2e−06`,
R² `0.2724` — reproduces on SOFR 2021–2026:

| colour | slope | t | R² |
|---|---:|---:|---:|
| **Blues** | **+5.28e−07** | **+2.59** | **0.124** |
| Reds / Greens / Golds | ≈0 | −1.66 / −0.23 / −0.29 | ≈0 |

Same sign, within 4× on slope, significant — and **only on Blues, the colour the
published figure is about**. The mechanism is real; the trade is still not
tradable after costs. Those are separate questions.

---

## W3 — CA against ultra-long curve convexity as vol RV: **DEAD at the diagnostic**

Both legs are curve-implied vol on the same ruler. Across 16 (colour, pair)
combinations: change correlation maxes at **|0.112|**; ADF says **14 of 16 spreads
cannot reject a unit root**; the two that can revert in **1.22 and 1.62 days**.

No `QueryDrivenBacktest` certification was spent, deliberately — an engine run
would price to 1e-13 a strategy whose stationarity assumption the data refuses.
Running diagnostics first is what stops a backtest being spent on two random
walks.

---

## W4 — ultra-long curve on risk-adjusted carry: **DEAD**

Gross Sharpe **0.397** against `E[max SR | null]` of **0.445 at 12 trials**
(n_eff ≈ 14; the exit × hold sweep alone was 12 cells). Net 0.180. Max drawdown
**−$20.2 M even gross**, against $21.4 M of total gross P&L.

Factor attribution: the only factor distinguishable from noise is **level, at
t = −4.85, incremental R² 0.1226 of a total 0.1244** — and the book loses to it.
It is duration, not convexity.

The screen underneath it is sound: **120 published cells** from Citi's 2019-12-04
table reproduce in rank (Spearman **0.988** on the decision statistic). What does
not transfer is the *level* — no pair of ours reaches her 1.0 steepener threshold,
so the rule is keyed on rank and percentile instead.

---

## Two look-ahead defects removed

* `get_barchart_timeseries` `bfill()`-ed the price panel — look-ahead *inside the
  prices*, before any strategy code ran.
* `build_positioning_panel` indexed CFTC positioning by **Tuesday's report date**
  and forward-filled, but TFF publishes **Friday 15:30 ET** — three business days
  of look-ahead. Now lagged, with the dealer leg added (measured: dealer net vs
  leveraged + asset manager correlates **−0.955**).

---

## For a human, not for an unattended agent

1. **A live credential is committed to this repository** at
   `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py:7-8`. Not touched here, not
   reproduced anywhere in this work. It should be rotated.
2. **The repaired `warm_sr3_settles` is on this branch only.** The roster entry is
   in the primary checkout so the nightly *fires*, but until this merges it runs
   with the blind depth scan and no settle guard.
3. One pre-existing test failure, unrelated:
   `test_citi_velocity_intraday_curve.py::test_irswapsmdp_citivelo_source` expects
   a minute snapshot at 11:58 and gets 11:57. It fails with every change on this
   branch stashed.

---

## Testing

Convexity suite green throughout. Subsystem regression across everything touched:
**1,018 passed, 1 failed** — that one being the pre-existing failure above.

Every module here is mutation-checked, and two of those checks earned their keep
by surviving first drafts: a default value no test exercised (every test passed
the parameter explicitly), and a source-text assertion that a `pass` walked
straight through.
