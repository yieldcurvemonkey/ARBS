# `_MODEL2` — Hull-White convexity for the payoff SR3 actually settles on

**Status:** shipped. `IRSwapsTB.sfr_cvx_adj(["BLUES_MODEL2", ...])`.
**Code:** `RVUtils/ConvexityRV/hw1f_sofr.py`, wired in `TB/IRSwapsTB.py`.
**Evidence:** `notebooks/backtests/convexity_rv/_hl2_verify.py` (7 checks, live
data), `_hl2_mutate.py` (25/25 killed), `_hl2_repair_cache.py` (the store
repair, §3), `tests/test_convexity_rv_hw1f_sofr.py` (the arithmetic),
`tests/test_irswaps_tb_model2.py` (the wiring).

```python
df = tb.sfr_cvx_adj(["BLUES", "BLUES_MODEL", "BLUES_MODEL2"], start, end)
# observed | Ho-Lee (Citi's screen) | Hull-White on the compounded payoff
```

Every label `sfr_cvx_adj` accepts takes the suffix: IMM codes, `SFR<n>` ranks,
all pack colours, all bundles. Knobs: `model2_mean_reversion` (default 0.03),
`model2_payoff` (`compounded` | `average` | `term`), and the volatility knobs
shared with `_MODEL` (`model_vol_provider`, `model_vol_source`,
`model_vol_tenor`).

---

## 1. What changed against `_MODEL`, and which change matters

`_MODEL` is Ho-Lee under Citi's convention: `CA = ½σ²·mean(T1²)`, one constant
volatility, no mean reversion. `_MODEL2` changes three things.

**(a) The settlement convention — first order, ~15%.** An SR3 contract settles
on the *daily-compounded* SOFR over its reference quarter. Under Hull-White the
futures price is a risk-neutral expectation of that compounded rate, and it is
exact (up to approximating daily compounding by continuous):

```
futures = (1/τ)·(E^Q[exp(∫_{T1}^{T2} r ds)] − 1) = (1/τ)·((1/D)·e^{μ+v/2} − 1)
forward = (1/τ)·(1/D − 1)
CA      = (1/τ)·(1/D)·(e^{μ+v/2} − 1)

μ = (σ²/2)·∫_{T1}^{T2} B(0,s)² ds                       the Hull-White α-drift
v = σ²·[B(τ)²(1−e^{−2aT1})/(2a) + ∫_0^τ B(w)² dw]        Var(∫ x ds)
B(a,t) = (1−e^{−at})/a
```

Its `a → 0` limit is **`½σ²·(T2² − τ²/3)`**. That is not Citi's `T1²` and not
Hull's `T1·T2` — those are two *other* payoffs:

| weighting (`a→0`) | payoff | instrument | @ T1=3.5, τ=0.25, σ=100bp |
|---|---|---|---|
| `½σ²(T2² − τ²/3)` | daily-compounded | **SR3 / SOFR 3M** | **7.02 bp** |
| `½σ²(T1T2 + τ²/3)` | arithmetic average | SR1 / ZQ | 6.57 bp |
| `½σ²·T1T2` | forward-looking term | ED / LIBOR (Hull Ch31) | 6.56 bp |
| `½σ²·T1²` | — | what Citi's screen prints | 6.13 bp |

All four use the same volatility. The spread between them is convention alone,
and it is wider than most of the richness this gets traded against.

**(b) A volatility mapping — second order in `a`, but load-bearing in the
tail.** `σ` in those formulas is the *short-rate* volatility; a quoted normal
vol is a *swap-rate* volatility. Under mean reversion they differ:

```
σ_HW = vol · sqrt(T / V(T)) · tail / B(a, tail),     V(T) = (1−e^{−2aT})/(2a)
```

which is the identity at `a = 0` for any tail — so `_MODEL` feeding a quote
straight into Ho-Lee is this mapping's own zero-mean-reversion case, not a
different convention. `_MODEL2` calibrates **one volatility per contract at that
contract's own expiry** (the standard flat-vol-per-instrument shortcut), where
`_MODEL` reads one vol at the structure's mean expiry — Ho-Lee has a single
constant vol by construction and cannot carry a term structure.

