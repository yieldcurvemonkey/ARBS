# W4 — ultra-long curve pairs on risk-adjusted carry: **DEAD**

Measured 2026-08-21, worktree `ARBS-cvx2`. 2021-01-01 → 2026-08-20, 1,470 daily
marks, 117 episodes, 234 closed legs, $100k package DV01.

**Verdict: the gross Sharpe does not clear the null expectation for the search
that produced it.** This is not a marginal call and no cost assumption rescues
it.

---

## 1. The headline

| | terminal | ann Sharpe | max drawdown |
|---|---:|---:|---:|
| 0.25 bp half-spread | +$9,731,902 | **0.180** | −$23,810,491 |
| zero cost | +$21,431,902 | **0.397** | −$20,206,356 |

P&L by year (USD m): **+1.9 / −9.8 / +3.4 / −2.0 / +12.3 / +3.9**.

Two things are visible before any statistic is computed. The maximum drawdown is
**−$20.2 m even gross**, against $21.4 m of total gross P&L over the whole
sample. And a single year, 2022, loses $9.8 m on a book nominally sized at
$100 k DV01.

## 2. Why it is dead: multiple testing at the effective sample size

Positions are held a **mean of 102 business days**, so 117 episodes over 5.63
years are not 117 independent observations. Effective sample size is about
**14 independent holds**.

`RVUtils.ConvexityRV.strat1_threeway.expected_max_sharpe_under_null` on **two**
clocks, because the default one is not the clock the Sharpes are measured on.
`n_obs = 14` sets the standard error to `1/sqrt(14) = 0.268`, the SE of a
**per-hold** Sharpe. The figures quoted here are **annualised**, whose null SE
is `1/sqrt(span_years) = 1/sqrt(5.63) = 0.421`. With holds this long the
annualised clock is the **stricter** of the two, so quoting only the per-hold
number understated the bar:

| trials | E[max SR \| null], per-hold (SE 0.268) | E[max SR \| null], annualised (SE 0.421) |
|---:|---:|---:|
| 6 | 0.348 | 0.548 |
| 12 | **0.446** | **0.702** |
| 24 | 0.530 | 0.834 |
| 48 | 0.605 | 0.953 |

The **gross** Sharpe is **0.397**. The exit-rule × minimum-hold sweep alone was
**12 cells**, and the signal design explored more than that. So the best number
this strategy produces, *before any transaction cost*, sits below what a
zero-edge strategy would be expected to produce from the same search — on
**both** clocks, 0.397 against 0.446 and 0.702. The net Sharpe of 0.180 is
below even the six-trial null on either.

(`w4_rac_screener` reports a third figure, 0.4449, because it floors rather
than rounds its own slightly different `n_eff`. The spread across all three is
0.445–0.702 and the gross Sharpe is below all of it, which is the only reason
the arithmetic detail can be left as a footnote.)

## 3. Costs, and why they are not the reason

Costs remove **$11.7 m of $21.4 m gross — 54.6 %**. The charge is 2 legs × 2
sides × 0.25 bp on the package DV01, i.e. **$100,000 per closed episode**.

That is *more conservative* than the only external datapoint available: Citi's
own 15y5y/20y10y round trip ran **+$187 K gross to +$155 K net on $50 K DV01**,
about **$64 K per $100 k DV01 including every resize**, against the $100 K
charged here.

Break-even is at a **0.458 bp half-spread**, i.e. 1.83 bp of package DV01 round
trip. So at Citi's measured cost the book would still be positive in dollars —
and it would still fail on Sharpe, because §2 is a statement about the gross
number. **Costs make it worse; they are not what makes it dead.**

## 4. What the signal actually did

Built on `RVUtils/ConvexityRV/rac_signal.py`; the screen underneath it ties out
to Citi's 2019-12-04 table on 120 published cells (rank Spearman 0.988 on the
decision statistic).

Two structural facts, both measured and neither engineered away:

* **2024 and 2025 fire zero flatteners; 2026 fires three.** Risk-adjusted carry
  declined monotonically — median `rac` +0.008 in 2023 to −0.074 in 2026 — so on
  a three-year trailing window every pair sits near the bottom of its own
  history. The book is effectively steepener-only for the last three years,
  which is half the sample.
* **The `10Yx10Y` family is structurally one-sided**, carrying positively on
  0.9–2.9 % of days against 24–54 % for the tight pairs. A carry-keyed rule can
  only ever say one thing about it.

