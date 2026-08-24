# GV — CA vs IMM-dated swap butterfly, gamma-vs-vega sized

**Pre-registered 2026-08-24, BEFORE any scoring.** Block 4 of the convexity RV
programme. Anything scored later that is not declared here expands the trial
count and must be added with a dated note — the null bar moves with it.

This is the **third** pass over the same CA panel (block 1 `strat2`, block 3
`cavf`/PR #492, now `gv`). The cumulative-search caveat is on the record and
travels with every number this block produces.

---

## 0. Why there is a block 4 at all

Block 3 declared the CA-vs-fly grid dead on 515 cells. The brief for this block
is a specific objection: **the previous results look bad because of sizing.**
That objection is testable, and three of its four possible mechanisms were
measured before this file was frozen. Sizing cannot change a Sharpe by scaling
a whole book — only the *relative* size of the two legs can — so the question
reduces to "was the hedge ratio wrong", and the answer is that it was wrong in
at least two identifiable ways.

### Measurements taken before the freeze (all on this machine, 2026-08-24)

**M1 — the level β and the daily-change β have opposite signs.**
On 2026-01-02..2026-08-21 (n=161), BLUES CA against five candidate hedge legs:

| regressor | level β | level R² | DW | daily corr | daily β |
|---|---:|---:|---:|---:|---:|
| `IMM_1x2y/IMM_1x5y/IMM_1x10y` fly | **+0.1461** | 0.394 | 1.146 | −0.171 | **−0.0970** |
| `IMM_2x…` fly | +0.1277 | 0.190 | 0.849 | −0.270 | −0.1776 |
| `IMM_U26x…` fly (dated) | +0.0587 | 0.060 | 0.675 | −0.264 | −0.1740 |
| `10y10y/20y10y` curve | −0.0570 | 0.064 | 0.610 | −0.248 | −0.0988 |
| `10y10y/15y10y` curve | +0.0040 | 0.000 | 0.602 | −0.100 | −0.0906 |
| 3Yx1Y ATMF nvol | −0.0003 | 0.000 | 0.602 | +0.088 | +0.0360 |

The first row reproduces the brief's printed OLS to four decimals (const
+7.6893, β +0.1461, R² 0.394, n 161) — the panel is the same object the brief
was computed on.

Block 3's family B sized the fly leg at `β_level·CA_DV01` with `β_level > 0`
while the legs actually co-move *negatively* day to day. `var(ΔCA − βΔfly) =
var(ΔCA) − 2β·cov + β²var(Δfly)`; with `cov < 0` and `β > 0` the middle term is
**positive**, so family B's "hedge" **added** variance to the traded object
rather than removing it. That is a sizing defect with a sign, not a magnitude.

**M2 — the CA mark is noise-dominated, and by a measurable amount.**
First-order autocorrelation of the *daily change* in CA, 2021-01-04..2026-08-21,
1,409 dates:

| pack | mean CA | sd CA | sd ΔCA | AC1(ΔCA) | implied σ_true | implied σ_noise | noise/true |
|---|---:|---:|---:|---:|---:|---:|---:|
| WHITES | 0.476 | 1.343 | 1.603 | **−0.540** | ~0 | ~1.13 | ∞ |
| REDS | 1.080 | 2.307 | 1.710 | **−0.517** | ~0 | ~1.21 | ~50 |
| GREENS | 4.423 | 1.990 | 0.364 | −0.228 | 0.269 | 0.174 | 0.65 |
| BLUES | 9.183 | 3.639 | 1.033 | −0.392 | 0.484 | 0.645 | 1.33 |
| GOLDS | 13.983 | 5.489 | 1.308 | −0.395 | 0.612 | 0.818 | 1.34 |

Under `observed = true + iid noise` with `true` a random walk,
`AC1(Δobs) = −ν/(τ+2ν)`, which is bounded below by −0.5 and attains it only
when `τ = 0`. **WHITES and REDS sit at or past that bound: their daily marks
carry no measurable signal at all** on the full sample. σ_true / σ_noise above
are the moment inversion of the same model. This originally justified excluding
them; **amendment A2 demotes rather than excludes them**, because the −0.5
reading is a full-sample statistic and the burn-in reading is not (−0.411 /
−0.165) — see §1.

