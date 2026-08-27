# The Kink Ledger — PCA forwards × kink-fading × the convexity framework

How the PCA RV framework on 1y forwards (CS *PCA Unleashed* 2012, ING
*Deconstructing the EUR yield curve* 2020), the practice of fading kinks, and
the convexity-RV framework (`docs/convexityrv/`, the Convexity Ledger) combine
into one screen — and what our own measured verdicts say about which cells of
the combination can be alive.

Companion to: *The Convexity Ledger* (corpus breakdown, 2026-08-25) and *Vol
Without Vega* (curve-fly screener + rac_net, 2026-08-23). Bank claims are
attributed; **ARBS-measured** facts are marked. Nothing here was implemented;
§7 is the build plan.

---

## 0. The answer

**The three frameworks are one identity read at three different terms.**
Salomon Part 6 (Ilmanen 1995, Eq. 11 / Fig 5):

```
E[return] = yield income + rolldown + ½·Cx·Vol(Δy)² + duration·(rate view) + local rich/cheap
            └──────── the rent (θ) ────────┘                                └─ the kink ─┘
```

The PCA framework measures the **last** term — the residual of a point on the
non-overlapping 1y-forward grid after the level/slope/curvature factors are
removed, which is exactly what a "kink" is. The convexity framework measures
the **middle** terms — the rent, which the Ledger normalizes as
`σ_BE = √(2·θ_daily/Γ)` against realized vol. Fading a kink is taking a
factor-neutral position in local curvature, and local curvature is priced by
vol: **the fade direction decides which side of the rent you are on.**

- **Receive an upward kink** (a forward that sticks up = cheap belly) =
  receive belly / pay wings = the bullet side of a barbell-bullet trade =
  **short local convexity ⇒ you collect the rent while positioned for the
  reversion.** This is the only configuration that "earns theta while fading
  kinks."
- **Pay a downward kink** (rich belly) = the barbell side = **long local
  convexity ⇒ you pay rent to hold the fade**, and the mispricing must beat
  the rent bill (Citi 2010's arithmetic: target = 28bp mispricing − 8bp
  convexity rent ≈ 20bp).

**The scarcity headline.** ARBS-measured across the 1,075-structure screen:
`corr(carry-roll, level z) = +0.61` (+0.574 within the forward-tenor family).
A kink that is cheap *is* a structure with fat roll — the reversion and the
carry are the same P&L booked on two clocks (a static kink is harvested by
rolling through it; a reverting kink by the reversion; a structure can't give
you both twice). So "earn theta while fading kinks" is not a strategy you
overlay — it is the **structurally rare cell** where carry and value decouple:
carry positive **and** z at-or-cheap-of fair, or carry in excess of what the
point's vol justifies. The combined screen's entire job is finding those
decoupled cells and refusing the rest. (Vol Without Vega measured the coupled
default: every named steepener was net-negative at the 3–6m horizon once
charged for reversion; the one survivor, 5s10s30s, was the *negative*-carry
cheap structure.)

---

## 1. What each source framework actually contributes

### 1.1 CS *PCA Unleashed* (Pelata/Giannopoulos/Haworth, 24-Oct-2012)

- **The grid**: 17 non-overlapping forwards — spot 1y, 1y1y … 9y1y, 10y2y,
  12y3y, 15y5y, 20y5y, 25y5y, 30y10y, 40y10y. Note the **widening tenors past
  10y** — the grid's resolution tracks quote support, a design decision our
  F-ING sawtooth verdict (§5) independently proves necessary.
- **The model**: covariance PCA on mean-centered levels, 1y rolling window
  (261d), ≤3 PCs (~95% of variance; EUR PC2 10.1%, PC3 4.3%).
  `residual = actual − reconstruction`; **positive residual = cheap**. For
  govvies they *drop* PC3 deliberately "as it is more valuable for curvature
  effects to be captured as part of the residual" — the k-factor choice
  defines what counts as a kink.
- **The kink-fade instruction, verbatim**: "If one residual is very positive
  on a particular day, while the surrounding points have negative residuals,
  then relative-value players might be tempted to enter a short-term butterfly
  position (pay wings, receive body)." No z-thresholds, no half-life — the
  statistics arrive via H-S and the blog post (§1.4).