Whether the first of those is the rule correctly refusing to buy expensive
convexity, or a trailing percentile degenerating on a trending series, the
backtest does not distinguish — and given §2 there is no reason to spend more on
finding out.

## 5. What this cost to learn, and what it caught

Four defects in the harness, each found by a guard or by a knob sweep returning
something impossible, **none by a number looking wrong**:

1. **`exit_pct` was wired to nothing.** Sweeping it over 0.50 / 0.35 / 0.20 /
   `None` returned byte-identical books — "the entry condition lapsed" dominated
   every other exit. Median hold was **2 days** on a trade Citi held seven months.
2. **`min_hold_days` deleted short episodes rather than holding them**, keeping
   exactly the trades that happened to persist. Not a tradable rule, since length
   is only knowable afterwards. The tell was that total leg-days *fell* as the
   minimum hold rose.
3. **Every `DateTrigger` silently never fired.**
   `DateTriggerRequirements.has_triggered` is `state.date() in set(self.dates)`,
   and a `pd.Timestamp` is a `datetime.datetime`, which never equals a `date`.
   Zero positions opened, 1,470 marks of exactly 0.0, and `run()` reported
   success — the flat-equity-curve failure this codebase explicitly warns about.
4. **Relative forward tenors re-resolve on every mark date**, so a `CURVE`
   package prices fresh at market daily and its NPV is ~0 by construction. Legs
   now resolve to explicit dates at entry.

The sign probe's own first draft double-applied the risk weight and reported
+100 k / +100 k summing to **200,000** on a package whose defining property is
that it sums to zero.

## 6. What would have to be true for this to be worth revisiting

Not "tune the thresholds" — the search is already what killed it. It would need a
different *structure*: fewer, larger, longer holds so that `n_eff` rises, or a
hedge that removes the drawdown rather than the return. The factor attribution
(§7) is the input to that judgement, and it is the only thing that says whether
the −$20 m drawdown is convexity being paid for or duration being taken.

## 7. Factor attribution — it is duration, not convexity

Daily P&L on the shared basis, Newey-West t-stats, 1,409 observations,
2020-06 → 2026-08. Basis: PC1 87.76 % of variance, PC2 11.26 %, PC3 0.75 %, with
PC1's loadings **all positive and humped** — 0.295 (2Y), 0.342 (5Y), 0.258 (50Y)
— i.e. a level factor, matching the 88.34 % the previous block measured on a
neighbouring window.

| factor | share of P&L | t (HAC) | incremental R² |
|---|---:|---:|---:|
| **level** | **−132.8 %** | **−4.85** | **0.1226** |
| convexity | −156.8 % | −0.67 | 0.0012 |
| curvature | +2.0 % | 0.14 | 0.0001 |
| slope | +0.1 % | 0.37 | 0.0004 |
| unexplained | +387.5 % | — | — |

Total R² 0.1244, of which **level supplies 0.1226**. The only factor that is
statistically distinguishable from nothing is the one the trade is supposed not
to have: a DV01-neutral package is a claim about level exposure, and this book
carries level at **t = −4.85** and *loses* money to it.

**One caveat, stated because it cuts the other way.** `DESIGN.md` records that
daily convexity is unidentified — a squared daily move is noise-sized against
daily P&L, and the codebase measures convexity t-stats of 2.1–5.4 at trade level
against 0.9–2.1 daily. So the convexity row here (t = −0.67) is **not** evidence
that convexity is absent; it is the expected reading at this frequency. What the
daily regression *can* establish is the level exposure, and that is unambiguous.

The two findings compose without needing the trade-level number: §2 already
shows the gross Sharpe fails its own search, and §7 shows the significant
exposure is unwanted duration. A trade-level convexity term, whatever it turns
out to be, does not rescue a book whose best gross number is below the null.

### The classifier needed checking before it could be believed

`classify_pcs` first labelled PC1 **"slope"**. It was handed
`list(rates.columns)` — twelve tenors, because `build_rate_panel` returns the
`extra_tenors` 1Y alongside — for an eleven-element loading vector, and reported
a phantom sign flip. The loadings are all positive; PC1 is level. Fixed to pass
`fm.tenors`, the tenors actually fitted. Worth recording because the label is the
thing the whole attribution is read through, and "a long-end-heavy grid can
rotate them" is a real hazard this repo already warns about — which is exactly
why a wrong label here was plausible enough to nearly accept.