Consequence for sizing: a rolling 252-day daily-change β has residual variance
inflated by `2ν` regardless of window length, so `SE(β̂)` is large and a
252-day rolling estimate is close to random. Block 3's family A hedge ratio was
noise. That is the second sizing defect.

**M3 — the CA label and the `IMM_k` swap leg roll ONE DAY APART, and the roll
jump is large and signed.**
`IRSwapsTB._cvx_front_imm_code` rolls the SR3 rank map **on** the IMM date;
`Query.Base.imm_resolution.resolve_imm_token("IMM_1", d)` advances from
`d + 1 day`, so an `IMM_k` swap leg rolls on the **business day before**. Over
2021-2026 both produce exactly 22 roll dates and **none of them coincide** —
e.g. CA H21→M21 on 2021-03-17, `IMM_1` 2021-03-16.

On those dates the CA jumps:

| pack | mean\|ΔCA\| off-roll | mean\|ΔCA\| on roll | ratio | signed mean on roll | t |
|---|---:|---:|---:|---:|---:|
| WHITES | 0.886 | 2.246 | 2.53 | — | — |
| REDS | 0.945 | 3.688 | 3.90 | — | — |
| GREENS | 0.208 | 1.170 | 5.63 | **+0.741** | **+2.44** |
| BLUES | 0.752 | 1.356 | 1.80 | **+0.946** | **+2.70** |
| GOLDS | 0.915 | 1.727 | 1.89 | **+1.223** | **+2.46** |

A book that simply holds long-CA across every roll books **+0.95 bp per
quarter on BLUES for free** — 22 rolls, ≈ +21 bp, on a structure whose whole
level is 9 bp. This is block 3's "CM labels book the IMM-roll jump" measured
and signed. It is also why the brief's requirement — *be flat across the roll*
— is not a nicety.

**M4 — what the vega-matched size actually is.**
Under Citi's convention `CA_bp = σ_bp²·w / 2e4` with `w = mean_i(T1_i²)`, so
`∂CA_bp/∂σ_bp = σ_bp·w/1e4` — the CA's **vega**, in bp of CA per bp/yr of
normal vol. Inverting the measured mean CA:

| pack | w = mean(T1²) | implied σ (bp/yr) | ∂CA/∂σ (bp per bp/yr) |
|---|---:|---:|---:|
| GREENS | 6.97 | 112.6 | 0.0785 |
| BLUES | 13.22 | 117.8 | 0.1557 |
| GOLDS | 21.47 | 114.1 | 0.2450 |

The three implied vols agree to ±3% across colours, which is the sanity check
that the inversion is being done in the right units.

A vega-matched hedge sets `belly_DV01 = CA_DV01 · (∂CA/∂σ) / (∂leg/∂σ)`. The
incumbent set it to `β·CA_DV01 ≈ 0.146·CA_DV01`. The ratio of the two is
`0.1557 / (0.146 · ∂leg/∂σ)`, so unless the fly moves **1.07 bp per bp/yr of
vol** the incumbent hedge was the wrong size — and a fly does not move 1 bp per
bp of vol. **The before/after hedge notional ratio is a headline deliverable of
this block**, reported whether or not the trade works.

---

## 1. Window, panels, conventions

* Window **2021-01-04 .. 2026-08-21** (1,409 CA panel dates).
* Curve MDP: `IRSwapsMDP(source="citivelo_excel_rl")` (house convention).
* CA panel: `cavf_ca_panel.parquet`, the block-3 TB build (`sfr_cvx_adj`, Q/Q
  matched swap, 31 labels, zero failures). **Carried forward, not re-derived**,
  and graded by a fresh re-price of a random date sample through
  `IRSwapsTB.sfr_cvx_adj` — a copied artifact is a hypothesis until tied out.
