# Trading the micro relative value in US Treasury ETF rebalancing

**Status: the headline hypothesis is DEAD, on a measurement rather than on a failure to find
anything.** The dataset it needed is built, audited and reusable, and the reason the trade does not
work is precise enough to be argued with.

---

## 1. What was asked, and what was built

> *"See if there's alpha in trading the micro relative value on US Treasury bond ETF rebalancing.
> Scrape and build a dataset of daily ETF holdings … we can trade micro flies based on historical
> DV01 or notional weightings of where constant-maturity 3-month buckets have been historically in
> that ETF's box."*

Four things exist that did not before.

| Artefact | What it is |
|---|---|
| `MDP/ETFHoldings/` | Daily iShares holdings, 2016–2026, **12 funds, 22,904 documents**. Rotating-exit fetcher, resumable manifest, content-hash dedup. |
| `RVUtils/ETFRebalance/` | UST price/yield/duration/convexity panel, monthly float panel, the constant-maturity ladder, the signal family, a local curve model, a measured cost model, an IC toolkit, a vectorised backtester and a grid searcher. |
| `BT/signals/etf_rebalance.py` | The same book on `QueryDrivenBacktest`, marked at dirty NPV with coupon cash. |
| `etf_rebalance_configurable_backtest.ipynb` | One `CONFIG` dict = one backtest. Knob sweeps, grid search, DSR, robustness, trade log. |

Plus `tests/test_etf_rebalance.py` — 34 tests, every one of them **mutation-verified**: the code
each test covers was deliberately broken and the test was required to fail (see
`tests/_mutate_etf_rebalance.py`). Three of the first five mutations were **not** caught, and fixing
that found a genuinely weak test — a butterfly fixture with symmetric wings, where hard-coding the
slope weight to 0.5 is a no-op.

---

## 2. The measuring stick, stated before the result

A DV01-neutral butterfly among 20-30y Treasuries costs, on **FedInvest's own published bid and
offer**, per completed round trip:

| year | 2016 | 2018 | 2020 | 2022 | 2024 | 2026 |
|---|---|---|---|---|---|---|
| butterfly round trip (yield bp) | 0.30 | 0.35 | 0.50 | 0.94 | 0.94 | 0.58 |

The median **cross-sectional** standard deviation of a bond's richness against its local fitted
curve is **0.434bp** (mean 0.53, p90 1.05; per-CUSIP time-series sd 0.384bp, lag-1
autocorrelation 0.958), against a median butterfly round trip of **0.535bp**. So the entire
dispersion this trade can capture is **0.81x of one round trip** -- a signal would have to
explain more than all of it.

### Why not the two cost tables already in the repo

* `BT/gss_fly/config.py` keys a half-spread on *time to maturity*. Every leg of a three-month
  butterfly has the same maturity, so it prices the differences this study trades at zero.
* **NY Fed SR1170 Table 3** keys on off-the-run *rank*, which is the right axis, but its
  "further off-the-run" bucket for the 30-year sector is **166.98 price bp**. Every bond TLT owns
  sits in that bucket. That is 11 yield bp per leg — a fly would cost 33bp round trip and nothing
  could survive. The number is dominated by odd lots in dead issues. Kept as the pessimistic
  bound (`costs.basis="sr1170"`), never as the default.

---

## 3. The result

### 3.1 The raw relationship is strong, significant, and backwards

TLT, 2016–2026, 80,953 gated bond-days, `exec_lag=1`, target = forward change in the richness
residual. Mean cross-sectional Spearman IC, t across dates:

| signal | 5d | 10d | 21d | 42d | 63d | naive t @ 63d |
|---|---|---|---|---|---|---|
| `resid` *(control — no ETF data)* | 0.128 | 0.177 | 0.243 | 0.309 | **0.349** | **+50.7** |
| `ownership` | 0.014 | 0.021 | 0.035 | 0.056 | 0.068 | +15.3 |
| `active_w` | −0.015 | −0.022 | −0.037 | −0.057 | **−0.065** | **−14.4** |
| `flow` | 0.001 | −0.001 | 0.006 | 0.008 | 0.006 | +1.3 |

`active_w` scores an *underweight* bond high. A negative IC therefore says **underweight bonds
subsequently cheapen** — the opposite of the hypothesis — and `ownership` says the same thing from
the other side.

### 3.2 …because it is the bond's own richness wearing the signal's clothes

A fund that overweights large, liquid, recently issued bonds is overweighting a set that is *also*
systematically rich. Orthogonalising each signal against `resid` cross-sectionally, date by date:

All t-statistics in this sub-section are **naive** (uncorrected for overlapping
windows); §3.4 restates them.

