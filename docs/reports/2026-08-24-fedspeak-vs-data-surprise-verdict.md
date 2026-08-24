# Trading where the data says Fedspeak is going — verdict

**2026-08-24 · branch `feat/fed-detachment-events` · worktree `ARBS-fdx`**

## The claim

JWS Macro #8 (23-Aug-2026):

> *"we see a tidy 5 week lead of data surprise vs. Fedspeak"* … *"Fed speakers
> will become/shift more dovish/hawkish on where the data is going … this allows
> us to predict how a speaker is thinking going into an event."*

Two trades follow from that, and both were built and backtested here.

1. **Outright.** Pay SR3 when the surprise composite says Fedspeak is turning
   hawkish; receive it when the data softens.
2. **As an overlay.** Condition the existing intraday Fed-speaker book on the
   same state, on the thesis that a speech only carries news to the extent it
   departs from what the data already implied.

Three studies already on `main` had taken the *measuring* end apart: the lead is
+11 to +13 weeks on 2023-2026 rather than five; that window is a twenty-year
maximum; twenty-one years of a second judge model leaves +2 weeks at r 0.12; and
trading the *gap* between the two sides gave 2048 dead cells. What none of them
asked was whether the direction of the data itself, traded outright, pays — or
whether knowing it changes how a speaker's speech should be traded.

## The verdict

**Dead, in every sample and every arm, and dead before costs.**

### Study 1 — outright SR3 (`notebooks/rv/fed_expected_sentiment_rv.ipynb`)

| sample | weeks | cells / trials | best cell | best SR/wk | null median | p_rot | DSR | RW rejects |
|---|---|---|---|---|---|---|---|---|
| SR3 futures 2018-2026 | 433 | 672 / 1344 | `chg/L11/thr0/h8/pack1/follow` | **0.1090** | **0.1155** | **0.6657** | 0.0080 | 0 of 669 |
| 2y SOFR OIS 2005-2026 | 1122 | 96 / 192 | `chg/L11/thr0/h8/ois2y/follow` | **0.0561** | **0.0610** | **0.6861** | 0.2707 | 0 of 96 |
| JPM PIT window | 121 | 288 / 576 | `chg/L2/thr0/h1/ois2y/follow` | **0.2038** | **0.2069** | **0.5682** | 0.1490 | 0 of 240 |

In every sample the best cell a several-hundred-cell search could find is
**below the median of its own rotation null**. Not below the 95th percentile —
below the median. A misaligned copy of the same signal beats the real one about
two thirds of the time.

The pre-registered cell (`chg`, lead 0, four weeks, always-on, third deferred
SR3, follow) earns **+1.4120bp** per trade over 108 trades, t **0.5229**,
sign-flip p **0.6059**, and against its own rotation null — no search, so the
statistic is the cell's own per-trade Sharpe — **p = 0.2244** on SR3, **0.7771**
on the 21-year OIS, **0.2697** on the JPM window. Unlike the searched maxima the
pre-registered cell is *above* its null's median on two of three samples; it is
simply nowhere near significant. The verdict does not rest on the primary being
below a median — it rests on nothing clearing any bar. The literal always-on weekly reading of the question —
receive when the data softens, pay when it firms, re-decided every Friday —
earns **+147.00bp** gross over 432 weeks, pays **49.75bp** of turnover for a net
**+97.25bp**, at an annualised Sharpe of **0.1169** with a maximum drawdown of
**-258.5bp**. Eight years, a third of a basis point a week, and a drawdown two
and a half times the total.

Extending to twenty-one years does not rescue it — it flips the sign. The same
cell on the 2y OIS over 1122 weeks loses **-411.19bp** at **-1.4686bp** a trade,
and splitting those same trades at the date SR3 began gives **+141.41bp** over
108 trades in the SR3 era against **-552.60bp** before it. Nothing about the rule
changed; only where the sample starts. A sign that depends on that is not a sign.

Note also that the 2y OIS leg is a **constant-maturity mid**: the 2y par rate at
`t` and at `t+h` are rates on two different swaps, so their difference contains
roll-down an actually-held swap would not experience. It is the only instrument
that exists over the full twenty-one years, and it is read as an association
rather than as a P&L.

### Study 2 — the overlay (`notebooks/backtests/intraday_fed_hawk_dove/usd_fed_macro_state_overlay.ipynb`)

| arm | baseline | 72 conditioned books: best / median / worst | searched max vs null median | p_rot |
|---|---|---|---|---|
| `data`, live config | 399 trades, **+143.5bp**, SR 0.878 | **+12.0** / **-69.5** / **-470.0** bp | 0.0953 vs **0.0932** | **0.4666** |
| `data`, whole book | 748 trades, **-159.5bp**, SR -0.538 | +56.0 / -67.0 / -310.0 bp | -0.0464 vs -0.0349 | **0.8349** |
| `detach`, live config | 257 trades, **+80.5bp**, SR 0.818 | **-26.0** / -180.0 / -278.0 bp | 0.0411 vs 0.0643 | **0.7647** |
| `detach`, whole book | 354 trades, -32.0bp | +45.0 / -110.0 / -206.0 bp | -0.0018 vs 0.0024 | 0.5490 |

