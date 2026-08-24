# CA-vs-fly: is this gamma-vs-vega? A sizing note

## 1. The mapping is wrong as stated. Both legs are vega-side.

The sources define the split cleanly, and it is not "variance-price vs vol-price":

- **Gamma P&L** accrues *through the path*: `½Γ(S,σᵢ)S²((dS/S)² − σᵢ²dt)` per step (D6/Quantuple, ex-post form), integrating to `∫½ΓS²(σᵣ²−σᵢ²)dt` (D2, D5). It is a bet on *realised* variance and it arrives only by rebalancing/settlement.
- **Vega P&L** is a *remark of the implied quote*: `ν·Δσᵢ`. Realised vol touches it not at all.

Now apply that to `CA_bp = σ_bp²·w/2e4`. This is a deterministic function of an **implied/model σ**. Nothing about it references a realised path. Its P&L over a holding period is exactly (no approximation — CA is exactly quadratic in σ, so the expansion terminates):

```
ΔCA_bp = (σ₀·w/1e4)·Δσ  +  (w/2e4)·(Δσ)²
         └─ vega ────┘     └─ volga ───┘
```

**The CA is an option-premium-like object, not a gamma.** It is the *price* of variance, and the sources are explicit that a premium is the integral of future gamma P&L (D2 §1.7; extraction 1 §4), not gamma itself. `∂CA/∂σ² = w/2e4` is the analogue of dollar-gamma-times-time — a *quantity of variance*, not a P&L accrual.

Which side you actually sit on is set by **monetisation**, and the sources make this a named fork:

- **Remark (Method 1)**: enter, mark the CA to a new σ, unwind in days/weeks. P&L = vega + volga on `Δσ_implied`. Kurt G.: once you have taken the remark, "there is a **zero** hedging PnL" left — nothing further accrues.
- **Carry (Method 2)**: hold the futures-vs-swap pair to the pack's expiry and let daily settlement deliver realised variance against the CA you paid. *That* is the gamma leg.

The horizon that fork implies is decisive here. `rms(T₁) = √w` = **2.64y (greens), 3.64y (blues), 4.63y (golds)**. Nobody carries an RV trade 3–5 years. **At any realistic RV horizon this is Method 1, so both legs are vega, and the trade is a vol-vs-vol basis — not gamma-vs-vega.** (INFERENCE: no source discusses futures/FRA convexity; the Method-1/2 fork and its consequences are theirs, the mapping onto CA is mine.)

That changes the trade's character in a way the trader should own: the expected P&L is a *spread between two implied vol exposures*, and per D4/D3 the expected P&L of the gamma-carry version is a different object entirely, with different timing even where terminal totals agree.

**Second-order carry point the thesis omits, and it is large.** The CA leg has a deterministic theta: `dCA/dt = −σ²·mean(T₁)/1e4` bp per year of calendar. That is **0.28 / 0.42 / 0.50 bp per month** (greens/blues/golds) of pull-to-zero, before any vol move. Hold for a month and that dwarfs the entire convexity term (§4). Any sizing rule that ignores it is sizing the wrong dominant term.

## 2. Sizing identity

There is exactly **one** sizing rule in the material — `ν = σS²τΓ`, stated four ways (extraction 1 §5) — and its content is: convert a variance-space sensitivity to a vol-space one by multiplying by **2σ**. Applied here:

```python
# UNITS AT EVERY STEP
# sigma_bp : normal vol, bp/yr          (112.6 / 117.8 / 114.1)
# w        : mean(T1^2), years^2        (6.97 / 13.22 / 21.47)
CA_bp   = sigma_bp**2 * w / 2e4         # bp of rate
V_CA    = sigma_bp * w / 1e4            # bp of CA per (bp/yr) of vol   [VEGA]
                                        # = 0.0785 / 0.1557 / 0.2450  (verified)
volga   = w / 1e4                       # bp of CA per (bp/yr)^2

# beta_fly MUST BE MEASURED, NOT DERIVED — see §3
beta_fly = d(Fly_bp)/d(sigma_bp)        # bp of fly per (bp/yr) of vol

# Dollarise both legs, then vega-match:
#   D_CA  : $/bp of the CA spread (pack DV01; 4 x SR3 = $100/bp)
#   D_fly : $/bp of the swap fly (net DV01 of the 2/5/10 IMM legs)
N_fly = N_CA * D_CA * V_CA / (D_fly * beta_fly)     # dimensionless ratio of leg sizes
```

Three constraints, each source-anchored:

