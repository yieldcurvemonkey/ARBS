# V3 — basis-as-option vs swaption · pre-registration

**Written and committed before any V3 backtest result was produced.** Branch
`feat/bvv-v3-basis-swaption`, based on `feat/basis-vs-vol-v1-qdb` (repaired data layer, PR #455;
V1 re-run, PR #456).

Source: **Citi Research, *US Rates Weekly — Summer lull*, 17 July 2015**, the "Futures" section.

---

## The strategy, as the note states it

> "Since the futures contract is unlikely to trade higher than the forward settlement price of the
> CTD, owning a futures bond net basis is like owning an option and hence, the net basis has a floor
> of 0. … Since a long basis trade is like owning an option, it is fair to measure its relative
> value by comparing it to a swaption. The gamma of a $100mm May37 basis (Long $100mm 5% May37s vs
> short 911 USZ5 contracts) is $420 and costs 4.2 ticks or $130K. For owning the same amount of
> gamma through a 1m25y swaption, it costs $187K, ie. approximately 1.4 times the cost of the May37
> basis."

Three mechanical claims, each of which V3 implements literally:

1. **The basis is an option.** Its cost is the net basis; its convexity comes from the CTD-switch
   option. The note's optionality analysis shifts the **forward yield as of the last delivery day**
   and uses **6m realized vol** for the distribution.
2. **The comparable is a matched ATMF receiver swaption** — expiry at the futures' last delivery day
   (5.5m for USZ5), tail matched to the CTD's maturity (25y).
3. **The decision rule is cost per unit of gamma.** 187/130 ≈ 1.44 ⇒ the basis is the cheaper way to
   own the same gamma ⇒ buy the basis.

## The signal

For an **ATMF** normal (Bachelier) swaption with annuity `A`, vol `σ` and expiry `T`:

```
price = A · σ · sqrt(T / 2π)          gamma = A / (σ · sqrt(2πT))
cost per unit gamma = σ² · T                       ← the annuity cancels
```

That the annuity cancels is what makes this robust: no curve, no notional convention, no
swap-spread assumption enters the swaption side of the ratio. For the basis:

```
cost per unit gamma = NetBasis$ / Γ_basis
richness = (σ² · T) / (NetBasis$ / Γ_basis)
```

`richness > 1` ⇔ the swaption costs more per unit of gamma ⇔ **the basis is the cheaper option**.
The note's own example sits at ≈ **1.44**.

`Γ_basis` is the second derivative of the delivery-option value with respect to a parallel yield
shift, by bump-and-revalue on `RVUtils/BasisVsVol/switch.py` (the same model V1 used). **The bump
size is fixed once at 5bp and frozen** — a second difference across a switch kink is unstable, and
choosing the bump after seeing results is a free parameter in disguise.

### Two degeneracies, guarded, and the guards are NOT searched

Both denominators can vanish, and each produces a signal that is not merely noisy but inverted:

| degeneracy | effect | guard (fixed, pre-registered) |
|---|---|---|
| `NetBasis → 0` or **negative** | basis looks infinitely cheap; a negative net basis inverts the sign | `net_basis_ticks ≥ 1.0` |
| `Γ_basis → 0` (no switch in reach) | basis looks infinitely expensive | `Γ_basis ≥ γ_min`, γ_min fixed |
| time-of-quarter | `σ²T` shrinks mechanically into delivery while wildcard gamma concentrates there — the grid would otherwise "discover" a days-to-delivery artifact | entries only when **21 ≤ days-to-delivery ≤ 120** |

These are **fixed at single values and are not grid axes.** A guard that is tuned is not a guard.
A negative net basis is also, on this repo's own evidence, a data-quality tell rather than a market:
the option floor is zero.

## The two arms — both pre-registered, neither chosen after the fact

The note's text and the instruction to build "ustf basis vs swaption" are two defensible readings.
Committing to one after seeing results would be selection, so both run and both are reported:

- **Arm A — long basis outright.** The note's literal trade: buy the basis when it is the cheaper
  option. The swaption enters only as the *yardstick*.
- **Arm B — long basis, short gamma-matched ATMF receiver.** The RV structure. Legs are
  gamma-matched **at entry, statically**; continuous re-hedging is a different strategy with a
  different cost model and is out of scope for this grid.

## The ablation, which is a kill condition in its own right

- **Arm C — cheap net basis alone**, no vol leg and no richness ratio. If Arm C matches A/B, then
  the swaption comparison — the entire content of the note — is decoration, and the honest name for
  the strategy is "buy cheap basis". This is the direct analogue of V1's raw-BNOC arm, and it is the
  question V3 exists to answer.

## Grid — 216 cells, fixed now

Per (root × arm), 36 configurations:

| axis | values |
|---|---|
| `entry_richness` | 1.10, 1.25, 1.50, 2.00 |
| `max_hold_days` | 10, 21, 42 |
| `take_profit_ticks` | none, 2.0, 4.0 |

`exit_richness` fixed at **1.00** (fair value). Roots **ZB** (the note's own contract, USZ5),
**ZN**, **UB**. Arms **A** and **B**. → 3 × 2 × 36 = **216 cells**, deliberately the same trial
count as the V1 re-run so the two E[max | null] figures are directly comparable.

Swaption tail is **duration-matched to the CTD** by interpolation on the cube's tenor axis (there is
no 25Y node; 20Y and 30Y bracket it). Tail choice is reported as a **sensitivity**, not searched.

Execution lag **1 day**. Both legs open and close together; forced close at the panel roll, reusing
V1's roll guard — a swaption held against no basis is not the trade. Costs: basis round trip in
32nds (0.5, as V1), **and a separate swaption round-trip cost in normal-bp of vol** — an RV trade
costed on one leg only flatters itself.

## Kill conditions — verbatim from V1

Alive requires **all** of:

1. deflated Sharpe > **0.95** against the realised trial count;
2. survives **2×** costs;
3. sign-flip permutation percentile > **0.95**;
4. top-3 trade share < **0.60**;
5. **the ablation**: Arm C must not match the full signal.

## Validation before any backtest

The note is from **July 2015**; the swaption cube starts **2015-10-08**, so reproducing its market
numbers is impossible and will not be attempted. What *is* pinned, by unit test, is that V3's
formulas reproduce **the note's own arithmetic from the note's own stated inputs**:

- 4.2 ticks on $100mm → **$131,250** (note: "$130K");
- the swaption/basis cost ratio **187/130 ≈ 1.44** recovered through V3's own functions;
- `cost_per_gamma = σ²T` verified against `RVUtils/BasisVsVol/bachelier.py` numerically, not just
  algebraically.

Plus, carried over from V1: the P&L identity, "a roll is never a return", and a deliberate-lookahead
detector.

## Known approximations, declared now

1. **Sticky-ATM marking.** The vol cube is ATM-only before the smile vintage, so a short receiver
   that has drifted off the money is marked with the current ATM vol at the original strike. Stated
   as a limitation, not hidden.
2. **The forward-rate source** for that marking is chosen on measured coverage 2019–2026. If only a
   Treasury-yield proxy is available, it embeds swap-spread moves into the very leg being tested and
   will be reported as a limitation with that caveat explicit.
3. **Static gamma matching** at entry only.

## Predictions, recorded so the result can embarrass me

- **Arm C will be hard to beat.** My prior is that most of any P&L comes from "the net basis is
  cheap", not from the swaption comparison — i.e. the ablation fires, as it did for V1's
  delivery-option model.
- **The richness ratio will spend most of its time > 1**, because the basis genuinely is a cheap way
  to own convexity most of the time; if so, the signal is nearly always "on" and the entry threshold
  becomes a lookback filter rather than a valuation signal.
- **Most likely outcome: dead**, on the same structural grounds as V1 and V2 — a winner below
  E[max | null].
- **The one thing that could surprise me** is 2020 and 2022–23: large CTD-switch optionality with
  violently repriced vol. If V3 has an edge anywhere it should be there, and it should show up as a
  *level* shift across cells rather than one lucky configuration.
