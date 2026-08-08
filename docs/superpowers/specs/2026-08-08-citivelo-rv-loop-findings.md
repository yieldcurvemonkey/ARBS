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
| at a `t+1` fill | +166.1 bp | 174.0 bp | **−7.9 bp** ⚠️ |

> **⚠️ The −7.9 bp is superseded — see `L-0065` and the checker section below.** The 174.0 bp is a
> *nominal* cost (it assumes realised DV01 ≡ $100k; the episodes average $103,961). Like-for-like
> the `t+1` net is **−9.85 bp** (panel) or **−10.24 bp** (full `shift(2)` re-book). Same side of
> zero — the finding is unchanged and slightly stronger.

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

## H17 — vol term-structure roll-down carry, dead at gate, twice over

> **⚠️ SUPERSEDED IN PART — see "The checker's verdict (C-0001)" below, and ledger `V-V-17B`.**
> The death stands. Its **grounds and every realized number in this section do not**: −0.29× RT and
> "12 of 15" were quoted at one arbitrary cycle phase. The phase-invariant figures are
> **−0.097× RT, 9 of 15 negative, best cell +0.165×**, and "two independent grounds" is **one**.

A new non-SV-lineage family, pre-registered before numbers: a vega-neutral ATM straddle calendar
harvesting the roll-down of the vol term structure; direction pinned by a written entry-day slide
rule; universe restricted to CM-1-printed cells (1M excluded as CM-1's worst); horizons registered
as a pair rather than tuned; 15 feasible cells of 18, 41–126 non-overlapping cycles each.

1. **The carry does not clear the boat even if the surface never moves.** The frozen-surface
   roll-down the rule is designed to harvest, from entry-day data alone, is a median **0.73×** the
   CM-1 round trip — above 1× in only 2 of 15 cells.
2. **The market takes back more than all of it.** Realized median gross is **−0.29× RT**, negative
   in 12 of 15 cells; best cell **+0.37×**; zero cells clear 1× on median or mean. Per-cycle
   Sharpes −0.371…+0.082, worst cycles −3.2 to −21.1 annual vol bp against a ~1bp round trip. The
   rule sits long-back/short-front 50–71% of the time — net short gamma — so the pre-registered
   steamroller criterion fires too.

The gate carries a **planted-value self-test**: a flat frozen surface pays exactly `0.000`, a
frozen sloped surface pays `+4.1454` bp/cycle and the gate reproduces it to `1e-6`. So `0.73×` and
`−0.29×` are statements about the market, not about the code. That closes L-0042(c)'s discipline
gap for this gate.

**Not crisis-driven** (L-0062): re-run on full / pre-2020 / 2020+, **zero of 15 cells clear 1× RT
in any subsample**. Best pre-2020 cell 0.39×, best 2020+ cell 0.66×. There was no calm-market
carry either.

**The sentence:** the vol term-structure carry is real, smaller than the round trip, and then the
front-vol spikes take it back.

Trial accounting is deliberately stricter than session 1's gate precedent — those measured oracles
and consumed nothing; this measured the registered rule's *realized* gross, so all 15 cells are
consumed. **22 → 37**.

## CM-2 — the measured linear cost line

The linear leg dominates every boat in this program (L-0019: 0.26–0.43 bp/day against a swaption
leg of 0.03–0.09), and that line is the Citi 2019 schedule — an *assumption* applied cross-market.
L-0042(a) named it as the reopener for F3 and H16. CM-2 measures it: **905,820** CFTC Part 43 USD
OIS prints over **700 days (2010-12-15 → 2026-07-21)** against the same-day Citi EOD curve, each
priced on **its own effective and maturity dates** (59,218 unique swaps).

Dedup drops any chain containing a CORR or EROR rather than resolving it — dropping cannot
introduce a wrong rate, and a wrong rate *inflates* the deviation, which is the direction that
would flatter the study.

**Planted-value verify PASS:** a print planted at the fair rate measures `0.00e+00` bp through the
real path; the same print with its rate read as percent measures `39,053` bp.

**The smear table locates the curve's own stamp without being told it** — median `|print − EOD mid|`
falls monotonically from 3.3bp overnight to **0.526 at 14:00 ET** and **0.508 at 15:00**, then rises
to 0.828 at 16:00. That V is the best single piece of evidence the measurement is working.

### What is decisive: the shape

| tenor | all-hours median | at 15:00 ET | assumed (`cost_model`) | at-stamp ÷ assumed |
|---:|---:|---:|---:|---:|
| 1Y | 1.47 | 0.41 | 0.30 | 1.36 |
| 5Y | 1.74 | 0.53 | 0.50 | 1.06 |
| 10Y | 1.53 | 0.46 | 0.75 | 0.62 |
| 20Y | 1.20 | 0.40 | 1.25 | 0.32 |
| 30Y | 1.35 | 0.43 | 1.75 | 0.24 |

At the stamp hour the measured deviation is **essentially flat in tenor** (0.32–0.53 bp from 1Y to
30Y) while `RVUtils/cost_model` is **linear in tenor** (0.30 → 1.75 bp). The assumed line
**over-charges 20Y+ by 3–4× and under-charges 1–3Y by ~1.2–1.4×**. Its shape is wrong, not merely
its level.

### What is not decisive: the level

The confound checks kill that claim, and they are reported rather than argued around. The deviation
distribution **peaks at mid even at the stamp hour** (density at zero *is* the modal bin,
centre/peak = 1.000), and 6.3% of stamp-hour prints sit within 0.05bp of mid. A half-spread should
show a **dip** at zero; there is none. The test is one-directional — one-sided flow produces a
*shifted unimodal* distribution, so the absence of a dip is not proof of drift-dominance — but it
does mean **0.508 bp cannot be asserted as a half-spread**. CM-2 measures an upper bound whose
composition it does not separate.

> **Later addition (L-0072).** One candidate explanation is now struck: **compression is excluded
> from the Part 43 public tape by §43.2**, per the sibling program's cited `(action, event)` →
> `on_p43` matrix — so compression cannot be what puts the mass at mid. The same matrix confirms
> CM-2's `NEWT`/`TRAD` filter is exactly the ECONOMIC_FLOW cell, which turns that filter from an
> assumption into a citation. The level remains unclaimable; only the reasoning is narrowed.

**Forward starts: uninformative.** 47 cells, median at-stamp **16.6×** the assumed line, **zero**
below it, small samples, and evident contamination by package legs and off-market unwinds (the 1Y
`<3M` cell prints 6.69 bp). The line F3 and H16 actually trade is **not measured**. The
size-vs-spread test is **unrun** (notional cells too sparse after the quartile guard).

## The L-0042(a) reopener closes — the wrong way

F3 traded a direction-neutral package of k-year-forward 1Y swaps and its gate charged a **flat
1.0 bp** package round trip. CM-2 cannot measure the forward line, but it **bounds** it: a
forward-starting swap cannot trade tighter than its spot equivalent, so the spot cell is a *lower*
bound.

At the tightest defensible reading — spot 1Y at the stamp hour, **0.407 bp per leg** — a 1-2-1
package round trip is `Σ|w| × 2 × hs = 8 × 0.407 =` **3.26 bp** against the **1.00 bp** charged
(11.73 bp at the all-hours upper bound). Even the most generous direction-neutral structure
(`Σ|w| = 2`) costs **1.63 bp**, still above 1.00.

| ccy | episodes | oracle median 63bd reversion | ÷ graded boat | ÷ measured lower-bound boat |
|---|---:|---:|---:|---:|
| USD | 292 | 2.260 bp | 2.26× | **0.69×** |
| EUR | 706 | 1.174 bp | 1.17× | **0.36×** |
| GBP | 197 | 2.341 bp | 2.34× | **0.72×** |
| JPY | 686 | 1.206 bp | 1.21× | **0.37×** |

And these are **oracle** medians; realized harvest has historically been 10–30% of oracle in this
program. So F3's flat 1.0 bp benchmark was **too generous** and its kill was, if anything,
understated. The clause was written as a hope that a better execution line existed; the measurement
says the assumed line was already better than reality for this instrument. **F3 stays dead and the
clause is closed by measurement rather than left open.** H16's linear leg is unmeasured for the
same reason and its half of the clause remains open but unsupported.

---

# The checker's verdict (C-0001)

**Verdict first: PASS / PASS-with-correction / KILL.** A fresh adversarial checker, calibrated on
a planted defect first per the charter, took session 2's three load-bearing claims. It modified
nothing in the repo, and its cold rerun of the H17 gate reproduced the committed parquet
**byte-identically** (max abs diff 0.0).

**Calibration passed.** Given a fabricated ALIVE memo, it found the planted defect precisely — the
memo estimates `sd(SR)` over six near-**clone** configs, driving its own bar to 0.00041 so that any
positive Sharpe passes, and it cites L-0057's design rule while skipping L-0057's own travelling
caveat. It added four corroborating defects: the bar *ratio* conflated with the DSR; "daily"
Sharpes quoted on a 41-**trade** book; a median of +14bp against a net of +58bp at *worse* costs;
and six new configs registered without moving `N`.

## Claim A — L-0057: PASS, with a required amendment

Every asserted number reproduced: `k(22) = 1.942343`, `k(3905) = 3.624245` (the ledger's 3.622 is
0.06% low), `sd = 0.275843` over −0.784227…+0.218662, bar `0.535781` / `0.999721`, and **max DSR
over the 14 arms at n_trials=22 = 0.101281**. The equivalence `DSR>0.5 ⟺ sr > sd × k(N)` is
**exact**, not approximate. It is robust to the Sharpe *unit* — rebuilt on daily series, 0 of 14
arms clear under either convention.

**It is not robust to the `sr_variance` source, and L-0057 failed to say so.** 62% of the
dispersion comes from two arms (GBP 10Y10Y/20Y10Y −0.784, GBP 15Y10Y/25Y10Y −0.520). Excluding
them: `sd` 0.2758 → **0.1033**, bar 0.536 → **0.201**, and USD 10Y5Y/15Y15Y reaches **DSR 0.5416 >
0.5** at N=22. It remains a PASS because the registered family is unambiguous (V-SV-13 carries
`trials_delta 17` for all 17 arms as one family; the house gate uses the whole grid's variance),
because at today's N=37 even the narrowed source gives 0.4920, and because that arm has
`biggest_trade_frac = 0.8997` — 90% of its net in one trade — failing charter 4 regardless.

**The design rule is replaced.** As written, *"register few closely-related configs and require
them all to work"* is a recipe for the calibration memo. It governs **selection only**, and must be
paired with a **separate, pre-stated source for `sd(SR)` that is not the registered set** — because
narrowing the registration drives `sd → 0` and the bar → 0. The deflation variance must come from a
wider reference distribution named *before* the numbers, and every verdict must report its
sensitivity to that choice. **A registration that does not name its sd source is not registered.**

## Claim B — the H13 fill day: PASS, with an arithmetic correction

The checker did not take the code reading on trust. It regressed the panel's `mtm` on the pair's
constant-maturity spread change:

| dating | corr | beta |
|---|---:|---:|
| `d(spread)` over **d−1 → d** | **−0.8516** | **−$96,022/bp** (the $100k package DV01, correct flattener sign) |
| `d(spread)` over d → d+1 | +0.3236 | — |

and confirmed `sv_citivelo_detector.py:51` builds the state from the **same** day's columns with no
shift. So `state = grail.shift(1)` on a d−1→d-dated panel *is* a fill at the signal's own close.
A **full re-book at `shift(2)`** — the actual strict `t+1` state — gives gross **+165.92bp**, net
**−10.24bp** over the same 116 episodes.

**Correction.** L-0051's −7.9bp mixed a *nominal* cost with an actual gross: 174.0 = 2 × 0.75 × 116
assumes realised DV01 ≡ $100k, but the episodes average **$103,961** (range $70,119–$181,095), so
true entry+exit is **171.46bp** and the arm's actual graded cost is **176.00bp**. Like-for-like the
`t+1` net is **−9.85bp** (panel) or **−10.24bp** (full re-book). Same side of zero — a sharpening.

The permutation also survives a tighter null: a circular-shift null preserving entry-day spacing
exactly gives p **0.0008 / 0.0111** against the iid draw's 0.0006 / 0.0112.

**New, unrecorded (L-0066).** The pair's daily CM **spread** change has **ac1 = −0.392** (ac2
+0.002, ac5 −0.013) while each **leg**'s daily change has ac1 −0.045 / −0.023. Pure one-day-
reversing noise is −0.5, so ~**39% of the daily spread move is one-day-reversing relative-pricing
noise in the Citi curve build**, not market — and that is what the graded book collects on its entry
day. It strengthens the kill and it generalises: any daily-frequency RV signal read off differences
of two points on this build inherits that noise floor.

## Claim C — the H17 gate: KILL as stated. The verdict survives; two of three grounds do not

**It is not a bug.** Every "is this death manufactured?" check cleared: units (`vol_bp` medians
74.9 / 73.1 / 69.0 — annual normal bp, the same unit as `CM1_HALF`), grid coverage (all 9 marking
expiries on **100.0%** of days), interpolation (the decisive 6M-1Y h=63 cell is interpolation-**free**
and reproduces to 4dp with node lookups only), the non-overlapping construction, the direction rule,
sample composition (no subsample above **+0.55×**), real elapsed time (ACT/365 dt moves cells by up
to +0.72bp and flips one sign, but 0/15 still clear), and cold reproduction (bit-identical).

**But the headline was quoted at one arbitrary cycle phase.** `run_cell` always started its
non-overlapping grid at `i=0`, and H-V-17 pins no phase — so all 21 (or 63) phases are equally the
pre-registered statistic.

| | across-cell median | negative | best cell |
|---|---:|---:|---:|
| published (phase 0) | −0.289× | 12/15 | +0.371× |
| **phase-median (all phases)** | **−0.097×** | **9/15** | **+0.165×** |

Within-cell phase sd is 0.233 at h=21 and **0.640 at h=63**; 5Y 6M-1Y h=63 spans **−2.87× to
+1.15×** across phases on 41 cycles. **And the gate bar itself is phase-crossable**: in four of the
six h=63 cells, 3–4 of 63 phases have median > 1× RT, and the registered bar is "median > 1× RT in
at least one pair" — so under an equally-valid start date **H17 would have PASSED the gate and been
graded**.

**The self-test could not have caught this.** Both its surfaces are *frozen*, so the exit row equals
the entry row and it is structurally blind to reading the aged marks off the wrong day — verified
with a surgical mutant that returns **byte-identical +4.145403** on both. A **moving** surface
detects it.

**And the two grounds are not independent of the cost line.** Ground (1) is phase-stable (published
0.734 vs phase-median 0.766, phase sd 0.079) — a real measurement — but `CM1_HALF` are recorded
**upper bounds**, and ground (1) flips if true half-spreads are ≤ **0.766×** those bounds, i.e. 23%
tighter. In the other direction the RT is *understated*: it charges the **entry** expiries'
half-spreads for both sides while the legs unwind at their **aged, wider** expiries — true RT
**1.05 vs the coded 0.92 (+14%)** on the 6M-1Y h=63 cells.

**Corrected statement.** H17 is dead on **one** phase-stable ground — the frozen-surface carry is a
median 0.766× of a cost line that is itself an admitted upper bound — plus a direction-correct but
phase-noise-dominated realized measurement of −0.097×. Not "two independent grounds".

## Both defects are fixed in the machine, not just the write-up

`run_cell_ensemble` now reports the median over **all** phases plus the phase dispersion as the
statistic of record; phase-0 survives only as a field labelled deprecated. A second self-test on a
**moving** surface (level factor `f(t) = 1 + 0.25·sin(t/13)`, total variance kept linear in `T` so
the interpolation stays exact) pins the time indexing to **<1e-9** on 3M-6M h21, 6M-1Y h63 and
1Y-2Y h21. The repaired gate reproduces the checker's numbers exactly.

## Why A is a PASS and C is a KILL when both are "an alternative convention crosses a bar"

The discriminator is the **registration**, not the size of the effect. Claim A's alternative `sd`
source is *barred* by the registration — V-SV-13 consumed all 17 arms as one family, and excluding
GBP post-hoc is the manoeuvre L-0057's own caveat prohibits. Claim C's phase 0 is registered
**nowhere**, so it has no privileged standing among 21 or 63 equally valid grids.

## The tally

Seven defects found in session 2 — the probe's error-payload hit, H13's fill day, H14's missing
re-initiations, H16b's vintage mix, H17's phase artifact, H17's blind self-test, and L-0051's
nominal-cost arithmetic. **All seven flattered the maker.** Session 1's tally was twelve of twelve.

---

# Session 3 (2026-08-09) — the first family to clear a capacity gate, and the first audit that killed a death's grounds

**Verdict: F7 is DEAD AT GATE. Thirteen families dead, nothing ALIVE. `trials_total` 55.**

Queue items 1 and 2 were both re-checked and both are still blocked, with evidence rather than
assumption: the famb STRG forward window does not open until **2026-09-02** (L-0047, not previewed),
and **no `DATABENTO_API_KEY` exists** in the process environment, `ARBS/.env`, `~/.databento` (the
directory does not exist), or any `.env` in either tree — `databento 0.83.0` is installed but
keyless and the filesystem still holds exactly one `.dbn` file. So session 3 is queue item 3: a new
family at loop N, on the one genuinely unexplored conditioning axis.

## F7 — fade only what forced flow made cheap

Every one of the twelve dead families is a **fade**, and not one conditioned on **why** the
dislocation exists. Huggins–Schaller ch1 says fade **transient** richness — forced flow, demand for
immediacy — and do not fade structural hedging demand. F7 tested that: condition a USD curve-structure
fade on a flow shock measured from the **DTCC Part 43 tape**, a dataset this loop had only ever used
to measure costs (CM-1, CM-2), never as a signal.

**The structural advantage that made it worth running:** the state is measured on a *different
dataset from the mark*. H13 died because its state was a function of the same Citi curves that
generated its P&L (L-0051, L-0066). F7's trigger cannot inherit that noise.

### The capacity gate passes — for the first time in this program

L-0071 named capacity as a kill dimension this loop had never measured. F7 carried it **before** the
cost gate, and it passes by an order of magnitude: **124,045 packages over 641 file-days**, with the
leaders printing ~17/day. 14 of 56 canonical signatures clear the pre-registered floor of ≥60
packages per 60 trading days.

### The measurement that outlives F7: most apparent 2-leg "packages" are coincidence

A shuffled-timestamp null permutes *which* legs sit in each second while preserving the group-size
distribution exactly, so it isolates tenor composition. Enrichment (as-built ÷ null):

| | 3-leg flies | 2-leg spreads |
|---|---|---|
| enriched | 5-10-30 **13.8x**, 2-5-10 8.2x, 5-7-10 11.9x, 10-15-30 24.9x, 10-20-30 24.2x | 5-30 2.44x, 2-10 2.28x, 10-30 1.71x, 2-30 1.53x, 5-10 1.23x |
| **actively depleted (z <= -3)** | — | 7-10 **0.45x**, 5-7 0.51x, 10-20 0.46x, 5-20 0.54x, 10-15 0.46x, 2-7 0.38x, 5-15 0.39x, 15-30 0.62x |

A depleted signature is not a thin structure — **it is not a structure**. The raw capacity table
would have handed F7 four signatures that do not exist as traded packages. The test is
one-directional: for a pair of very common tenors the null is enormous (5-10's null mean is 817.6),
so enrichment near 1 is *low power*, not evidence of unreality.

**Execution Timestamp is second precision, not sub-second** — L-0080 claimed otherwise and L-0081
withdrew it. Contamination is bounded by the permutation instead of asserted away.

### The death

**Ground 1, decisive, and it survives switching the universe filter off entirely.** H-F7 clause (5)
passes only if the conditional book clears the round trip on **at least 2 signatures at the same h**.
Re-run over the full **18-signature superset** — the 10 registered plus all 8 excluded:

| h | signatures clearing the round trip |
|---|---|
| 1 | **0 of 18** (best 5-10-30 +0.322 vs 3.60) |
| 5 | **0 of 18** (best 5-10-30 +0.731 vs 3.60) |
| 21 | **1 of 18** — 2-5 at +3.791 vs 1.80 |

One signature cannot satisfy a two-signature rule.

**Ground 2, the mechanism.** The shock variable is *not* broken: it fires on 11.7–14.2% of eligible
days and coincides with a **1.548x** median absolute-move elevation (10/10 signatures, Spearman
p <= 1.2e-3). But that elevation is **1.548x at the signal day, 1.075x at the fill day, and
1.056 / 1.016 / 0.883 across the h=1/5/21 holding windows.** By the time the registered lag-1 rule is
in the trade, there is nothing left to monetise.

**Ground 3, the increment is inside its own null**, under both registered shock definitions:

| shock definition | median increment h=1/5/21 | placebo p(null >= real) |
|---|---|---|
| count (primary) | −0.123 / −0.216 / −0.215 bp | 0.880 / 0.615 / 0.775 |
| notional-weighted (registered sensitivity) | −0.064 / −0.272 / −0.225 bp | 0.695 / 0.755 / 0.765 |

A randomly-dated shock beats the real one 62–88% of the time, and the null's dispersion (sd
0.096–0.446 bp) exceeds the effect.

**The executable check agrees.** The QDB notebook runs the gate's single *most favourable* cell —
5-10 at h=21, increment +3.750 bp, the largest anywhere — and it dies: per-trade Sharpe **−0.549**,
net **−3.108 bp** against the 1.80 bp round trip, NW t −4.06, engine ends **−$4,175,985**, DSR
**0.0000 / 0.0002 / 0.0000** at N=55 under all three pre-stated sd(SR) sources. That cell is also
the cleanest demonstration of why L-0082 registered the *median* as the headline: its +3.750 bp
increment is not the shock book being good, it is the **control being unusually bad** there (no-shock
hit rate 10%). Selecting the max-increment cell selects a bad control.

**The mark is exonerated by an independent dataset.** Rebuilding every structure from the **traded
leg rates in the Part 43 tape** gives traded-minus-grid deviation medians of +0.12 / −0.01 / −0.05 /
+0.01 / −0.07 / −0.05 / +0.06 bp, and pond ratios agreeing to two decimals at h=21. The model-mark
mirage — hit three times in this record — did not happen here.

### What survives: the pond is real, and it is the largest this program has measured

The five 2-leg spreads clear the perfect-direction upper bound at h=21 by **2.05–4.88x** on the
governing CM-2 line (5-30 4.88, 2-30 4.86, 10-30 2.66, 2-10 2.50, 5-10 2.05) and **0.96–2.08x** on
the pre-stated sensitivity line. **Caveat that must travel with it:** each is a median over only
19–21 non-overlapping episodes, and a sweep of all 21 block-phase offsets puts 10-30 anywhere in
1.49–3.23x against a committed 2.66x. It never crosses 1.0x at any offset, so it changes no decision
— but nothing may be sized against the point estimate.

What is dead is the **harvest**. Neither the conditional nor the unconditional fade collects it, and
`corr(z_t, forward move)` is **positive** (+0.110 at h=5, +0.127 at h=21) — these structures *trend*
at these horizons. Momentum therefore wins by construction and its increment is the exact negation
(+0.123 / +0.216 / +0.215 bp), which is 8.3–16.7x short of the round trip. **The better of two
mirrors is not information**, and any momentum family must be registered on a sample these numbers
were not read from.

## The audit inverted the brief — and killed three of the four headline numbers

F7 is a *death*, so the maker's failure mode is not wishful thinking but **killing a real family with
a bug**. Four probes (15 agents, 296 tool calls) were briefed to hunt defects that *manufacture a
death*; every claimed defect then went to a fresh agent briefed to refute it. All four returned
`death_is_sound` — and then withdrew three of the four numbers the maker was about to publish:

1. **"All five flies fail the pond at every horizon" is false.** 2-5-10 at h=21 is 1.08x on all
   eligible entries, 1.23x unconditional, 1.30x on the traded mark. It dies at step (ii), not at pond.
2. **The fill-lag monotonicity KILL criterion fires on 88–95% of pure-noise draws at this n.** See
   below — this rewrites a registration rule.
3. **The increment point estimates flip sign under a one-day change in the entry rule.** The placebo
   p-values are the only honest step-(ii) headline.

It also traced the "2.0–4.1x" pond in an earlier commit message to a superseded pre-fix run. The
committed figure is 2.05–4.88x — **the stale digit understated the pond, so for once the error
flattered the death rather than the maker.**

Verified clean by *running* code, not reading it: the fade sign (9 real episodes hand-recomputed to
under 1e-9), strict causality (0 boundary mismatches on truncated recomputation), loop bounds, the
flow join, the cost convention against L-0061, and a **bit-identical cold re-run**. The self-test is
not blind to the defect class that would manufacture this death: mutating `side` to `+np.sign(z)`
makes it fail as designed.

## L-0084 — a kill criterion that fires on noise is not a test

H-F7 made the fill-lag profile the spine of its placebo battery, on L-0069's import: a real
immediacy premium decays monotonically in fill lag, so non-monotonicity is a kill. At 4 lag points
and 11–38 episodes per cell, **exact monotonicity is a low-probability event whether or not an edge
exists** — the criterion fires on 88–95% of pure-noise draws. The import was not wrong, it was
**unpowered**: the sibling applied it to books with hundreds of trades.

> **Binding from here:** a fill-lag profile may be *reported* as a diagnostic at any n, but may only
> be *registered as a kill criterion* alongside a stated false-positive rate computed at the family's
> own episode count. Above roughly 20%, it is descriptive only.
>
> This is the companion to session 2's self-test rule. Before citing a test, ask not only **what
> mutation it would fail to catch** (V-V-17B) but **how often it fires when nothing is wrong**.

## L-0085 — the third instance, and the first on a signal that is not the mark

| | signal source | finding |
|---|---|---|
| H13 | same Citi curves as the P&L | the entire graded net was the entry-day flow (+70.9 of +106.7 bp; entry days 17x the unconditional mean; permutation p 0.0006) |
| Citi CM spread / sibling `pfin/ARBS` | the mark itself | ac1 −0.392 vs per-leg −0.045/−0.023; a +5.24-Sharpe book retired on AR(1) around −0.25, lag-1 removing ~80% of every Sharpe |
| **F7** | **DTCC Part 43 tape — independent of the mark** | shock coincides with 1.548x same-day absolute move; **1.075x by the fill day**; ~1.0 over the holding window |

The third case is the important one, because it removes the obvious escape — *"the effect was the
mark's noise, so a cleaner signal would survive."* F7's signal has no exposure to the mark's noise
and the effect still dies at the fill.

> **The information in a curve-RV signal at daily frequency is concentrated in the bar the signal is
> computed from** — demonstrated now for a vendor-mark signal, a same-mark signal, and an
> independent-dataset signal. Price impact from curve-package flow is substantially resolved within
> the session in which it prints.

That is also the sharpest statement of what an ALIVE candidate here would need: **either an intraday
fill** (F6 already killed that on cost arithmetic — the boat is frequency-invariant while the pond
shrinks), **or a signal whose information is not resolved same-session.** Everything this loop has
tested is the former.

## One imported claim does not describe this data

L-0072 imported from `pfin/SwapPulse` that `('*','COMP')` carries `on_p43 = False` — compression
excluded from Part 43 — and used it to strike compression as an explanation for CM-2's mid-peak.
Measured on ten files (47,029 USD-OIS rows): **246 NEWT+COMP rows on 5 of 10 days, all carrying a
parsed fixed rate.** The import is wrong about this tape. The conclusion it supported survives for a
better reason — CM-2's own `NEWT AND TRAD` filter already excluded those rows — so the honest
statement of why the level stays unclaimable is "other mid-printed populations remain unseparated",
not "compression is excluded by regulation". **Note the direction: this correction removes a reason
to be confident.**

## The tally

Session 1: twelve defects, twelve flattered the maker. Session 2: seven, all seven flattered the
maker. **Session 3's audit found defects that flatter the *death*** — which is what an inverted brief
is for, and it is the first time this program has caught that direction. They were caught **before**
the verdict row existed rather than after: the V-V-17 to V-V-17B sequence, run in the right order for
the first time.

One defect this session flattered nothing and was mine: V-F7 quoted its DSR figures at N=55 while the
notebook that produced them hardcoded N=47 (L-0086). Every quoted digit reproduces at N=55, the
notebook constant is fixed and re-executed, and the provenance is on record — a number quoted at a
parameter it was not computed at is exactly the class this program keeps finding.
