# STIR Dealer Direction Classifier — Design Spec

**Date:** 2026-07-12
**Scope:** P1 (direction classifier) + P2 (tick size estimation)
**Status:** Draft

---

## 1. Goal

Classify **dealer direction** (paid or received fixed) on sub-3Y USD interest rate swap SDR prints by comparing each trade to our STIR curve mids at the time of execution. Two classification paths:

- **On-market trades:** compare traded rate (or spread) to curve mid.
- **Off-market trades (UFRO):** reprice the swap at the off-market rate → get NPV → compare to reported OPA.

This is a **separate feature** from the existing USD swaps SDR trade tape. It produces new tables consumed by a future STIR flow dashboard.

---

## 2. Trade Selection

Source: `arbs_usd_swap_tape_legs_v2` joined to `arbs_usd_swap_tape_packages_v2`.

Filter criteria:
- `economic_class = 'ECONOMIC_FLOW'`
- `contributes_to_flow = true`
- `venue = 'D2C'` (dealer-to-customer only)
- `rate_index_clean IN ('SOFR', 'FED_FUNDS')`
- `fixed_rate IS NOT NULL`
- Tenor ≤ 3Y: `tenor_years <= 3.0` OR maturity within 3 years of trade date
- `trade_type IN ('OUTRIGHT', 'CURVE', 'FLY')`

**Outrights** are classified at the leg level.
**Curves and flies** are classified at the package level.

Package eligibility rules (validated on 07/10 data):
- ALL legs of the package must be sub-3Y (mixed packages like 2Y/30Y are excluded, even though their sub-3Y legs pass the leg filter).
- Off-market package NPV must sum over ALL legs of the package — pull legs by `package_id` without the eligibility filters (the PTP covers every leg; summing a filtered subset invalidates the comparison).
- Exclude exotic underliers: CME Term SOFR, Amortizing schedules, MAC, SPREADOVER, MATCHED_MATURITY (UST-driven pricing).

---

## 3. Curve Selection

| `rate_index_clean` | Curve name |
|---|---|
| `SOFR` | `USD-SOFR-1D-Q12xM12STIRT` |
| `FED_FUNDS` | `USD-OIS-Q12xM12STIRT-SERFFX-MIX23` |

Both are Q12xM12 variants with FOMC meeting-date nodes + quarterly IMM nodes, suitable for pricing all sub-3Y tenor types (FOMC, IMM, standard spot/forward).

**Curve timestamp:** `floor(original_execution_timestamp → ET, 1min) − 1min`. This avoids lookahead bias — the dealer priced the swap ~1 minute before it hit the SDR feed. Bucket on `original_execution_timestamp` (falls back to `execution_timestamp` when NULL) per the SDRUtils area rule for intraday curve snapshots. The curve is fetched via:

```python
curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
curve_handle = curve_mdp._get_curve(curve_name=curve, timestamp=ts_minus_1min)
```

Historical curves use the `LayeredCacheMixin` disk/memory cache, so previously calibrated timestamps are instant hits.

---

## 4. Tenor Resolution

Map tape columns to IRSwapQuery tenor strings:

| `special_tenor_type` | Resolution | Example |
|---|---|---|
| `FOMC` | `f"fomc_{fomc_meeting_label.lower()}"` | `"fomc_jul26"` |
| `IMM` | Map `effective_date`/`expiration_date` to IMM codes: `"IMM_{eff}xIMM_{mat}"` | `"IMM_H2027xIMM_M2027"` |
| `STANDARD` | Spot: `tenor_label`. Forward: `f"{forward_label}x{tenor_label}"` | `"1Y"`, `"6Mx1Y"` |

Fallback for broken dates (`is_off_date=True`): pass `effective_date` and `maturity_date` directly to IRSwapQuery.

For **packages** (CURVE/FLY): each leg is resolved independently to its own tenor string.

---

## 5. Direction Classification

### 5a. On-market trades (no UFRO)