**(c) Mean reversion — second order once calibrated, and the sign flips.** At a
*fixed* short-rate vol, `a = 3%` damps Golds by **−13%**. Recalibrated to the
same ATM quote it also raises the implied `σ_HW`, and the two nearly cancel:
measured on live data, `a = 3%` moves the level **+2.5%** and `a = 10%` moves it
+8%. Anyone reaching for `a` to explain a rich/cheap signal is turning the wrong
dial; the payoff convention is the one that moves the number.

---

## 2. Reconciling the sources

Three published statements needed resolving before any of this could be trusted.

**arXiv:2304.13402 (Garcia-Lorite & Merino) eq (17) prints a minus sign.**
Their Theorem 4.3 gives the OIS-futures adjustment as
`exp(E^Q[I])·exp(−½∫Γ²)`, and their Remark 4.4 says it is *exact* for
Hull-White. Their eq (19) defines `Γ` as exactly the integrand of `Var(I)` —
verified term for term against the stochastic integral. So the printed formula
says `E[e^I] = e^{E[I] − Var/2}`, which contradicts Jensen. Two things settle it:
their own eq (18) for the average future inverts from (17) and reproduces (18)'s
minus **only if (17) carries a plus**; and the Monte-Carlo check in
`test_convexity_rv_hw1f_sofr.py` measures `E[exp(I)] = exp(+v/2)` directly, far
outside its own error bars. Their Example 4.6 additionally prints `Γ` with an
`e^{−ks}` prefactor where its own eq (19) requires `e^{+ks}`. Both are
transcription-level errors; the framework is right and `E^Q[I]` matches this
implementation exactly for all `a`.

The near-miss is worth recording: with the printed **minus**, the `a → 0` limit
is exactly `½σ²T1²` — *Citi's* weighting. Three signs, three conventions, all
plausible-looking numbers within 15% of each other.

**QuantLib's `HullWhite.convexityBias` is not Hull's textbook formula.** Its
one-line docstring and the `futuresPrice` argument leave its normalisation
unclear, so it was identified before being used as an oracle (worst relative
difference 3.5e-10 across a grid of `a`, `T1`, `τ`, `σ`):

```
QL bias = (1 − e^{−λ})·(F + 1/τ),   F = (100 − price)/100
λ       = σ²/(2a)·[B(τ)²(1−e^{−2aT1}) + a·B(τ)·B(0,T1)²]
        = Λ_Burgess + ½·v_pre
```

i.e. Burgess's term/ED adjustment (SSRN 2850320 eq 4) **plus half the pre-`T1`
compounding variance. At `a → 0` it is `½σ²τ·T1·(T1+2τ)`, 6.7% above Hull's
`½σ²T1T2`.** That decomposition is now a test: it pins `B`, `B(0,T1)`, the term
branch and the pre-`T1` variance against code this repository did not write.

**The smile is deliberately not modelled.** Piterbarg & Renedo (SSRN 610223)
show the smile matters for the adjustment, and Turfus & Romero-Bermúdez
(SSRN 4708715) give a skew/smile-aware SOFR futures price. Turfus's own summary,
on the "convexity — SOFR futures options" thread: *"Basically I would advise
using a Hull-White ATM-calibrated model for the futures convexity. The
smile/skew makes no difference until you look at options."* Any smile-effective
volatility can still be injected through `model_vol_provider`.

---

## 3. How it is verified

Closed-form algebra runs, returns a plausible number, and is wrong — so nothing
checks the module against itself.

| check | what it pins | result |
|---|---|---|
| `scipy.quad` on each defining integrand | the closed forms for `μ`, `v`, `J1`, `J2` | agree to 1e-9 across `a ∈ [0, 0.25]`, `T1 ∈ [0.05, 6]` |
| Monte Carlo, exactly-stepped OU with antithetics | `E[e^I] = e^{+v/2}` — **the sign** | var matches to 3%, mean to 2e-4, and 20× closer to `+v/2` than `−v/2` |
| QuantLib `convexityBias` | `B`, `B(0,T1)`, term branch, pre-`T1` variance | 1e-9 across the grid |
| analytic `a→0` limits | all three payoff weightings | exact (1e-13) |