- **Hedge math**: 2-security PC1 ratio = ratio of PC1 loadings; PC1+PC2 ratio
  `γ = [u₁ˣu₁ʸλ₁² + u₂ˣu₂ʸλ₂²]/[(u₁ʸ)²λ₁² + (u₂ʸ)²λ₂²]`; portfolio variance
  `Σ λ_p²(u_pˣ)²`. Book-level PCA hedging to zero net PC1/PC2/PC3.
- **The filter that matters**: "They indicate dislocations, but that does not
  always mean there is a related trade." Worked counter-example: the 2012
  15y5y/25y5y residual divergence was Dutch FTK-II pension regulation — a
  structural demand shift, not an inefficiency. **The classification layer
  (§4.4) is CS's own missing module.**
- **The finding CS reports but cannot explain**: EUR PC1 loadings **flip
  negative past 20y5y** (25y5y −0.044, 30y10y −0.056, 40y10y −0.031), and
  ultra-long-vs-belly hedge ratios blow out 6.5–11.5×. That is the convexity
  zone announcing itself inside the factor model: long yields are structurally
  less volatile and locally decoupled *because* ½Cx·σ² dominates there
  (Salomon Part 5; H-S Ch5's Dybvig-Ingersoll-Ross argument). PCA sees it,
  cannot name it, and silently mis-hedges across it.

### 1.2 ING (Jan–Mar 2020, five notes)

- **The kink definition**: PC1 residuals of non-overlapping 1F1Y…30F1Y
  forwards (PC1 explains 97–99%), read against each tenor's own trailing
  3-year 5th/50th/95th percentile bands. **ARBS replication note**: our v1
  time-series-PC1 build failed to reproduce ING's published frontier
  (R² 0.03); a **per-day cross-sectional smooth fit** through the day's
  forward strip reproduces it exactly (slope −1.27, R² 0.93 —
  `RVUtils/INGCurve/xsec.py`, ledger L-0015/L-0035). Whatever the prose says,
  ING's numbers behave like curve-vs-its-own-smooth-fit residuals. Keep both
  definitions and require sign agreement (§4.1).
- **Frontier 1 — value vs carry** (Deconstructing, Fig 3): cross-sectional
  regression of residual on 3m rolldown, `residual = −1.2716·roll + 16.425`,
  R² 0.927. Richness and carry trade off ~one-for-one on the frontier — ING's
  version of our +0.61. **PC1-neutral weighting doubles the frontier slope**
  (Fig 5: −2.696, R² 0.86): "the trade-off between value and carry … is
  almost twice as attractive" once direction is removed. The tradeable object
  is the **off-frontier** component, not the raw residual.
- **Frontier 2 — carry vs vol** (Fig 4): `ATM nvol = 5.6200·roll − 25.893`,
  R² 0.9699 — **rolldown is priced vol compensation**, point by point. "One
  of the insights of our option valuation theory is the trade-off between
  carry and volatility." This is the Ledger's σ_BE/σ_rlzd axis in regression
  form, and it **breaks down at 20F1Y/25F1Y/30F1Y** — the same boundary as
  CS's loading flip.
- **The negative-carry gate**: breakeven months ≈ (mispricing / |carry per
  3m|)·3, compared to the trade horizon ("this trade would need to revert to
  its mean in more than 36 months for carry to eat out the profit").
- **Conduct under stress (the Feb→Mar 2020 sequence)**: 50% risk sizing when
  vol doubles; stops honored (the Eonia hedge trade stopped at −10bp); "only
  the simplest trades stand a chance to be implemented" (pivot to Euribor
  futures, then to a plain DV01-weighted calendar); and the closing risk
  statement — long-end flattening "led for instance by convexity hedging
  needs" is a **rising-probability structural risk, so favour butterflies
  weighted towards front-end flatteners than back-end steepeners**. ING
  treats the convexity zone as a thing to *avoid being short against*, never
  to fade.

### 1.3 Salomon *Understanding the Yield Curve* 1–7 (Ilmanen 1995–96) + Kopprasch 1985

- **The identity** (Part 6 App A, Eq 11):
  `FSP_n ≈ BRP_n + (1+f/100)·[−Dur·E(Δs) + ½·Cx·Vol(Δs)²]` — forward-spot
  premium = risk premium + expectations impact + convexity bias (the CB term
  carries its minus sign internally: `CB = −½·Cx·Vol(Δy)²`).
- **Convexity mechanics**: zero-coupon `Cx ≈ duration²/100`; value of
  convexity `= ½·Cx·Vol(Δy)²` with **Vol in absolute bp terms** (13% lognormal
  × 7% yield = 91bp — the units trap the Ledger already guards). The Sep-95
  ladder: 30y zero convexity value 253bp/yr (30% of its expected return);
  even the convexity-*adjusted* curve stays inverted past 25y (liquidity +
  financing premia). Barbell-vs-bullet worked breakeven: a 71bp rolling-yield
  giveup needs an 11bp 10s30s flattening **or** a 138bp parallel move;
  historically flattening delivered ≥11bp 30% of years, |shift|>138bp only
  17% — **"a rolling yield disadvantage tends to offset the convexity
  advantage,"** and the bullet beat the barbell ~100bp/yr, in 4 of 5
  subperiods. Short local convexity is a small structural harvest.
- **Part 7's two verdicts that discipline this whole framework**:
  1. **Curvature is ~0.8-correlated with curve-reshaping expectations and
     only ~0.1 with implied vol.** The LSW "curvature = volatility" result
     held only 1984–88; in 1981 vol was extreme and the curve was *convex*.
     "Investors who try to 'arbitrage' between the volatility implied in the
     curvature of the yield curve and the yield volatility implied in option
     prices will find it very difficult to neutralize the inherent curve
     shape exposure." — the 1996 statement of our own measured
     fly-is-not-a-vol-hedge (partial R² 0.000–0.044, weekly change R²
     0.0003–0.089). **Vol prices the rent; it is never the hedge pair.**
  2. **The *average* concave shape is convexity bias + a concave risk-premium
     curve, not flattening expectations** (realized flattening averages
     ~zero). So the persistent long-end concavity is real rent, not a
     standing dislocation — a smooth fit that ignores it will flag a
     permanent "kink" at the long end that never converges.
- Supply never appears as a curvature driver in Salomon — the modern
  LDI/Formosa layer (JPM 2017–20, the Ledger §II.1) is a post-2010 addition
  the classification layer must carry.
- Kopprasch: hedge ratio = (PVBP ratio) × **yield beta**, with the closing
  warning that beta estimation risk "can be more important than statistics" —
  the 1985 version of our hedge-ratios-at-the-holding-horizon rule.

### 1.4 Huggins–Schaller 2ed (+ the "pca part2" post)

- **Box 3.1** is the operating manual the CS note lacks: covariance (never
  correlation) PCA on **constant-maturity fitted-curve series** ("to avoid
  rolldown effects"); two-pass (broad PCA to find the sector, narrow PCA for
  clean weights); PCA-neutral weights by matrix inversion (worked 2s5s7s:
  −80/+100/−58mm; the BPV-neutral version of the same fly is 44% factor-1 /
  29% factor-2 / 28% factor-3 — "a fuzzy exposure," and "there are instances
  where BPV-neutral steepeners are actually non-directional flatteners").
- **The carry⊕reversion netting procedure** (Ch3 fn 24 — the formalization of
  rac_net): expected holding horizon = the OU **first-passage time** to
  target; charge carry over *that* horizon, not a fixed one; then compute
  `P(FPT > carry-breakeven horizon)` as the explicit tail metric. Targets at
  half the distance to the mean; stops on the evolving 2σ band; annualized
  Sharpe *declines* with holding horizon under OU — recycle capital.
- **The pre-entry "cloud" diagnostic**: regress the candidate structure on
  factor 1 over the window leading into entry; a correlated cloud (ephemeral
  factor correlation) is the main PCA pitfall — screening it raised their hit
  rate 82%→90%. Plus the eigenvector-regime critique: loading shapes rotate
  with the vol regime (ZIRP, YCC); stress the trade under alternate historical
  eigenvectors; truncate samples across regime breaks.
- **Structural vs ephemeral** (Ch8/Ch17): "in some cases, bonds are
  structurally rich, and the rich/cheap indicator will revert around a number
  that reflects this structural richness" — regress out the structural
  drivers; **what survives the regression is the tradeable residual**; the
  trade is conditioned explicitly on "if these are deemed to be ephemeral."
- **Provenance flag**: *"pca part2 (good trade idea framework)"* is **not a
  CS document** — it is a 2015 bquanttrading blog post (asmquantmacro.com).
  Its contribution is the worked PC3-weighted 3s5s10s fly (weights −0.90/1.00/
  −0.46, OU half-life 11bd, z −2.15, E[reversion] 5bp quoted *separately*
  from carry 6.25bp/3m) — plus an unresolved look-ahead ambiguity its own
  comment thread never answers (fixed current weights applied retroactively
  vs per-date refits). Do not treat its backtest chart as evidence.
- **Delivery options** (Grieves/Marcus/Woodhams 2010 + H-S Ch7): CTD-switch
  optionality makes futures PVBP *rise* with yield near the notional coupon —
  negative convexity, cleanly present in the note contract, swamped by curve
  slope in the bond contract. **A kink in a futures-implied forward curve
  near the delivery-cusp region is a delivery-option artifact, not a fade** —
  and one-factor DO models understate the option far from the notional coupon
  (JGB worked case: <1 sen vs 7 sen multi-factor).

---

## 2. The unification, formally

### 2.1 A kink is a fly; a fly is signed convexity

On the forward grid, `kink_k = f_k − smooth(f)_k` (xsec definition) or
`f_k − PCA-recon_k` (factor definition) — both are the local second
difference in forward-start space up to the smoother's hat matrix. The
tradeable expression is a 3-leg fly on adjacent grid points, and the Ledger's
venue table already priced that family (**ARBS**, 1,075 structures): forward
flies are the **pay-for-convexity** family (mean carry −2.55bp/yr, 30%
positive); same-tenor forward curve pairs are the **collect-rent** family
(+6.63bp, 78%). Receiving the belly of an upward kink puts you in the
collect column; paying a rich belly puts you in the pay column. There is no
sign-free kink fade.

### 2.2 The two-clock identity (why carry and reversion must be netted)

Ageing a fly through a **static** kink books the kink's shape as rolldown;
holding a fly through a **reverting** kink books the same bp as reversion.
`corr(carry, z) = +0.61` is this identity showing up in a screen that
computes carry as aged-level-minus-level. Consequences:

- Never rank on `carry + E[reversion]` — that double-counts. Rank on
  `rac_net` (carry net of reversion drag at the measured AR(1)/OU horizon),
  which is the screen form of H-S fn 24.
- The decoupled cells are the strategy: **(i)** carry > 0 with z ≤ 0 (paid to
  hold something already cheap — rare; 5s10s30s was the only named survivor,
  and it decouples the other way: negative carry as the price of a 1σ-cheap
  level, +1.6bp net at 3–6m); **(ii)** carry above the carry-vs-vol frontier
  (rent in excess of the point's priced vol — excess rent, not recycled
  richness); **(iii)** a kink whose anchor classification (§2.4) says the
  roll-off is real and will not migrate with the position.

### 2.3 The five layers of a kink (subtract before fading)

Per the Salomon identity, local curvature at forward-start T decomposes as:

| layer | driver | zone where it dominates | treatment |
|---|---|---|---|
| 1 · expectations | meeting steps, reshaping expectations | fwd start ≲ 2–3y; **everywhere** per Part 7 (corr 0.8) | model meetings explicitly or exclude the zone (**ARBS**: ZQ kink-fade died because a meeting-step model explained 91% of the "kink") |
| 2 · risk-premium curvature | concave BRP curve | belly | slow-moving; part of the fair curve, not a fade |
| 3 · convexity bias | `−½·Cx(T)·σ(T)²`, σ from the cube | fwd start ≳ 20y (CS loading flip; ING frontier breakdown) | **the rent model**: compute it, add it back to the fair curve, never fade it, never "hedge" it with vol |
| 4 · local/technical | supply, LDI/regulation (FTK-II), Formosa, CTD/delivery zones, index events | point-specific | the classification layer; H-S: regress out, trade only what's deemed ephemeral — or *harvest* it (§2.4) |
| 5 · residual | flow, positioning, stop-outs | anywhere | the fade candidate — with the L-0088 constraint (§5) |

The fair curve to fit is therefore the **convexity-adjusted** forward curve:
`f̃_k = f_k + ½·Cx_k·σ_k²` with σ_k read from the SwaptionCubeStore at
(expiry = forward start, tail = tenor). A raw spline flags the long-end
concavity as a permanent cheap kink (layer 3 wearing a residual costume);
the adjusted fit removes exactly that. Part 7's 0.1 correlation caps the
ambition: in the belly this adjustment is small and the residual is mostly
layers 1/4/5 — which is where the classification work, not the vol work,
earns its keep.

### 2.4 Kink taxonomy by anchor — which clock pays

- **Calendar-anchored** (FOMC dates, turns, auction cycles): the structure
  ages *through* the hump; over a full passage the three legs net ≈ 0. Not a
  carry trade; only an entry/exit timing trade. (Front-end SR3/ZQ verdicts.)
- **Maturity-anchored** (the 20y supply point, 10y liquidity point, 30y+ LDI
  richness, CTD zones): the position **rolls off** the anchor once — the
  kink's shape *is* the rolldown, no reversion required. This is Nordea's
  "brain-dead trade" (receive 10y5y/pay 15y5y at the forward-curve top,
  +13.5bp/y of roll) and our same-tenor family. **This is the honest home of
  "earning theta while fading kinks": receive the structurally cheap point,
  let the position slide off it, and the kink can persist forever.**
- **Floating** (flow/positioning dislocations): the reversion clock — JPM
  beta-stability entry machinery (6M two-factor residual, R²≥60%, |z|≥1.5,
  |resid|≥4bp; exits zero-cross/+2SD/1M; skip when √(Zb²+Zw²)>3), with the
  L-0088 constraint that a *daily-mark* fade of a flow move is measured dead
  (§5) — the state that licenses these must be non-flow (supply calendar,
  regulatory event, index extension), not the mark's own z.

---

## 3. The three frontiers (the screen's pricing layer)

Every candidate is priced against three frontiers; the trade is the deviation
from the *surface*, not from any single axis:

1. **Value–carry** (ING Fig 3/5; ARBS +0.61): fit the cross-sectional
   frontier each day (PC1-neutral, which doubles its slope); the signal is
   the **off-frontier residual** — value not already explained by carry.
2. **Carry–vol** (ING Fig 4: `nvol = 5.62·roll − 25.9`, R² 0.97; Ledger:
   `σ_BE = √(2θ/Γ)` vs σ_rlzd, everything bp/day): rent above the frontier =
   excess rent; rent on the frontier = fair convexity compensation. Citi's
   published two-sided anchors (long gamma ≤0.42–0.8, short ≥1.17–1.38) are
   **curve-pair anchors, never validated on micro-flies** — import as
   reference points, re-derive gates per family.
3. **Reversion–horizon** (H-S Ch2/fn 24): OU fit per structure; expected
   FPT to a half-distance target; carry charged over the FPT;
   `P(FPT > carry-breakeven)` reported as the tail number; ING's
   breakeven-months rule as the coarse form.

---

## 4. Construction rules (the ones our evidence enforces)

1. **Weights**: PC1/PC2-neutral from the walk-forward PCA (the 5:1 solve on
   the PM's flattener+fly package is the in-house confirmation — median
   5.05:1 over 950 solves). BPV-neutral is a factor smear. **Do not
   PCA-hedge across the 20y boundary** — CS's own hedge ratios blow out
   6.5–11.5× there and the loadings flip sign; the ultra-long is its own book
   (the W1 flattener franchise), not a wing for belly flies.
2. **Two series per trade** (H-S Step 11/12): constant-maturity composed
   history for *statistics*; actual-instrument repriced roll for *carry*
   (**ARBS**: `CARRY_AND_ROLL_BPS_RUNNING` correlated −0.136 with published
   carry against the repriced `Curve.roll`'s +0.991; its ageing rule was fixed
   on 2026-08-27 and it now scores +0.991 / MAE 0.338 bp itself — see
   `Query/IRSwaps/_carry_roll.py`).
3. **Entry hygiene**: the H-S pre-entry cloud diagnostic (candidate vs PC1
   over the trailing window); the JPM β-stability skip; eigenvector
   walk-forward-vs-full-sample gap gate ("a large gap means you are trading
   the estimator").
4. **Classification before signal**: every grid point carries a tag —
   `meeting-zone` (fwd start ≲ 2y: excluded or meeting-modeled),
   `delivery-zone` (futures-derived points near the CTD cusp: excluded),
   `convexity-zone` (≳ 20y: harvest-only, no residual fades, no vol "hedges"),
   `supply/anchor` (named event or standing flow: harvest by roll-off,
   condition dislocation entries on the event calendar), `clean` (fadeable).
5. **Grid follows quotes**: CS's widening long-end tenors, not a uniform
   1y-forward comb (**ARBS**: F-ING's 21–29Y sawtooth was interpolated-par
   construction, not market; the degeneracy gate — legs between the same
   curve nodes fake both the best and worst rankings — is the same lesson).
6. **The two books** (the Ledger's structure, specialized):
   - **Harvest book** — short local convexity: receive-belly fades of cheap
     maturity-anchored kinks + same-tenor forward pairs. Gates: σ_BE/σ_rlzd
     in your favor, `rac_net > 0` at the OU horizon, z not rich, anchor
     classified. Needs **no reversion** to pay — the roll-off is the P&L.
     Its tail risk is episodic realized vol (the −$20.2m W4 exhibit), so it
     is sized against…
   - **Dislocation book** — long local convexity: pay-belly fades of rich
     kinks at extreme z, entered only when
     `E[reversion]·P(hit) − rent·E[FPT] − costs > 0` (Citi 2010's line item),
     conditioned on a named non-flow state. Negative carry here is the price
     of a value position, not a defect (the 5s10s30s lesson). The book
     doubles as the harvest book's convexity hedge — Nordea runs exactly this
     pairing (the 20y5y/25y5y receive "doing what it was supposed to do"
     against the steepener book), and ING's March-2020 vol-benefiting
     receive-belly played the same role.

---

## 5. The constraint layer — what is already measured dead, and what that implies

The naive versions of this combination are **all dead in our own ledger**, and
the framework above is only worth building because each death names the layer
it lacked:

| dead result (ARBS) | what it was | the layer it lacked |
|---|---|---|
| F3 xsec liquid-tenor fade — "the cleanest kill": median 63d reversion +0.81…+1.14bp vs ≥1.0bp RT (later re-bounded ~2.0–2.6bp for flies) | raw residual z-fade, EOD swap marks | no theta ledger, no state conditioning — pond equals boat |
| F-ING (v1+v2) | ING replication on EUR panel | construction sawtooth 21–29Y; no realization passes the RT |
| ZQ kink-fade | front-end curve kinks | layer 1: a meeting-step model explains 91% |
| SFR kink-fade v2 / STIR intraday kink | SR3 CM-slot kinks | the kink was not the FOMC calendar *and* not fadeable at cost; cost is frequency-invariant |
| SR3 fly mean-reversion | listed flies | edge +0.75bp vs 1.5–2bp RT |
| W4 ultra-long risk-adjusted carry | rent harvest, unhedged | gross 0.397 < null 0.446 — it was duration (level t −4.85): no factor neutrality, no reversion charge |
| CA-vs-fly hedging, fly-as-vega generally | fly as a vol hedge | Part 7 said it in 1996; partial R² ≤ 0.044 says it now |

Two program-level results bound what can be alive (ledger L-0085/L-0088, on
the Citi EOD + DTCC data at the CM-2 cost line): **the information in a daily
curve-RV signal is concentrated in the bar it is computed from** — flow-driven
dislocations resolve inside their own session, and knowing what traded does
not help you fade what moved. The surviving candidate class named there is
**a non-flow persistent state: positioning, issuance/supply calendars,
index-extension demand, mortgage/LDI convexity events** — which is precisely
what §2.4's classification layer supplies, and precisely the filter CS (the
FTK-II case) and H-S (structural-vs-ephemeral) formalize.

So the honest status of the combination:

- **As a new standalone fade family on the same daily marks: pre-dead.** Do
  not register it; that is the manufacture-a-family shape the loop mandate
  forbids.
- **As a selection overlay on the harvest book: the main event.** The harvest
  family (+6.63bp/78%) needs no reversion to pay; what kills it is buying
  rent that is really richness (+0.61) and wearing unhedged factor risk (W4).
  The kink layer supplies exactly those two missing charges: off-frontier
  rac_net and PC1/PC2-neutral sizing. This upgrade is testable **without a
  new data class**.
- **As a dislocation book: alive only conditioned on named non-flow states**
  (supply/issuance calendar, LDI/regulatory events, index extension, CTD
  migrations), with the rent line in the target and JPM's β-stability
  machinery at entry — a pre-registered empirical question, not a claim.

Statistical bars carried over unchanged: pre-registered grids with declared
cell counts and E[max SR | null]; DSR at n_eff on both clocks; few
closely-related configs, all required to work (L-0064); placebos
**scale-matched to the smoother** (the xsec hat matrix is exposed for exactly
this); cost curves at 0×/0.5×/1×/2× with per-leg break-evens (anchors: swaps
~0.3bp/leg one-way at-stamp, fly packages ~2.0–2.6bp honest band, long-end
packages ~3bp); support gate on every vol input; negative controls that must
fail; research bugs flatter the hypothesis (12/12).

---

## 6. The ledger row (schema)

One row per grid point / candidate structure, everything in bp/day:

```
point | tags (meeting/delivery/convexity/supply/clean)
residual_xsec | residual_pca | sign_agree | z | pctl_3y
OU: k, half_life, E[FPT to half-target], P(FPT > carry_BE)
θ: carry (actual instruments, repriced) + roll + decay | rac | rev_drag | rac_net@FPT
Γ: repriced ±10/25/50/100 | σ_BE = √(2θ/Γ)
σ_impl (cube @ fwd-start × tenor) | σ_rlzd (composed, ex-roll) | σ_BE/σ_rlzd
frontier residuals: off value–carry | off carry–vol
E[net@FPT] = P·reversion − rent·FPT − cost | book (harvest / dislocation / none)
```

---

## 7. Build plan (nothing here implemented)

The legs already exist; the join is the work:

1. **Grid + residuals**: run `RVUtils/INGCurve/xsec.py` (per-day smooth fit,
   hat matrix exposed) on the **USD** Citi grid with a CS-style
   quote-supported tenor comb; add the PCA residual from `RVUtils/pca_rv.py`
   (walk-forward, frozen monthly loadings — machinery already in
   `INGCurve/screen.py`). Require sign agreement.
2. **Convexity adjustment**: per-point `½·Cx·σ²` with σ from
   `SwaptionCubeStore` (expiry = fwd start, tail = tenor; support gate on the
   cube's quoted range); publish the fair-curvature curve alongside the raw
   one. `RVUtils/ConvexityRV/curve_ops.py::payoff_profile` supplies Γ by
   repricing (never `Curve.translate`, never closed forms).
3. **Screen join**: extend `RVUtils/CurveFlyScreener` (already: carry, z,
   AR(1) half-life, rac, rac_net, degeneracy gate, 7 gates) with σ_BE,
   σ_impl, σ_rlzd, the two frontier residuals, and the classification tags.
4. **Weights**: PC1/PC2-neutral solver from `pca_rv.fly_weights` /
   `ConvexityRV/factor_neutral_sizing.py`, with the walk-forward-gap gate and
   the H-S cloud diagnostic as entry checks.
5. **Books + report**: the two-book split with per-book gates (§4.6); the
   dislocation book's state calendar (issuance/LDI/index/CTD events) is the
   one genuinely **new data** requirement — consistent with L-0088's "the
   honest next move is new data."
6. **Pre-registration before any backtest**: declared universe, config count,
   cost line (CM-2 shape: ~flat 0.32–0.53bp per leg at-stamp), null model,
   placebo battery scale-matched to the xsec smoother, and the F3/W4 numbers
   as the incumbent nulls to beat.

---

## Sources

- CS *PCA Unleashed* (2012): `Downloads/convexityrv_markdown/PCA Unleashed….pdf.md` (clean).
- ING five notes (Jan–Mar 2020): **the `.md` conversions are empty (0 bytes)** — read from the PDFs in `Downloads/convexityrv/`.
- Salomon Parts 1–7 + Kopprasch 1985: **no usable conversion exists anywhere**
  (`convexityrv_markdown` copies are ~213-byte shells; nothing in the repo) —
  read from the PDFs in `Downloads/convexityrv/salomon_*.pdf`. Part 5 =
  *Convexity Bias and the Yield Curve*; Part 6 = *A Framework for Analyzing
  Yield Curve Trades*; Part 7 = *The Dynamics of the Shape of the Yield
  Curve*.
- Huggins–Schaller 2ed: `Downloads/convexityrv_markdown/Fixed Income Relative
  Value Analysis 2ed.pdf.md` (prose fine; equation images dropped).
- "pca part2" = bquanttrading blog (2015), not CS; `.md` empty, read from PDF.
- Grieves/Marcus/Woodhams delivery-options paper: `.md` corrupt (footer
  boilerplate only), read from PDF.
- ARBS: the Convexity Ledger + Vol Without Vega artifacts;
  `docs/convexityrv/DESIGN.md`; CurveFlyScreener/INGCurve/pca_rv modules; the
  citivelo-rv-loop ledger (F3, F-ING, F7/F8, L-0085/L-0088, CM-2, L-0064).

*Compiled 2026-08-26. Bank numbers quoted as published; ARBS verdicts marked.*