* Leg panel: `p2_legs.parquet` — `IMM_k × {1,2,3,5,7,10,20,30}y` par rates for
  k ∈ {1,2,4,5,8,9,12,13,16,17,20}, spot par legs, eight long-end forwards, the
  two fly columns and two curve columns the brief printed (verbatim, as
  tie-outs), and ten ATMF straddle normal vols.
* Enrichment reused **unchanged** from block 3: CFTC TFF (release-lagged 3 bd),
  CME–LCH CCP basis (lagged 1 bd), whole-strip OI.
* All signals use **t−1 information; fills execute at the t+1 mark** (block 3's
  mark-noise amendment, retained; the same-day variant is a reported diagnostic
  only).

### Denoising, and where it may and may not be used

The signal is computed on a **denoised** CA: an exponentially weighted mean
whose half-life is *derived*, not chosen. **P&L is always marked on the raw
panel at the raw t+1 mark.** Smoothing the signal is legitimate; smoothing the
execution price is not, and the two are never allowed to touch the same series.

> **Amendment A1 (2026-08-24, before any scoring) — the half-life is computed,
> not guessed.** This section originally froze `GREENS 1.5 d / BLUES 3 d /
> GOLDS 3 d` by eye. Those numbers are replaced by the steady-state Kalman gain
> of the same local-level model M2 already fits: for a random walk observed with
> iid noise, the optimal filter **is** an EWMA with weight
> `K = (−q + sqrt(q² + 4q))/2`, `q = τ/ν`. The fit is taken on the **first 252
> panel dates only** (2021) and frozen — a trailing fit would make the filter
> time-varying and a full-sample fit would be look-ahead. Measured:
>
> | pack | AC1 burn-in | AC1 full | σ_true | σ_noise | q | α | half-life (bd) |
> |---|---:|---:|---:|---:|---:|---:|---:|
> | WHITES | −0.411 | −0.540 | 0.181 | 0.275 | 0.43 | 0.477 | 1.07 |
> | REDS | −0.165 | −0.517 | 0.653 | 0.324 | 4.05 | 0.830 | 0.39 |
> | GREENS | −0.107 | −0.228 | 0.462 | 0.171 | 7.31 | 0.891 | 0.31 |
> | BLUES | −0.303 | −0.392 | 0.739 | 0.648 | 1.30 | 0.663 | 0.64 |
> | GOLDS | −0.379 | −0.395 | 0.901 | 1.126 | 0.64 | 0.542 | 0.89 |
>
> This adds no cells and no trials; it replaces three hand-picked constants with
> the model's own answer.

> **Amendment A2 (2026-08-24, before any scoring) — WHITES and REDS are demoted,
> not excluded, and the reason the original exclusion was weak is on the
> record.** §2 excluded them on a **full-sample** AC1 at or past the −0.5
> pure-noise bound. The burn-in AC1 (table above) is −0.411 and −0.165, i.e. the
> full-sample statistic that justified the exclusion is not available at the
> start of the backtest. Using a full-sample *data-quality* statistic to pick a
> universe is not the same sin as using a full-sample *performance* statistic,
> but it is still selection, so both structures move to the **secondary** tier
> and are scored and reported there. Trials rise 290 → 298. Their marks are the
> least trustworthy on the board and the results doc will say so next to every
> number they produce.

---

## 2. Structure universe (CA / gamma side)

**Primary, scored:** `GREENS`, `BLUES`, `GOLDS` (front ranks 9, 13, 17).

**Secondary, scored and reported with its own null:** `BUNDLE4Y`, `BUNDLE5Y`,
`SFR12`, `SFR16`, `SFR20`.

**Secondary, with the noise caveat attached (amendment A2):** `WHITES`, `REDS`
— full-sample AC1(ΔCA) −0.540 / −0.517, at or past the pure-noise bound, but
burn-in AC1 −0.411 / −0.165, so the exclusion criterion is not available at the
start of the sample. Scored in the secondary tier; every number they produce
carries the caveat.

