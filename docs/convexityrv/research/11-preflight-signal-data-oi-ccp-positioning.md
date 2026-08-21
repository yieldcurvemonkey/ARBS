<!-- Verbatim return of a preflight investigation agent, 2026-08-20/21.
     Measured on this machine; see the report's own probe list. Kept as
     research evidence, not as a design document. -->

# Preflight scout: open interest, CME-LCH basis, dealer positioning

All measurements complete and line references confirmed.

## VERDICT TABLE

| family | verdict | accessor | measured coverage |
|---|---|---|---|
| (a) SOFR/ED futures OPEN INTEREST | **PARTIAL** (survivorship-shaped) | `Query/STIRFutures/STIRFutureValue.py:85,112` → `pricer.meta()["openinterest"]`; cache `%LOCALAPPDATA%/ARBS/Cache/diskcache/dump/STIRFuturePricer_Cache` | SR3 daily, 97–99% of dates, **only the ~21 contracts live today** (SR3U26…SR3M31), each back to its listing. ZQ 27 rows / 4 dates. GE(ED) 1 row. |
| (b) CME-LCH basis via gs_quant | **AVAILABLE** — entitled, live, verified | `MDP/IRClearingHouseBasisSwaps/IRClearingHouseBasisSwapsMDP.py.get_pricer()` | USD SOFR/OIS/LIBOR, 1y–30y spot + fwd ladder, `historyStartDate` 2018-04-27 (catalogue). Live read returned USD SOFR 10y basis −2.00/−2.05 bp. |
| (c) DEALER POSITIONING | **AVAILABLE but 14 wks stale** (CFTC TFF) / **UNAVAILABLE** (NY Fed PD) | `BT/signals/cftc_positioning.py:83` `build_positioning_panel()` over `BT/results/tfp_screener/cftc_raw.parquet` | Weekly (modal gap 7.0d, 325/331), **2020-01-07 → 2026-05-12**, 332 report dates, 154 markets, fully offline. |

---

## (a) OPEN INTEREST — PARTIAL

**Accessors**
- `Query/STIRFutures/STIRFutureValue.py:18,85,112-121` — `OPEN_INTEREST` reads `pricer.meta()["openinterest"]`.
- `MDP/STIRFutures/STIRFutureMDP.py:904` `_fetch_barchart_eod_oi()` — the only futures OI fetch (Barchart `queryeod`, `merge_val_col="Open Interest"`).
- `MDP/STIRFutures/STIRFutureMDP.py:1145` — **the gate**: `if want_eod and src == "BARCHART_STIRF-RL"`. Intraday and TOS-live never fetch OI. Measured: TOS_LIVE **0 / 17,910,002** rows carry OI; BARCHART **3,387,029 / 4,694,464** (72.1%).
- `RVUtils/MeanRev/panel.py:135` `structure_liquidity(cols=("volume","open_interest"))` — consumer, takes min across legs.
- `RVUtils/SFRConvexScreener/_market_data.py:151` — live screener read.

**Measured cache census** (22,604,466 rows across 8 shards; 14.98% carry `openinterest`):

EOD keys only (17:00 NY), distinct (date,symbol): SR3 41,437 rows / 2,100 dates 2018-05-04→2026-08-19; ZQ 73,954 / 2,084; GE 395 / 148.

SR3 dates with ≥1 positive OI, by year: 2018 **0.0%**, 2019 0.4%, 2020 0.4%, 2021 4.0%, 2022 34.0%, 2023 79.8%, 2024 **99.6%**, 2025 99.6%, 2026 98.7%.

**The dominant finding — the panel is survivorship-shaped, not liquidity-shaped.** Per-symbol OI-coverage fraction splits into two disjoint groups with no middle:
- `SR3H20…SR3M26` (all **expired**): frac **0.004–0.028** (2–34 dates of 1,200–1,700 cached).
- `SR3U26…SR3M31` (all **still live** today): frac **0.976–0.996**.

The boundary sits exactly at the live/expired line (SR3M26 = 0.008, SR3U26 = 0.980; today is 2026-08-20). The values themselves are genuine, correctly date-stamped history — SR3U26 runs 835 dates 2021-10-27→2026-08-18, OI 24 → 1,402,860, gaps {1d:566, 3d:137}. So the year×rank grid (2024: rank 1-7 = 0%, rank 11-20 = 100%; 2026: rank 5+ = 100%) is the *calendar drift of a fixed code set*, not vendor coverage. **Any historical study on front ranks before ~2025 has no OI**, because that contract has since expired and was never harvested.

