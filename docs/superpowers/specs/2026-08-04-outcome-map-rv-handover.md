# HANDOVER — Outcome-Map RV: actually trading vol AGAINST linear

You are working autonomously with FULL permissions in the ARBS repo. You are
the successor to a long research program (PRs #375–#383, all merged or open
on main). Read this file first; it is the complete handover.

## MISSION

Build and backtest a strategy that ACTUALLY TRADES VOL AGAINST LINEAR: for
each SR3 quarterly option contract, enumerate the FOMC outcome space of its
resolved-by-expiry meetings (k meetings → combinations of hike/hold/cut in
25bp moves), map every outcome cell to BOTH prices — the option-implied
probability (listed verticals) and the linear-conditional probability (ZQ
FedWatch lattice and/or FOMC-swap lattice) — and trade the cell-level
disagreements with BOTH legs on: option structures on the vol side, the ZQ
meeting basket (or FOMC-dated swap package) on the linear side. The prior
program only used linear as the measuring stick; your job is to find an
expression where the linear leg EARNS its costs.

## CRITICAL IDENTIFICATION FACTS (proven in this program — do not rediscover)

1. **Exchangeability**: for quarterly SR3 options, every resolved meeting
   has day-weight 1, so all orderings of moves land on the same settlement
   rate. "All combinations" COLLAPSES to the total move-count distribution
   P(N). Hike-hold-cut orderings are NOT identified by one expiry. Your
   outcome map is therefore per-expiry a COUNT distribution (cells = net
   moves −k..+k plus two off-lattice tails), not a 3^k tree.
   Two partial escapes, both open research: (a) cross-expiry deconvolution
   (H27 counts = Z26 counts ⊛ Bernoulli) measured WEAK (one-Bernoulli fit
   leaves L1 0.33–0.41); (b) meetings with day-weight < 1 (effective inside
   the reference window but decision before expiry) break exchangeability —
   rare but real, unexplored.
2. **Supports are two-point**: the ZQ lattice brackets each meeting with
   TWO adjacent 25bp outcomes (mantissa). A hike/hold/cut TRINOMIAL per
   meeting is a lattice EXTENSION you'd have to build and justify — the
   listed FedWatch convention (and `RVUtils/FlyVsVol/baselines.mantissa_probs`)
   is two-point. Off-support outcomes live in the smear/tails.
3. **The feasibility frontier**: the lattice can only carry the option
   surface's width inside ~60 days to expiry (0% refit saturation <30dte,
   100% at 200–300dte). Cell-level convergence trades only exist near
   expiry; far expiries price one indivisible dispersion premium
   (probability conservation: the modal deficit IS the wing surplus — one
   premium, not many edges).
4. **Frame-freezing**: the correct hedge frame holds atom locations at
   ABSOLUTE rates (base + n·25bp); a fixed-strike digital is then exactly
   multilinear in per-meeting probabilities. `AtomEngine.rates_probs(...,
   q_ref=...)` implements it; the replication identity is tested.

## WHAT WAS ALREADY TRIED — VERDICTS (do not silently retest)