| signal | | 5d | 10d | 21d | 42d | 63d |
|---|---|---|---|---|---|---|
| `active_w` | raw t | −3.8 | −5.5 | −8.7 | −12.5 | −14.4 |
| | **partial t** | **+3.6** | **+5.0** | **+4.5** | **+3.4** | **+3.8** |
| `ownership` | raw t | +3.6 | +5.2 | +8.1 | +12.4 | +15.3 |
| | **partial t** | **−3.4** | **−4.6** | **−4.1** | **−3.1** | **−2.7** |

**Every sign flips.** What survives points the way the hypothesis predicted — underweight bonds do
richen — and it is significant. It is also tiny.

### 3.3 The magnitude is the verdict

Bivariate cross-sectional regression, forward bp of richening per unit of signal z:

| horizon | β(`active_w`) | naive t | β(`resid`) | naive t |
|---|---|---|---|---|
| 10d | +0.0032 | 3.25 | 0.0395 | 21.7 |
| 21d | +0.0029 | 2.55 | 0.0628 | 24.5 |
| 63d | +0.0046 | 4.02 | 0.1317 | 27.8 |

A top-versus-bottom spread of ~4 z is worth **≈0.02bp gross** against a **≈0.5bp** round trip.
The control is worth **thirty times more** per unit z — and even the control's costless
top-3-minus-bottom-3 at 63 days is +0.47bp, i.e. roughly the cost line, which is what every prior
ARBS cash-UST study also found.

### 3.4 The t-statistics above are overstated, and correcting them matters

A 63-day forward return sampled every day shares 62 of its 63 days with the next
observation, so the IC series is enormously autocorrelated and a naive
`mean / (sd/√n)` treats ~2,400 overlapping windows as 2,400 independent draws. Every
t in §3.1–3.3 is inflated by that. With a Newey-West correction at `h−1` lags:

| signal | horizon | β (bp per z) | naive t | **HAC t** |
|---|---|---|---|---|
| `active_w` | 5d | +0.0023 | 2.96 | **1.76** |
| `active_w` | 21d | +0.0029 | 2.55 | **0.83** |
| `active_w` | 63d | +0.0046 | 4.02 | **0.89** |
| `active_rel` | 63d | +0.0123 | 8.16 | **1.71** |
| `ownership` | 63d | −0.0076 | −4.97 | **−1.02** |

**Not one holdings-based signal reaches t = 2 at any horizon once the overlap is
counted.** The direction of the correction is uniform, so the *ranking* of signals
survives; the *significance* does not. §3.2's "significant" should be read as
"marginally significant before the correction, and not significant after it".

### 3.5 The one thing that looked alive was the calendar — and a placebo killed it

Repairing the standardiser (a signal that is zero for 98% of the cross-section has a
median absolute deviation of exactly zero, so a pure MAD z-score was NaN on **all 2,528
dates** and `deletion` had been silently dropped as "too few finite values") brought the
calendar signal back. It looked strong: bivariate β **+0.05bp per z with HAC t = 3.5**,
about ten times any holdings signal, and it reads **no holdings file at all**.

It is also perfectly confounded. A bond about to fall below TLT's 20-year boundary is by
construction the **shortest bond in a curve fitted over 20–31 years** — the extreme edge
of the fit, where a cubic is least constrained. So two matched controls:

* **widen the fit to 15–31y**, making a 20-year bond interior rather than terminal; and
* **matched placebo boundaries** at 22/24/26/28 years — the same crossing shape, the same
  ~2% firing rate, at maturities where no index does anything whatsoever.

| boundary | flags | β @63d (bp/z) | HAC t @63d |
|---|---|---|---|
| **REAL 20y**, fit 20–31y (20y is the *edge*) | 2.33% | +0.042 | **+3.26** |
| **REAL 20y**, fit 15–31y (interior, matched) | 1.59% | +0.058 | **+2.40** |
| PLACEBO 22y | 1.93% | −0.025 | −2.07 |
| PLACEBO 24y | 2.09% | +0.015 | +1.63 |
| PLACEBO 26y | 2.08% | +0.016 | +1.23 |
| PLACEBO 28y | 2.09% | −0.050 | **−2.41** |

**The real boundary is beaten by a placebo.** Across all horizons the real 20-year
boundary's largest |t| is **2.40**; the placebos' largest is **2.74** (28y at 21 days).
A maturity-shaped dummy at a boundary where no index does anything produces a *stronger*
statistic than the real one, so the real one sits inside its own null distribution rather
than outside it. Half its apparent strength (t 3.26 → 2.40) was the fit edge; the rest is
what searching five boundaries buys.