**Tie-out (independent validation of my census tool):** summing cached per-contract SR3 OI vs CFTC `Open_Interest_All` for SOFR-3M on 40 common dates → ratio median **0.609**, range 0.514–0.892, and OI declines monotonically with rank (2026-05-12: SR3U26 1,360,639 → SR3H31 46,916). Below 1 exactly as predicted: cache holds 18–20 deferred contracts, CFTC counts the whole strip incl. the missing front.

**MEASURED DEFECT — the last-bar zero reaches the futures path.** `blank_unpublished_open_interest` (`MDP/STIRFutures/BARCHART/BarchartFetcher.py:601`) is called **only** from the options path, `STIRFutureOptionMDP.py:5002` and `:5297`. The futures path instead does:
```python
# MDP/STIRFutures/STIRFutureMDP.py:1155-1161
def _lookup_oi(symbol: str) -> Optional[float]:
    series = oi_df[symbol].dropna()
    return float(series.iloc[-1])
```
`dropna()` does not remove a zero, and the fetch window (`:922-924`) ends at `ts_dt` — the fabricated-zero bar. Measured: **42 zero-OI rows on exactly 3 dates** — 2025-04-17 (15 SR3), 2026-08-07 (7 ZQ, i.e. all of them), 2026-08-19 (20 SR3, i.e. the entire live set, yesterday). Confirms the trap bites when the as-of date is the current/most-recent session, and does not bite historical backfill (published by then).

**Not measured:** whether `queryeod` serves OI for **expired** contracts (fetch prohibited by hard rule 4). The path that would answer it is `BarchartFetcher.barchart_timeseries_api(merge_val_col="Open Interest")`, ~1 request/contract. Do not assume the pre-2025 hole is backfillable.

**Other OI sources checked:** `RVUtils/MBO/` — grep for open.?interest returns **nothing** (order-flow engine, no OI). QuikStrike (`MDP/STIRFutures/QuikStrikeSDK/core/_BaseQuikStrikeFetcher.py:219-220`) carries `open_interest_date`/`open_interest_status` — publication *metadata*, not an OI series. `scripts/` — no OI. No CME-direct OI feed is wired.

**Caveat on rank:** rank was computed among contracts present in the pricer cache per date, not among all listed contracts (2026-05-12 begins at rank 2). Price coverage is dense (2,100 dates) so slippage is small, but the grid overstates precision slightly.

**Nearest proxy for the missing pre-2025 history:** CFTC TFF `Open_Interest_All` for `SOFR-3M`/`3-MONTH SOFR` — weekly whole-contract aggregate, 2020-01-07→2026-05-12, 131,476 → 13,320,834, contiguous across the Feb-2022 rename (2022-02-01 2,711,352 → 2022-02-08 2,869,048). No per-contract dimension.

## (b) CME-LCH BASIS — AVAILABLE

**Dataset id: `IR_SWAP_RATES_V1_STANDARD`**, assets tagged per clearing house, matched by `parse_coverage_name` (`gs_quant_fetcher.py:11-19`, pattern `^(ccy) Swap (index) \S+ ATM \S+ to (tenor) (clearing_house) Cleared$`).

Offline catalogue (`MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx`, 33,111 rows, 33,057 parse): clearing houses LCH 21,721 / CME 4,532 / EUREX 4,301 / JSCC 2,503. **Exactly 3 (ccy,index) pairs carry both LCH and CME**: USD SOFR (1,145/1,146), USD OIS (899/899), USD LIBOR (2,487/2,487). Spot-start ladder 1y,2y,3y,4y,5y,7y,10y,15y,20y,25y,30y all present at both CCPs, `historyStartDate` 2018-04-27 (USD SOFR both CCPs; USD OIS 2010-01-04; USD LIBOR 1999-01-01).

**Second CCP-tagged dataset (candidate, previously unused): `IR_BASIS_SWAP_RATES_V1_STANDARD`** — 40,221 assets, 100% "Cleared", LCH 34,637 / CME 2,972. USD LCH+CME matched pairs on `SOFR/OIS` (801 each), `SOFR/1m` (544), `SOFR/3m` (542), `SOFR/6m` (540), `SOFR/12m` (538). The repo's `_NAME_PATTERN` matches **0** of these (name form is `BasisSwap USD SOFR/OIS ATM <fwd> to <tenor> <CH> Cleared`) — a second regex is needed to use it.

