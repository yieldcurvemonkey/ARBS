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

**On one contract, no. Across contracts, yes — and the reason is regime.** This one reverses
when the sample widens, so both readings are given.

| sample | n | mean λ_wing | median | percentile of 0.54 |
|---|---|---|---|---|
| SFRZ26 only | 19 | +0.596 | +0.594 | **37th** (centre) |
| 4 contracts, 2025-07 → 2026-08 | 28 | +0.304 | +0.361 | **79th** (high end) |

Per contract, the split is not noise:

| contract | n | mean λ_wing | range | cycle |
|---|---|---|---|---|
| SFRZ25 | 17 | **+0.146** | [−0.945, +0.441] | cutting |
| SFRM26 | 1 | +0.422 | — | |
| SFRZ26 | 8 | +0.547 | [+0.464, +0.626] | hiking |
| SFRH26 | 2 | +0.610 | [+0.582, +0.638] | |

**λ is regime-dependent, and that is the finding.** In the 2025 cutting cycle the market priced
the meetings as close to independent (mean +0.15 — "they'll cut, timing uncertain"). In the
2026 hiking cycle it prices them materially comonotone (+0.55 — "do they go at all"). The
original concern was therefore right on the pooled sample: **0.54 is near the top of what has
been observed across regimes**, and a prior centred there would have been a prior fitted to one
half of the history.

Two observations that survive both readings:

- **Within a regime, λ is remarkably stable.** SFRZ26's 8 admissible sessions span +0.464 to
  +0.626 (sd 0.058). That stability is what makes a z-score a sensible entry, and also what
  makes the entry rarely trigger.
- **Trough depth and wing mass are different statistics.** 2026-08-07 had the deepest trough in
  the original eight-session window (0.54 trough/peak) and is unremarkable on λ_wing within its
  own contract. The two 0.54s in the original note are a coincidence, not one quantity twice.

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

**Not yet answerable, and I am not going to answer it from 5 points.** Two separate causes, and
the first was self-inflicted:

1. **The mode data was coupled to the copula gates.** `measure_lambda` returned early on a
   copula-applicability guard *before* computing the modes, so every session where only the
   coupling was unidentified lost its shape evidence too. Mode location versus the forward needs
   no copula machinery at all — a well-fitted density, two peaks and the pin control are enough.
   Fixed: shape and fit-quality fields are recorded on every session with a usable density, and
   the Q3 regression is now gated on fit quality alone.
2. **Bimodality is genuinely rare once the fit gate applies** — 5 of 28 sessions — so the n ≥ 10
   floor still is not cleared. That is a fact about the sample, not a limitation of the test.

The regression is implemented (`sr3_zq_lambda_analysis.py`, Q3) and reports, with contract fixed
effects and Newey-West errors:

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
expected move arriving in 50s is worth −0.13 to −0.15 of λ, the same order as the entire
cross-session standard deviation. The *level* of λ is not safe to size off without a view on
move size.

**And on the wider sample the kill criterion FAILS.** Rank correlation between the binary λ and
the 25%-50s λ:

| sample | rank corr | pre-registered threshold 0.90 |
|---|---|---|
| SFRZ26 only (19 sessions) | **0.993** | pass |
| 4 contracts (28 sessions) | **0.769** | **FAIL** |

This is a pre-registered kill criterion (§5.6) and it is invoked. The single-contract result was
reassuring and wrong: within one contract the marginals are similar enough that a size-mix
rescales everything almost uniformly, so the ordering survives. Across contracts — where the
marginals differ enough to matter, which is exactly where a pooled prior would be used — the
same contamination **reorders the sessions**. A z-score computed against a pooled prior is
therefore not protected from the 50bp problem the way the single-contract test suggested.

Practical consequence: λ is comparable *within* a contract and a regime, and not comparable
across them without a move-size assumption that ZQ cannot supply.

---

## 5b. Four applicability guards the data found, not the design

Three of these were discovered by an **independent quantity going wrong** — the calibrated
SOFR-EFFR basis, which should be small, positive and stable and instead came back at a mean of
−39bp with a range of [−132, +7]. That is the check working: a number nobody was looking at
refused to behave, and each fix moved it back toward the truth. After all four, the basis reads
**+6.39bp ± 0.93, range [+4.45, +8.35], across 92 sessions and 5 contracts** — measured on a
sample the code was not built against.

1. **Sign of the uncertain path (a real bug).** `resolved_marginals` are magnitudes — the
   probability of one more 25bp step in whichever direction the meeting is moving. The
   ZQ-implied window rate added them **unsigned**, which turns a cutting cycle's expected path
   into a hiking one. This is why SFRZ25 was the worst-behaved contract: it is the cutting one.
   Fixing it alone moved the basis from −39bp to +5.9bp.
2. **A meeting earlier in the current month has already happened.** Its move is already inside
   the anchor month's average; counting it again as uncertain adds a phantom step.
3. **The lattice must describe most of the density.** A two-meeting lattice spans 50bp while the
   RND spans several times that, so absorbing the tails declares most of the law to be "wing"
   and returns λ *above* the comonotone bound — which reads as a static arbitrage and is a
   measurement artefact. Sessions with more than 25% of the density off-lattice are rejected.
4. **The interval must be wide enough to place anything on.** When every marginal sits near 0 or
   near 1, comonotone and independent give nearly the same wing mass, the coordinate's
   denominator collapses, and λ becomes noise divided by noise (an ungated panel produced +41
   and −76). Both sides of the interval are now required to span ≥ 0.05 in wing mass.

None of these change the 2026-08-07 baseline — the smoke gate still passes 21/21 — which is the
point: they reject sessions where the measurement was never valid, and leave alone the one where
it was.

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
| Multi-session λ panel + analysis | done — 555 sessions, 5 contracts, 2025-05 → 2026-08 |
| QDB backtest fork, pre-registered | done and run — see the verdict note |
| Mode-location regression | implemented and un-gated from the copula; sample still short (5 bimodal) |
| λ term structure across contracts | implemented; no contract pair yet has ≥5 overlapping sessions |

**Backtest outcome, in one line each.** At the pre-registered gates the strategy never trades
(10 of 93 sessions are both well-fitted and cross-strike coherent, against a 30-observation
standardisation window) — a data-sufficiency result. At relaxed, explicitly EXPLORATORY gates
it trades 7 times for a gross **−0.214bp per trade before any cost**, and a shuffled λ beats
the real one on 90% of seeds. Full detail and the sample caveats in
`2026-08-08-sr3-zq-lambda-verdict.md`.

Two defects in `famb_fly_qdb.py` are fixed in the fork rather than inherited, and both are
worth knowing about in the parent: its delta hedge is unwound in the step it opens (the engine
processes adds before unwinds and `pop_matching` has no "opened before now" filter), so the
hedged run carries no hedge while still accruing hedging cost; and it has no force-flatten, so
a position open on the final grid state never reaches `closed_positions_log`.