The point estimate is worth stating anyway, because it is the ceiling: a flagged bond
carries z ≈ −5 (clipped), so ~**0.29bp of cheapening over 63 days** — still below the
0.5bp round trip before any of the above is taken into account.

### 3.6 And a double sort will not reproduce even that

Sorting on richness first and on `active_w` inside each richness quintile, 63-day forward bp:

| richness quintile | 0 (rich) | 1 | 2 | 3 | 4 (cheap) |
|---|---|---|---|---|---|
| high-minus-low `active_w` | +0.028 | +0.010 | −0.021 | −0.033 | +0.030 |

Not monotone, sign-flipping, and of the same size as its own noise. **A naive t of 4 that survives neither a
HAC correction nor a double sort is a linear artefact.**

### 3.7 The backtest agrees, and so does the grid

Baseline config (per-CUSIP `active_w`, 10-day hold, `exec_lag=1`, 3 bellies each side): **1,407
butterflies, gross +0.0045bp per trade, cost 0.502bp, net −0.498bp.** The book loses almost exactly
its own execution cost, because there is no gross edge to pay it with.

Three more numbers from the executed notebook:

* **The grid: 0 ALIVE of 152 scored configurations** (DSR > 0.95, ≥ 50 trades, positive net),
  against a selection hurdle of `sr* = 0.5067` per trade with **321 trials counted** — the grid's
  160 plus the 169 searched in the IC, partial-IC, timing, structure and fund sweeps.
* **The lookahead is worth 0.0011bp.** Mean gross bp is +0.0103 at `exec_lag = 0` and +0.0092 at
  `exec_lag = 1`. Even reading tomorrow's file buys essentially nothing, which is its own kind of
  evidence: there is no edge to lose to causality.
* **The sign-flip permutation on GROSS P&L gives p = 0.413** (realised Sharpe/trade +0.0221 against
  a null of −0.0002 ± 0.0268). The direction the signal chose is indistinguishable from a coin.

A wide grid over 5 funds × 1,680 configurations was also run; the two funds that completed
(IEF, TLH — 3,360 configurations) had **0 with gross above cost**, best gross 0.207bp against a
0.53–0.66bp cost. The remaining three were stopped: `keep_results=True` holds ~1MB per
configuration and the large-universe workers were thrashing, which is now fixed
(`keep_pnl=True` keeps only what the DSR needs).

---

## 4. Six independent investigations, and the one number that explains them all

Run as parallel investigations with an adversarial verification pass on each. Every one
returned DEAD, and — more usefully — they converge on a single mechanism.

### 4.1 The ETF's trading does not move the bond, even on the same day

This is the number that settles the project. Regressing a bond's **same-day** richening on
the ETF's realized trade in it, as a share of the bond's free float:

| fund | slope t (aligned) | IC t | slope t (non-flow days) |
|---|---|---|---|
| TLT | −0.11 | +0.45 | +0.05 |
| TLH | −0.11 | −0.06 | −0.05 |
| GOVT | +0.39 | +1.31 | +0.41 |
| IEF | +0.78 | +0.64 | +0.57 |
| IEI | +0.94 | +0.68 | +0.93 |

Contemporaneous impact is **not a tradeable signal** — it is the feasibility test. If a
fund's own trade cannot be detected in the same day's price, no *predictive* version of
that flow can work. It cannot be detected in any of the five.

The reason is size. Median share of a bond's publicly held float owned by the fund:
**TLT 1.7%** (p90 5.3%), TLH 0.8%, IEF 2.5%, IEI 0.4%, GOVT 0.3%, SHY 0.8%. A holder of
1.7% of the float does not price a US Treasury.

### 4.2 The calendar beats the scrape on five funds out of six

Best holdings-based signal versus the calendar-only `deletion` signal, by partial IC at
63 days — the calendar version reads **no holdings file at all**:

| fund | best holdings signal | its IC | `deletion` IC | calendar wins |
|---|---|---|---|---|
| TLT | `bucket_hist_z` | 0.058 | **0.290** | yes |
| TLH | `ownership` | −0.061 | **0.291** | yes |
| IEF | `bucket_active` | 0.060 | 0.080 | yes |
| IEI | `bucket_active` | −0.056 | **−0.319** | yes |
| SHY | `bucket_active` | −0.025 | −0.146 | yes |
| GOVT | `bucket_active` | 0.050 | 0.016 | no |

And §3.5 shows the calendar signal is itself a fit-boundary artifact. So the ranking is:
placebo > calendar > holdings.

### 4.3 The bucket ladder's own null twin matches it