**Outrights:**
```
mid = IRSwapValue.RATE from curve at (execution_timestamp - 1min)
spread_to_mid = (fixed_rate - mid)  # in percentage points

if spread_to_mid > 0: dealer_direction = 'RECEIVED'  # custy paid above fair
if spread_to_mid < 0: dealer_direction = 'PAID'      # custy received below fair
```

**Curves (on-market, has PTS):**
```
mid_front = price_leg(curve, front_tenor) → RATE
mid_back  = price_leg(curve, back_tenor)  → RATE
mid_spread = mid_back - mid_front  # in bps

traded_spread = back_rate - front_rate  # or PTS if available

if traded_spread > mid_spread: dealer_direction = 'RECEIVED'  # dealer received the curve
if traded_spread < mid_spread: dealer_direction = 'PAID'      # dealer paid the curve
```

### 5b. Off-market trades (has UFRO)

For off-market trades, **do not** compare rate to mid. The rate is intentionally off-market; direction comes solely from NPV vs OPA.

**Outrights:**
```
Reprice at off-market rate:
  IRSwapQuery(curve, tenor, structure_kwargs={
      "notional": trade_notional,
      "fixed_rate": fixed_rate / 100   # decimal form
  }) → NPV, PV01

Compare:
  if |PTP| < |NPV|: dealer_direction = 'PAID'      # dealer bought
  if |PTP| > |NPV|: dealer_direction = 'RECEIVED'   # dealer sold

dealer_charge = |repriced_npv| - |PTP|    # bid/ask / transaction cost
dealer_charge_bps = dealer_charge / PV01  # PV01 = leg DV01 for outrights
```

**Curves/flies (off-market):**
```
Reprice each leg at its off-market rate → NPV per leg
package_npv = sum of leg NPVs (with appropriate risk-weight signs)

Compare package |NPV| to |PTP|:
  if |PTP| < |package_npv|: dealer_direction = 'PAID'
  if |PTP| > |package_npv|: dealer_direction = 'RECEIVED'

dealer_charge = |package_npv| - |PTP|
# DV01 denominator follows existing tape summary_risk convention:
#   CURVE: max(|leg DV01|)   — spread risk
#   FLY:   belly DV01        — butterfly risk
structure_dv01 = summary_risk_convention(trade_type, leg_pv01s)
dealer_charge_bps = dealer_charge / structure_dv01
```

### 5c. Key conventions (validated on 07/10 prod data)

- **`fixed_rate` in the tape DB is already decimal** (0.03713 for 3.713%) — pass it to the pricer as-is. The pricer expects decimal; `IRSwapValue.RATE` output is percentage (3.713). Passing percentage form would double-convert (`npv()` internally does `fixed_rate * 100`) and produce NPV off by 100×.
- **Dates path preferred over tenor strings:** pass `effective_date`/`maturity_date` from the tape directly to `IRSwapQuery` — reprices the exact swap as reported, handles broken dates, and is verified identical to the tenor-string path (`fomc_jul26` vs dates: 0.0000bp difference).
- **Upfront field:** use `|package_transaction_price|` (PTP) when it is a plausible USD amount (`|PTP| > $500` — smaller magnitudes are notation-polluted prices like `9.99` or `-0.000865`, not dollars); otherwise fall back to the sum of leg UFROs. On clean packages the two agree (e.g. |PTP| 48,419 vs UFRO sum 48,501).
- **Direction labels:** primary label for off-market is the cash frame — dealer **BOUGHT** (paid the upfront and holds the ITM side for less than model value) when `|upfront| < |NPV_pay|`, dealer **SOLD** when `|upfront| > |NPV_pay|`. The fixed-rate frame (PAID/RECEIVED) follows `sign(NPV_pay)`: the ITM side is the payer when `NPV_pay > 0`, the receiver when `NPV_pay < 0`; the dealer is the ITM side iff BOUGHT.

---

## 6. Tick Size & Liquidity Metrics

### 6a. Layer 1 — Structural floor (CME futures specs)

The minimum meaningful price increment is bounded by the hedge instrument's exchange-defined tick:

