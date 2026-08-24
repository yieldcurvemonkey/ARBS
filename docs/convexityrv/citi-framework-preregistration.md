# CITI — the published convexity trade, backtested in its own framework

**Pre-registered 2026-08-24, BEFORE any P&L was computed.** Block 5 of the
convexity RV programme. Anything scored later that is not declared here expands
the trial count and must be added as a dated amendment — the null bar moves with
it, and the test suite counts the declared cells against this document
(`tests/test_convexity_rv_citi_rule.py::test_declared_count_matches_the_preregistration_document`).

This is the **fifth** pass over the same CA panel: block 1 `strat2`, block 3
`cavf`/PR #492, block 4 `gv`/PR #496, the reproduction/PR #499, now this. The
cumulative-search caveat is on the record and travels with every number this
block produces. Declaring one rule today does not undo four prior searches.

---

## 0. What this block is, and why it is not block 4 again

Block 4 scored **298 declared cells** of CA-vs-fly and found nothing: best
primary cell **0.851** against an annualised `E[max SR | null]` of **1.2198**.
**That grid did not test Citi's rule.** The differences are specific and every
one of them matters:

| | block 4's grid | Citi's actual framework |
|---|---|---|
| hedge weights | β from a rolling fit of CA on ONE fly with fixed 50/50 wings | the weights are the **output** of a 3-rate regression — the fly shape is fitted |
| rebalance | β frozen at entry | re-struck at each quarterly refit |
| structure choice | one per cell | a **screen across the strip** picks the most attractive (Figure 20) |
| entry | `\|z\| ≥ 2` | a **conjunction**: wide to model AND wide to the fly AND positive roll AND rich implied/realised AND stretched positioning |
| exit | z-exit / max hold | an explicit **dollar target and stop** (+$600k / −$350k on $200k DV01 ≈ +3.0 / −1.75 bp) |
| direction | two-sided (declared, and it doubled the opportunity set) | **short-only** — sell rich convexity |
| roll | flat across every roll (blackout) | held through, on dated instruments |
| trials | 298 | 23 (§7) |

The two sources, both already extracted:

* **`print (12).pdf`** — Citi, NA Rates Trade Idea, **09 Feb 2017**, Bikbov &
  Williams, *"Sell Blues convexity adjustments, hedged"*.
* **`print (15/18).pdf`** — Citi, US Rates Weekly, **13 Jan 2017**, *"Swearing
  in huge expectations"* §*Smart convexity sells*.

