# STIR Dealer Direction Classifier — POC Results (2026-07-13)

## Run Parameters

- **Classify date:** 2026-07-10
- **Tick calibration window:** 2026-06-10 to 2026-07-10 (30 days)
- **Calibration mode:** ticks-only (no month-long curve repricing for DispJNS/dealer-charge)
- **Tables written:** `arbs_stir_direction_v1`, `arbs_stir_tick_size_v1`

## Direction Classification (07/10)

| Metric | Value |
|--------|-------|
| Total eligible legs queried | 1,775 |
| Units classified | 562 |
| Units excluded | 1,213 (914 LEG_BEYOND_3Y, 234 EXCLUDED_TRADE_TYPE, 65 EXCLUDED_UNDERLIER) |
| PAID | 378 (67.3%) |
| RECEIVED | 181 (32.2%) |
| UNKNOWN | 3 (0.5%) |

### Confidence Distribution

| Direction | HIGH | MEDIUM | LOW |
|-----------|------|--------|-----|
| PAID | 169 | 35 | 174 |
| RECEIVED | 67 | 21 | 93 |

### Golden Trade Verification

| Unit Key | Method | Direction | Bought | Charge (bps) | Confidence | Expected |
|----------|--------|-----------|--------|-------------|------------|----------|
| 4137861837000000101 | NPV_VS_UPFRONT | PAID | True | 0.183 | LOW | 0.183bp ✓ |
| PTP_4135370792000000201 | NPV_VS_UPFRONT | RECEIVED | True | 0.457 | HIGH | 0.457bp ✓ |

## Tick Size Calibration

- **Tick stat rows:** 4,249 (across all tenor_bucket × structure_type × dv01_bucket × date combos)
- **FOMC_JUL26 ALL bucket:** median tick 0.13–0.25bp (below 0.5bp FF futures tick — consistent with FOMC meetings trading sub-tick)
- **Sample counts:** 7–16 tick pairs per day for JUL26

## Curve Suspect Rates

Top flagged tenor buckets (curve_suspect_trade = true):

| Tenor Bucket | Suspect | Total | Rate |
|-------------|---------|-------|------|
| 2Y | 33 | 65 | 50.8% |
| FOMC_JUL26 | 29 | 53 | 54.7% |
| IMM_1Y | 10 | 33 | 30.3% |
| IMM_2Y | 10 | 19 | 52.6% |
| 3Y | 9 | 48 | 18.8% |
| FOMC_OCT26 | 8 | 8 | 100.0% |

High suspect rates on 2Y, IMM_2Y, and FOMC_OCT26 are expected — these tenors sit at the edge of the Q12xM12STIRT curve's calibration density. FOMC_JUL26's 55% suspect rate reflects the known ~2bp systematic mid offset on 07/10 (the curve's JUL26 node was stale relative to the traded FOMC pricing).

## PRICING_ERROR Units (UNKNOWN)

Only 3 units landed UNKNOWN — all from seasoned-leg repricing failures (rateslib fixings gap on 2026-07-03 holiday). This matches the known issue documented in the plan.

## Observations

1. **PAID skew (67/33):** Consistent with net dealer buying on 07/10 — dealers absorbed customer receiving flow, consistent with a rate-cutting environment where customers lock in higher fixed rates.
2. **Charge distribution:** Golden trades bracket the range: 0.18bp (textbook print, half the FF tick) to 0.46bp (moderate curve spread). The hump model correctly scores 0.18bp as LOW (near mid) and 0.46bp as HIGH (clear spread-cross).
3. **Tick-rule fallback:** Active for ambiguous prints near mid. Reduced UNKNOWN from 18 (pre-fix) to 3.
4. **Sub-tick FOMC trading:** Median ticks 0.13–0.25bp vs 0.50bp futures tick confirm that FOMC OIS markets trade inside the exchange minimum — the swap dealers offer tighter markets than the listed hedge.
