The confirmed flake passes in isolation. All work is complete and verified.

## STRAT 2 ON THE Q20 CURVE — DEEP PACKS

### 1. The brief's premise is false, and that is the first finding
There is **no `USD-SOFR-1D-Q20STIRT` curve store** on this machine. `curve_store/raw` carries Q12STIRT (2,061 dates) and Q16STIRT (197 dates, 2024 only); no Q20 asset exists. Worse, `IRSwapsMDP.get_pricer` for that curve makes **52–57 Barchart requests per date** and `offline=True` is passed through and ignored. Root cause, measured: `BARCHART_STIRF_CURVE.__init__` (`MDP/IRSwaps/BARCHART_STIRF/rl.py:1039`) wires its pricer fetcher to `STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")` — the **intraday** source, which reaches depth 20 on **zero** local dates. So even a fully-cached date misses and crawls.

Fix: `build_q20_pricer` fetches `SFRCM1..k` from the **17:00 EOD** `BARCHART_STIRF-RL` source and injects them into the production `_build_curve_from_pricers` (same node construction, same Levenberg-Marquardt solve, no shared store mutated). **0 requests, ~0.15s/date.** Every build is wrapped in `cache_only()`; across the 1,410-date panel build, the executed notebook and the tests, **nothing was sent**. The 77 attempts recorded came from 2 dates with no local data and were all blocked. One further attempt seen in the backtest was a NY Fed **SOFR fixings** top-up (not Barchart), served from local cache — all 743 marks complete.

Also measured: the config carries `SFRCM1..`**`20`**, not `..21` as the brief stated; `max_tenor_from_timestamp_months=60`.

### 2. The 2019 rejection was right about the front end and wrong about the deep end
The prior work measured 9.375bp median disagreement in 2019 — **pooled across ranks**. Decomposed (median max|settle − Q20 fwd|, bp):

| year | ranks 1‑4 | 5‑8 | 9‑12 | 13‑16 | 17‑20 |
|---|---|---|---|---|---|
| 2018 | 16.983 | 12.793 | 3.872 | **0.280** | **0.281** |
| 2019 | 15.765 | 10.004 | **0.268** | **0.258** | 0.549 |
| 2020 | 0.691 | 0.354 | 0.226 | 0.309 | 0.370 |
| 2022 | 1.542 | 0.629 | 0.398 | 0.307 | 0.788 |
| 2023 | 1.661 | 0.797 | 0.348 | 0.646 | 1.900 |

Mechanism, identified exactly: every `*STIRT` node grid is built from the central-bank meeting map, and `central_bank_dates/meeting_dates_v1.json` for `USD-SOFR-1D` **starts apr21 (2021-04-28)**, 56 windows to sep27. Before then the *front* is one log-linear segment while deep windows sit in a resolved region. `spans_window` in 2019: ranks 1‑4 = 78.9%, 5‑8 = 5.4%, **9+ = 0.0%**. Gate pass 2019: ranks 1‑4 = **0.0%**, 5‑8 = 20.9%, 9‑12 = 94.3%, 13‑16 = **100%**.

`CA≥0` and `corr(CA,T1²)` are **reported but never gated on** — both sources violate `CA≥0` at the same rate (29.2% vs 29.5%), so it is a market property (ZIRP), not a source property.

### 3. Gate (`strat2_q20.window_gate`)
Three independent conditions per (date, window): **resolution** (`spans_window==0`, ≥1 node inside, forward spread ≥1bp), **settle agreement** (`max` over the four contracts — not mean — ≤ **2.0bp**, set at the measured EOD-timing noise floor 0.89–2.55bp/pack-day), **coverage** (`rank+3 ≤ depth`). Incidence: covered 100%, resolved 89.7%, agrees 77.9%, **ok 76.9%** (16,655/21,671).

Control: gate-passed, ranks ≥9 (n=9,554) — median |CA_q20 − CA_settle| = **0.0366bp**, p95 0.2773bp, **corr 0.99990**. Rank 13: 0.0279bp, corr 1.0000. Rank 17: 0.0184bp, corr 1.0000. Gated, the Q20 forward **is** the settlement mark.

### 4. Tie-out — Citi Fig 58, close 6/9/2023, all 13 rows
Q20: mean **−0.008bp**, median −0.560, sd 1.695, |max| 3.060, corr **0.9659**. Settles: mean −0.109, median −0.580, |max| 3.120, corr 0.9667 (reproduces the documented near-pack tie-out exactly). Implied-vol inversion of Citi's own CA vs Citi's own IV column: median **0.9973** (0.9940–0.9980). All 13 rows pass the gate.

**BLUES M6-H7: Citi 15.40 → ours 15.72 (+0.32bp). GOLDS M7-H8: Citi 22.29 → ours 21.73 (−0.56bp).** Both unreachable at rank ≤10.

### 5. Why deep packs (2021‑23, gate-passed)
Noise (Roll/MA(1)) barely grows while the adjustment grows four-fold: **ranks 1‑8 noise/CA-level 30.1%, CA-implied vol error 15.1%; ranks 13‑17 noise/level 6.7%, vol error 3.4%.**