1. **Evaluate the identity once; never integrate a gamma profile over the life.** Extraction 1 §2.3/§6.2 documents a source that does exactly that and lands **2× too large**. `V_CA` above is a point evaluation. Correct.
2. **`V_CA` carries σ, so this is a tangent, not a standing hedge.** A ratio set at σ₀ is wrong by `σ/σ₀` at a new vol level. Restate it, don't set-and-forget. (Gordon's `γ = ν/(S²σT)`.)
3. **The 2σ vs (σᵣ+σᵢ) wedge.** The vol-space form substitutes `2σ` for `(σᵣ+σᵢ)`, valid only near σᵣ≈σᵢ. The 100c/10c/30c example is the size of the error: doubling the vol *differential* pays 3×, not 2×. **A ratio fitted at one Δσ is wrong at another.**

## 3. What must be measured before the ratio can be trusted

**Neither extraction supports the claim that a linear-rates butterfly has vega at all.** Both say so explicitly in their own not-supported sections. The entire fly leg is INFERENCE until measured. Two regressions, in this order:

**(a) CA-leg validity.** Regress the *measured* CA (futures pack minus matched IMM swap, bp) on `σ_bp²·w/2e4`. Slope must be ≈1 with small residual. If not, the leg you are trading is not the variance price the formula describes, and everything downstream is fitted to a fiction. (D7's measured lesson: the author asserted the recalibration term was negligible; replication found it "basically eats up the P&L".)

**(b) The fly's vega — the gate.**

```
Δfly_bp,t = a + β_v·Δσ_bp,t + β_L·Δlevel_t + β_S·Δslope_t + ε_t
```
σ must be **the same normal vol at the pack's own T₁**, not a generic ATM. Gate on:
- **partial R² of Δσ after the level/slope controls ≥ ~5%**, not raw R². If the fly loads on level and not vol, this is a duration bet wearing a vol costume.
- **β_v sign-stable and within ~2× across sub-samples** (2021-22 hiking vs 2023-26). Newey-West SEs — vol changes are persistent and daily overlaps will manufacture t-stats.
- **Run it in LEVELS too.** The thesis ("flies are vol proxies") is a claim about the fly's *level*. If only the change regression works, you have a co-movement, not a valuation relationship, and there is no reversion to trade.
- **Tenor match.** corr(Δσ at pack expiry, Δσ at whatever surface point the fly proxies). The sources are unanimous that maturity is the axis on which two "long vol" legs go opposite ways (AlRacoon's calendar is long gamma *and* short vega simultaneously). A low correlation here means you have built a vol calendar basis, not a hedge.

If (b) fails, stop — there is no pair.

## 4. The P&L signature that confirms convexity

Because CA is *exactly* quadratic in σ, this is a **point prediction**, not a shape assertion:

- Bucket realised pair P&L by **Δσ** (signed). The fitted quadratic coefficient must equal `N_CA·D_CA·w/2e4` $ per (bp/yr)². A U with the wrong coefficient is not a pass.
- Bucket by **Δrate**, orthogonalised to Δσ. Must be **flat**. A ramp here is the direction bet. Do not skip the orthogonalisation: SOFR vol and level are correlated, so a raw Δrate bucket will show a spurious smile inherited from the vol channel.
- Bucket by **Δfly**. Must be flat if the hedge holds.

**Amplitude — read this before running the test.** The convex fraction is `Δσ/(2σ)`, independent of w. At σ≈114, a **±20 bp/yr vol shock** (a large 17% relative move) produces only:

| Pack | linear (vega) | convex (volga) | convex/linear |
|---|---|---|---|
| Greens | 1.57 bp | **0.14 bp** | 8.8% |
| Blues | 3.11 bp | **0.26 bp** | 8.8% |
| Golds | 4.90 bp | **0.43 bp** | 8.8% |

**So ~91% of this trade is linear vol basis and ~9% is convexity, and the convexity term is 0.14–0.43 bp against a round-trip cost that is a multiple of that, and against 0.28–0.50 bp/month of CA theta.** Confirming the smile is not the same as having a convexity trade. Judge and size this as a vol-vs-vol basis trade with a rounding error of convexity, or don't put it on.

Two implementation traps to check in the harness:
- **If the daily P&L series looks smooth, you computed the ex-ante average form, not the realisation** (D6: "my daily PnLs range wildly, yet the values given by above formula remain somewhat small"; the aggregates agree, the days never do).
- **Gamma/vega neutrality does not persist.** D7: a spread built neutral in one order "can quickly turn into a leveraged directional bet" via the next derivative under stress. Re-measure β_v in the stressed sub-sample specifically, not just the full sample.

**Not supported by the sources, stated so the note does not over-claim:** no source gives a rates CA formula, a swap-fly hedge ratio, any DV01-based sizing, or cross-gamma between two *different* underlyings (D7's "cross gamma" is dS·dATM on one underlying — not a pack against a fly of another tenor). The gamma↔vega identity is Black-Scholes-specific ("Bergomi's derivation relies on the volatility being independent of S"); any level-dependence of the SOFR vol surface breaks it and is out of scope of every source read.