Prose extraction at `docs/convexityrv/research/corpus2/g10-print-files.md` §4
and §8; the reproduction of the note's figures on current data is
`notebooks/backtests/convexity_rv/citi_blues_ca_repro.py` (PR #499).

---

## 1. Measurements taken BEFORE this file was frozen

All on USD SOFR, 1,409 dates 2021-01-04 .. 2026-08-21, from
`_p4_certify_inputs.py`, `_p4_leg_vintage_diff.py`, `_p4_preflight.py` and
`_p4_conjunction_probe.py`. **No P&L was computed by any of them.** Looking at
the distribution of an *input* before freezing a threshold is what block 4's own
§0 did; looking at a P&L is not, and nothing here does.

### M0 — the carried panels re-price, and the leg panel needed checking

A copied artifact is a hypothesis until it is re-priced.

* **CA panel** (`cavf_ca_panel.parquet`): 6 random dates × 5 colours re-priced
  through `IRSwapsTB.sfr_cvx_adj`, **max |fresh − panel| = 0.00000000 bp** over
  30 cells.
* **Leg panel** (`p2_legs.parquet`): the first sample said the spot 2y/5y/10y
  were **off by up to 0.0121 percent = 1.21 bp**, which would have moved every
  fitted fly. A full-window re-pull of all 13 columns the block uses found them
  **exact on 1,409 of 1,409 dates**. The difference was the *request shape*: the
  sample was pulled as one 940-day span, the panel and the re-pull year-chunked.
  **A single multi-year `IRSwapsTB` span request returns different par rates for
  the same dates than the year-chunked request does.** The panel build here is
  year-chunked, like every other panel build in this package, and that is now a
  stated convention rather than an accident.

### M1 — the two roll clocks, and the roll jump IS the theta

22 CA rank-map rolls (ON the IMM date) and 22 `IMM_k` leg rolls (the business
day BEFORE), **zero in common** — block 4's M3, reproduced on this panel.

| pack | mean ΔCA on roll | t | mean \|ΔCA\| off roll | θ, bp/month | quarter-θ | jump ÷ quarter-θ |
|---|---:|---:|---:|---:|---:|---:|
| WHITES | +0.703 | 0.80 | 0.887 | −0.054 | 0.163 | 4.31 |
| REDS | −0.334 | −0.32 | 0.945 | −0.153 | 0.458 | −0.73 |
| GREENS | **+0.741** | **2.44** | 0.208 | −0.237 | 0.710 | **1.045** |
| BLUES | **+0.946** | **2.70** | 0.752 | −0.308 | 0.924 | **1.024** |
| GOLDS | **+1.223** | **2.46** | 0.915 | −0.367 | 1.101 | **1.111** |

The three tradeable colours agree with the analytic quarter-theta to 2–11%. The
two front packs do not, and their marks are the noise-dominated ones (§2).

### M2 — the splice belongs in the P&L and NOT in the signal

`roll_spliced` removes each roll's jump from every later value. Because the jump
*is* the theta being paid back, the spliced series inherits the whole undone
decay as a drift:

| pack | undone jumps over the window | raw CA drift | spliced drift | median 1Y z, raw | median 1Y z, spliced |
|---|---:|---:|---:|---:|---:|
| GREENS | +16.3 bp | +1.37 | −14.94 | −0.203 | **−1.313** |
| BLUES | +20.8 bp | +4.33 | −16.48 | −0.369 | **−1.146** |
| GOLDS | +26.9 bp | +5.65 | −21.25 | −0.532 | **−1.277** |

A 252-day rolling z of a trending series mostly measures the trend. So:

* the **screen** asks whether a RANK of the curve is rich against its own
  history, and a constant-rank CA is stationary *because* the roll pays the
  decay back — so **the conditions are evaluated on the RAW quoted CA**, which
  is the object Citi's Figure 20 z-scores;
* the **P&L** asks what a DATED position earns, and a dated position has no
  label to switch — so **the panel P&L marks the SPLICED series**.

Both are declared, both are swept as sensitivities (§9), and the engine — which
prices real dated instruments — is the authority on the difference. The known
cost of the splice is that a roll date's genuine market move is discarded along
with the contract switch: about 0.15 bp of level over 22 rolls against the
+0.95 bp/roll it removes.

### M3 — the screen's own identities

`CA − Model − VsModel = 0.000e+00` exactly (10 of 7,045 cells skipped: two dates
carry no vol mark). `implied² · w / 2e4 − CA = 7.1e-15` (997 cells skipped: a
non-positive CA has no real implied vol, and the front packs go negative often).

The note's `3m Roll` is `CA(p) − CA(p one contract nearer)`. Colour packs are
one YEAR apart, so the adjacent-quarter neighbour does not exist in the
tradeable set; the declared column is the analytic `−θ/4`, and the
term-structure form `[CA(p) − CA(p one year nearer)]/4` is reported beside it:

| pack | analytic, bp | term structure, bp | ratio | corr |
|---|---:|---:|---:|---:|
| REDS | 0.458 | 0.153 | 3.00 | 0.38 |
| GREENS | 0.710 | 0.835 | 0.85 | −0.06 |
| BLUES | 0.924 | 1.190 | 0.78 | 0.58 |
| GOLDS | 1.101 | 1.201 | 0.92 | 0.76 |

A rolling-pack CA at every quarterly rank could be built from the outright strip
(measured: mean |pack − mean of its four outrights| is 0.06–0.08 bp for
GREENS/BLUES/GOLDS, 0.19/0.37 for REDS/WHITES), but the individual outrights are
the noisiest marks on the board — Citi's own reason for using packs — so that
construction is a **display diagnostic only** and is never traded.

### M4 — the five conditions, and the fact that they do not co-occur

Pass rates on the raw quoted series, whole panel:

| pack | wide_to_model | wide_to_fly | positive_roll | implied_rich | positioning | **all five** |
|---|---:|---:|---:|---:|---:|---:|
| GREENS | 0.0248 | 0.0199 | 0.9986 | 0.1923 | 0.3534 | **0.0007** |
| BLUES | 0.0234 | 0.0234 | 0.9986 | 0.2697 | 0.3534 | **0.0007** |
| GOLDS | 0.0284 | 0.0546 | 0.9986 | 0.2229 | 0.3534 | **0.0000** |

**The five-way conjunction is satisfied on 2 of 1,409 dates across the whole
primary universe.** Nested, one condition at a time:

| pack | wide_to_model | + wide_to_fly | + positive_roll | + implied_rich | + positioning |
|---|---:|---:|---:|---:|---:|
| GREENS | 35 | 6 | 6 | 2 | 1 |
| BLUES | 33 | 2 | 2 | 1 | 1 |
| GOLDS | 40 | 0 | 0 | 0 | 0 |

The reason is in the pairwise lift (observed joint rate ÷ the rate under
independence), BLUES:

| | wide_to_model | wide_to_fly | implied_rich | positioning |
|---|---:|---:|---:|---:|
| **wide_to_model** | — | **2.59** | **0.34** | **0.43** |
| **wide_to_fly** | 2.59 | — | 0.90 | 1.03 |
| **implied_rich** | 0.34 | 0.90 | — | 1.01 |
| **positioning** | 0.43 | 1.03 | 1.01 | — |

Two of the note's own conditions **fight** the first one on SOFR: a CA that is
unusually wide to the Ho-Lee model tends to occur when realised vol has been
high (so `implied/realised` is low, lift 0.34), and when dealers are *not*
stretched long (lift 0.43 — consistent with the separately measured
`corr(vs_model, dealer 1Y z) = −0.187`, which is the note's own positioning
mechanism failing to reproduce on SOFR). And the two "wideness" measures the
note treats as saying the same thing are nearly orthogonal: 2.3% each, 0.14%
jointly.

### M5 — the fair value on this window

Citi's method (fly-constrained 3-rate fit, refit at every CA roll, 504 bd
trailing window or all available history):