### 6. Zero-convexity control (Q/Q throughout, via `matched_forward_swap_rate`)
Median ≈0.00bp across 21,671 rows; residual equals the no-free-parameter annuity term (control − prediction: mean −0.0019bp, sd 0.1447bp). Annual-vs-Q/Q gap `~b·r²`: **b = 0.37195 vs predicted 0.375 (−0.81%), r² 0.9982**, intercept +0.036bp. **Caveat stated in the notebook**: at ranks ≥9 `USD-SOFR-1D` carries ~1 node per window and forward spreads of only 0.05–13bp, so the control is **underpowered exactly where the deep packs live** — the settle-agreement gate carries the weight there.

### 7. Staleness
The default auto-reference rule picks `SR3H27` (present 117/1,410 dates) on a rolling strip and finds nothing — a real defect in usage. With an explicit always-present FRONT reference: repeat_price 0.638%, stale_run 0.055%, jump_after_stale 0.007%, **4 catch-up dates**. Detector mutation-verified (injected 5 repeats + 10bp catch-up in the 2022 hiking cycle — a mutation placed in ZIRP is unfalsifiable because the reference never moves ≥0.5bp).

### 8. Backtest — windows 9..14 (traded ranks 9‑13, **includes Blues**), 743 days 2019-06-20..2023-02-01

| run | P&L | Sharpe | maxDD | ex-catchup P&L | ex-catchup Sharpe |
|---|---|---|---|---|---|
| deep Q20 unhedged | −$421,378 | −0.106 | −$1,410,456 | −$382,740 | −0.096 |
| deep Q20 hedged | **+$1,036,450** | 0.212 | −$2,565,956 | +$1,879,005 | 0.403 |
| deep settle unhedged | −$963,821 | −0.252 | −$1,885,474 | −$925,183 | −0.242 |
| deep settle hedged | **+$2,296,819** | 0.343 | −$2,650,248 | +$3,139,798 | 0.480 |
| near settle, same gate (301d 2020-12-01..2022-03-23) | +$116,038 | 0.068 | −$1,008,434 | — | — |
| near settle hedged, same gate | +$852,414 | 0.515 | −$858,243 | — | — |
| **published near-pack reference** (2020-08-03..2024-05-08) | +$5,054,411 | 0.470 | — | — | — |
| **published near-pack hedged** | +$4,448,142 | 0.409 | — | — | — |

The published near-pack figure is **not comparable on window**: it spans 2020-08..2024-05 and owes most of its P&L to the 2023–24 CA narrowing, which lies entirely outside the deep window. On a common gated window the near strategy made +$116k unhedged. Dropping the 2 in-window catch-up days **raises** deep P&L (the flagged days carried losses, so the result is penalised by staleness, not manufactured by it) — but 2 days moving hedged P&L by ~$0.8mn bounds the precision of every headline number above.

### 9. Honest caveats
- **Selection fragility (dominant).** The two sources agree on CA level to 0.03bp and correlate at 1.0000, yet pick the same pack on only **134/149 screen days (89.9%)** — the ranking compares near-identical numbers, so a 0.03bp difference flips an entire epoch. That is the ~2× P&L spread between sources, and it is a statement about the strategy, not the rate source.
- **Golds is screenable but not backtestable.** Rank 17 needs depth 20 → 681 dates whose longest gap-free run is 2019-09-13..2020-12-16 (309 days, entirely ZIRP, leaving ~57 tradeable days after a 252-day z-score warm-up). Data-coverage limit, not modelling — the code produces Citi's exact 13 rows when the strip is warm.
- **IMM roll off-by-one (found and fixed).** The `SFRCM` ladder rolls on the IMM date; the pack universe does not. 8 of 10 network reaches in the first build were roll dates; `instrument_count` fixes it (failures 10 → 2).
  - **Superseded 2026-08-19 — fixed at source instead.** The two ladders were reconciled rather than bridged: `tos._imm_cutoff` now returns IMM + 1 day, so the MDP keeps the contract whose reference quarter begins today, and the `instrument_count` `-1` shim was deleted in the same change. The evidence that settled which side is right (the vendor “continuous ladder” corroboration was circular; the ending contract is off-grid 18/18 on IMM dates and the starting one on-grid 32/32) is in `RVUtils/ConvexityRV/packs.py`'s module docstring. Measured on a full 1,946-date rebuild: every non-IMM date bit-identical; on the 31 IMM dates the front leg's `|settle − Q20 forward|` fell from a median 6.84bp to 1.13bp, improving on 30/30 dates.

### Files (all absolute)
- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat2_q20.py`
- `C:/Users/chris/clee/ARBS-cvx/scripts/strat2_q20_build.py`
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat2_q20_deep_packs.py` + executed `.ipynb` (**28 code cells, 0 unrun, 0 errors, 6 plotly figures, 0 network calls**)
- `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_strat2_q20.py` — 30 pass, **8/8 mutations caught**
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/run_convexity_rv.py` — added `strat2_q20_deep_packs` to `NOTEBOOKS`
- Data: `notebooks/data/convexity_rv/strat2_q20_{panel,rates,settles,equity,equity_near}.parquet`, `strat2_q20_{skips,epochs}.json` (all under `C:/Users/chris/clee/ARBS-cvx/`)

### Test status
343 convexity tests pass. Full fast gate: **8,264 passed, 1 failed, 60 skipped** — the failure is `tests/test_citivelo_read_path_perf.py::test_fixings_kwargs_resolve_once_per_wrapper`, which **passes in isolation** (order-dependent flake in a CitiVelo perf test, unrelated to these files; nothing here touches CitiVelo fixings caching).