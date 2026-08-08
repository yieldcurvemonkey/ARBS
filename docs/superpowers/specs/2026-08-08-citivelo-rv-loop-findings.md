# Citi Velocity RV loop — findings

**VERDICT (session 1, complete): NOTHING ALIVE — every registered hypothesis graded and
killed, three families killed at gate, on validated 20-year multi-currency data with a
measured cost line, and the adversarial checker killed the maker's last positive claim.
H13 grail-conditional (17 arms, 3 currencies): DEAD — median +0.0bp, DSR 0.000 everywhere;
its placebo-certified wording was withdrawn by the rival check (raw spread-z reproduces 137%
of the ex-carry). H16 z-fade: dead at gate. H16b sandwich basis: DEAD — median −1.35bp,
steamroller confirmed. H14-graded (Peter's manufactured package): the "+9.9bp at 1×" headline
was a CARRY DOUBLE-COUNT found by the checker (V-SV-14G-KILL) — corrected, the fly's net
contribution is **−22.2bp full-sample at 1×** (negative at every multiplier), +14.1bp
post-2017; what survives is the belly-received solve, genuine risk-reduction, and the
roll-based gate counterfactuals. F1 and F2: dead at gate. Twelve-of-twelve one more time:
every defect found this session flattered the maker, and the maker≠checker machinery caught
them. The loop continues per L-0029; the machine, the ledger, the measured costs, and one
repo-wide pricing fix are the session's durable output.**

**Predecessors:** `2026-08-08-citivelo-rv-loop-design.md` (+ ledger
`docs/superpowers/ledgers/2026-08-08-citivelo-rv-loop-ledger.jsonl` — the row-level record),
`docs/superpowers/plans/2026-08-04-strikeless-vol.md` (PR #392, continued here).

This skeleton is committed before results per the addendum ordering rule (a findings doc
written before the trial count is final publishes a count later work invalidates). Sections
fill in grading order; the DSR trial count is quoted only in the final revision.

## What went right

- **The gates killed cheaply.** Four families/expressions died before any backtest could
  flatter them: H16 z-fade (oracle 0.5–1.8× a *measured* boat), F1 surface residual (tradeable
  cells a coin flip; the "winners" live in the dealer-extrapolated corner — a marking-model
  mirage caught at gate, not post-hoc), F2 gamma IV/RV (no conditioning signal; unconditional
  premium mean-zero with −95-vol-bp tails), JPY grail arms (0–1.1% occupancy over 20 years).
- **The checker discipline worked twice on the maker's own claims.** A calibration run killed
  a fabricated memo on the planted defect *and* on arithmetic it found unprompted (L-0025);
  then the rival check (L-0030) withdrew the maker's strongest surviving claim — the "grail
  state times convexity harvest" wording — by showing occupancy-matched raw-spread-z states
  reproduce a median 137% of the ex-carry at 0–52% day overlap. Every defect that mattered
  favoured the hypothesis, again; adversarial specificity found them, again.
- **A measured cost line replaced an assumed one** (CM-1: 643 days of SDR swaption prints vs
  the cube mid; ATM half-spread 0.17–0.71 annual bp by expiry, upper bound; two SDR
  convention discoveries: forward premiums, UPI package-total duplication).
- **A live repo-wide pricing bug fixed**: the QDB direction-blind signed-bpv seam (buy ≡ sell
  since at least 2026-07-30), root-caused to one line, pinned by tests, mirror verified.
- **The 20-year multi-currency data spine validated**: 2019/2023 published-table tie-outs
  (spreads to ~1bp; Γ matches Citi's, roll convention ~2× open), GS-overlap basis stable, the
  holiday-ghost defect found and filtered before grading.
- **The PM's construction measured, then corrected by the checker**: the roll-based gate
  numbers stand (occupancy 18.6%→39.9%, 82% median-bleed coverage, belly received on 948/950
  days, risk-reducing) — but the graded "+9.9bp net at 1×" was a carry double-count
  (V-SV-14G-KILL); corrected, the fly is net −22.2bp full-sample and +14.1bp post-2017, the
  gamma-retention figure is retracted as uncommitted, and the maintenance line was itself
  understated by a dedup nondeterminism. The strongest surviving statement is direction-only:
  the fly's post-2017 carry contribution is real and roughly half what the maker first
  published.

## Machine (built 2026-08-08, session 1)

- Worktree `ARBS-rv`, branch `feat/citivelo-rv-loop` off main 33fe6981; baseline fast gate
  4159/0 (pure main); sv merge Task 29 complete, sv suite 544/0.
- Ledger, checker charter, reference corpus committed; three reading fan-outs (10 agents)
  distilled the cost line + framework corpus.
- **Repo fix shipped:** the QDB direction-blind signed-bpv seam (kink-v2 §6) — root-caused to
  `resolve_pricable` double-signing signed rateslib notionals; fixed, pinned, mirror verified
  live. See ledger L-0012.
- Data: banked par grids 2005+ × 5 ccy to 50Y; EOD curve warms extended (USD full 2005–2026;
  JPY 2006+; GBP by concurrent session; EUR/CAD in flight); cube 2,699 days (ATM 2015-10+,
  full smile 2020-01-24+).

## Gates (run FIRST, before any graded number)

| gate | spec | outcome |
|---|---|---|
| (a) 2019-05-08 Figure-7 tie-out | L-0009/L-0017 | **PASS** — spreads to −0.8bp median, Spearman BE 0.958, carry sign 7/8 |
| (b) 2023-06-08 steepener-carry tie-out | L-0009/L-0017/L-0020 | **FAIL on tolerance → root-caused** — spread exact (−51.5); Γ validated; roll convention ~2× (unresolved, sign-invariant internally) |
| (c) GS-vs-Citi basis stability 2017–2026 | L-0009/L-0017 | **PASS** — spread basis median −0.2bp, rolling-median range 4.4bp |
| Data integrity | L-0018 | holiday-ghost curves found (990 dup rows) → filter in all engines, panels rebuilt |
| H15 aging | L-0013 | **NOT falsified** — pure-aging Γ retention 1.01–1.06× to 5y (curve-held-fixed) |
| H14 carry-engine gate | L-0024→V-SV-14/V-SV-14G-KILL | gate numbers stand; graded headline KILLED (carry double-count) — corrected fly net −22.2bp at 1× full-sample, +14.1bp post-2017 |
| H13 occupancy | L-0016 (JPY), USD detector | USD pond exists (10–50% by pair); **JPY pure-flattener arm DEAD at gate (0–1.1%)** |
| H16 z-fade basis pond | L-0019 | **THIN** (0.8–1.8× boat) — expected DEAD at grading |
| H16b sandwich pond | L-0023→V-SV-16B | gate OPEN → graded **DEAD** (the wedge proxy did not translate) |
| CM-1 measured swaption cost line | L-0022 | **DONE** — 0.17–0.71 annual bp ATM half-spread by expiry (upper bound), checker 3/3 |
| F1 surface residual | L-0028 | **DEAD AT GATE** — tradeable cells coin-flip; "winners" are the extrapolated corner |
| F2 gamma IV/RV | L-0032 | **DEAD AT GATE** — no conditioning signal; unconditional mean-zero with −95bp tails |
| H14G mechanism columns | V-SV-14G-KILL | **KILLED by the checker** — carry double-count; corrected −22.2bp at 1×; Γ-retention figure retracted (uncommitted); belly-received + risk-reduction survive |
| H13 rival check | L-0030 | spread-z reproduces 137% of grail ex-carry → mechanism wording withdrawn |
| Checker calibration | L-0025 | **PASSED** — planted defect + unprompted fabrication both killed |
| Merged-tree fast gate | L-0033 | **4,766 / 0 failed** (baseline 4,159/0) |

## Graded hypotheses (pre-registered in the ledger before their numbers)

- **H-SV-13** grail-conditional entries — **DEAD** (V-SV-13F: 17/17 arms, median +0.0bp,
  DSR 0.000; mechanism wording withdrawn per L-0030)
- **H-SV-14 / H-SV-14G** manufactured package — **DEAD; graded headline KILLED by the
  checker** (V-SV-14G-KILL: the fly ledger double-counted carry; corrected net −22.2bp at 1×
  full-sample, +14.1bp post-2017; maintenance understated by a dedup nondeterminism;
  Γ-retention retracted as uncommitted; both registrations closed with terminal rows, the
  dropped 2-7-29/5:1 reports stated in V-SV-14)
- **H-SV-16** z-fade — **DEAD AT GATE** (V-SV-16, clean panel, measured boat; never backtested)
- **H-SV-16B** sandwich basis — **DEAD** (V-SV-16B: median −1.35bp, steamroller −$0.7–1.2M)
- **F-ING** EUR forward-strip residual screen — built + gated (L-0015); graded run BLOCKED on
  the fair-value-construction fidelity gap (our PC1 residual ≠ ING's; their 2020-01-15 example
  does not reproduce) — parked, not silently rescoped

## Deaths

- **H13 grail-conditional entries (V-SV-13, 17 pre-registered arms).** DEAD at the registered
  spec. The number that killed it: **DSR 0.000 at n_trials = 3,905** on every arm, median
  across arms ≈ 0. Best arm USD 15y5y/20y10y: +106.7bp net@1× over 116 episodes (+0.92/trade,
  NW t 1.23). GBP arms −816/−517bp: the state chatters at the carry-zero boundary (~3-day
  episodes), so in-state carry ≈ 0 *by construction* while entry/exit churn burns 1.5bp per
  crossing. JPY arms gate-dead (occupancy 0–1.1% over 20 years). What survives: the state
  genuinely times convexity harvest (ex-carry placebo p ≤ 0.014 on 7 USD arms; no post-exit
  steamroller), and always-on flattener profits are first-half (2005–2016) concentrated —
  which *reconciles* the +157…+296bp 21-year controls with the sv-on-GS all-DEAD verdict on
  its 2017+ sample. Regime, not contradiction.
- **H16b sandwich basis trade (V-SV-16B, 4 pre-registered combos).** DEAD. The number:
  **median −1.35bp across combos**, best +23.1bp/19 trades at placebo p 0.075, and worst
  episodes −$0.7–1.2M on ~$30k-vega books. The gate's 15–35× wedge pond was a state-margin
  proxy; premium-marked collection is a fraction of it, and the sandwich exits *with* the vol
  spike (63-day realized lags), hitting the short straddle first — the famb insurance lesson,
  reproduced in swaption space.
- **H16 z-fade (L-0019/V-SV-16).** Killed at its oracle gate: pond/boat 0.8–1.8× with harvest
  historically 10–30% of oracle. Never backtested — the gate said stop.
- **F-ING cross-sectional curve RV (V-FING, cycle 2).** Dead at its fidelity gate — the v2
  cross-sectional construction closed the v1 gap (frontier R² 0.03→0.68/0.78) but no single
  realization passes all three registered prongs, and the blockers are structural (21–29Y
  par-interpolation sawtooth; ESTR-OIS grid vs ING's 2020 EURIBOR curve).
- **F3 liquid-tenor cross-sectional RV (L-0036, cycle 2).** Dead at gate with the cleanest
  numbers in the program: 303–686 genuinely independent episodes per currency, median
  dislocation 2.2–3.4bp, median 63-day reversion +0.81…+1.14bp vs a 1.0bp round trip — the
  pond equals the boat at the *oracle* median, before the signal-harvest haircut. The
  fly-mean-reversion sentence, transplanted to swaps.
- **F4 FOMC event windows (L-0037).** No pond exists: decision days move the ultra-long
  spreads at 0.92×/0.58× ordinary days — which independently CONFIRMS the framework's
  expectations-wash premise.
- **F5 expiry-kink vol flies (L-0038).** Oracle-median reversion (+0.61/+1.08bp at 21bd)
  under the measured 3-leg round trip (1.38/1.68bp); 30% of fires clear it.
- **F6 intraday (L-0039).** The STIR arithmetic reproduced in swap space: SV spreads move
  0.07–0.10bp/hour against a frequency-invariant 1.5bp round trip; every RV structure under
  the boat out to a week. Only the 10y outright clears — a directional pond, not RV.

## DSR accounting

Convention: each verdict was graded at the family count current at its grading time
(V-SV-13 at 3,905; V-SV-16B at 3,909; V-SV-14G at 3,910); the final session-1 count is
**N_sv 3,888 + 22 loop trials = 3,910**. Recomputing H13 at the final count changes nothing
(DSR 0.000 either way). Gate-killed families consumed no trials (no selection occurred); the
H16 registration's 4 budgeted trials were released unconsumed.

## The structural finding (L-0029)

At N ≈ 3,900 inherited trials, DSR > 0.5 is out of reach for any carry-class book — Citi's own
published Sharpes for this family are 0.05–0.35, our best measured 0.28. The bar is the bar;
what it implies is family selection: the loop's remaining realistic ALIVE candidates need many
independent periods with high per-period Sharpe (intraday minute-curve constructions,
cross-sectional many-bet books, event windows), not more EOD carry variants.

## Current state worth knowing (2026-08-07/08 close)

- EUR 15y5y/20y10y: grail occupancy **76.9%** over 21y; today BE/RV **0.61** at carry
  −0.7bp/y — the closest live analogue anywhere to Citi's 2019 USD entry (BE/RV 0.42).
- USD: all pairs carry-negative today; BE/RV 0.96–1.72; 20s30s spot inverted.
- JPY 10y10y/20y10y at −3.7bp, flattest in a year — the PM's Japan-flattener thesis is a
  multi-year expectations-wash argument, not a current BE/RV entry state (both recorded).

---

# Session 2 (2026-08-08) — the QDB backlog, and what making it executable found

**Verdict first: no verdict changed, and three of them got worse.** The standing rule asked for
`QueryDrivenBacktest` implementations of the graded strategies as executed notebooks. Building
them forced conventions into the open that the panel engines had left implicit, and every one
of them had been flattering its strategy. Branch `feat/citivelo-rv-loop-s2`, PR #405.
`trials_total` is unchanged at **22** — these are implementations of DEAD strategies.

## The continuation contract, items 1 and 2

**famb STRG forward run — BLOCKED** (L-0047). Four of the ~20 required forward sessions have
elapsed since the spec froze on 2026-08-04. Re-check on or after 2026-09-02. Nothing was run:
previewing it would consume the one pre-registered trial's independence.

**SR3 listed-butterfly history — NOT REACHABLE** (L-0048). Barchart's EOD endpoint serves no
exchange-listed spread instrument under any of seven encodings, and the cross-product control
(`CLF27-CLG27`, the most heavily traded listed calendar in US futures) fails identically — so
this is a property of the endpoint, not a symbology guess that missed. Databento is installed
but has no API key anywhere reachable, and one MBO day is the entire local corpus.

> **A Databento API key is the only thing standing between this program and its
> highest-value remaining study** — re-costing the dead STIR labs at the measured 0.506 bp
> round trip instead of the 2.0 bp they were killed at.

The probe's first version scored a hit as `len(df) > 0`. Barchart answers an unknown symbol
with HTTP 200 and a one-row body reading `Error: invalid symbol`, so it reported all seven
encodings served — **the defect manufactured the high-value outcome on the session's first
measurement** (L-0049). Hits now require a parsed date, and both a positive and a
cross-product negative control run every time.

## H13 — the fill day is the whole edge

`sv_h13_qdb.ipynb`. Engine ties out against a matched-semantics panel rerun at **corr 0.99995**
over 2,755 days, on episodes asserted byte-equal to the graded ones.

The panel sums the flows *dated* `entry..exit`, and the flow dated at the entry is the move
from the **previous** close. So the graded book fills at the same close its signal was computed
from — `state = grail.shift(1)` removes the lookahead but leaves zero implementation lag. The
design doc's marking policy requires lag-1 fills ("signal on day t, execute at day t+1 marks")
and the checker charter asks "Fills at t+1?".

On the same aged panel package, moving the window one day later:

| | gross | registered cost @1x | net |
|---|---:|---:|---:|
| as graded (fill at signal close) | +282.7 bp | 174.0 bp | **+106.7 bp** |
| at a `t+1` fill | +166.1 bp | 174.0 bp | **−7.9 bp** |

The engine books agree in direction and size: **+162.4 bp `SELECTION-ARTIFACT` → −13.8 bp
`DEAD`**, median episode −1.29 bp, hit 31%, per-episode Sharpe −0.019.

Split by end (L-0052): dropping the entry-dated flow costs **+70.9 bp**, adding the day after
the exit costs a further **−45.6 bp**. Both ends are material, and the pairing is the finding —
the state does not merely *begin* on a big favourable day, it *ends* just before a big adverse
one. Both boundaries are timed on same-day information. That is a spread-extreme **bracket**,
which is L-0030's occupancy-matched rival check with a price at each end, and L-0027's
"chattering at the carry-zero boundary" made quantitative: carry crosses zero on days the
spread moves, in both directions.

**Containment:** this is specific to H13's state-scaled `_book` path. The always-on controls and
H14G have trivial states, the F-gates have no fills at all, and the rival check compared
like-for-like. No other verdict needs re-auditing for it.

**The alternative reading, stated:** a desk prices this state intraday and could trade before
the close, so a same-close fill is defensible as a description of practice. It is simply not the
convention this program grades on.

## H14 — the engine re-derives the checker's kill, and prices what it could only qualify

`sv_h14_qdb.ipynb`, the fly leg only (the flattener is what L-0045 certified).

A `QueryDrivenBacktest` book **cannot** double-count carry: its equity change *is* the total PV
change, once, with no separate carry bucket to add. The engine lands at **+13.0 bp** — 4.2 bp
from the committed `fly_mtm` (+8.8) and 27.8 bp from `fly_mtm + fly_carry` (+40.9). V-SV-14G-KILL,
re-derived from an independent code path.

Correlation cannot settle this and is not asked to: `fly_carry` is a smooth ~0.006 bp/day drift
and both readings correlate at 0.995. The **terminal level** is the discriminating statistic.

The solve schedule is replayed from the artifact; the weights are re-derived, because the
artifact stores only the per-leg DV01 *changes* and never the levels. **187 of 201 solves
reproduce to floating-point equality** off the re-derived path — 200-odd independent PCA solves
do not agree to the last bit by accident.

The 14 that do not close the checker's other finding. There are **22** annual segments, so 22
re-initiations; the ledger carries **8**. Every unexplained solve is the first one after a
segment start whose row is absent — **paired 1:1, 14/14**. So "~14 lost re-initiations" is
exactly 14, they are named, and at `cost_model` half-spreads they are worth **+5.27 bp** of
maintenance the graded bill never charged. Restoring them in the engine moves gross by only
−0.54 bp, which is the useful negative: their damage is almost entirely in the cost line.

Net contribution is negative at every multiplier: **−5.1 / −23.2 / −59.5 bp** at 0.5x / 1x / 2x.

**A live trap, recorded not repaired:** `h14_fly_ledger_USD.parquet` is stored in the **pre-fix**
convention while `scripts/sv_citivelo_h14_graded.py` was repaired at `f362eac4` and never re-run.
Read `fly_mtm` alone from the committed parquet; read the sum from any freshly generated one.

## H16b — the cube-served swaption path works, and the vol mark has a vintage mix

`sv_h16b_qdb.ipynb`. The handover pre-authorised recording a gap if this needed real plumbing.
It does not. Recipe of record:

    IRSwaptionMDP(source="CITIVELO-RL", curve_source="CITIVELO_EXCEL")
    IRSwaptionQuery(STRADDLE, SPOT_NPV, shorthand="2Yx10Y", strike="ATMF", side="sell",
                    structure_kwargs={"notional": m * 100e6})

`IRSwaptionPositionHandler` is entry-anchored as documented, so strike and exercise date are
both frozen — a real held swaption. **Four silent failure modes** on the way (L-0055): the source
token needs a provider-engine pair; `curve_source` is a constructor argument, not a request key;
`curve_source="CITIVELO"` is the **minute** asset and has no pre-2023 days; and `run()` swallows
all three into a completed backtest with a full equity curve, no holes, no NaNs and **every mark
exactly 0.0**. The non-zero-marks assertion carried over from the H13 notebook is what caught
the third.

The graded vol leg freezes the strike and ages the time to expiry, but takes the forward and
annuity from the **constant-maturity** locus panel — an ageing option written on a forward that
never ages, the vintage trap the `CurvePricer` docstring warns about on the linear side,
reproduced on the vol side. Unhedged and short the same straddle, the daily paths track at
corr 0.999, so the disagreement is a level: the held swaption loses **16.2%** and **11.2%** more
than the graded mark. Not apportioned — vol interpolation and the business-day time-to-expiry
approximation are also candidates — but both episodes agree on the sign, and the sign says the
convention flattered the short-straddle leg. Two episodes; a scoping result, recorded as one.

## The engine assertion that earns its keep

`DateTriggerRequirements` tests `state.date() in set(self.dates)`, so a `pd.Timestamp` in that
set never compares equal and **every trigger becomes a silent no-op**. The run completes, the
equity curve has no holes, there are no NaNs, and every mark is exactly zero. "No holes and no
NaNs" does not distinguish a working book from an empty one. Every engine cell in these three
notebooks now asserts non-zero marks *and* a closed-position count — the assertion caught two
further instances in the H16b work.

## The pattern, again

Four defects were found this session — the probe's error-payload hit, H13's fill day, H14's
missing re-initiations, H16b's vintage mix. **All four flattered the thing being measured.** The
session-1 tally was twelve of twelve. Nothing about that has changed.

## The DSR wall is not the trial count — it is config disagreement (L-0057)

Computed before spending a gate on the next family, because the answer decides what a next
family should even look like.

`DSR > 0.5` is exactly `sr > sr0`, and `sr0 = expected_max_sharpe_null(N, var_sr) = sd(SR) × k(N)`
where `k` grows like `sqrt(2 ln N)`. Measured:

| N | k(N) |
|---:|---:|
| 22 | 1.943 |
| 30 | 2.073 |
| 40 | 2.190 |
| 3,905 | 3.622 |

**The trial count enters through a term that barely moves — N from 3,905 down to 22 buys a
factor of 1.87 — while the cross-trial Sharpe dispersion enters linearly.**

For the SV arms the measured `sd(per-trade Sharpe)` is **0.2758** (range −0.784…+0.219 across 14
arms). So the bar was **0.536 at N=22** and **0.9997 at N=3,905**, and the best arm was **0.219**.
It failed both. Recomputed directly on the committed `h13_trades_*`:

> **Max DSR over all 14 H13 arms at n_trials = 22 is 0.101.**
> H13 would have died at the loop's own trial count.

So the handover's framing — *"this is why carry-class books can never be ALIVE in the SV family —
and why family selection matters more than signal cleverness"* — is too generous to family
selection. L-0042(b) is arithmetically true and nearly irrelevant.

### What this binds on every registration from here

A family passes DSR when **its configs agree on a positive Sharpe**, not when it has few trials.
A wide sweep is self-defeating twice over: it raises `N` a little and `sd(SR)` a lot. Register
**few, closely-related configs and require them all to work.**

Two caveats that must travel with this, because it is otherwise a recipe for gaming the bar:

1. The house convention estimates `var_sr` **from the sweep itself** (`deflated_sharpe`
   docstring: "the honest input"). A deliberately tiny sweep would therefore understate its own
   penalty. Any registration relying on this must **pre-state where `sd(SR)` comes from** and
   report the verdict's sensitivity to it.
2. DSR is pulled toward 0.5 *from below* on small samples — the n=6 arm scores the **highest**
   DSR at N=22 while being net **negative**. A DSR near 0.5 on few observations is not evidence.
