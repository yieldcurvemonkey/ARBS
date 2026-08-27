# Curve fly screener — design

Screen every butterfly on the USD swap curve, in spot **and** forward space, on
risk-adjusted carry-and-roll. One curve build per date, then cheap par-rate
evaluations — no per-structure market query.

## 1. The carry-and-roll convention, and why this one

Three conventions are in circulation. Only one is usable for a screener.

| convention | what it gives | verdict |
|---|---|---|
| forward rates realised | identically **zero** for any par swap | useless — it is the arbitrage-free statement, not a signal |
| yields unchanged (static curve) | age the trade on a frozen curve, reprice | **this one** |
| expectations of short rates realised | Tuckman's preferred | needs a subjective rate path; not screenable |

The forwards-realised case is worth stating explicitly because it is the common
trap: if the forward curve is realised, carry-and-roll over the life of a par
swap is exactly zero by construction, so a screener built on it ranks nothing.

Under the static-curve convention the measure is: **carry-and-roll over horizon `h`
is the aged structure's rate, read off today's curve, minus the structure's rate
today.**

    CR(structure, h) = R(aged structure | today's curve) - R(structure | today's curve)

"Aged" means the trade has `h` less time to run and is read off the *same* curve,
so both the start and the remaining life shift toward zero:

| structure | today | aged by `h` | comparison point |
|---|---|---|---|
| spot `T`y swap | `0y x T` | `0y x (T-h)` | the **shorter spot** rate |
| forward `f x T` | `f x T` | `(f-h) x T` | the **nearer forward** rate |

### The spot row is the one that is easy to get wrong

Comparing a struck `T`y swap against the **`h x (T-h)` forward** instead of the
`(T-h)` spot silently implements the *forwards-realised* convention — under which
carry-and-roll is identically zero, so the screen ranks nothing. The first cut of
`age()` did exactly this and gates G1/G3 rejected it: on an upward-sloping curve it
reported a paid 10y swap rolling **up** +4.34bp, when a payer struck at 433bp facing
a 9y spot of ~431bp a year later is plainly losing.

Nordea's note *does* use the forward comparison (a 5y at 1.023% against a 6m-forward
4.5y at 1.10%, giving 7.7bp) — but it is quoting carry-and-roll **inclusive of
financing**, which is a different and also-valid number. The two differ by exactly
the accrued floating coupon. This screener ranks on pure static-curve roll; the
carry-inclusive measure is a documented follow-up, not the default, because mixing
the two across spot and forward structures makes the ranking incomparable.

A consequence worth flagging on the output: **forward-starting structures have no
carry, only roll**, because no floating coupon is fixed at inception. Measured in
`ConvexityRV`, forward packages carry ~0 (+0.006bp on 2022-09-13). So on the forward
flies the two measures coincide — which is why G1 can tie the forward legs to an
independent repricing exactly, and cannot do so for the spot legs.

### What this is NOT

`IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` used not to be this quantity: graded
against Citi's published Figure 7 it correlated **−0.136** and got the cross-pair
rank order wrong, where a repriced 1-year roll of the aged package correlates
**+0.991** (`docs/convexityrv/`, lesson 3). 2026-08-27: fixed. The query value aged a forward-starting leg by shortening its TAIL instead of bringing its START nearer (a 10Yx10Y aged 1Y became 10Yx9Y, not 9Yx10Y); `Query/IRSwaps/_carry_roll.py` is now the single kernel behind both backends and scores **+0.991 / MAE 0.338 bp** on the same eight pairs. It implements the
same `age()` rule this module documents. It is still computed here as
`cr_query_bp` alongside the screener's own kernel; the two agreeing is the
check, and the ranking still runs off this module's kernel.

`rateslib.Curve.translate()` is also not a way to age a struck swap — it
renormalises discount factors and returns 0.000bp on a DV01-neutral forward
package. `ConvexityRV.curve_ops.horizon_handle()` raises rather than return it.

## 2. Risk adjustment

    rac = cr_1y_bp / (rlzd_vol_bp * sqrt(252))

the continuous statistic underneath Citi's published screen — carry over the
horizon divided by annualised realised volatility of the structure's own level.
Signed, smooth through zero, no truncation. The published ratio truncates the
breakeven to zero whenever carry is non-negative, which makes it exactly 0 on
56% of 2023 and undefined precisely where a rule wants to fire; the tie-out to
Citi is kept in `ConvexityRV.strat3_strikeless_vol.screen_frame` (Spearman 0.988
on 120 published cells) and the traded statistic is this one.

## 3. Weights

Fly rate in bp uses the market convention `2*belly - front - back`. Risk weights
default to **DV01-neutral with the belly carrying 2x**, solved off repriced DV01
(central difference on a ±1bp parallel shift), not the analytic annuity — the two
diverge by up to 10% on an inverted long end, and sizing on one while checking
neutrality on the other is how a directional residual gets in.

## 4. Universe

Integer-year tenors only, so every aged structure has a clean shorthand and no
fractional-tenor parsing is involved.

* spot flies: `a < b < c` from {2,3,4,5,7,10,15,20,30}, requiring `a >= 2` so a
  1-year ageing is expressible
* forward flies: starts {1,2,3,5,10} x the same tenor grid

## 5. Gates

Nothing is reported until these pass.

* **G1 forward** — on FORWARD legs the static-curve roll must equal an independent
  repricing of the same calendar swap on a rolled curve, since a forward swap has
  no carry and the two measures coincide there. Spot legs are deliberately *not*
  gated this way: rateslib's aged repricing also books the accrued floating coupon,
  which is carry, not roll, and the gap between them is that coupon.
* **G2 reduction** — a fly with the back wing weighted 0 must reproduce the
  two-leg curve CR exactly.
* **G3 sign** — on an upward-sloping curve a *paid* spot swap must show negative
  carry-and-roll.
* **G4 tie-out** — the pair CR for `10Yx10Y/20Yx10Y` must reproduce the value the
  `ConvexityRV` screen reports for the same date.

## 6. Carry and entry level are not independent

Measured on this screen: **`corr(cr_bp, zs) = +0.61`** across all 1,019 surviving
structures, and **+0.57** within the forward-curve-same-tenor family alone.

That is a property of the measure, not a coincidence. Carry-and-roll here *is*
the aged level minus the level, so a structure sitting at an extreme of its own
range tends to show large roll for the same reason it looks rich. Ranking on
carry alone therefore systematically surfaces structures that have already run,
and reports as "carry" what is partly compensation for a level that reverts.

The measured cost of ignoring this, on the desk's own trade: `10y10y/20y10y`
carries +9.13bp/yr and sits 10.79bp above its 2-year mean with an AR(1) half-life
of **3.1 months**. Full reversion inside the year nets **-1.66bp** -- the carry and
the entry approximately cancel, well inside a 3-6 month horizon.

So the screen reports three columns, and they must be read together:

| column | meaning |
|---|---|
| `rac` | carry per unit of realised vol -- ignores where the level sits |
| `rev_drag_bp` | distance to the sample mean, i.e. what full reversion costs |
| `rac_net` | `(carry + rev_drag) / annualised vol` -- carry charged for reversion |

`rac` alone is the number that flatters. `rac_net` is the conservative bound
(it assumes full reversion within the horizon, which is pessimistic for a
half-life longer than the holding period). Neither is the answer on its own.