`bucket_hist_z` — a bucket's weight against its own history, the literal original
formulation — produces the largest linear IC in the study (partial IC 0.058, naive t
+15.3). Replacing the fund's weight with the **index** weight, which needs no holdings
file, gives 0.065 at t +15.3: the null twin is *larger*. Regressing the signal on
bucket age, weight level and 250-day weight change gives R² 0.10–0.19, so a fifth of it
is mechanical before any of this.

The same investigation caught and discarded its own first pass: scoring a bucket by the
median residual of *whoever occupies the slot* produced partial-IC t of 30–67, because a
bond rolls clean through a 3-month bucket in ~63 business days and the "return" was ~100%
composition turnover. Holding composition fixed at entry removes it.

### 4.4 The deletion cliff, tested as an event rather than a score

32 usable crossings, verified against the holdings: TLT really does shed **85–90%** of its
position by day +120, in two tranches rather than one month-end cliff. The richness
effect is there — tail window mean **+0.47bp**, t = 2.93, 8 of 11 years positive — but two
identification checks refuse it as a *flow* story:

* **Amplitude does not scale with ownership.** corr(TLT's share of the bond's float,
  event amplitude) = **0.002**, and a tercile sort runs *backwards* (low-ownership 0.73bp
  vs high-ownership 0.43bp). A forced-selling effect must scale with the forced seller.
* **Reversing the flow direction does not reverse the sign.** The same test at the 10-year
  boundary — where a *small* seller (TLH, $11bn) is replaced by a *large* buyer (IEF,
  $43bn), the opposite flow — gives **+0.52bp, t = 2.31**: statistically indistinguishable.

Tradeable: 1,274 trades over 40 entry/exit cells. Best gross 0.40bp against a measured
1.09bp cost; **0 of 40 cells net positive even at the optimistic 0.5bp floor**. The
addition side (119 new-30y inclusions) shows nothing at all (t = 0.24–0.26).

### 4.5 Aggregate ownership is a level, not a forecast

Summed across every scraped fund, ETF ownership is worth **+0.032bp of richness per
percentage point of float owned, contemporaneously** — and that survives HAC correction
(t 32 → 8.8). Predictively it does not: the multivariate 21-day coefficient falls to
t = 0.58. Fed SOMA ownership, a far larger holder, carries a *negative* coefficient
(−0.005bp/pp, HAC t −4.7), which is the wrong sign for scarcity and marks the whole
channel as a proxy for issue characteristics rather than a supply effect.

### 4.6 No conditioning cell concentrates the effect

Dislocation size (|z| > 1 … 3), month-end vs month-start, creation vs redemption vs quiet
days, by year and by rate-volatility regime: the share of positive outcomes stays in
**0.52–0.56** across every cut. There is no corner where this works.

### 4.7 What the adversarial pass caught

The verification agents found real defects rather than rubber-stamping, and two changed
numbers that had already been written down:

* **IEI's apparent signal was a curve-fit artifact.** `bucket_active` IC of −0.056
  came from a whole-curve fit; refitting locally it collapses to **−0.0009**. (This bullet
  previously attributed the −0.056 to GOVT, contradicting §4.2's own table, where −0.056 is
  IEI and GOVT is **+0.050**. `_data/adv_calnull_recheck.csv` holds IEI −0.0562 and GOVT
  +0.0497; the table was right and this bullet was wrong.)
* **Naive t-statistics were inflated 5–6×** by overlapping windows — measured
  independently at 5.19× (TLT `bucket_hist_z`) and 5.95× (GOVT `bucket_active`), which is
  the same correction §3.4 applies.
* **Publication lag confirmed empirically**: a holdings file's implied trade correlates
  0.10–0.19 with the same day and **0.74–0.99** with the next file, so `exec_lag ≥ 1` is
  a measurement, not a convention.
* Phantom deletion events (a freshly issued 20-year registering as a crossing) were found
  and excluded, and a config-count reconciliation caught a report claiming 1,760
  evaluated cells against 1,673 actually written.

---

## 5. Two things the data layer taught, both worth keeping

**A refusal is not a data point.** The first backfill ran six unpaced workers, fetched 143
documents, was served `403 Access Denied` for the next 2,515, wrote all 2,515 as "no file for this
date", and **exited 0** — leaving a manifest that resume would have honoured. The provider now
raises on a refusal, and requests rotate across a pool of exits because the block was IP-level
(plain `curl` from the same machine was refused identically).