**Excluded:** `SFR1..SFR11`, `BUNDLE2Y`, `BUNDLE3Y` — front-weighted structures
inside the same noise regime and adding nothing the packs do not already say.
They remain in the screener as display quantities.

---

## 3. Vega / linear-proxy leg universe

Seven legs. All are built from the leg panel by arithmetic, so no weighting is
baked into the data. Fly weights are **DV01-neutral 50/50 wings**,
`fly = belly − ½(front + back)` in bp, unless a fitted weighting is named.

| id | definition | why declared |
|---|---|---|
| `immF_2s5s10s` | `IMM_1x2y / IMM_1x5y / IMM_1x10y` | the brief's own regressor, verbatim |
| `imm2_2s5s10s` | `IMM_2x2y / IMM_2x5y / IMM_2x10y` | the brief's second regressor |
| `immM_2s5s10s` | `IMM_kx2y / IMM_kx5y / IMM_kx10y`, k = the structure's front rank | the vol-locality hypothesis in IMM space |
| `immM_1s2s3s` | `IMM_kx1y / IMM_kx2y / IMM_kx3y`, same k | the only shape with a measured R² plateau in block 2 |
| `le_10y10y_20y10y` | `10Yx10Y` vs `20Yx10Y` curve | the brief's ultra-long regressor (its printed R² 0.505) |
| `le_10y10y_15y10y` | `10Yx10Y` vs `15Yx10Y` curve | the brief's tighter sibling |
| `spot_2s5s10s` | `2Y / 5Y / 10Y` spot fly | Citi's published shape — the incumbent control |

## 4. Sizing rules — the object of the block

`belly_DV01 = |β| · CA_DV01`, direction from `sign(β)`, with β from:

| id | β | note |
|---|---|---|
| `beta_chg` | rolling 252 bd OLS of ΔCA on Δleg (daily changes) | block 3 family A — the incumbent |
| `beta_lvl` | rolling 252 bd OLS of CA on leg (levels, with intercept) | block 3 family B — the brief's own regression |
| `vega_match` | `(∂CA/∂σ) / (∂leg/∂σ)` | the fix; ∂leg/∂σ from a rolling 252 bd levels regression of the leg on the matched ATMF normal vol, **gated: \|t\| ≥ 2.0 and R² ≥ 0.20**; a day failing the gate cannot open a position and the refusal count is reported |
| `vol_ratio` | `sign(ρ_chg) · sd(ΔCA_denoised) / sd(Δleg)`, 252 bd | risk parity — needs no vol regression, so it survives if `vega_match` is gated out |

Plus two controls: `none` (β = 0, CA leg alone) and `unit` (β = 1.0 bp/bp, a
declared scale reference so the sweep spans the plausible range at both ends).

**Book scale**, orthogonal to the hedge ratio:

| id | rule |
|---|---|
| `const_dv01` | CA_DV01 = $100,000 throughout (block 3's convention) |
| `inv_vol` | CA_DV01 scaled so the trailing 63 bd realised P&L sd of the *pair* equals its full-sample median; capped at 3× |

`∂CA/∂σ` uses `holee.pack_time_weight` (`mean_i(T1_i²)`, per date), never
`T1_mean²`, and the vol inversion is carried in **variance** space —
`v = 2·CA/w`, a signed variance price — because a negative CA has no real
implied vol and the ZIRP window contains many. Days with `v < 0` are kept in
variance space and flagged; `σ = sqrt(v)` is computed only where `v > 0` and
the exclusion count is reported.

## 5. Signals

| id | definition | entry / exit |
|---|---|---|
| `z_resid` | z of `CA_denoised − β·leg` against its own rolling 252 bd mean/sd | \|z\| ≥ 2.0 in, \|z\| ≤ 0.5 out |
| `z_ca` | z of `CA_denoised` level (control) | same |
| `z_varbasis` | z of `v_CA − v_bench`, both in bp²/yr variance units, where `v_bench` is the matched ATMF straddle normal vol squared | same |

Two-sided (long and short the spread). Every position is force-closed by the
roll blackout regardless of z.

## 6. Roll handling — the brief's explicit requirement

**Blackout: flat from IMM − 3 business days through IMM + 1 business day**,
where IMM is the quarterly SR3 roll date. The window is the union of the two
measured roll clocks (CA on IMM, `IMM_k` legs on IMM − 1 bd) plus a symmetric
buffer. No position may be open inside it; an open episode is force-closed at
its last pre-blackout mark and cannot re-open until after.

Because rolls are quarterly, this caps holds at roughly one quarter and makes
every episode a within-quarter trade. `max_hold_bd = 63` is therefore not
binding for most cells and is kept only as a backstop.

Sensitivity `pre ∈ {1, 3, 5}` is run **on the finalists only** and reported as
a sensitivity, not scored as trials.

**Known-answer control that must fail:** running the same book with the
blackout disabled must reproduce the M3 artifact — a long-CA book must pick up
≈ +0.95 bp per roll on BLUES. A blackout implementation that does not change
that number is not switched on.

## 7. Scored cells and the trial count

**Headline (declared first, tightest null): 12 cells.**
`{GREENS, BLUES, GOLDS} × {immF_2s5s10s, immM_2s5s10s} × {beta_lvl, vega_match}
× z_resid × const_dv01`. This is the brief's own trade, at the incumbent sizing
and at the fix, and nothing else.

**Full grid: 3 × 7 × 6 × 2 = 252 cells** (primary structures × legs × sizing
rules × book scales), all on `z_resid`, plus:

| arm | cells |
|---|---:|
| primary grid | 252 |
| `z_ca` control | 3 × 2 (book scales) = 6 |
| `z_varbasis` | 3 × {vega_match, vol_ratio} × 2 = 12 |
| secondary structures (7: BUNDLE4Y/5Y, SFR12/16/20, WHITES, REDS) × {immF, immM} × {beta_lvl, vega_match} × const_dv01 | 28 |
| **total declared** | **298** |

Overlays (CFTC positioning, CME–LCH basis) are **conditioning masks on
finalists only**, reported as diagnostics with their own stated trial cost, not
as standalone scored cells — block 3 measured them at ≈ 0 and re-scoring them
here would buy nothing but null bar.

## 8. Costs

Per leg, round trip, on that leg's own DV01, charged at the unwind:

* futures package **0.25 bp** on CA_DV01 (one bundle/pack tick, independent of
  leg count — CME's own bundle execution economics);
* matched swap **0.5 bp** on CA_DV01;
* each fly/curve leg **0.5 bp** on its own DV01 (belly `|β|·CA_DV01`, wings half
  the belly each under 50/50 weights).

Swept × {0, 0.5, 1, 2}. Break-even quoted on **gross DV01 traded**, because the
per-cohort denominator is wrong once leg counts differ.

**Stated in advance:** `vega_match` is expected to size the hedge leg several
times larger than `beta_lvl`, so it pays several times the hedge-leg cost. If
the fix wins gross and loses net, that is the result, and it will be reported in
exactly those words.

## 9. Statistics, controls, certification

* `n_eff` per cell on both clocks: span × 252 / mean hold, **and** the count of
  non-overlapping quarters actually traded (≤ 22 per structure after blackout).
* `E[max SR | null]` at **12 trials** for the headline and **298** for the full
  grid, quoted per-hold and annualised, with the deflated Sharpe of any winner.
* Null by **shared sign flips** on episode P&L (row permutation cannot test a
  Sharpe), preserving cross-cell correlation.
* Placebo: signal lagged +20 bd must kill the edge.
* **Convexity signature:** P&L bucketed by the size of the underlying move must
  show a smile, not a ramp, for any cell claimed to be a convexity trade.
* Negative controls that must fail: blackout-off must show the roll artifact
  (§6); annual-frequency matched swap must not tie to Citi's screen; same-day
  fills must inflate the hit rate.
* Finalists (top ≤ 3 by DSR, plus the two headline `vega_match` cells) run
  end-to-end through `QueryDrivenBacktest` — futures legs + matched swap + each
  fly leg as separate queries, `assert` on `mtm_history`, daily-change
  correlation against the panel reported honestly.

## 10. What this block will report even if nothing trades

1. The before/after hedge-notional table (§0 M4) — the direct answer to "was it
   sizing".
2. The measured noise decomposition of every CA structure (§0 M2), which sets
   which structures are tradable at all at daily frequency.
3. The two roll clocks and the size of the artifact they create (§0 M3).
4. Whether a swap butterfly is a volatility proxy at all — the rolling
   regression of each leg on matched ATMF normal vol, with its R², its t, and
   the fraction of days the `vega_match` gate refuses. If that regression is
   empty, the brief's premise ("butterflies are vol proxies in linear space") is
   answered by measurement rather than by a backtest.

---

## 11. Amendment A3 (2026-08-24, before any scoring) — what the options literature says the CA actually is

The brief frames this as *"convexity adjustment is pure gamma, swap butterflies
are vol proxies in linear space, we are trading gamma vs vega."* An extraction
of the options-theory reading set (`docs/convexityrv/research/corpus3/`,
13 Quantitative Finance Stack Exchange threads on the gamma/vega link,
delta-hedging at fixed vs floating implied vol, and break-even vol) says the
first half of that needs a correction, and the correction has three consequences
that change what this block measures.

### A3.1 The CA is a VEGA-side object, not a gamma

The literature's split is between a *price* and an *accrual*:

* **Gamma P&L** accrues through the path — `½Γ·S²·((ΔS/S)² − σ_i²Δt)` per step,
  integrating to `∫½ΓS²(σ_r² − σ_i²)dt`. It is a bet on **realised** variance and
  it arrives only by rebalancing or settlement.
* **Vega P&L** is a re-mark of an implied quote: `ν·Δσ_i`. Realised vol does not
  touch it.

`CA_bp = σ_bp²·w/2e4` is a deterministic function of an **implied/model** σ. It
references no path. Its holding-period P&L is exact, because the CA is exactly
quadratic in σ and the expansion terminates:

```
ΔCA_bp = (σ₀·w/1e4)·Δσ   +   (w/2e4)·(Δσ)²
         └── vega ────┘       └── volga ──┘
```

So the CA is an option-**premium**-like object. The premium is the integral of
future gamma P&L, not gamma itself. Which side you actually sit on is set by
monetisation, and the horizon decides it: `rms(T1) = sqrt(w)` is **2.5 / 3.5 /
4.5 years** for GREENS / BLUES / GOLDS, and no RV book carries a position to a
pack's expiry. **At the horizon this block trades, both legs are vega, and the
trade is a vol-vs-vol basis rather than gamma-vs-vega.**

That is not a reason not to run it — a vol-vs-vol basis across the curve is a
real RV object, and the desk chat in the corpus describes the long-end leg in
exactly those terms ("10y10y/20y10y curve flattener … leaves you long vega short
gamma without having to trade a swaption"; "15y5y vs 20y10y is the pure vega
expression"). It is a reason to **stop calling the result a convexity trade
without qualification**, and to size the convexity claim honestly:

| pack | linear (vega) on a ±20 bp/yr vol shock | convex (volga) | convex share |
|---|---:|---:|---:|
| GREENS | 1.57 bp | 0.14 bp | 8.8% |
| BLUES | 3.11 bp | 0.26 bp | 8.8% |
| GOLDS | 4.90 bp | 0.43 bp | 8.8% |

The convex fraction is `Δσ/(2σ)` and is independent of `w`, so it is 8.8% for
every structure. **~91% of this trade is linear vol basis.**

### A3.2 The CA has a large deterministic theta, and the roll jump IS that theta

`w = mean_i(T1_i²)` and every `T1_i` shortens with calendar time, so
`dw/dt = −2·mean_i(T1_i)` and

```
dCA_bp/dt = −σ_bp² · mean(T1) / 1e4      bp per year
```

Measured on this panel: **−0.277 / −0.419 / −0.502 bp per MONTH** for
GREENS / BLUES / GOLDS. That is larger than anything the RV signal is trying to
catch, and it is deterministic.

A constant-rank CA series hides it, because at each quarterly roll the rank map
advances, `w` jumps back up and the level recovers. **The roll jump is the theta
being paid back**, and the two numbers agree: the formula predicts a 1.21 bp
step for BLUES when every contract rolls out one quarter, and §0 M3 measured
**+0.946 bp**. They are the same quantity.

Two consequences, both structural:

1. **A roll blackout leaves the decay one-sided.** A two-sided book that never
   holds through a roll acquires a systematic **short-CA carry**, ≈ +1.2 bp per
   quarter held short and −1.2 bp per quarter held long. That is Citi's own
   published trade ("sell Blues CA"), and it is **carry, not alpha**.
2. **Every headline number is therefore decomposed** into the analytic carry
   `side·Σθ_t·CA_DV01` and the residual, and the Sharpe of the residual is
   reported next to the Sharpe of the total. `gv_sizing.episode_decomposition`
   does this; `carry_usd`, `residual_usd` and `carry_share` are columns of the
   grid stats frame. A Sharpe quoted on the total alone would report a
   short-convexity carry trade as relative value.

### A3.3 `vega_match` is estimated with level and slope controls

The CA's vega `σ·w/1e4` is a pure volatility derivative by construction.
Matching it against an **uncontrolled** `∂leg/∂σ` would match a vega against a
coefficient that is partly duration — a fly that loads on level and not on vol
is a duration bet wearing a vol costume, and dividing by its slope points the
hedge at the wrong risk. `vega_match` therefore fits

```
Δleg_bp = a + b_v·Δσ_bp + b_L·Δlevel + b_S·Δslope + ε
```

rolling 252 bd, and gates on `|t(b_v)| ≥ 2.0` **and the partial R² of the vol
term ≥ 0.05** — the partial, not the regression's raw R², because the raw R² of
a level-driven fly is high for the wrong reason. Level = spot 10Y, slope =
10Y − 2Y, both from the leg panel. `rolling_vol_beta` (uncontrolled) is retained
and reported side by side in the vol-proxy matrix so the gap is visible.

**This changes no declared cell and adds no trials** — it replaces one
estimator with a correctly specified one. The rule now *refuses to run* without
the controls rather than silently falling back.

### A3.4 The convexity signature becomes a point prediction, not a shape

Because the CA is exactly quadratic in σ, "a convex payoff must show a smile"
can be sharpened: bucketing realised pair P&L by **Δσ** must give a fitted
quadratic coefficient equal to `CA_DV01·w/2e4` USD per (bp/yr)². A U-shape with
the wrong coefficient is not a pass. Bucketing by **Δrate, orthogonalised to
Δσ**, must be flat — SOFR vol and level are correlated, so a raw Δrate bucket
inherits a spurious smile through the vol channel.

### A3.5 What the corpus audit found

`docs/convexityrv/research/corpus3/` also carries a coverage audit of the whole
Downloads corpus against the block-3 extraction: **97 of 97 markdown files
covered, 88 distinct documents after de-duplication, 100%**, with the match rate
reported at each stage. There are no unextracted research documents. The only
depth gap was `pm_bbgchat.txt`, triaged in block 3 as "not STIR CA"; it has been
read in full for this block and is the source of the long-end vega framing
quoted in A3.1.

---

## 12. Amendment A4 (2026-08-24, after the grid ran, before the verdict) — declared diagnostics

Three diagnostics were added after the grid and before the verdict. None of them
is a scored cell; each is a control on cells already scored, and each is named
here so the record is complete.

* **β = 0 control on the top cells** — the same rule with the hedge leg removed.
  It asks whether the fly contributes to the cells that survived. Answer: the
  fly adds Sharpe on 2 of the top 8 and removes it on 3.
* **Always-short / always-long buy-and-hold** inside every tradeable segment,
  same structure, same leg, same β, signal switched off. It asks how much of a
  cell is a static position. Answer: 2 of the top 8 are entirely explained by
  the static short and 2 more are majority-static.
* **Placebo ladder** at +0/5/10/20/40/60 bd rather than the declared single
  +20 bd. A timing signal must decay as the lag grows; this separates the two
  families cleanly and is the single most discriminating control in the block.

## 13. Amendment A5 (2026-08-24, declared before scoring) — the dated, through-roll arm

**6 cells. Trial total 298 → 304.**

The block's own measurement says the residual the brief wants to trade reverts
with a half-life of **68–99 business days** on the long-end curve pairs, against
a tradeable segment of only ~56 bd between roll blackouts; 1,738 of the main
grid's 2,591 episodes exit at `segment_end` rather than on the signal. The trade
cannot converge inside a roll-flat window.

But "flat across the roll" was only ever a proxy for the real requirement: *do
not book a contract-switching jump as P&L*. A **dated** package — fixed SR3
contracts, a fixed matched swap, an IMM-pinned fly, all resolved at entry — has
no label to switch, so it can be held straight through a roll. What it has
instead is the CA's own theta, which the engine prices because it prices real
ageing instruments.

* Cells: `{GREENS, BLUES, GOLDS} × {immM_2s5s10s, le_10y10y_15y10y} × beta_lvl
  × const_dv01`.
* Blackout **off**, `max_hold_bd = 126` (two quarters).
* Signal on the **roll-spliced** CA (`gv_sizing.roll_spliced`, forward-adjusted
  so it stays causal — a backward adjustment rewrites history at every new roll,
  which is fine for a chart and look-ahead for a z-score). The known cost of the
  convention is stated and tested: on a roll date the observed change is the
  contract switch *plus* that day's market move and the panel cannot separate
  them, so the splice discards both — about 0.15 bp of level over 22 rolls
  against the +0.95 bp/roll jump it removes.
* **P&L on the ENGINE only.** A constant-rank panel cannot represent a dated
  hold, and the certification measured that the par-rate panel overstates these
  books (panel Sharpe 2.141 / 0.867 / 0.414 against engine 1.409 / 0.151 /
  0.131) because it prices par-rate changes rather than struck-instrument P&L
  and the omitted term is carry.

## 14. Amendment A6 (2026-08-24) — finalist selection, and why not by DSR

Section 9 says finalists are the "top ≤3 by DSR". That is **unimplementable on
this grid**: every cell has 6–13 episodes and `deflated_sharpe_of_best` returns
`dsr = NaN` at that sample size (it did, and the run recorded
`n_trials_effective = 227.9` over `n = 6` observations with an ill-conditioned
correlation matrix). Rather than substitute a criterion silently, the three
finalists are named and the reason for each is stated:

1. `S|SFR12|immM_2s5s10s|beta_lvl|const_dv01` — the best cell by gross
   annualised Sharpe, and the only one of 298 that clears the annualised
   298-trial null bar.
2. `A|GREENS|le_10y10y_15y10y|beta_chg|const_dv01` — the cell that *behaves*
   like a timing signal: the only finalist whose P&L dies under lag
   (0.851 → −0.247 at 60 bd).
3. `A|GOLDS|imm2_2s5s10s|beta_lvl|inv_vol` — the **sign-flip null's own best
   cell** (per-observation Sharpe 2.009, family-wise p = 0.0225). It was not in
   the Sharpe-ranked top 8, so it would otherwise never have faced the
   always-short control or the placebo ladder, and a sub-5% p-value left
   unexamined in the record is exactly the kind of loose thread this package
   keeps writing down.

Also recorded: the grid summary's `emax_perhold` was first computed with an
`n_eff` that assumed an always-invested book (median 48.5). The honest `n_eff`
is `min(n_episodes, span × 252 / mean_hold)` — 6–13, not 48 — and every null bar
quoted in the results doc uses the corrected figure.
