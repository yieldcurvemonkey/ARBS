# HANDOVER — backtest the CA-vs-fly trade in Citi's own framework

Written 2026-08-24 at the end of the session that produced PR #496 (merged) and
PR #499 (open). Paste this whole file into a fresh Claude Code session.

---

## The task

**Backtest Citi's actual published convexity trade — the screen, the fitted
hedge, the conjunction entry, the dollar target and stop — as a faithful,
pre-registered, engine-certified strategy.** Not another z-score grid. Block 4
already did that and it is dead; §3 explains precisely why this is a different
experiment and not a re-run.

Two sources, both already extracted:

* **`print (12).pdf`** — Citi, NA Rates Trade Idea, **09 Feb 2017**, Bikbov &
  Williams, *"Sell Blues convexity adjustments, hedged"*.
* **`print (18).pdf`** — Citi, US Rates Weekly, **13 Jan 2017**, *"Swearing in
  huge expectations"* §*Smart convexity sells* (byte-identical to
  `print (5/7/15).pdf`).

Both in `C:\Users\chris\Downloads\convexityrv\`, markdown conversions in
`C:\Users\chris\Downloads\convexityrv_markdown\`, prose extraction at
`docs/convexityrv/research/corpus2/g10-print-files.md` §4 and §8.

---

## 1. Working agreement

* **Work autonomously.** Make every design and implementation decision. If
  something is ambiguous, pick the defensible option, write the assumption
  down, and continue.
* **New git worktree**, short sibling path. There is an open PR on
  `feat/convexity-rv4`; do not disturb it.
  ```bash
  git -C C:/Users/chris/clee/ARBS worktree add ../ARBS-cvx5 -b feat/convexity-rv5
  ```
  **Every git command names its tree: `git -C <path> ...`.** Never rely on `cd`.
* Repo `C:/Users/chris/clee/ARBS`. Python
  `C:/Users/chris/anaconda3/envs/stir/python.exe`. Always
  `ARBS_SUPABASE_ENABLED=0`.
* Fast gate: `pytest tests -m "not slow and not network and not db"` (~30 min).
  Scoped: `pytest tests -k "convexity_rv or ccp_basis"` (~450s, 1,112 tests).

---

## 2. FOLLOW THE EXISTING PATTERNS — this is the part that matters most

Every one of these is already implemented somewhere in the tree. Read the
reference file before writing the equivalent.

### 2.1 Pre-register before scoring
`docs/convexityrv/gv-preregistration.md` is the model. Freeze the cell list,
the entry/exit rules, the cost convention, the null bars and the controls
**before** any P&L is computed. Every later change is a **dated amendment** with
its trial cost stated (that file has six: A1–A6). A scored cell not declared
there is a trial-count leak, and the test suite counts the declared cells
against the document (`tests/test_convexity_rv_gv_grid.py::
test_declared_count_matches_the_preregistration_document`).

### 2.2 Signals strategy-side, engine owns marks
Build a daily panel keyed by (date, structure); **lag it** — entry uses `t−1`
information, rolling fits estimated through `t−1` and applied at `t`; derive
episodes; persist to `notebooks/data/convexity_rv/`. Never compute a signal
inside a trigger from live pricers.

### 2.3 Fills lag decisions by one mark
`exec_lag_bd=1`. `exec_lag_bd=0` is a reported diagnostic whose gap to `t+1`
**is** the mark-noise harvest, and it has a known-answer test
(`tests/test_convexity_rv_gv_signals.py::
test_same_day_fills_harvest_engineered_noise_and_t_plus_one_kills_it`).

### 2.4 The engine is the number, the panel is a signal tool
`RVUtils/ConvexityRV/gv_engine.py` — futures legs + matched swap + hedge as
separate queries through `QueryDrivenBacktest`; **`assert_ran`** afterwards
because `run()` swallows exceptions and prints them, so a failed backtest looks
like a flat equity curve. **Quote P&L from the engine, not the panel** (§4.5).

### 2.5 The notebook gate, non-negotiable
Percent-format `.py` → `notebooks/backtests/_py2nb.py` → `nbconvert --to
notebook --execute --inplace` → `notebooks/backtests/_verify_nb.py` with
**0 unrun, 0 errors**. Structure: markdown title quoting the source note
verbatim; imports/env; **CONFIG dataclass with every knob documented inline**;
a **sign-probe cell with asserts**; a **known-answer tie-out cell with
asserts**; then results. Models:
`notebooks/backtests/convexity_rv/citi_blues_ca_repro.py` and
`gv_ca_vs_imm_fly.py`.

### 2.6 Mutation-test every suite
`notebooks/backtests/convexity_rv/_p2_mutate_gv.py` plants 27 defects one at a
time; all 27 are killed. Extend it. Its three built-in lessons are load-bearing:
anchors normalised to the file's own line ending, every mutant `compile()`d
before pytest runs, and **exit codes tested, never output text**.

### 2.7 Statistics
`E[max SR | null]` at the declared trial count on **both** clocks (per-hold and
annualised) via `RVUtils/StatisticalFinance/deflated_sharpe.expected_max_sharpe`;
**honest `n_eff` = `min(n_episodes, span×252/mean_hold)`**; deflated Sharpe;
**shared sign-flip** resampling (a row permutation leaves a Sharpe unchanged);
a **+20bd lag placebo** that must kill the edge; costs swept ×{0, 0.5, 1, 2}
with break-even quoted on **gross DV01 traded**.

### 2.8 Analytics the user asks for by name
```python
import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"
from BT.trade_dashboard import compare_curves, trade_dashboard
```
Pass `span_years` explicitly or the annualised Sharpe is wrong.

### 2.9 Data through Query + TimeseriesBuilder
Curves via `IRSwapsMDP(source="citivelo_excel_rl")`; vol via
`IRSwaptionMDP(source="CITIVELO-RL", curve_source="citivelo_excel_rl")`;
**CME–LCH basis via the new `CHBASIS` query and router** added in PR #499:
```python
TimeseriesBuilder().get_timeseries(
    start=..., end=..., n_jobs=4,
    queries=[IRClearingHouseBasisQuery(tenor=t) for t in TENORS],
    routers={"CHBASIS": IRClearingHouseBasisTB(IRClearingHouseBasisSwapsMDP())})
