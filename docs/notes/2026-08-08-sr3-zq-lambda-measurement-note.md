# Measurement note: the SR3 copula coordinate (λ), and the OI bug underneath it

Branch `feat/sr3-zq-lambda`, worktree `../ARBS-lam`. Every number here is computed by code in
this branch; nothing is transcribed from an earlier run.

Reproduce with:

```
python notebooks/rv/sr3_zq_lambda_smoke.py --zq-from published    # the baseline gate, 21/21
python notebooks/rv/sr3_zq_lambda_backfill.py --symbols SFRZ26 --start 2026-01-01 \
       --end 2026-08-07 --auto-window --out notebooks/data/sr3_zq_lambda/z26.csv
python notebooks/rv/sr3_zq_lambda_analysis.py --panel notebooks/data/sr3_zq_lambda/z26.csv
```

---

## 0. The open-interest bug: found, and it is not the spelling

**The reported cause is not the cause.** `openinterest` at `BarchartFetcher.py:1310/:1335` and
`openInterest` at `:1579/:1670` live in different namespaces — the first is a normalized
history column, the second a Barchart core-api request field — and `_pricer_open_interest`
(`STIRFutureOptionMDP.py:2555`) already accepts all five spellings. Neither is on the path the
smile takes.

**The actual cause**, found by reading the on-disk raw-EOD cache rather than by inference:
Barchart's `queryeod` feed reports `Open Interest = 0` on **the last bar of every frame**.
Not for options specifically — for everything. `SQZ26|9537P` reads 85,356 / 85,356 / 90,104 /
90,104 / 89,604 / **0**; the SQZ26 *future* reads 1,714,534 / 1,729,546 / **0** on 1.7 million
lots. A contract that expired in 2023 does the same thing on its last bar. The exchange
disseminates a session's open interest the following morning, so the newest bar has none.

That makes the failure exact and total. `SFRImpliedDistribution()` defaults to
`raw_market_open_interest_min=100.0`; a chain fetched for the newest session reads 0 on all 75
strikes; the screen rejects the entire chain; and the `min_strikes` guard substitutes a **SABR
model density**, which is unimodal by construction. It does not degrade the answer to a
bimodality question — it manufactures it. `force_refresh=True` cannot help, because the
refetched newest bar has no open interest either.

The "confirmed on 07-31 too, so it is not a T+1 lag" reading was reasonable and wrong: at the
time of that test, 07-31 *was* the newest bar in the cached frames. Verified directly — with
the frames now running to 08-07, `fetch_sabr_smile` for 07-31 and 08-06 returns **51 of 54
strikes with OI ≥ 100**.

Fixed in three places (`1800c6fa`):

- `BarchartFetcher.blank_unpublished_open_interest` surfaces the unpublished last bar as NaN.
  Only the last bar, and only when an earlier bar carries non-zero OI, so a strike that
  genuinely has none is untouched and the blanked bar refills next session. Applied at the EOD
  fetch chokepoint before the cache write, and again on read so pre-existing entries heal.
- `smile_to_rnd_input` skips an open-interest screen that cannot discriminate. When no leg has
  usable OI, the screen does not filter the chain, it deletes it. `strike_source` becomes
  `"market_jpm_no_oi_screen"`. Present-but-tiny OI is a real liquidity signal and still bites.
- `ImpliedDistributionSnapshot.strike_source` / `.is_model_density` make the model-vs-observed
  distinction machine-readable, because a warning string is missable and this one was missed.

Verified on the exact repro — `SFRZ26`, `as_of=2026-08-07`, `force_refresh=True`, default
config: `is_model_density=False`, 68/75 legs reporting OI as *unknown* rather than a
fabricated zero. 24 regression tests, both halves mutation-tested (9 fail when the fix is
reverted).

**Residual, and it is a vendor limit not a bug:** the OI screen can never run on the current
session. For any `as_of` that is not the newest vendor bar it works normally, which is every
backtest. For live use, screen on T-1 open interest.

---

## 1. The baseline reproduces exactly — on the published strip

`sr3_zq_lambda_smoke.py --zq-from published`: **21 of 21 checks pass.**

| quantity | computed | measured baseline |
|---|---|---|
| marginals sep/oct/dec/jan | 0.4200 / 0.2500 / 0.4313 / 0.1687 | 42.0 / 25.0 / 43.1 / 16.9 |
| cumulative hikes through Dec | 1.1013 | 1.101 |
| V/X/F fly reconstruction | −6.017bp vs market −6.000 | −6.02 vs −6.00 |
| ZQ-implied window rate | 3.9305% | 3.9305% |
| basis + term premium | +5.4465bp | +5.45bp |
| comonotone P | (.569, .011, .170, .250), wings 81.9% | identical |
| independent P | (.247, .449, .258, .045), wings 29.3% | identical |
| λ_wing | **0.520** | 0.54 |

Three things the gate forced out that would otherwise have stayed silent:

**Marginals must be anchored on meeting-free months.** The repo's `build_fedwatch_tree` solves
October by walking *back* from November, re-deriving the pre-meeting level from ZQV26 — a month
only 4/31 at the new rate, so the 27/31 lever amplifies any error about sevenfold. It returns
p(oct) = **0.276** where the clean chain returns **0.250**. `clean_anchored_jumps()` solves a
meeting month from the next meeting-free month whenever one exists and falls back to its own
partial-month average only when the following month also holds a meeting. That is the
published method, and it reproduces it to 4 decimal places.

**The off-lattice mass has to go somewhere.** The move count cannot be below 0 or above n, so
mass outside the lattice is not a state. Leaving it out gives an observed law summing to 0.83
compared against bounds summing to 1.0. Absorbing it into the nearest end atom is the
like-for-like reading and is what recovers 0.54; the strict reading gives 0.19 and the
renormalised one 0.36. All three are emitted; **absorbed is the headline**.

**The ZQ input moves the answer by more than the signal's own daily variation.** The serff EOD
cache and the published strip disagree by 0.5–1.0bp on the 2026-08-07 back months (Aug and Sep
agree exactly), which alone moves λ_wing from 0.520 to 0.480. **1bp of ZQ back-month noise is
worth ~0.04 of λ.** Whatever ZQ source is used must be used consistently.

---

## 2. Q1 — does the ±0.44 error bar on the variance route reproduce?

**Yes, and the route is worse than that: it is not merely noisy, it is unidentified.**

Over 19 admissible SFRZ26 sessions (Apr–Aug 2026):

- λ_var mean **+3.35**, and **100% of sessions sit above the comonotone bound**.
- Sensitivity to the non-meeting-vol assumption: **±0.65 per ±10 bp/yr** (predicted ±0.44).
- Non-meeting vol *needed just to bring λ_var on-scale*: mean **66 bp/yr**, range 54–80.

That last line is the decisive one. Total ATM normal vol is ~70bp/yr. To make the variance
route return a λ inside [−1, +1] you must assume a non-meeting component that consumes almost
the entire variance budget, leaving nothing for the meetings. On 2026-08-07, `var_observed` =
2387bp² against a comonotone bound of 1080bp² — the RND carries more than twice the variance
that *any* coupling of the ZQ marginals can produce, **at zero assumed non-meeting variance**.

**Verdict: the variance route is dead. Shape-only, as pre-committed.** This is a legitimate
result, not a failure — and it is a stronger statement than the ±0.44 conjecture, because it
does not depend on the size of the assumption, only on its existence.

*(Read carefully: this is not the HARD arbitrage tier. `var_observed` includes all non-meeting
variance; the hard tier compares the meeting-attributed variance, which is exactly the
quantity this section shows is not identified.)*

---

## 3. Q2 — is 0.54 the favourable end of the range?

**No. It is close to the centre.** On the 19 admissible sessions:

| statistic | λ_wing (absorbed) |
|---|---|
| mean | +0.596 |
| sd | 0.140 |
| min / max | +0.324 / +0.981 |
| median | +0.594 |
| **percentile of 0.54** | **37th** |

The published session was not cherry-picked in the direction feared. Two observations that
matter more than the percentile:

- **λ_wing never goes near zero.** The minimum over the sample is +0.32. The market has priced
  materially comonotone Fed behaviour on every admissible session measured. If λ is a
  mean-reverting quantity, it reverts around ~0.6, not around the independent null.
- **Trough depth and wing mass are different statistics.** 2026-08-07 had the deepest trough in
  the original eight-session window (0.54 trough/peak) but sits *below* the median on λ_wing.
  The two 0.54s in the original note are a coincidence, not one quantity seen twice.

**Modal count on admissible sessions: 12 unimodal, 7 bimodal.** Once the fit gate is applied,
bimodality is the minority — but by the one-way validity argument (convolution with a
log-concave kernel is variation-diminishing, so smoothing destroys modes and never creates
them) a unimodal session does not refute the lattice, and an observed λ is a lower bound on
the true one. The asymmetry is respected in both directions here: the bimodal sessions are
evidence, the unimodal ones are not counter-evidence.

**The fit gate is the binding constraint on everything.** Only **29%** of successfully extracted
sessions (19 of 65) clear |forward_residual| < 1bp, pre-normalisation mass ≤ 1.02, ghost ≤ 5%
and cross-strike spread ≤ 0.60. That is the real limit on this programme — not the idea.

---

## 4. Q3 — do the modes stay put while the forward moves?

**Not yet answerable, and I am not going to answer it from 7 points.** The mode-location
regression needs bimodal *admissible* sessions; SFRZ26 alone supplies 7, below the n ≥ 10 floor
the analysis enforces. The multi-contract panel required for this is still warming its option
chains. The regression is implemented (`sr3_zq_lambda_analysis.py`, Q3) and reports, with
contract fixed effects and Newey-West errors:

- `mode_hi ~ forward` and `mode_lo ~ forward` — β ≈ 0 is the lattice signature.
- `pin_hi ~ forward` — **the control that the original framing omits.** The atom pins are
  ZQ-anchored, so if the pins also move one-for-one with the forward, a flat mode-vs-forward
  β says nothing at all. The pin regression is what separates "the modes are pinned" from
  "nothing here moves with the forward".