Plus, on live data (`_hl2_verify.py`): the observed adjustment **and** the
Ho-Lee `_MODEL` level are byte-identical to a reference captured on the
unmodified tree (max |diff| **0.000000000000**, 26 columns × 63 dates); a
`_MODEL2`-only request makes **0** BarChart calls; the three cache entries for
one structure stay three and do not cross-write.

Mutation harness `_hl2_mutate.py`: **25 anchors, 25/25 killed**. Three survivors
were found and fixed before merge — a wrong `cvx_model` provenance string (the
other keys already separated the fingerprints, so nothing collided; the row
would just have been *labelled* Ho-Lee), and `T2` hard-coded at `T1 + 0.25`
(every test derived its expectation from the same helper, so the expectation
moved with the mutant; the fix recomputes IMM dates from rateslib and asserts
the accrual is 91 or 92 days, never 91.25). The third is instructive: removing
the `injected:` namespace survived at first, because the *write* is already
blocked for an unnamed provider — the damage is on the **read**, where a warm
built-in cache is served back and the provider is never called. The test that
kills it plants built-in rows first.

**Two defects were found by measurement, not by a test.**

*The vol mapping* originally read `vol·sqrt(T/V)/B(a,tail)`, missing the `·tail`.
At the 1Y tail that factor is 1, so every test passed; at a 3M tail it is a
**16× error in the adjustment**, and it left the mapping discontinuous at
`a = 0`. It surfaced in a sensitivity probe across tails, and the regression
test is continuity into `a → 0` at a *non-unit* tail — which no 1Y-tail test can
express.

*An injected volatility provider used to write under the built-in key.*
`model_vol_provider=` did not appear in `value_kwargs`, so its rows landed under
`cvx_vol_source="swaption_cube"` — the built-in model's own fingerprint — and
`ignore_cache=True` recomputes the **read** while still performing the
**write**. Both verification scripts did exactly that. Measured damage, still in
the store days later:

| column | stored | true | max abs |
|---|---|---|---|
| `BLUES_MODEL` | 5.9057 | 5.9549 | 0.202 bp |
| `GOLDS_MODEL` | 9.5646 | 9.6369 | 0.232 bp |
| `GREENS_MODEL` | 3.0598 | 3.0895 | 0.118 bp |
| `REDS_MODEL` | 1.1450 | 1.1516 | 0.051 bp |
| `WHITES_MODEL` | 0.1619 | 0.1419 | 0.038 bp |
| `BLUES_MODEL2` | 6.5636 | 6.9853 | (self-healed mid-run) |

Five of those were written by PR #504's own verification, which prices five
packs with node-**snapped** vols; the sixth by this branch's check 2, which
prices Blues at a fixed 95bp. The first draft of the table in §4 was reading
them back.

The fix is the same rule this repository keeps paying for — **the cache key must
move with the inputs, and a provider is an input**. An injected provider is now
served under `injected:<model_vol_source>`, so it can neither read nor overwrite
the built-in rows, and an *unnamed* one is computed but never stored, because
two different unnamed providers would otherwise share one key. `ignore_cache`
still writes: with an honest key a recompute *should* refresh the row. The guard
prevents recurrence and does not heal what is already stored — the built-in key
did not change — so `_hl2_repair_cache.py` recomputes those rows under
`ignore_cache=True` and asserts cached == recomputed afterwards (residual
**0.000000000000**). It has been run against this machine's store.

---

## 4. What it prices, measured

63 dates, 2025-06-02 → 2025-08-29, `a = 3%`, ATM 1Y-tail swaption vols, on a
repaired store (§3). Mean bp.