```

---

## 3. WHY THIS IS NOT A RE-RUN OF BLOCK 4

Block 4 (`docs/convexityrv/results/gv-ca-vs-imm-fly.md`, PR #496) scored **298
declared cells** of CA-vs-fly and found nothing: best **primary** cell **0.851**
against an annualised `E[max SR | null]` of **1.2198**. **That grid did not test
Citi's rule.** The differences are specific and every one of them matters:

| | block 4's grid | Citi's actual framework |
|---|---|---|
| hedge weights | β from a rolling fit of CA on ONE fly with fixed 50/50 wings | the weights are the **output** of a 3-rate regression — the fly shape is fitted |
| rebalance | β frozen at entry | re-struck periodically |
| structure choice | one per cell | a **screen across the strip** picks the most attractive (Fig 20) |
| entry | `\|z\| ≥ 2` | a **conjunction**: wide to model AND wide to the fly AND positive roll AND rich implied/realised AND stretched positioning |
| exit | z-exit / max hold | an explicit **dollar target and stop** (+$600k / −$350k on $200k DV01 ≈ +3.0 / −1.75 bp) |
| direction | two-sided (declared, and it doubled the opportunity set) | **short-only** — sell rich convexity |
| trials | 298 | **one pre-specified rule** |

The last row is the statistical crux. The annualised null bar at **12** trials
is **0.7019**; at 298 it is **1.2198**. A faithful single-rule backtest is
graded against roughly 0.55–0.70, not 1.22 — so a book at 0.8 that was dead in
the grid is alive as a pre-specified rule. **That is the honest reason to do
this properly, and it is also the reason not to let the cell count creep.**

**But carry the cumulative-search caveat anyway.** This is the fifth pass over
the same CA panel (block 1 `strat2`, block 3 `cavf`/PR #492, block 4 `gv`/PR
#496, the reproduction/PR #499, now this). Declaring one rule today does not
undo four prior searches. Report the nominal single-rule bar **and** say plainly
that the structure being tested was chosen after four passes over the same data.

---

## 4. WHAT IS ALREADY MEASURED — do not re-derive, do not contradict without evidence

All on USD SOFR, 1,409 dates 2021-01-04..2026-08-21 unless stated.

### 4.1 The two roll clocks are one business day apart
`IRSwapsTB._cvx_front_imm_code` advances the SR3 rank map **on** the IMM date;
`Query.Base.imm_resolution.resolve_imm_token("IMM_1", d)` searches from `d+1`
and advances the business day **before**. 22 roll dates each, **zero in
common**. Any blackout must be the **union**. `gv_universe.blackout_mask`.

### 4.2 The roll jump IS the theta
`dCA/dt = −σ²·mean(T1)/1e4` → **−0.237 / −0.308 / −0.367 bp per month** for
GREENS / BLUES / GOLDS. A quarter of that against the measured roll jump:
**1.045 / 1.024 / 1.111**. The causal forward roll-splice drifts −14.9 / −16.5 /
−21.2 bp against a predicted theta of −16.0 / −20.8 / −24.8. **A constant-rank
CA is stationary only because the roll pays the decay back**, so a book flat
across rolls runs a one-sided carry of ≈ +1.2 bp/quarter when short.
**Citi's book is short-only, so it is a carry trade by construction** — decompose
carry from residual before quoting any Sharpe (`gv_sizing.episode_decomposition`).

### 4.3 The CA mark is noise-dominated, structure by structure
AC1 of the daily change: WHITES **−0.540**, REDS **−0.517** (at or past the
−0.5 pure-noise bound), GREENS −0.228, BLUES −0.392, GOLDS −0.395. Kalman-derived
denoise half-lives are fitted on a 252-day burn-in and frozen
(`gv_sizing.fit_denoise_halflives`). **Signal on the denoised series, P&L on the
raw marks.**

### 4.4 A swap butterfly is not a vol proxy in the sense a hedge ratio needs
After level/slope controls, **0 of 11 legs** clear a partial-R² gate of 0.05
against ATMF normal vol; median rolling gate-pass 0.127. Raw level R² is high
and correctly signed (10y10y/20y10y on 10Yx10Y nvol: R² **0.814**, β −1.13) —
a co-trend, not an incremental response. Weekly sampling confirms it: level R²
0.05–0.58 survives, **change R² is 0.0003–0.089**.

### 4.5 A par-rate panel is a signal tool, not a P&L model
Certified on five books: the panel **overstated** three hedged Sharpes
(2.141/0.867/0.414 → engine **1.409/0.151/0.131**) and **understated** an
unhedged book's dollars by 2–3.8× while halving its Sharpe (daily-change
correlation 0.09–0.16). `Δrate × DV01` omits the carry and accrual of the
struck legs.

### 4.6 The half-life exceeds the roll-flat window
Long-end residual reverts in **68–99 business days** against a **56 bd**
tradeable segment; **67%** of the grid's 2,591 episodes exited at `segment_end`
rather than on the signal. The dated hold-through-roll variant (A5) was dead on
the engine: best **0.184** vs a 304-trial bar of 1.2225. **Citi held ~4 months
and through a roll, so the faithful design must use dated instruments and price
the roll, not blackout around it.**

### 4.7 Sizing
Median |β|: `beta_lvl` 0.105, `beta_chg` 0.115, `vol_ratio` 0.308,
`vega_match` 0.324 — the incumbent hedge was 2.0–7.7× too small to be a vol
hedge — but `vega_match`'s gate refuses 72–100% of days. Median gross Sharpe by
rule: **`none` 0.571 > `beta_chg` 0.336 > `beta_lvl` 0.251 > `vol_ratio` 0.203**
— monotone in hedge size, and only `none` survives 1× costs.

### 4.8 From the reproduction (PR #499) — the two findings that shape this work
* **The fitted scale `b` reverses sign in mid-2023** (at the 2023-06-20 refit):
  `w2` moves 0.05 → 0.95 and `b` goes +19.1 → −7.6. Before it a higher fly meant
  a higher CA; after it, the opposite. **A desk refitting periodically would have
  flipped its hedge. Whether that flip destroys the book is THE question this
  backtest exists to answer.**
* **Rebalancing moves the error rather than shrinking it.** Citi's fixed 2017
  Eurodollar weights give the **lowest** OOS residual sd (2.149 bp) of any scheme
  tried, ahead of the IMM-roll refit (2.232) — but the refit wins on mean
  absolute residual (1.674 vs 1.892) and on bias.
* Fly starts rank **monotone in how far forward they start** — spot 2.232 best,
  IMM_13 (the Blues pack's own front, the matched-expiry case) **3.396, 9th of
  10**. Putting the fly where the risk is makes the fit worse.

### 4.9 Structures whose marks you should not trust
`SFR12` scored `frac_ok` **0.667** on its own trading dates, wanders **4.05 bp**
from its own 10-day EWMA on **38.3%** of days with AC1 **+0.863**, and certified
at engine daily-change correlation **0.527** against a ≥0.99 bar. `noise_fit`
detects i.i.d. error only and is **blind** to multi-day dislocation — use the
EWMA-deviation diagnostic in `_p2_certify.py` §1.

---

## 5. WHAT IS BUILT AND REUSABLE

```
RVUtils/ConvexityRV/
  gv_universe.py   structures, IMM-dated legs, BOTH roll clocks, blackout,
                   per-date time weights, quoted fly/curve conventions
                   (FLY RATE = (2b−f−k)×100, charged at 4× the quoted DV01)
  gv_sizing.py     noise model + Kalman half-life, variance-space CA price,
                   CA vega and THETA, six sizing rules, causal roll_spliced,
                   episode_decomposition (carry vs residual)
  gv_signals.py    t+1 fills, roll-segmented episodes, per-leg costs
  gv_grid.py       declared cells, stats frame, null bars, vol-proxy matrix
  gv_engine.py     QueryDrivenBacktest wiring, IMM-pinned instruments,
                   the 2×-fly / 1×-curve bpv, the sign map, assert_ran