**Live entitlement — confirmed, exactly 2 calls:** auth OK 0.3s; `Dataset("IR_SWAP_RATES_V1_STANDARD").get_data(2026-08-10, 2026-08-14, assetId=[MA4X9S4FR3MNW2JQ (LCH), MASHESG4P65M6ST5 (CME)])` OK 1.2s, shape (8,8), columns `[date, assetId, pricingLocation, csaTerms, rate, effectiveDate, terminationDate, annuity, updateTime]`. **USD SOFR 10y LCH−CME basis: 2026-08-10 −2.00 bp, 08-11 −2.05, 08-13 −2.05, 08-14 −2.05.** Note only 4 of 5 business days returned — **2026-08-12 absent, unexplained, not investigated**.

**Credentials:** `GS_CLIENT_ID`, `GS_CLIENT_SECRET`, `GS_QUANT_CLIENT_ID`, `GS_QUANT_SECRET`, `GSQUANT_CLIENT_ID` all **unset**; no `.env` (only `docs/.env.example`, `SDRUtils/dashboard/.env.example`). Auth succeeded on **hardcoded literals committed to the repo at `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py:7-8`** (client_id len 32, secret len 64), resolved at `:63-64`. Values not reproduced here. **This is a checked-in live secret and should be treated as a finding.**

**Two integration defects:** `IRClearingHouseBasisSwapsMDP` has **no caching layer** (no diskcache dir `GSQUANT_CH_BASIS` exists — every call refetches); and its default `coverage_path` at `IRClearingHouseBasisSwapsMDP.py:34` hardcodes `C:\Users\chris\clee\ARBS\...` — the **primary checkout**, not the worktree (the file does also exist in cvx2).

**Not measured:** actual served history depth. 2018-04-27 is the catalogue's claim (xlsx dated Dec 2025), not a measurement — the 2-call budget covered 4 days only. Fallback if entitlement ever lapses: 5 Clarus/FIA PDFs in `C:/Users/chris/Downloads/convexityrv/` (`CME-LCH Basis For Dummies`, `CME-LCH Basis Spread`, `CME-LCH Basis - What does the Term Structure tell us`, `Hedging the CME-LCH Basis`, `CME-LCH Basis: Convexity in Eurodollar Futures`, plus `CME vs. LCH_ Take Two _ FIA.pdf`) — published levels usable as a tie-out, **not a time series**.

## (c) DEALER POSITIONING

**AVAILABLE (stale) — CFTC Traders in Financial Futures.** Local cache `BT/results/tfp_screener/cftc_raw.parquet`, weekly, 2020-01-07→2026-05-12.

Raw carries the full TFF column set including `Dealer_Positions_Long_All`/`Short_All`, `Asset_Mgr_*`, `Lev_Money_*`, `Open_Interest_All`, `Pct_of_OI_Dealer_*`, `Traders_Dealer_*`, `Change_in_Dealer_*`.

`build_positioning_panel()` produces (1656, 4) daily-ffilled panels for 2Y/5Y/10Y/30Y, 1,656 non-null per column, 2020-01-07→2026-05-12, for `lev_net`/`am_net`/`total_net`. Coverage is continuous across the Feb-2022 market rename because `_CONTRACT_MAP` (`cftc_positioning.py:22-43`) lists both vintages (`2-YEAR U.S. TREASURY NOTES…` n=109 to 2022-02-01; `UST 2Y NOTE…` n=223 from 2022-02-08).

**Gap worth one line of code:** `build_positioning_panel` extracts only lev/am — there is **no `dealer_net` metric**, yet the raw column exists and is fully populated. Measured directly: 2Y n=332 dealer_net range −557,177…+40,213 (last −369,528); 5Y −978,189…−16,058 (last −549,334); 10Y −793,974…+176,777 (last −655,582); 30Y −603,201…−99,316 (last −520,426). **This is the answer to "primary dealer positioning"** — the TFF Dealer/Intermediary category, already on disk.

**STIR positioning also present in the same cache** (12 markets): `SOFR-3M` n=223 2022-02-08→2026-05-12 (dealer_net last +1,719,008), `3-MONTH SOFR` n=109 2020-01-07→2022-02-01, `SOFR-1M` n=223, `FED FUNDS` n=223, `EURODOLLARS-3M` n=71 →2023-06-13, `3-MONTH EURODOLLARS` n=109, plus 2/3/5/7/10Y ERIS SOFR SWAP.