| label | observed | `_MODEL` | `_MODEL2` | obs − `_MODEL` | obs − `_MODEL2` |
|---|---|---|---|---|---|
| WHITES | 0.103 | 0.142 | 0.288 | −0.039 | −0.185 |
| REDS | −0.627 | 1.152 | 1.578 | −1.779 | −2.205 |
| GREENS | 2.831 | 3.090 | 3.824 | −0.258 | −0.993 |
| BLUES | 6.786 | 5.955 | 6.985 | **+0.831** | **−0.199** |
| GOLDS | 9.569 | 9.637 | 10.982 | −0.068 | −1.414 |
| BUNDLE5Y | 3.851 | 4.083 | 4.732 | −0.233 | −0.881 |
| SFR20 | 11.253 | 11.194 | 12.665 | +0.058 | −1.413 |

**`_MODEL2` is the right model for the payoff and it is not the better fit.**
Every pack sits **below** it — the sign is uniform, −0.19 on Whites widening to
−1.41 on Golds — and across the five colour packs the mean absolute gap goes
**0.595 → 0.999 bp**. Ho-Lee's `T1²` weighting is closest on Golds (−0.068) and
worst on Blues (+0.831); the compounded model is the reverse.

Two things follow, and only the first is a claim.

1. **The market prices SR3 convexity cheaper than an ATM-calibrated Hull-White
   model on the correct payoff, and increasingly so with maturity.** That is
   what the uniform negative column says. Citi's `T1²` weighting under-weights
   the deep end by roughly the amount the market is cheap there, so two errors
   partly cancel in their screen — worth knowing before reading a `VsModel`
   print as richness.
2. At `a = 0` the compounded model prices Blues at **6.811** against an observed
   **6.786** — a 0.03bp miss — while over-pricing Golds by 1.08bp. So the
   observed term structure is *flatter in maturity* than the ATM swaption curve
   implies. The obvious next test, which this model makes possible and which is
   **not** done here: fit a single `(a, σ)` to the ATM term structure and price
   the whole strip with it, instead of recalibrating per contract. At a fixed
   short-rate vol `a = 3%` damps Golds 13%, which is the order of the gap. That
   is a fit worth running, not a conclusion.

## 5. Deliberate omissions

Each is dropped identically by `_MODEL`, so `VsModel` comparisons stay
apples-to-apples. Sizes measured, not estimated:

* the forward discount factor `1/D = 1 + τf` — **+1%** at 4% rates. Pass
  `fwd_discount` to `hw1f_sofr.futures_ca` to put it back;
* the `(1+S)` level term in the vol mapping — up to **8%** at 4% rates;
* ACT/365 against the contract's ACT/360 quoting basis — **~1.4%** on the level;
* daily compounding approximated by continuous compounding.

## References

* Burgess, N. (2015). *The Hull-White 1 Factor Convexity Adjustment and the
  Special Case when the Hull-White and Ho-Lee Models are Equivalent.* SSRN 2850320.
* Garcia-Lorite, D. & Merino, R. (2023). *Convexity adjustments à la Malliavin.*
  arXiv:2304.13402, Thm 4.3 / Ex 4.6.
* Turfus, C. & Romero-Bermúdez, A. (2024). *Analytic Pricing of SOFR Futures
  Contracts with Smile and Skew.* SSRN 4708715.
* Piterbarg, V. & Renedo, M. (2004). *Eurodollar Futures Convexity Adjustments in
  Stochastic Volatility Models.* SSRN 610223.
* Hull, J. C. *Options, Futures and Other Derivatives*, 9th ed., Ch. 31.
* West, G. (2010). *Interest Rate Derivatives: Lecture notes.*
* BSIC (Bocconi Students Investment Club). *Understanding Convexity Bias in
  STIR Futures Markets.* — practitioner framing; same two models, states the
  Ho-Lee adjustment in `T1`/`T2` (the term convention), calibrates from
  cap/floor vols, and notes mean reversion reduces the bias at long maturities
  (true at a fixed short-rate vol; §1(c) above measures what happens once the
  vol is recalibrated).