- **Channel-1 (PR #375)**: fade listed boundary digitals vs the ZQ meeting
  basket, frame-frozen hedge, resolution exits. Mechanism CERTIFIED by
  placebos (Gaussian tree kills 75% of the edge, wrong calendar kills all).
  But 5 trades/2y at EOD, +46.6bp gross/+6.0 net@1×/−34.6@2× → DEAD (too
  few trades). Your cost budget problem in one number: the digital hedge's
  ZQ traffic ate the edge.
- **Linvol grid (PR #377)**: 272 configs / 4 families / 384 placebo rows —
  NOTHING ALIVE, DSR 0.000 everywhere. Family E (decomposed ICS residual,
  linear-vs-linear) is the one populated mechanism: fade gross +0.14–0.84
  bp/trade over 114–150 trades, perfect momentum mirror, costs 3–7× the
  edge → MARGINAL-maker-only.
- **Family B (PR #378, full 2021–2026 sample incl. 2022 hikes + SVB)**:
  passive tail-short carry DEAD (worst days −55/−92bp, skew −7); frontier
  calendar DEAD (beta −0.93 to outright); the CONDITIONAL intra-quarter
  richness fade survives with positive skew — STRG75 Q1 thr4/exit0.25/
  hold15: 16 trades, 88% hit, +75.3bp net@1×, Sharpe 1.62, NW t 2.10,
  collected +44bp of post-SVB convergence — but SELECTION-ARTIFACT at 720
  trials (DSR 0.000). Pre-registered and ported to the engine.
- **QDB ports (PRs #382/#383)**: the fade, the FLY25 carry, and the
  COMBINED book all run on `QueryDrivenBacktest` with production QL marks;
  reconciliations vs vectorized replays at corr 1.000. Combined book:
  +$2,844 (+113.8bp), Sharpe 1.06, NW t 2.61. NOTE: neither sleeve trades
  a linear leg (deltas ~0 by construction; the wired SR3 futures hedge
  traded 6.6 contracts in 4y). That gap is YOUR mission.
- **Sep-2024 50bp cut was ON-support** (eve lattice (−2,−1), P(50)=0.78) —
  the modern sample has ZERO off-lattice terminal events; 2022/SVB windows
  are where fixed strikes got beaten.
- **The triangle + path ledger** (PR #376, `linear_vs_vol_distributions
  .ipynb` sections A–F): at 2026-07-31 the surface priced the modal 1-move
  bucket −16.7pp vs the tree (−4.2bp on its 25bp vertical) and every
  non-modal cell rich; upper edges validated against LISTED verticals to
  <1pp; the BELOW-lattice tail HALVES on listed quotes (spline artifact —
  never trust BL tails for PnL). ICS decomposition: observed 5.25bp =
  2.0 basis + 2.1 compounding − 0.2 calendar wedge + 1.3 residual.

## THE NEW STRATEGY SPACE (explore, grid, judge)

Daily, per contract (front 1–3 quarterlies), build the OUTCOME MAP:
count-cells with p_opt (from LISTED 6.25bp verticals at atom midpoints —
the boundaries panel already holds these digitals) and p_lin (ZQ lattice;
FOMC-swap lattice as second linear read + tie-out gate). Then trade:

1. **Cell-pair RV (primary)**: LONG the cheapest cell's box (verticals at
   its edges) vs SHORT the richest cell's box, probability-normalized, with
   the residual linear exposure hedged by the ZQ meeting basket (frame-
   frozen ratios from `RVUtils/MeetingProb/backtest.hedge_ratios`). The
   options-vs-options core makes the linear leg SMALL (residual delta
   only) — that is the cost thesis vs dead channel-1 (which hedged a full
   digital). Exit at resolutions / convergence / clock.
2. **Full-map replication book**: sell every rich cell, buy every cheap
   cell in tree-implied proportions, hedge the net with the ZQ basket —
   the distribution-arbitrage portfolio. Exploit leg TELESCOPING (adjacent
   cell boxes share strikes; a condor of cells nets contracts) — engineer
   the contract count down before judging costs.
3. **Resolution-window expression**: enter cell spreads 1–5 sessions
   before a decision only where the option-vs-linear CONDITIONAL split for
   that meeting's bracket disagrees (the last-resolved-meeting bracket is
   the one place near-term attribution is sharp); exit at the decision.
   Short holds = small hedge traffic.
4. **Linear-leg variants**: ZQ basket vs FOMC-swap package
   (`RVUtils/MeetingProb/swap_ladder.py` — no expiry seam, tie-outs ≤2bp
   vs ZQ; the swap leg was NEVER used as a hedge leg). Cost each at
   0.25bp/side/contract (futures) — make the linear t-cost a config dial
   like `famb_fly_qdb` did.
5. **Weight-<1 meetings** (optional probe): find contract-days where a
   resolved meeting has day-weight <1 → orderings partially identified →
   a genuinely new cell dimension. Small sample; treat as a probe.

Grid axes (pre-declare, keep ≤ ~300 configs): expression {pair, map,
resolution-window} × dte band {<30, 30–60, <60} × entry gap threshold
{4, 6, 8pp} × exit {resolution, converge-half, 10d} × linear leg {ZQ,
swap, none} × direction {fade, momentum}. n-floor the winner (≥10), DSR at
full trial count, placebos (Gaussian tree + wrong calendar — reuse
`linvol_grid_common.gaussian_tree_gaps` / `shifted_ladders` /
`tree_digitals_from_ladders`), NW t on dailies, chronological halves.

## WHERE EVERYTHING LIVES (absolute paths)

- **Worktree (work here)**: `C:\Users\chris\clee\ARBS-xm` — branch off
  `origin/main` (all RV PRs merged through #379+; #383 may still be open —
  check `gh pr list`). Main tree `C:\Users\chris\clee\ARBS` is the user's;
  treat as read-only except `notebooks\data\sfr_rv_lab\` (read) — other
  sessions may be active there.
- **Framework modules**: `C:\Users\chris\clee\ARBS-xm\RVUtils\MeetingProb\`
  — `ladder.py` (ZQ FedWatch lattice; current-month meeting REQUIRED;
  just-expired front ZQ needs `backfill_settles(force_refresh=True)`),
  `swap_ladder.py`, `atoms.py` (split_meetings/AtomEngine/frame-freezing;
  degenerate-support mask), `pricer.py` (Bachelier over atoms — tree-fair
  pricing of any listed structure), `refit.py`, `monitor.py`,
  `backtest.py` (channel-1 engine + hedge_ratios + package_cost_bp),
  `ics.py` (blend/spread/wedges/ff_conditional_atoms).
- **Backtest harnesses**: `C:\Users\chris\clee\ARBS-xm\notebooks\backtests\`
  — `linvol_grid_common.py` (boundary signal frames, claim/fly marks from
  quotes, placebos, pick_winner), `run_linvol_grid.py`, `famb_common.py`
  (parity-completed surface, rolled books, richness, series_stats),
  `famb_fade_qdb.py` / `famb_fly_qdb.py` / `famb_combined_qdb.py` (the
  QueryDrivenBacktest ports — copy their trigger patterns), run notebooks
  `famb_*_run.ipynb`, converters `_py2nb.py` / `_verify_nb.py`.
- **QDB framework**: `C:\Users\chris\clee\ARBS-xm\BT\` — `query_engine.py`
  (run loop SWALLOWS exceptions with print(e) under tqdm — a silent
  zero-trade backtest is a bug signature; `mtm_history` is TOTAL account
  value), `query_strategy.py`, `query_actions.py` (AddQueryFactoryAction
  for dynamic sizing), `triggers.py`, `position_handler.py` (registry);
  `Query\STIRFutureOptions\` (STRADDLE/VERTICAL/FLY structures; the
  `build_mdp_request` symbol collector MUST know every structure's leg
  kwargs), `Query\STIRFutures\` (futures leg, `BARCHART_STIRF-RL`).
- **Data panels** (gitignored, both trees):
  `C:\Users\chris\clee\ARBS-xm\notebooks\data\meeting_prob\`
  (boundaries.parquet = per contract-day LISTED 6.25bp digitals vs strict
  tree + strikes + gates, 2024-07→2026-07-28; monitor.parquet = channel/
  saturation/q_opt/q_zq/pgaps; tieout_gate.parquet),
  `...\data\linvol_grid\` (league + ics_residuals),
  `...\data\famb\` (quotes_old.parquet + parts: 2021-02→2024 option quotes
  backfill), and `C:\Users\chris\clee\ARBS\notebooks\data\sfr_rv_lab\
  quotes.parquet` (199k listed premiums 2024-07→2026-07-28, OTM-ONLY —
  parity-complete before building any ATM-straddling structure).
- **Specs/findings (read these for full numbers)**:
  `C:\Users\chris\clee\ARBS-xm\docs\superpowers\specs\` —
  `2026-07-30-zq-sr3-meeting-prob-{design,findings}.md`,
  `2026-08-02-impdist-linear-vs-vol-{design,findings}.md`,
  `2026-08-03-linvol-backtest-grid-{design,findings}.md`,
  `2026-08-04-family-b-dispersion-{design,findings}.md`.
- **Key executed notebooks**: `...\notebooks\rv\linear_vs_vol_distributions
  .ipynb` (the triangle + count ledger — your outcome map's prototype is
  section F), `...\notebooks\rv\linvol_dislocation_dashboard.ipynb`.
- **Memory**: `C:\Users\chris\.claude\projects\C--Users-chris-clee-ARBS\
  memory\` — read `project_famb_dispersion.md`,
  `project_linvol_backtest_grid.md`, `project_zq_sr3_meeting_prob.md`,
  `project_impdist_linear_vs_vol.md` before starting.

## HONESTY RULES (house law, non-negotiable)

Listed marks only in PnL (never BL/spline — the below-lattice BL tail is
half artifact); lag-1 entries on the global session calendar; costs per
contract per side (SR3 option half-tick 0.125bp = $3.125; SR3/ZQ futures
0.25bp = $6.25; report 0×/1×/2×; 2021–22 era was thinner — flag);
both directions always (fade AND momentum must mirror on gross); DSR at
the FULL trial count with an n≥10 floor before naming a winner (max() over
a grid crowns 1-trade rows); placebo the mechanism (Gaussian tree = same
moments no lattice; wrong calendar = shifted meetings — re-derive
classification flags INSIDE the placebo world); NW t on dailies
(overlapping trades overstate plain t); probability conservation check
(cell gaps sum to ~0 — you are trading ONE premium redistributed, price
the package not the sum of cells); notebooks compute their own conclusions
(no asserted numbers in markdown); verdict taxonomy via
`RVUtils/SFRRVLab/stats.verdict` (ALIVE / SELECTION-ARTIFACT /
MARGINAL-maker-only / DEAD).

## ENGINEERING GOTCHAS (each cost real time this session)

- Run everything with `conda run -n stir`; NEVER multi-line `python -c`
  (conda mangles it — use script files); background `| tail` pipes drop
  output — redirect pytest to a file and READ the tail before claiming a
  green gate (`conda run -n stir python -m pytest tests -m "not slow and
  not network and not db" -q > file 2>&1`; last green: 3,373 passed).
- MPLBACKEND=Agg for plain-python notebook dry-runs (plt.show blocks;
  plotly fig.show → cp1252 UnicodeEncodeError — gate display on ipykernel).
- Notebook flow: `# %%` .py source → `_py2nb.py` → `jupyter nbconvert
  --execute --inplace` → `_verify_nb.py` (0 errors / 0 unrun) — commit
  BOTH .py and .ipynb.
- Option symbols `SFRZ26|9500P` (strike×100); futures root SR3*, options
  root SFR*; serff futures cache keys SR3*; pricer accessors are METHODS
  (`p.delta()`); handler $2500/price-point/contract.
- QDB: entry gates must be TAG-scoped in multi-sleeve books (an always-on
  sleeve jams "no open position" gates); no open-position gate on roll-day
  re-entries (the outgoing package is still in the portfolio during
  evaluate); engine prices only when positions exist.
- Quotes panel is OTM-only → parity-complete (`famb_common.premium_surface`,
  C = P + DF·(F−K), ~0.03bp error); NEVER synthesize an ITM leg into a
  strangle (smuggles a forward).
- barchart serves expired option chains to 2022 at ~12.6s/day warm
  (`famb_backfill_quotes.py` pattern, checkpoint per symbol).

## WORKFLOW

Branch `feat/outcome-map-rv` off origin/main in ARBS-xm. Spec first
(`docs/superpowers/specs/2026-08-XX-outcome-map-rv-design.md`, committed),
then module + synthetic tests (pattern: `tests/test_meeting_prob*.py`,
`tests/test_famb_*.py` — all no-network), then panels/backtest, then
executed notebooks, findings doc, memory update
(`C:\Users\chris\.claude\projects\C--Users-chris-clee-ARBS\memory\` — new
file + MEMORY.md index line), fast gate green (READ the tail), push, PR to
main with the house-style body. Commit trailer:
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## KILL CRITERIA (pre-declare, judge against them)

- If the linear leg's costs exceed half the gross of the paired expression
  across the grid median → the answer is "linear still doesn't earn its
  leg" — write it up as a closed question, don't torture the grid.
- If cell-pair trades collapse to the same 1–5 trades/2y as channel-1 →
  DEAD (too few trades) and the EOD ceiling is confirmed; recommend the
  intraday escalation rather than more EOD configs.
- If the placebos retain the edge → it was never lattice information.
- ALIVE requires: n≥10, positive at 2× costs, DSR>0.5, non-negative median
  config, mirrored sign test, and survival of both placebos.