**MEASURED DEFECT — the cache never refreshes:**
```python
# BT/signals/cftc_positioning.py:51-52
if cache_path and Path(cache_path).exists():
    return pd.read_parquet(cache_path)
```
Unconditional short-circuit before any date check. Last report date 2026-05-12; today 2026-08-20 → **~14 weeks stale**, and no call site can refresh it without deleting the file. Only caller: `notebooks/backtests/pca_mmss_dislocation_gridsearch.ipynb:111`.

**UNAVAILABLE — NY Fed primary dealer statistics.** Grep for `newyorkfed|nyfed|primarydealer|pd_stats|SBN2|markets.newyorkfed` across `*.py`/`*.ipynb`/`*.md` returns only SOFR/EFFR *fixings* usage (`BT/serff/data.py:3`) and prose citations in `docs/`. No PD-stats fetcher, no cache, no schema. Nearest proxies: the TFF Dealer category above, and `SDRUtils/dealer_direction/`.

**JPM package corpus carries NO positioning and NO open interest — schema-measured, not assumed.** All 8 parquets in `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/` scanned for any column matching `open_int|openint|oi|volume|position|posn|dealer|flow`: **NONE** in every file (treasury_vol 21,286×48, stir_vol 18,914×48, midcurve_vol 18,879×48, skew 59,503×17, skew_atm 7,432×12, otc_exchange_ratio 5,212×15, maturity_structure 5,118×14, swaption_vol 33,800×19). Consistent with `RVUtils/ConvexityRV/jpm_package.py` — grep for open-interest/volume/position in that module hits only the word "volatility". The package is a **vol product**; `docs/convexityrv/results/jpm-package-parser.md` §1 confirms every parsed report is a volatility table. **Note: these artifacts live in the `ARBS-cvx` worktree, not `ARBS-cvx2` — `notebooks/data/convexity_rv/` does not exist in cvx2** (0 jpm parquets).

**`SDRUtils/dealer_direction/ladder.py:432` `interdealer_flow` — a FLOW series, explicitly not an inventory.** Its own header (`ladder.py:1-22`) states accumulating it into a position "carries an unbounded, *monotone* error". Coverage **not measured**: no local `sdr_cache` found at the paths checked; the source is remote-fetch, and per the task's `ARBS_SUPABASE_ENABLED=0` constraint I did not query it. Repo memory records this line of work as concluded no-signal.

---

## NOT MEASURED (explicit)

1. Whether Barchart `queryeod` serves OI for **expired** contracts — fetch prohibited; determines if the pre-2025 SR3 hole is backfillable.
2. gs_quant **actual** history depth — catalogue-claimed 2018-04-27; only a 4-day live window was read (2-call budget).
3. Why 2026-08-12 is missing from the gs_quant 5-business-day window.
4. `SDRUtils/dealer_direction` coverage window — remote-only source, not queried.
5. CFTC live-fetch behaviour (`fetch_cftc_financial_futures` network path) — not run.

## PROBE SCRIPTS (all runnable, all offline except `probe_b3`)

Scratch dir: `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/`

| script | proves | runtime |
|---|---|---|
| `probe_c_positioning.py` | CFTC schema/window; JPM 8-parquet OI-column scan | 0.1s |
| `probe_c2_cftc_detail.py` | renamed markets, dealer_net, STIR OI, rename continuity | 2.5s |
| `probe_a1_cache_shape.py` | diskcache key format, 2.8M rows/shard | 1.6s |
| `probe_a2_oi_presence.py` | 22.6M-row OI census by source × root × year | 129.5s |
| `probe_a3_eod_oi_rank.py` | EOD OI by year/rank; the 42 zero rows → `eod_oi_census.parquet` | 7.5s |
| `probe_a4_oi_shape.py` | survivorship split (0.004–0.028 vs 0.976–0.996) | <1s |
| `probe_a5_tieout.py` | cache-vs-CFTC tie-out, ratio median 0.609 | <1s |
| `probe_b1_gs_coverage.py` | 33,057 CCP-tagged assets; 3 LCH+CME pairs; creds unset | 1.5s |
| `probe_b2_hist_window.py` | historyStartDate per CCP; `find_asset_pair` resolves 10y | <1s |
| `probe_b3_gs_live.py` | **2 network calls** — entitlement + −2.00/−2.05 bp basis | 5.1s |

Run pattern used for every one:
```
ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe "<scratchpad>/<script>.py"
```