Query/IRClearingHouseBasis/  +  TB/IRClearingHouseBasisTB.py     (new, PR #499)
tests/test_convexity_rv_gv_{universe,sizing,signals,grid,engine}.py
tests/test_ccp_basis_query_tb.py
notebooks/backtests/convexity_rv/
  _p2_build_panel.py        118-query IMM leg panel        (~36 min)
  _p3_citi_repro_panel.py   the Citi-figure panel          (~4 min)
  _p2_mutate_gv.py          27-mutant harness
  _p2_certify.py            engine certification + mark-quality diagnostics
  citi_blues_ca_repro.py    the reproduction (28 cells, executed)
  gv_ca_vs_imm_fly.py       block 4 (35 cells, executed)
```

Panels in `notebooks/data/convexity_rv/` (**gitignored, regenerable**):
`cavf_ca_panel.parquet` (1,409×31 CA), `p2_legs.parquet` (1,416×118 IMM legs,
spot, long-end forwards, ATMF vols), `p3_citi_repro.parquet` (1,159×~60, all
five colours + fwd-start fly legs + the 3m10y smile + CFTC).

**A copied panel is a hypothesis until re-priced** — `_p2_measure_premise.py` §0
re-prices a random date sample through `IRSwapsTB.sfr_cvx_adj` and got
max |diff| **0.00000000 bp**. Do the same.

---

## 6. FIRST BLOCKER

**The reproduction's fitting machinery lives only in notebook cells**
(`citi_blues_ca_repro.py`: `_fit_on`, `_combo`, `imm_refit`, `FLY_STARTS`,
`fit_fly_constrained`). A backtest cannot import from a notebook. **Promote it
to `RVUtils/ConvexityRV/citi_fv.py` with its own test suite first**, then have
the notebook import it so the two can never drift. That is also the pattern the
rest of the package follows.

---

## 7. SUGGESTED BUILD ORDER

1. Worktree; scoped suite green; re-price a CA sample; confirm both panels load.
2. **`citi_fv.py`** — the Figure-6 fair-value machinery as a module + tests +
   mutants (§6).
3. **`citi_screen.py`** — Figure 20 across the strip: CA, 1wk chg, CA 3m/1Y z,
   Model, VsModel, VsModel 3m/1Y z, 3m Roll, Implied, Realized, Impl/Rlzd, with
   the note's two identities asserted (`CA − Model − VsModel == 0`;
   `Roll(p) = CA(p) − CA(p one contract nearer)`). Already prototyped in the
   reproduction's Figure-20 cell.
4. **Pre-register** `docs/convexityrv/citi-framework-preregistration.md`: the
   entry conjunction and each threshold, the target/stop in bp and dollars, the
   rebalance rule, the structure-selection rule, short-only vs two-sided,
   the cost convention, the trial count, and every control.
5. **Panel backtest** of the declared rule — cheap, for shape only.
6. **Engine certification** of every reported book on dated instruments through
   `QueryDrivenBacktest`, held through rolls. **These are the numbers you quote.**
7. Controls: always-short buy-and-hold, β=0, placebo ladder (0/10/20/40/60 bd),
   sub-period split, carry-vs-residual decomposition, cost sweep, convexity
   signature as a **point** prediction (the quadratic coefficient must equal
   `CA_DV01·w/2e4`).
8. Notebook through the gate; results doc in `docs/convexityrv/results/`; PR.

---

## 8. THE BAR, AND THE HONESTY REQUIREMENTS

* Quote `E[max SR | null]` at your **declared** trial count on both clocks, with
  the honest `n_eff`, and state the cumulative-search caveat (§3).
* **Decompose carry from residual.** A short-CA book earns ≈1.2 bp/quarter of
  theta. Citi's published book **is** a carry trade; the question is whether
  anything survives beyond it.
* **A timing signal must die under lag.** If P&L survives a 40–60 bd stale
  signal, it is a slow level effect, not timing.
* **Report the engine number.** If the panel and the engine disagree, the engine
  wins and the gap gets named.
* **A negative result is a result.** This package's most valuable outputs have
  been the strategies that turned out not to work and why. Prefer an honestly
  measured negative over a positive that rests on an unexamined assumption.
* If a measurement contradicts a sentence you have already written, **fix the
  sentence**. That happened four times in the last session and each time the
  measurement was right.

## 9. PROCESS TRAPS ALREADY PAID FOR

* **Heredocs collapse backslashes.** `\n` inside a quoted heredoc becomes a real
  newline and silently breaks f-strings. Use the Write tool for anything with
  `\` or backticks. This bit three times last session.
* **Scratch names collide.** `_q` (a residual sd) was clobbered by a plotly
  vline loop variable and did **not** raise, because `format(Timestamp, ".2f")`
  falls through to `strftime` and returns the literal `".2f"`. Re-derive summary
  numbers from the frame that holds them; do not carry `_x` names across cells.
* **`nohup … &` does not survive a tool call.** Use `run_in_background`.
* **Do not run panel builds concurrently** — cache contention surfaces as a
  spurious miss.
* **`notebooks/data` is gitignored.** Never commit panels.
* Sign conventions are established **empirically, never read off the code**:
  `OUTRIGHT bpv>0 = PAYER`; `CURVE bpv<0 = FLATTENER = long convexity`; a
  negative `contracts` on a `STIRFutureQuery` silently goes **LONG**.

---

## 10. DEFINITION OF DONE

A pre-registration frozen before scoring; a module + tests + killed mutants for
every new primitive; a panel backtest and an **engine-certified** finalist; the
full control battery; a notebook through the gate at 0 unrun / 0 errors; a
results doc that states the verdict, the null bar it was graded against, and the
cumulative-search caveat; the scoped suite green; a PR.