| Swap type | Hedge instrument | Min tick (bps) | Near-expiry tick (bps) |
|---|---|---|---|
| Fed Funds OIS, FOMC-dated | 30-Day FF futures (Ch. 22) | 0.50 | 0.25 |
| SOFR OIS, FOMC-dated | 1-Month SOFR futures (Ch. 461) | 0.50 | 0.25 |
| SOFR OIS, IMM/standard | 3-Month SOFR futures (SR3, Ch. 460) | 0.25 | 0.125 |

"Near-expiry" = contract is in its delivery month (per CME rule 22102.C / 46102.C).

DV01 per tick:
- FF / 1M SOFR: $41.67 per bp per contract → min tick (0.5bp) = $20.84
- SR3: $25 per bp per contract → min tick (0.25bp) = $6.25

### 6b. Layer 2 — Realized tick (Clarus methodology, SDR data)

**Tick size** = |rate_k - rate_{k-1}| between two time-consecutive same-tenor **on-market** D2C prints. This proxies the OTC bid/offer spread.

Key insight from Clarus: tick size varies with trade size (DV01). Bucket by (tenor_bucket, dv01_bucket):

| DV01 bucket | Range |
|---|---|
| `MICRO` | 0–5K |
| `SMALL` | 5K–15K |
| `MID` | 15K–50K |
| `LARGE` | 50K–150K |
| `BLOCK` | 150K+ |

Compute per (tenor_bucket, dv01_bucket, date):
- `mean_tick_bps`: average tick size
- `median_tick_bps`: median tick size
- `p25_tick_bps`, `p75_tick_bps`: percentiles
- `sample_count`: number of consecutive-trade pairs

### 6b-i. Tick pair validity

A tick pair is valid only when the two prints are consecutive in market time: same (tenor_bucket, structure_type), both on-market D2C, and separated by ≤ 60 minutes (else the pair measures drift, not bid/offer). Pairs spanning a session boundary are dropped.

### 6b-ii. BoE SWP 580 liquidity variables (per tenor_bucket, day; bps-DV01 space)

- **DispVW** — DV01-weighted RMS deviation of traded rates from the bucket-day DV01-weighted average rate (model-free):
  `DispVW = sqrt( Σ_k (dv01_k/Σdv01) · (rate_k − vwap_rate)² )` in bps.
