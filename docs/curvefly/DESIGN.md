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

Under the static-curve convention there is a clean identity (the Nordea note
formulation): **carry-and-roll over horizon `h` is the rate of the aged structure,
seen from today, minus the structure's rate today.**

    CR(structure, h) = R(aged structure | today's curve) - R(structure | today's curve)

Ageing moves the start closer by `h` and leaves the maturity fixed:

| structure | today | aged by `h` |
|---|---|---|
| spot `T`y swap | `0y x T` | `h x (T-h)` |
| forward `f x T` | `f x T` | `(f-h) x T` |

Nordea's worked example is the spot case: a 5y swap at 1.023% against a 6m-forward
4.5y at 1.10% gives CR = +7.7bp, which is what their DV01 route also produces.
The identity subsumes both components — a spot swap's accrued-coupon carry and its
roll down the curve — so it needs no carry/roll split, which is the part every
published treatment disagrees about.

A consequence worth flagging on the output: **forward-starting structures have no
carry, only roll**, because no floating coupon is fixed at inception. Measured in
`ConvexityRV`, forward packages carry ~0 (+0.006bp on 2022-09-13). So on the
forward flies the `cr_1y_bp` column is pure roll-down and will be small.

### What this is NOT

`IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` is not this quantity. Graded against
Citi's published Figure 7 it correlates **−0.136** and gets the cross-pair rank
order wrong, where a repriced 1-year roll of the aged package correlates **+0.991**
(`docs/convexityrv/`, lesson 3). It is computed here as `cr_query_bp` for
comparison only and never used in the ranking.

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

* **G1 identity** — CR from the aged-rate identity must equal an independent
  repricing of the aged package for the same structure.
* **G2 reduction** — a fly with the back wing weighted 0 must reproduce the
  two-leg curve CR exactly.
* **G3 sign** — on an upward-sloping curve a *paid* spot swap must show negative
  carry-and-roll.
* **G4 tie-out** — the pair CR for `10Yx10Y/20Yx10Y` must reproduce the value the
  `ConvexityRV` screen reports for the same date.