**`eod_price` and the published bid/offer are not two points on one quote.** Across 727,289
two-sided observations `eod` sits at the bid at the median and reaches ±20 spread widths at the
1st/99th percentiles. Neither is stale — both unchanged d/d on 1.1–1.8% of days, identical
daily-change σ, cross-sectional cubic-fit RMSE 0.916bp vs 0.919bp. This is a genuine basis
difference between two live series, so `price_basis` is a swept knob rather than a decision.

Two vendor defects are gated rather than trusted: `eod_price = 0.00` for **every** bond on 9 whole
dates, and `offer_price = 0.00` for bonds inside their last year (1,441 of 1,543 rows under six
months). Averaging a real bid with a zero offer gave a mid of ~50 on a par bond and a yield of
3.1e+20 %.

**The one real hole** is honest and bounded: iShares publishes no TLT or TLH document before
**2017-07-06**, verified by re-requesting from clean exits and receiving HTTP 200 with a
non-holdings body. 2016 is complete; 2017 H1 does not exist.

**A butterfly amplifies the price basis, and that is not a rounding error.** Three near-identical
legs cancel the level and leave whatever differs between them — which includes the choice of price
basis. The two FedInvest series differ by a median of **1.07bp** in yield, and marking the same ten
packages on each produced daily P&L that disagreed by **13×** on a single day of the March 2023 SVB
week. On a genuinely common basis the same 60-package book agrees to **0.05bp on the level** with a
daily-change correlation of **0.71**.

Two defects had to be removed to get there, and both are the same shape — *something that looked
like it was working*:

* the first eod conversion was first-order (`dy = −dP/(D·P/100)`), and its error lives exactly where
  a butterfly is most sensitive; the panel now solves **both** bases exactly (`ytm`, `ytm_eod`);
* the `price_basis` **knob itself was inert**. `prepare_universe` repriced the panel, but every
  price column the universe uses comes from the *holdings join*, which was untouched — so the two
  bases produced books identical to six decimal places, and the sensitivity check compared a thing
  to itself while reporting the result as robust. Wiring it took the QDB correlation from 0.45 to
  0.71 and the level gap from 0.44bp to 0.05bp. The headline is genuinely basis-robust
  (gross +0.0045bp on mid, +0.0047bp on eod) — but that is now a measurement rather than an
  artefact of a knob that did nothing.

---

## 6. What this does *not* rule out

* **The deletion cliff, as an EVENT study.** §3.5 tested it as a cross-sectional score and it did
  not survive a matched placebo. What that does not settle is the event itself: a bond crossing
  below 20 years leaves a $47bn holder and joins an $11bn one on a date known years in advance,
  and the right object is the cumulative abnormal move of *that bond* against maturity-matched
  controls from T−60 to T+60, not a daily cross-sectional tilt. The point estimate here (~0.3bp
  over 63 days) is the ceiling such a study would be working under.
* **A cheaper execution.** Every number here is a cash butterfly paying three measured spreads. The
  gross column is the one to carry to any venue where execution is cheaper.
* **Intraday.** Holdings are daily; the rebalance is not. If the flow moves a bond at all, it moves
  it inside a session, and this dataset cannot see that.
* **ETF premium/discount as a flow forecast.** A fund trading above NAV is about to create. That is
  a fund-level flow signal, daily-observable, and it is not in the registry — it needs ETF market
  prices, which were out of scope here.

---

## 7. How to reproduce

```bash
export ARBS_ETF_HOLDINGS_DIR="C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache"
PY=C:/Users/chris/anaconda3/envs/stir/python.exe

# data (already built; both are resumable and idempotent)
$PY -m MDP.ETFHoldings.backfill --plan all --verify
$PY -m RVUtils.ETFRebalance.bond_panel  --start 2015-06-01
$PY -m RVUtils.ETFRebalance.float_panel --start 2015-06-01

# warm the GC fixing cache over EVERY panel date FIRST. engine._gc_series fetches
# missing dates one at a time; warmed over only one fund's universe, the other funds'
# extra dates become hundreds of serialised live lookups INSIDE a notebook cell, and
# the kernel reads as hung (100 threads, open sockets, ~25 CPU-seconds per hour).
$PY RVUtils/ETFRebalance/_prewarm_gc.py

# the checks that must pass before any number is believed
$PY RVUtils/ETFRebalance/_tie_out_panel.py      # panel vs FixedRateBondsMDP, an identity
$PY -m pytest tests/test_etf_rebalance.py -q
$PY tests/_mutate_etf_rebalance.py              # do the tests actually bite?

# the study
$PY RVUtils/ETFRebalance/_run_ic.py --funds TLT
$PY RVUtils/ETFRebalance/_run_partial_ic.py --fund TLT
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/backtests/etf_rebalance/etf_rebalance_configurable_backtest.ipynb
```