- **DispJNS** — same weighting, deviations from OUR t−1min curve mid per print (improves on BoE's end-of-day mid):
  `DispJNS = sqrt( Σ_k (dv01_k/Σdv01) · spread_to_mid_bps_k² )`.
- **Amihud** — |daily change in bucket mid| / Σ DV01 traded, averaged over the window (price impact per unit DV01; consumed by the P4/P5 signal phases).

**Curve-quality gate:** if `DispJNS / DispVW > 2` for a bucket-day, the market agrees with itself but not with our curve → set `curve_suspect = true` for that bucket-day and cap all its classifications at LOW confidence. This is the automated check for prints like the 07/10 SOFR FOMC JUL26 outright (−3.1bp "through mid").

**Execution-quality / aggressiveness score:** per print, `|spread_to_mid_bps|` (on-market) or `dealer_charge_bps` (off-market) ÷ expected tick for its (tenor, DV01) bucket — Clarus slippage-to-benchmark inverted into an information weight for the future imbalance signal (a customer paying 2× the expected tick traded urgently).

### 6c. Separate tick populations

| Trade structure | Tick definition |
|---|---|
| Outright | \|rate_k - rate_{k-1}\| on consecutive same-tenor outright prints |
| Curve spread | \|spread_k - spread_{k-1}\| on consecutive same-tenor-pair curve prints |

### 6d. Off-market dealer edge distribution

Off-market trades do **not** contribute to the tick size computation (their rates are intentionally off-market). Instead, compute the distribution of dealer edge:

```
dealer_charge_bps = |NPV - OPA| / PV01
```

Bucketed by (tenor_bucket, dv01_bucket), stored as `mean_dealer_charge_bps`, `median_dealer_charge_bps`.

### 6e. Confidence scoring — hump-shaped likelihood model

The realized tick S estimates the effective bid/offer, so a correctly classified on-market
customer print should land near **mid ± S/2**. Confidence is therefore hump-shaped in
|spread_to_mid| — NOT monotonic. Deviations far beyond the expected half-spread signal
curve error or data problems, not stronger conviction.

**Error decomposition** (per tenor_bucket × dv01_bucket, from the 1-month calibration):
```
S        = realized median tick               # full effective spread
DispJNS² ≈ (S/2)² + σ_mid²                    # total dispersion = spread + our mid error
σ_mid    = sqrt(max(DispJNS² − (S/2)², ε))    # fallback: futures_tick/2 when sample thin
P_flip   = 1 − Φ(|s2m| / σ_mid)               # probability the direction call is wrong
```

**On-market:**
```python
s2m = abs(spread_to_mid_bps)
if s2m > 3 * S:                     # far outside expected spread — curve error / bad data,
    confidence = 'LOW'              # not conviction (MEDIUM if is_block: real impact)
    flag curve_suspect_trade
elif s2m < 0.5 * (S / 2):           # inside the spread: side ambiguous from quote rule
    # tick rule fallback (Lee-Ready rule 2): sign(rate_k − rate_prev) on the previous
    # valid same-bucket print (≤60min, same session — the tick-pair machinery of 6b-i)
    method = 'TICK_RULE'; confidence ≤ 'MEDIUM'   # no prior print → 'LOW'
else:                               # consistent with a spread-cross
    confidence = 'HIGH' if P_flip < 0.05 else 'MEDIUM' if P_flip < 0.20 else 'LOW'
```

**Off-market:** same hump applied to `dealer_charge_bps` vs the expected half-spread:
- charge ≈ S/2 → textbook print; confidence from P_flip on the |NPV|−|upfront| gap.
  A gap ≈ 0 means the parties' agreed fair value matches ours and BOUGHT/SOLD flips with
  tiny mid error → LOW.
- charge > 3 × S → `curve_suspect_trade`, LOW (observed 07/10: the 06:47 ET pre-open
  curve print, 0.67bp charge with the JUL26 mid 2.1bp under traded).

POC validation of the hump: the user-verified FF JUL26 outright (charge 0.18bp ≈ half the
0.5bp FF tick) is a textbook print the old monotonic scheme scored LOW; the −3.11bp SOFR
FOMC print scored HIGH under the old scheme but sits 6× beyond the expected half-spread
and is exactly the print flagged manually as curve-suspect. The hump model corrects both.
Thresholds (3×S, 0.5×half-spread, 5%/20% P_flip) are POC parameters to recalibrate from
the 1-month distribution.

---

## 7. Database Schema

### `arbs_stir_direction_v1` — one row per classified trade/package

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `trade_id` | TEXT | FK→legs_v2, NULL for package-level |
| `package_id` | TEXT | FK→packages_v2, NULL for leg-level outrights |
| `as_of_date` | DATE | |
| `execution_timestamp` | TIMESTAMPTZ | |
| `trade_type` | TEXT | OUTRIGHT / CURVE / FLY |
| `rate_index_clean` | TEXT | SOFR / FED_FUNDS |
| `curve_name` | TEXT | Which curve was used |
| `curve_timestamp` | TIMESTAMPTZ | Curve calibration timestamp (exec - 1min) |
| `is_off_market` | BOOLEAN | Whether trade has UFRO |
| `classification_method` | TEXT | RATE_VS_MID / NPV_VS_OPA / SPREAD_VS_MID / PKG_NPV_VS_OPA / TICK_RULE |
| `curve_suspect_trade` | BOOLEAN | Deviation > 3× realized tick — curve error / bad data suspected |
| `curve_mid` | NUMERIC | Fair rate from curve (%, outrights only) |
| `curve_mid_spread_bps` | NUMERIC | Fair spread from curve (bps, curves only) |
| `fixed_rate` | NUMERIC | Reported fixed rate (%, outrights) |
| `traded_spread_bps` | NUMERIC | Reported spread (bps, curves) |
| `spread_to_mid_bps` | NUMERIC | On-market: (traded - mid) in bps |
| `repriced_npv` | NUMERIC | Off-market: NPV at off-market rate |
| `repriced_pv01` | NUMERIC | PV01 from pricer |
| `reported_opa` | NUMERIC | OPA/UFRO from tape |
| `reported_ptp` | NUMERIC | Package Transaction Price (signed) |
| `dealer_direction` | TEXT | PAID / RECEIVED / UNKNOWN |
| `direction_confidence` | TEXT | HIGH / MEDIUM / LOW |
| `dealer_charge` | NUMERIC | Off-market: \|repriced_npv\| - \|PTP\| (bid/ask/transaction cost) |
| `dealer_charge_bps` | NUMERIC | dealer_charge / structure_dv01 (outright=leg, curve=max leg, fly=belly) |
| `notional` | NUMERIC | Trade notional |
| `dv01` | NUMERIC | Trade DV01 |
| `tenor_query` | TEXT | Resolved tenor string(s) used |
| `classified_at` | TIMESTAMPTZ DEFAULT now() | |

Indexes: `(as_of_date)`, `(trade_id)`, `(package_id)`, `(dealer_direction, as_of_date)`.

### `arbs_stir_tick_size_v1` — per-tenor rolling liquidity stats

| Column | Type | Description |
|--------|------|-------------|
| `tenor_bucket` | TEXT | PK component — e.g. "FOMC_JUL26", "1Y" |
| `structure_type` | TEXT | PK component — OUTRIGHT / CURVE |
| `dv01_bucket` | TEXT | PK component — MICRO/SMALL/MID/LARGE/BLOCK |
| `as_of_date` | DATE | PK component |
| `futures_min_tick_bps` | NUMERIC | Floor from CME specs |
| `mean_tick_bps` | NUMERIC | On-market: avg Clarus tick |
| `median_tick_bps` | NUMERIC | On-market: median Clarus tick |
| `p25_tick_bps` | NUMERIC | |
| `p75_tick_bps` | NUMERIC | |
| `tick_sample_count` | INT | Number of consecutive-trade pairs |
| `mean_dealer_charge_bps` | NUMERIC | Off-market: avg \|NPV-OPA\|/PV01 |
| `median_dealer_charge_bps` | NUMERIC | Off-market: median |
| `edge_sample_count` | INT | Number of off-market trades |
| `disp_vw` | NUMERIC | DispVW: DV01-weighted RMS dispersion from bucket-day VWAP rate (model-free) |
| `disp_jns` | NUMERIC | DispJNS: DV01-weighted RMS of spread_to_mid vs our t−1min curve mid |
| `curve_suspect` | BOOLEAN | DispJNS/DispVW > 2 → curve wrong in this bucket-day; classifications capped LOW |
| `amihud` | NUMERIC | Amihud illiquidity: \|Δ bucket mid\| per unit DV01 traded |
| `total_dv01_traded` | NUMERIC | Daily volume in DV01 |
| `trade_count` | INT | Daily trade count |
| `window_days` | INT | Rolling window used for stats |

Primary key: `(tenor_bucket, structure_type, dv01_bucket, as_of_date)`.

---

## 8. Backfill Process

New script: `SDRUtils/_swappulse_scripts/backfill_stir_direction.py`

### 8a. POC scope

- **Direction classification:** 2026-07-10 (single day)
- **Tick size calibration:** past 1 month (2026-06-10 to 2026-07-10)

### 8b. Steps

1. **Create tables** in Supabase (DDL from Section 7).
2. **Tick size calibration** (1 month window):
   a. Query all eligible on-market D2C sub-3Y trades for the past month.
   b. For each tenor bucket: sort by execution_timestamp, compute consecutive tick sizes.
   c. Bucket by DV01, compute stats (mean, median, percentiles).
   d. Query off-market trades, classify each (needs curve lookups), compute dealer_charge distribution.
   e. Write to `arbs_stir_tick_size_v1`.
3. **Direction classification** (07/10 POC):
   a. Query all eligible trades from 07/10.
   b. Group by `(curve_name, floor(execution_timestamp, 1min))` to batch curve calibrations.
   c. For each group: calibrate curve once at (execution_timestamp - 1min).
   d. For each trade in group:
      - Resolve tenor from tape columns (Section 4).
      - If on-market outright: compare rate to mid.
      - If on-market curve: compare spread to mid spread.
      - If off-market outright: reprice at off-market rate, compare NPV to OPA.
      - If off-market curve: reprice each leg, sum NPVs, compare to UFRO.
      - Look up tick size for confidence scoring.
   e. Write to `arbs_stir_direction_v1`.

### 8c. Curve calibration batching

Group trades by `(curve_name, execution_minute)` where `execution_minute = floor(execution_timestamp - 1min, 1min)`. Calibrate the curve once per group. For a typical trading day with ~500 STIR prints, this reduces from ~500 curve calibrations to ~300 (many trades share the same minute).

Historical curves already cached via `LayeredCacheMixin` from the curve service — expect most to be cache hits.

### 8d. Error handling

- **Curve calibration failure:** mark trade as `dealer_direction = 'UNKNOWN'`, log the error, continue.
- **Tenor resolution failure:** mark as UNKNOWN, log.
- **NPV computation failure:** mark as UNKNOWN, log.
- **Missing notional for off-market:** if notional is capped/NULL, attempt to infer from PV01 ratio. If impossible, mark as UNKNOWN.
- **Seasoned legs (effective date in the past):** repricing needs historical fixings; rateslib raises when the curve's fixings series is missing a holiday date (observed 07/10: a JUN26/JUL26/SEP26 meeting strip whose front leg started 06/17 failed on the missing 07/03 July-4th-observed fixing). Mark UNKNOWN and log; a fixings-calendar patch is a follow-up.
- **PTP/UFRO disagreement:** when a package's |PTP| and UFRO sum disagree materially (>2× apart), flag the row (`quality_flag`) — the seasoned strip above reported PTP −5,392 vs UFRO sum 46,906.

---

## 9. Verified Example

**Trade:** USD-Federal Funds-OIS Compound 1D Constant FOMC JUL26/SEP26 CURVE PHYS
**Execution:** 2026-07-10 12:57:28 ET
**Curve:** USD-OIS-Q12xM12STIRT-SERFFX-MIX23 at 12:56 ET
**Type:** Off-market (UFRO = $48,500)

| Leg | Tenor | Notional | Traded rate | Repriced NPV | PV01 |
|-----|-------|----------|-------------|-------------|------|
| 1 | FOMC JUL26 | $7.4B | 3.710% | +$16,207 | $100,003 |
| 2 | FOMC SEP26 | $8.7B | 3.833% | -$108,445 | $100,328 |
| **Package** | | | | **-$92,238** | **$200,331** |

- Package |NPV| = $92,238
- PTP = -$48,419
- |PTP| ($48,419) < |NPV| ($92,238) → **dealer PAID (bought the curve)**
- Dealer charge (bid/ask) = |NPV| - |PTP| = $43,819
- Curve DV01 = max(|leg DV01|) ≈ $100K (spread risk, not gross)
- Dealer charge = $43,819 / $100,000 ≈ **0.44 bps**

---

## 10. What This Spec Does NOT Cover (Future Phases)

- **Dashboard/UI:** The `/stir-flow` page consuming these tables.
- **SR3 DV01 mapping:** Mapping classified prints to SR3 contracts by DV01 for hedging-flow prediction.
- **Rolling order flow imbalance:** Signed DV01 imbalance per SR3 contract with EWMA decay.
- **Event study:** Forward return drift calibration at T+1/5/15/30/60min after classified prints.
- **Signal generation:** Z-score threshold for trading, conditioning filters (cluster, cap-threshold, liquidity regime).
- **Live service:** 15-minute delay classifier piggybacking on the tape ingest loop.
