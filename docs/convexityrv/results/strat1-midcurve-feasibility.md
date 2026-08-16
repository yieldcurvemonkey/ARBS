**VERDICT: OBTAINABLE** — via the Barchart per-strike EOD path (not `qs_timeseries`). ~1 HTTP call per (contract, strike, right) buys that leg's ENTIRE daily history. A 2-root × 8-quarterly, 2-year panel ≈ 1,280 legs ≈ 1,900 calls ≈ **73 min — hours, not days.**

**The premise in the shared context was wrong.** "682 midcurve keys, ALL EMPTY" is false: **55 already held real daily frames before I made a single network call**, and `MMCZ26` was already a complete 28-strike × 218-day panel with coherent prices. The `no_data` majority is largely **poisoned cache** — `_fetch_barchart_eod_series` writes a permanent `no_data` marker whenever a batch drops a symbol, gated only on *some other* symbol in that batch succeeding (`STIRFutureOptionMDP.py:5335`), and only `force_refresh=True` ever retries. Proof: **8 of 8** near-money `MMAZ26` legs marked `no_data` returned **231 clean bars each** on forced refetch. Expired contracts are served too (`MMAZ24`: 314 bars, 2023-09-18..2024-12-13), so multi-year backfill is real. Each leg's history starts ~15 months before expiry.

**Live usage: ~278 HTTP calls of the 400 cap** (169 counted exactly across four runs; the fifth planned 74 legs, estimated ~109 from the measured 1.48 calls/leg, hard-bounded by its 120 cap). Rates: **0.32 s/call for legs that exist, 2.33 s/call when many don't** — the 5-attempt backoff on absent strikes is the real cost driver, so ladder accuracy matters more than call count.

**`network_calls_blocked()` = 0, and that number is meaningless here.** `cache_only()` patches `requests`; the Barchart EOD data plane is **httpx**. Measured directly: inside `cache_only()`, `requests.get`/`Session.request` are blocked while `httpx.AsyncClient.send`/`Client.send` are **not**. All my counts come from a `NetGuard` in the script that patches both. **No unattended job on this path is currently guarded** — I did not modify the shared guard; recommend extending it to httpx as follow-up.

**Headline result — a forward-vol term structure at ONE expiry (all 2026-12-11, only the underlying differs):**

| contract | underlying | ATM bp/yr | vs SFRZ26 | corr |
|---|---|---|---|---|
| SFRZ26 | SFRZ26 (spot) | 75.04 | 1.000 | 1.000 |
| 0QZ26 | SFRZ27 (+1y) | 91.60 | 1.263 | 0.706 |
| 2QZ26 | SFRZ28 (+2y) | 88.24 | 1.206 | 0.791 |
| 3QZ26 | SFRZ29 (+3y) | 85.49 | 1.138 | 0.850 |

Forward vol > spot vol everywhere; humped, peaking at the 1y-forward belly; correlation rises monotonically with forward distance; series smoothen further out (16.5 → 11.7 → 9.0 bp max daily move vs 21.2 standard). `0QZ24`/`SFRZ24` reproduces the sign in the 2023-24 regime (137.05 vs 93.34).

**The engine is validated, not asserted:** vs QuikStrike ABPV, `SFRM26` 45.01 vs 44.74 (+0.6%) and `SFRZ26` 69.08 vs 68.45 (+0.9%) — two contracts spanning a 50% level gap. Mutation-tested (τ×1.2 → −7%, τ×0.8 → +12%, τ in months → −60%, price×1.1 → +10%). 20 tie-out asserts all pass; `--mode offline` proven zero-network by blocking httpx+requests and observing 0 attempts.

**Deliverables (absolute paths):**
- `C:/Users/chris/clee/ARBS-cvx/docs/convexityrv/midcurve_feasibility.md`
- `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/sofr_midcurve_probe.parquet` — 3,873 rows, 7 contracts
- `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/sofr_midcurve_probe_coverage.json`
- `C:/Users/chris/clee/ARBS-cvx/scripts/harvest_sofr_midcurve_vol.py` — `--mode offline|probe|harvest`, `--dry-run`, `--verify`, `NetGuard` hard cap

`ust_listed_vol.parquet` untouched. No existing code modified; no git run; no strategy built.

**Hazards:** (1) never trust a `no_data` marker on this cache — and re-running a harvest is *not* free, since genuinely-absent strikes re-pay backoff each time; (2) the `cache_only()`/httpx gap above; (3) `_cme_listed_strike_rule_for_contract` uses a stale 1/16 step for 0Q/2Q — 95 of 189 historical `MMAU26` misses were 1/16 requests that never list, so harvest on the 0.125/0.25 grid only; (4) `qs_timeseries` silent-SR3 hazard stands, unchanged and un-retested; (5) 4Q/5Q (`MMD`/`MME`) untested, weekly midcurves out of scope; (6) `option_snapshot`/`option_timeseries` were not run end-to-end — they consume exactly this proven raw-EOD layer, but their ATM/delta alias resolution inherits hazard (3).