On the detachment state over the live window — the sharper reading — **0 of 72**
conditioned books improve on their baseline. Over the whole-book window it is not
uniform: 1 cell of 24 helps in each contract, on a baseline that is itself
negative.

Gating costs money wherever the baseline earns any, and always costs trades: the
best of 24 gated books on the live config gives up **+37.0bp** and **154** trades.
On the two arms whose baseline is negative, gating improves the total — which is
what dropping three quarters of a losing book does, and is not evidence about the
state. None of the 96 gated cells is scored against any null; they are a
description, not a result.

Across all twelve searches the smallest p-value anywhere is **0.3922**. Note that
each p prices the 24-cell search *within one contract*; the choice of contract is
a third axis it does not charge for, which can only make the p larger.

## Two things worth keeping regardless of the verdict

### 1. The roll placebo

A weekly directional futures book is exactly what a naive roll destroys, and
this is the number:

Measured on 432 Fridays of which 33 contain a contract change (SR3 rank 3,
2018-05-11 to 2026-08-21) —

* differencing a fixed-rank price column gives a signed mean weekly move of
  **+4.56bp** on roll weeks against **-0.81bp** otherwise, |median| **16.5bp**
  against **5.0bp**;
* the change in the contract *actually held* over those same weeks is **-2.35bp**;
* the gap is **+6.91bp per roll week and +228.0bp in total** — more than twice
  what the whole always-on book earns (against the incoming contract instead,
  the other single-contract reading, **+6.59bp** and **+217.5bp**);
* and off the roll weeks the two constructions agree to **0.0bp**, which is the
  known answer that certifies the measurement before it is pointed at anything.

`reference_imm_roll_fomc_collision` records that 22 of the 33 SR3 rolls *are*
FOMC decision dates, so that fabricated drift is correlated with the signal
rather than being noise. Nothing in either study differences two contracts, and
`gate_no_roll_jump` checks every priced row against the settle panel: worst
disagreement anywhere, **0.0**.

### 2. A weekly stamp is a Friday CLOSE

Found and fixed while building the overlay's join. A W-FRI weekly value is the
last daily observation in the `(Sat..Fri]` bin — a number computed at that
Friday's close — but pandas stamps it at that Friday's **midnight**. Comparing
an entry *timestamp* against the stamp lets a position opened at 09:00 on a
Friday read a number that will not exist until 16:00 that day: a look-ahead of
most of a session, on every Friday speech, in the direction that flatters.

The cutoff is now the entry **day**. `G-S2` asserts the resulting state age is at
least one day; measured, it is 3 to 7. `G-S3` refuses to let that gate pass
vacuously — the first version of the probe reported PASS having checked 0 of 400
events, because the raw book starts in 2019 and the detachment state in 2023.

## What is gated and what is not

Gated, with an assertion each: trailing-only signals under truncation (G-X1,
G-S1); the fill is the next session, never the signal session (G-X2); no P&L
differences two contracts (G-X3); a rate is a rate — the 2y leg comes from the
CurveStore discount factors, not the `RATES.OIS.USD_SOFR.PAR.2Y` tag, which is
47% swaption vol (G-X4); every structure the grid searches is actually
priceable (G-P3); the state cutoff precedes the entry day (G-S2), on a
non-vacuous sample (G-S3).

**Not gated, and named rather than buried.** Two exposures.

**The Citi surprise snapshot is a single vintage with no publication axis.** Citi
revises and periodically rebases, and a revision is silently back-propagated into
the trailing z-score. It cannot be removed here, only bounded — and the bound
neither confirms nor kills the edge, it shows there was none to confirm. Delaying
the composite one extra week moves the 21-year cell from **-411.19bp to
+198.44bp**, the SR3 cell from **+152.50bp to +60.50bp**, and the 121-week cell
from **+47.50bp to +196.50bp**. Nothing that quadruples, quarters or changes sign
on a one-week delay of its own input had a stable edge for a revision to have
created. The un-gated exposure remains a real limitation of anything built on
this composite.

**The borrowed grid decides whether to open by reading the FORWARD return.**
`fed_detachment_grid.run_cell` skips a week whose exit settle is missing, so that
decision uses information dated after it. Measured: **28** such weeks each on
`out1`, `spr1x3` and `pack1` (3 at h=4, 25 at h=8), **0** on `out2`, `out3`,
`out4`, `spr2x4`, and zero entry-side holes anywhere — it lands only on the
structures containing rank 1. The full grid's winner is a `pack1` cell at h=8,
i.e. inside it, which is why the study also scores the grid over the four
unaffected structures: best **0.1051** against a null median of **0.1146**,
**p = 0.6826**, still below its own null's median. The pre-registered cell has
zero such weeks and is priced by code that never reads the forward return.

## A side finding about the book being overlaid

Over the whole 748-trade 2019-2026 FED book, reading every speech as labelled
**loses money**: **-159.5bp** on the third deferred contract (t -1.4818) and
**-200.5bp** on the second (t -2.3049, sign-flip p **0.0197**). The live config's
positive result comes from its *filters* — voters only, ≥10 days from a meeting,
SR3 era, 2022 onwards — and those filters were themselves chosen from a sweep.
That is worth knowing before any further work treats the +143.5bp as a base to
build on.