---

## 5. Q4 — the 50bp question (pre-registered kill test)

The binary 0/25 framing is what makes ZQ pin each marginal *exactly*. Admit a 50bp move and ZQ
gives only the **mean** of each marginal: one equation, two unknowns. Marginal shape and copula
stop being separately identified, and size uncertainty is booked as dependence.

Measured, by rebuilding the comonotone and independent bounds on three-point {0, 25, 50}
marginals that keep ZQ's mean exactly (`_copula.categorical_*`, `three_point_marginal`):

| 50bp share of the expected move | mean λ_wing | shift vs binary |
|---|---|---|
| 0% (binary) | +0.596 | — |
| 10% | +0.543 | −0.053 |
| 25% | +0.453 | −0.143 |
| 40% | +0.348 | −0.248 |

**The direction of the bias is confirmed: the binary reading overstates λ.** A quarter of the
expected move arriving in 50s is worth −0.14 of λ — the same order as the entire cross-session
standard deviation (0.140). So the *level* of λ is not safe to size off without a view on move
size.

**But the kill criterion passes.** Rank correlation between the binary λ and the 25%-50s λ is
**0.993**: the ordering across sessions is preserved. A signal that trades the standardised
z-score, not the level, survives this contamination. That is exactly why the pre-registration
fixed entry on z rather than on the raw level, and it is the single most important reason that
choice was made in advance.

---

## 6. Cross-strike consistency — the RV that lives *inside* the copula

λ_wing is one number fitted to a whole surface. Every atom is linear along the mixture family,
so a density that lies inside the one-parameter family returns the *same* λ from each atom
independently. The spread across atoms is therefore a direct measure of dislocation: the market
cannot be coupling at two rates at once.

- 2026-08-07: per-atom λ = **[0.473, 0.546, 0.504, 0.643]**, spread **0.170**. Coherent.
- Across the sample: spread median **0.598**, p90 **1.15**, max **1.41**.

So the surface is *sometimes* coherent and often not. When the spread is wide, a headline λ is
an average of readings that contradict each other, and the signal is suppressed rather than
qualified (`signal_lambda_dependence`, `atom_spread_max=0.60`). This is the cleanest candidate
for genuine copula-vs-copula RV in the framework, and it is measured here for the first time.

---

## 7. On what can and cannot be traded here

**There is no copula-versus-marginal RV, and this is structural, not practical.** Sklar's
theorem makes the decomposition orthogonal: any copula pairs with any marginals and the result
is a valid joint law. There is no no-arbitrage relation binding them, so no exchange rate and
no convergence. The framework respects this by splitting into exactly two tiers — a HARD tier
where the meeting-attributed variance leaves `[Var_min, Var_com]` (a genuine static arbitrage,
`TradeFlagKind.LAMBDA_ARBITRAGE`) and a SOFT tier where λ is a view against a prior
(`LAMBDA_DEPENDENCE`). Nothing in between is claimed.

Three axes that *are* real, in descending order of what this work supports:

1. **Cross-strike λ** (§6). Copula-vs-copula, measured, and the only one with a number attached.
2. **Term structure of dependence.** λ on the near meeting cluster versus the far one.
   Dependence should be higher near-dated — one decision, clearly framed — and decay out the
   strip. Falls out of the multi-contract panel for free once it lands; not yet measured.
3. **Dispersion.** SR3 is the index (it sees the *sum*); ZQ/SR1 are the constituents. Long an
   SR3 straddle against a vega-matched basket of constituent straddles, each delta-hedged in
   its own future, is long dependence with the marginals cancelling by construction. The
   binding constraint is real and known in this repo: SR3's IMM-to-IMM window does not align
   with ZQ's calendar months (`covering_zq_months(SR3Z26)` = ZQZ26 at 0.516, ZQF27 at 1.0,
   ZQG27 at 1.0, ZQH27 at 0.516), so a stub basis is carried, and the constituent option leg is
   thin. Not attempted here.

---

## 8. What is built

| deliverable | state |
|---|---|
| OI bug fix + 24 regression tests, mutation-tested | done, `1800c6fa` |
| `_copula.py`: comonotone / independent / min-variance LP / mixture family / categorical | done, 51 known-answer tests |
| `_lambda_signal.py`: meeting sets, clean anchoring, atoms, modes, the coordinate | done |
| `lambda_dependence` + `lambda_arbitrage` signals, wired through `SignalRecord` | done |
| Baseline smoke gate | done, 21/21 |
| Multi-session λ panel + analysis | done for SFRZ26; multi-contract panel warming |
| QDB backtest fork, pre-registered | done; run pending the panel |
| Mode-location regression | implemented; needs the multi-contract panel |

Two defects in `famb_fly_qdb.py` are fixed in the fork rather than inherited, and both are
worth knowing about in the parent: its delta hedge is unwound in the step it opens (the engine
processes adds before unwinds and `pop_matching` has no "opened before now" filter), so the
hedged run carries no hedge while still accruing hedging cost; and it has no force-flatten, so
a position open on the final grid state never reaches `closed_positions_log`.
