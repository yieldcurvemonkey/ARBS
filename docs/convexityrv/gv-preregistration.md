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