## The adversarial review

Six independent lenses (look-ahead, roll accounting, inference, sign conventions,
vacuous gates, prose-vs-arithmetic) over the new code, then two skeptics per
medium/high finding prompted to refute it. **33 raw findings, 12 verified, 9
survived refutation.** All nine were acted on:

| finding | what it was | acted on |
|---|---|---|
| G-S1 re-implemented the `data` state instead of calling `build_state` | the gate computed its own correct answer and checked it against itself, so breaking the production path left it passing | now truncates *through* `build_state`; one shared `_build_data_state` |
| both audits whitelisted `"0.0"` | shadowing the three known-answer certifications the studies rest on | removed from both whitelists; a fifth audit blind spot documented |
| `assert_flat_weeks_agree` passed on NaN | `not isfinite(worst) or worst < tol` is satisfied by exactly the state a broken join produces | NaN now fails; a minimum flat-week count added |
| G-X3 reported `worst_mark_diff: 0.0` having checked zero marks | on `ois2y` and every multi-leg quote it verified nothing while reading as a pass | reports `mark_check_applies: False` and a note instead |
| the `ois2y` leg is a constant-maturity mid | its two marks are rates on two different swaps | disclosed; the arm is read as an association, not a P&L |
| `roll_placebo`'s flat-week certification is an algebraic identity | it cannot fail, so it is weaker evidence than claimed | said so; the independent hand-check is the real evidence |
| `roll_placebo`'s comparator was the INCOMING contract, labelled as the one held | over that interval the book held the OUTGOING one | both are computed and both reported (+6.91 / +6.59bp) |
| "gating always costs" / "0 of 72 improve" / "every cell of every instrument" | each false on one or two of the four arms | scoped to the arms where they hold |
| the forward-return entry condition | measured at 28 weeks on three structures, and the grid's winner sits in it | measured, disclosed, and scored again with those structures removed |

Three findings were killed by their refuters and are recorded here because the
reasoning is worth keeping: the primary cell *does* now get a rotation null (it
was added before the refuters ran); the "2018+ subsample" claim was true but its
diagnostic core was not; and the 48.8% follow-share bullet was already scoped
correctly by its own text. The follow-share bullet was rewritten anyway, because
a number that reads as supporting the claim while a bare majority points the
other way should not need scoping to be read right.

## What shipped

```
notebooks/rv/
  fed_expected_sentiment.py            signal, both books, roll placebo, gates, inference
  fed_expected_sentiment_run.py        grid + samples, reusing fed_detachment_grid's scoring
  fed_expected_sentiment_grids.py      headless runner  (~5 min, all three samples)
  fed_expected_sentiment_rv.{py,ipynb} the study        (66/66 figures audited)
  run_fed_expected_sentiment.py        build + execute + verify + audit
  _audit_fed_expected_sentiment_numbers.py
notebooks/backtests/intraday_fed_hawk_dove/
  hawk_dove_config.py                  + one `signal` block, default {"mode": "off"}
  fed_signal_overlay.py                the weekly macro state and its gates
  _signal_overlay_report.py            the overlay grid + exact rotation null
  _probe20_signal_knob.py              26 known-answer checks, 2 routes without the knob
  usd_fed_macro_state_overlay.{py,ipynb}                (38/38 figures audited)
  run_macro_state_overlay.py
  _audit_macro_state_overlay_numbers.py
  _probe_expect_handcheck.py           re-derives both headline numbers with plain
                                       pandas and no part of the study's own code
  _probe_expect_exit_holes.py          measures the borrowed grid's forward-look
tests/
  test_fed_expected_sentiment.py       35 tests
  test_fed_signal_overlay.py           18 tests
```

The independent hand-check is the load-bearing verification, because a checking
tool written by the same hand as the thing it checks agrees with it whether or
not either is right. It re-derives the roll fabrication from the raw settle panel
with plain pandas (agreeing to **0.0000bp**) and re-prices the whole 108-trade
pre-registered book contract by contract: **worst difference 0.000e+00 bp**. It
also reports that **33 of those 108 trades** hold a contract the rank rolls away
from before they exit — the exposure is a third of the book, not a corner case.

Reproduce:

```
conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/_probe20_signal_knob.py
conda run -n stir python notebooks/rv/_probe_expect_handcheck.py
conda run -n stir python notebooks/rv/_probe_expect_exit_holes.py
conda run -n stir python notebooks/rv/fed_expected_sentiment_grids.py
conda run -n stir python notebooks/rv/run_fed_expected_sentiment.py
conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/_signal_overlay_report.py
conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/run_macro_state_overlay.py
```

The overlay report and the probe need the warm bar cache in
`_global_cache/bars.pkl`, which lives only in `ARBS-gcb`; this worktree reaches
it through a directory junction. **Do not `git worktree remove` this tree while
that junction exists** — on Windows the removal deletes *through* it
(`reference_worktree_junction_hazard`).