| pack | refits | w2 median | w2 range | b median | **b sign flips** | w2 at a boundary | OOS resid sd | first fitted |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| GREENS | 21 | 0.31 | 0.90 | −8.95 | **4** | 11/21 | 2.350 bp | 2021-06-16 |
| BLUES | 21 | 0.70 | 0.90 | +12.42 | **4** | 9/21 | 4.537 bp | 2021-06-16 |
| GOLDS | 21 | 0.34 | 0.90 | +31.20 | **2** | 6/21 | 7.280 bp | 2021-06-16 |

On the reproduction's own narrower window (2022-01-03 start) BLUES has **one**
sign flip and a residual sd of 2.232 bp; adding 2021 doubles the residual and
doubles the flips. **The window is not narrowed to make this look better.** The
panel is the full CA panel, the fit uses whatever history exists, and the
instability of Citi's fair value on this window is a result, not a nuisance to
be tuned away.

### M6 — the threshold ladder, measured before it was declared

Days on which SOME primary structure satisfies all five conditions:

| z threshold ↓ / impl-rlzd → | 1.3 (the note's) | 1.0 | dropped |
|---|---:|---:|---:|
| **2.0 (the note's)** | **2** | 2 | 2 |
| 1.5 | 2 | 4 | 4 |
| **1.0** | **11** | 18 | 20 |
| 0.5 | 30 | 59 | 84 |
| 0.0 | 51 | 108 | 161 |

Two rungs are scored: **2.0**, the note's own printed reading, and **1.0**, the
loosest reading of "wide" that still means wide and the first rung with enough
entry-eligible days to be scoreable. **1.5, 0.5 and 0.0 are measured above and
deliberately NOT scored** — the ladder this block did not walk is printed here
so that a reader can see it rather than wonder about it.

---

## 2. Window, panels, conventions

* Panel window **2021-01-04 .. 2026-08-21**, 1,409 CA dates, span 5.626 y.
* **Tradeable span 4.682 y**, from **2021-12-15** — the first date on which the
  fair value, both z-scores, the realised-vol column and the positioning z all
  exist. Every null bar in this block is computed against 4.682 y, not 5.626 y:
  a book that cannot open until its inputs exist has not been running for the
  whole panel.
* Curve MDP `IRSwapsMDP(source="citivelo_excel_rl")`; vol from the swaption
  cube via `IRSwaptionsTB`; CFTC TFF release-lagged 3 business days.
* Panel `p4_citi.parquet` (1,409 × 82), built by `_p4_build_panel.py` from
  artifacts certified in M0.
* All signals use **t−1 information; fills execute at the t+1 mark**
  (`exec_lag_bd = 1`). `exec_lag_bd = 0` is a reported diagnostic whose gap to
  t+1 **is** the mark-noise harvest, and it has a known-answer test.

### Structure universe

**Primary selection universe:** `GREENS`, `BLUES`, `GOLDS` (front ranks 9, 13,
17). **`WHITES` and `REDS` are excluded from the primary universe** because the
AC1 of their daily CA change is −0.540 / −0.517, at or past the −0.5 pure-noise
bound: a "pick the widest" rule over them adversely selects their noise spikes
rather than dislocations, which is a different failure from merely trading a
noisy mark. `screen_best_all5` (§7) is the declared secondary cell that measures
exactly that, and its numbers carry the caveat.

---

## 3. The rule

### 3.1 Fair value — Citi's Figure 6

`CA_bp ~ a + b·(−w₂·r2 + r5 − w₁₀·r10)` on **spot** 2y/5y/10y percent par rates,
**fly-constrained** (`w₂ + w₁₀ = 1`, so the fitted object is a real butterfly and
the hedge is DV01-neutral), refit at **every quarterly SR3 IMM roll** on a
trailing **504 bd** window (or all available history) ending **strictly before**
the roll, in force from that roll until the next. `b/100` is the hedge ratio in
bp of CA per bp of the quoted fly.

Spot is Citi's own start, and the reproduction measured it best of ten
(OOS residual sd 2.232 bp against 3.396 for the matched-expiry `IMM_13`, 9th of
10). No other start is scored here.

### 3.2 The screen — Citi's Figure 20

Every date, every colour: `CA`, `1wk chg`, `CA 3m/1Y z`, `Model` (Ho-Lee on the
ATMF normal vol of the straddle at the structure's own mean expiry against a 1y
tenor), `VsModel`, `VsModel 3m/1Y z`, `3m Roll`, `Implied`, `Realized` (63 bd,
roll returns excluded), `Impl/Rlzd`.

### 3.3 Entry — the conjunction

All five must hold on the same date, on `t−1` information, evaluated on the
**raw** quoted series (M2). A NaN input cannot confirm a condition.

| id | rule | the note's words | threshold |
|---|---|---|---|
| `wide_to_model` | `VsModel 1Y z ≥ Z` | *"roughly 4bp (about two sigmas) wide to the model"* | **Z** |
| `wide_to_fly` | `(CA − fitted) 1Y z ≥ Z` | *"about 3bp (about 2 sigmas) wide to the fly"* | **Z** |
| `positive_roll` | `3m Roll > 0` | *"short-CA rolldown +1.3bp over 3m"* | 0 |
| `implied_rich` | `Impl/Rlzd ≥ 1.3` | Figure 20's H0-Z0 row prints **1.3**; the origin note says *"about 30% rich to 3m realized"* | **1.3** |
| `positioning_stretched` | dealer-net 1Y z ≥ 1.0 | *"Long dealers' positions in futures reached historically high levels"* | **1.0** |

`Z ∈ {2.0, 1.0}` — the two declared rungs of §1 M6. The 1Y z is the gate; the
3m z is reported. `impl_rlzd` and the positioning threshold are the note's own
values at both rungs and are swept **on finalists only**, as sensitivities, not
as trials.

### 3.4 Selection

Among the structures passing the conjunction, take the one with the **highest
`VsModel 1Y z`** — the note's own ordering (*"The Blues pack CA looks especially
attractive being roughly 4bp (about two sigmas) wide to the model"*). **At most
one position is open at a time**: Citi's Blues ticket closed on 6-Jun-2017 and
its Greens ticket opened the same day.

### 3.5 Direction and size

**Short only** — sell rich convexity: buy the futures pack, pay the matched
quarterly/quarterly swap. `CA_DV01 = $200,000`, the note's own ticket, constant.

### 3.6 Hedge

`belly_DV01 = β · CA_DV01` with `β = b/100` from the fit in force, direction
from `sign(b)` — and the sign matters: the reproduction measured `b` reversing
in mid-2023, so after that date selling a rich CA means being **long** the fly,
the opposite side from Citi's 2017 ticket. Four declared schemes:

| id | rule | why declared |
|---|---|---|
| `fitted_refit` | the fly-constrained fit, **re-struck** at each refit inside the hold | Citi's method: *"re-struck periodically"* |
| `fitted_frozen` | the same fit, frozen at entry | block 4's convention, and the direct test of whether the mid-2023 sign reversal destroys the book |
| `citi_2017` | Citi's published **0.705 / −1 / 0.465** held, level and scale refit each roll | measured as the LOWEST OOS residual sd of any scheme tried |
| `unhedged` | no fly leg | the note's own April-2018 variant (*"outright/unhedged this time"*), and block 4 measured `none` as the best median gross Sharpe of six sizing rules |

`unhedged` still uses the fitted fair value for the **signal**, so all four
schemes share one tradeable window and one entry rule.

### 3.7 Exit

An explicit dollar target and stop on cumulative gross episode P&L:
**+$600,000** and **−$350,000** on $200k DV01 = **+3.0 / −1.75 bp** of the
spread. `max_hold_bd = 126` (~2 quarters) is a backstop, not a signal — Citi's
two published trades ran 82 and 45 business days and the note's own carry
horizon is three months. The trigger is evaluated on the mark at `t` and the
position is closed at `t+1`, so the realised P&L differs from the trigger value
by one mark; that slippage is the honest cost of a one-day fill lag and it is
reported, not netted out.

### 3.8 Roll handling

**Held through.** The instruments are dated: fixed SR3 contracts, a fixed
matched swap, a fly struck at entry. There is no label to switch and therefore
no blackout. Block 4's A5 measured the alternative — the residual reverts in
68–99 bd against a 56 bd roll-flat segment, and 67% of its episodes exited at
`segment_end` rather than on the signal — so a roll-flat design cannot express
Citi's four-month hold at all.

---

## 4. Costs

Per leg, round trip, on that leg's own DV01, charged at the unwind. Block 4's
convention unchanged, so the two blocks' net numbers are comparable:

* futures package **0.25 bp** on `CA_DV01` (one pack tick, independent of leg
  count — CME's own bundle execution economics);
* matched swap **0.5 bp** on `CA_DV01`;
* each fly leg **0.5 bp** on its own DV01: `(w₂, 1, w₁₀) · |β| · CA_DV01`, so
  `2×` the belly under the fly constraint and `2.17×` under Citi's published
  weights;
* **each re-strike is one further fly round trip**, charged separately. This is
  the term that grows when the hedge is maintained rather than frozen, and
  hiding it would flatter exactly the scheme the note recommends.

Swept × {0, 0.5, 1, 2}. Break-even quoted on **gross DV01 traded**.

**Stated in advance:** `fitted_refit` pays more than `fitted_frozen` by
construction. If maintaining the hedge wins gross and loses net, that is the
result and it will be reported in exactly those words.

---

## 5. What the panel may and may not be used for

The panel is a **signal tool**. This package certified that a par-rate panel
overstated three hedged Sharpes (2.141 / 0.867 / 0.414 → engine 1.409 / 0.151 /
0.131) and understated an unhedged book's dollars by 2–3.8× while halving its
Sharpe. Therefore:

* the panel produces the **decision dates** and the shape;
* **every reported book is re-priced through `QueryDrivenBacktest`** on dated
  instruments — futures legs, matched swap and fly as separate queries — with
  `assert_ran` afterwards, because `run()` swallows exceptions and a failed
  backtest looks like a flat equity curve;
* **the engine number is the one quoted.** Where the two disagree the gap is
  named rather than averaged.

**A stated approximation.** `QueryDrivenBacktest` takes precomputed
`DateTrigger`s, so an in-engine dollar stop is not expressible. Exits are
decided on panel marks and the engine replays those exact dates. Two things are
therefore invisible to the stop: the fly's own rolldown (Citi prints it at
+$76k/3m on the Jan-2017 ticket) and the swap leg's accrual. The engine prices
what those exits were actually worth; the panel decides when they happened.

**Certification bar.** For a dated hedged hold the panel-engine daily
correlation will not reach 0.99 and the design already says why (the panel
prices par-rate changes; the engine prices struck instruments with carry).
Certification here is `assert_ran` + the closed-position count + the
carry-versus-residual decomposition, with the gap named.

---

## 6. Statistics

* `n_eff` per cell = **`min(n_episodes, span × 252 / mean_hold)`**. The smaller
  clock is the honest count: a book with 6 episodes over 4.7 years has made 6
  bets, not 48.
* `E[max SR | null]` at the declared trial count on **both** clocks
  (`RVUtils/StatisticalFinance/deflated_sharpe.expected_max_sharpe`), with the
  tradeable span of §2.
* Null by **shared sign flips** on episode P&L — a row permutation leaves a
  Sharpe unchanged.
* **Placebo ladder** at +0/10/20/40/60 bd. A timing signal must die under lag;
  if P&L survives a 40–60 bd stale signal it is a slow level effect.
* **Carry versus residual.** A short-CA book earns ≈ +1.2 bp/quarter of theta
  and Citi's published book **is** a carry trade by construction. Every headline
  number is decomposed into the analytic carry `side · Σθ_t · CA_DV01` and the
  residual, and the Sharpe of the residual is reported next to the Sharpe of the
  total.
* **Convexity signature as a point prediction.** Bucketing realised pair P&L by
  Δσ must give a fitted quadratic coefficient equal to `CA_DV01 · w / 2e4` USD
  per (bp/yr)². A U-shape with the wrong coefficient is not a pass.
* Cost sweep × {0, 0.5, 1, 2} with break-even on gross DV01 traded.

### The bar

At **23 declared trials** and a **4.682 y** tradeable span:

| | per-hold (n_eff 6) | annualised |
|---|---:|---:|
| `E[max SR \| null]`, 23 trials | **0.8008** | **0.9065** |
| for reference, 16 trials (primary only) | 0.7350 | 0.8321 |
| for reference, 2 trials | 0.2122 | 0.2402 |
| for reference, block 4 at 298 trials, 5.626 y | 1.1812 | 1.2199 |

A cell must clear **0.9065 annualised** to be alive at this block's own trial
count. The cumulative-search caveat of the header applies on top of that: the
structure being tested was chosen after four prior passes over the same data.

---

## 7. The declared cells

| arm | cells |
|---|---:|
| primary: 2 threshold rungs × {`screen_best`, `blues`} × 4 hedge schemes | 16 |
| secondary: `screen_best_all5` × {`fitted_refit`, `citi_2017`} at Z = 1.0 | 2 |
| diagnostic: the rule at Z = 1.0 with one condition of the conjunction dropped | 5 |
| **total declared** | **23** |

**Headline: exactly one cell** — `P|z2.0|screen_best|fitted_refit`. The note's
own trade at the note's own thresholds: screen-selected structure,
fly-constrained fit re-struck at each roll, five-way conjunction, dollar target
and stop, short only, held through rolls.

The five drop-one diagnostics are declared and **counted** because a drop-one
variant that beat the headline would otherwise be a trial nobody paid for. They
answer "which condition is load-bearing" with a scored cell rather than with
inspection.

Overlays beyond the note's own five conditions are **not** scored. Block 3
measured the CFTC and CME–LCH overlays at ≈ 0 and re-scoring them here would buy
nothing but null bar.

---

## 8. Negative controls that must fail

1. **Same-day fills must inflate the book.** `exec_lag_bd = 0` against `1`; the
   gap is the mark-noise harvest. Known-answer test:
   `test_same_day_fills_harvest_engineered_mark_noise_and_t_plus_one_kills_it`.
2. **The placebo must kill it.** +40/60 bd stale signal.
3. **The always-short control.** The same structure, the same hedge, the signal
   switched off, held for the same mean duration. If the book is explained by a
   static short, the screen contributed nothing.
4. **β = 0 on the top cells.** Does the fly leg contribute at all?
5. **The blackout control.** Running with the splice off must reproduce the
   +0.95 bp/roll BLUES artifact; a splice implementation that does not change
   that number is not switched on.

---

## 9. Sensitivities — reported, not scored

Run on finalists only, with the trial cost of each stated if any is promoted to
a headline:

* `impl_rlzd_min ∈ {1.0, 1.3, 1.5}` and `z_pos_min ∈ {0.0, 1.0, 1.5}`;
* `max_hold_bd ∈ {63, 126, 189}`;
* `fit_window_bd ∈ {252, 504, 756}` (the reproduction measured the OOS residual
  moving little across the three);
* signal on the **spliced** series / P&L on the **raw** series — both of the
  M2 conventions inverted, so the choice is visible;
* the reproduction's own narrower window (2022-01-03 start), where Citi's fair
  value is measurably better behaved.

---

## 10. What this block will report even if nothing trades

1. **Whether Citi's own conjunction ever fires.** §1 M4 says it fires on 2 of
   1,409 dates and shows which pairs of conditions are incompatible. That is a
   result about the framework, independent of any P&L.
2. **Whether the note's positioning mechanism reproduces on SOFR.** Measured:
   `corr(BLUES CA-vs-model, dealer 1Y z) = −0.187`, and the widest dislocations
   sit in the *low* dealer-position bucket. The note's causal chain runs the
   other way.
3. **Whether Citi's fair value is stable enough to hedge with.** §1 M5: four
   sign reversals of `b` in 21 refits on GREENS and BLUES over this window, and
   `w2` at a grid boundary on 9–11 of 21.
4. **The before/after of maintaining the hedge** — `fitted_refit` against
   `fitted_frozen`, gross and net of the re-strike cost.
5. **The carry share of every book**, so a short-convexity carry trade is never
   reported as relative value.

---

## 11. Amendment A1 (2026-08-24, after the grid ran, before the verdict) — the second clock was declared and initially not graded

§6 and §11 require `E[max SR | null]` **on both clocks**. `_p4_run_grid.py`
reported the annualised Sharpe of the daily P&L series and graded it against
`emax_annualised`, which is a correct comparison — but it is one of the two,
and the other one says something different. `_p4_perhold.py` adds it.

For a book that is flat on 99% of its dates the two clocks are not
interchangeable:

* the **annualised daily** Sharpe divides by the sd of a series that is mostly
  zeros, so it measures the equity curve an investor would actually hold, idle
  capital included. Four trades over 1,409 dates score low almost by
  construction;
* the **per-hold** Sharpe is `mean / sd` over the EPISODES and measures the
  quality of the trades that were taken. Its null sd is `1/sqrt(n_eff)`, which
  is what `null_bars(..., n_eff=...)["emax_perhold"]` already returned.

**This adds no cells and no trials** — it grades the 23 already-declared cells
on the clock this document already required. It is recorded as a dated
amendment because the grading was computed *after* the grid ran, and because it
changes what the verdict says: **8 of 23 cells clear their own per-hold bar
GROSS and 0 of 23 clear it NET**, against 0 of 23 on the annualised clock at
either cost level. Both numbers are in the results doc and neither is quoted
without the other.

---

## 12. Honesty requirements

* Quote `E[max SR | null]` at **23** trials on both clocks with the honest
  `n_eff`, and state the cumulative-search caveat.
* **Report the engine number.** If the panel and the engine disagree, the engine
  wins and the gap gets named.
* **A negative result is a result.** This package's most valuable outputs have
  been the strategies that turned out not to work, and why.
* If a measurement contradicts a sentence already written here, **fix the
  sentence** and date the amendment.
