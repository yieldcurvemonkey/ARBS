# FOMC-Dated Swap Analytics Notebook — Design Document

## Overview

A dedicated Jupyter notebook (`notebooks/sdr/11_fomc_swaps.ipynb`) providing comprehensive analytics for FOMC-dated OIS swaps — combining SDR flow analysis with implied policy rate extraction.

FOMC-dated swaps are OIS contracts whose effective/maturity dates align with FOMC meeting boundaries. Each meeting period spans from one FOMC effective date to the next (e.g., Jan25: 2025-01-29 to 2025-03-19). These swaps directly price the expected overnight rate for that specific meeting period, making them the cleanest expression of individual meeting expectations.

**Scope:** USD SOFR/FedFunds FOMC-dated swaps from DTCC SDR data, enriched with curve-based pricing.

---

## Architecture

```
notebooks/sdr/11_fomc_swaps.ipynb

Part 1: Flow Analytics
  ├── FOMC calendar + trade extraction
  ├── Volume by meeting (DV01 bar/time series)
  ├── Activity timing around meetings (T-10..T+2 profiles)
  └── FOMC swap characteristics (notional, packages, blocks)

Part 2: Implied Rate Extraction
  ├── Meeting-by-meeting implied SOFR (SDR VWAP + curve-based)
  ├── Cut/hike probability extraction
  ├── Term structure of meeting expectations ("FOMC curve")
  └── FOMC calendar spreads (meeting-to-meeting)
```

---

## Integration Points

| Component | Usage |
|-----------|-------|
| `_CENTRAL_BANK_DATES["USD-SOFR-1D"]` | Meeting schedule: `(effective_date, maturity_date)` per meeting |
| `_CENTRAL_BANK_DATES["USD-FEDFUNDS"]` | FedFunds meeting dates (same meetings, same dates for USD) |
| `resolve_central_bank_tenor(curve_id, token)` | Price FOMC-tenor swaps off the SOFR curve |
| `SDRUtils.core.tenors.get_fomc_label()` | Detect FOMC-dated trades in SDR data |
| `classify_intrinsic_special_tenor()` | Tags trades with `special_tenor_type == "FOMC"` |
| `IRSwapQuery` + `IRSwapsMDP` | Curve-based implied rate extraction per meeting |
| `curve_store` | Historical FOMC curve snapshots for time-series comparison |
| `_sdr_common.py` | Data loading, DV01 enrichment, filtering, viz helpers |
| `SDRUtils.analytics.seasonality.get_fomc_dates()` | Flat list of FOMC meeting dates |

---

## Detailed Cell Design

### Part 1: Flow Analytics

#### Cell Group 1 — FOMC Calendar & Trade Extraction

Build the FOMC meeting schedule from `_CENTRAL_BANK_DATES["USD-SOFR-1D"]`:
- Each entry is `label -> (effective_date, maturity_date)` e.g., `"jan25" -> (2025-01-29, 2025-03-19)`
- The effective_date is the FOMC meeting date; maturity_date is the *next* meeting date
- A swap spanning this period prices the expected average SOFR for that meeting window

Filter classified SDR trades to FOMC-dated:
- Primary: `special_tenor_type == "FOMC"`
- Fallback: match effective/expiration dates against meeting boundaries
- Assign `meeting_label` (e.g., "Jan25") to each trade based on which meeting period it spans

#### Cell Group 2 — Volume by Meeting

- Bar chart: total DV01 per FOMC meeting label (upcoming meetings)
- Time series: daily DV01 of all FOMC-dated trades with meeting dates as vertical lines
- Near vs far split: DV01 share in next 1-3 meetings vs 4-8 meetings — where is positioning concentrated?

#### Cell Group 3 — Activity Timing Around Meetings

- For each meeting: volume profile in T-10 to T+2 business days window
- Average across all meetings: composite event profile — does flow peak T-1? T-3?
- "Live" vs "skip" comparison: split meetings by whether consensus expected a rate change vs hold. Proxy: pre-meeting implied probability > 50% = "live"

#### Cell Group 4 — FOMC Swap Characteristics

- Notional distribution: histogram of FOMC swap notionals vs standard outrights
- Package detection: do FOMC swaps appear as outrights or part of FOMC curves/flies?
  - FOMC curve = simultaneous trades in two consecutive meeting periods (e.g., Jan25 vs Mar25)
  - Detection: same timestamp, different meeting labels, offsetting direction
- Block/capped analysis: fraction of FOMC trades that are block-eligible or capped

### Part 2: Implied Rate Extraction

#### Cell Group 5 — Meeting-by-Meeting Implied SOFR

Two extraction methods:

**SDR-based (direct market observation):**
- For each meeting period, compute VWAP of FOMC-dated swap fixed rates from SDR trades
- Weight by DV01 (or notional where DV01 unavailable)
- Use most recent trading day's VWAP as "current" implied rate

**Curve-based (model-consistent):**
- Use `IRSwapsMDP` to get the current SOFR curve
- For each meeting period `(eff, mat)`, use `IRSwapQuery` to price a swap from eff to mat
- Extract the implied par rate = the market-implied average SOFR for that period

Output table:
```
Meeting | Eff Date   | Mat Date   | Implied (SDR) | Implied (Curve) | Current SOFR | Δ (bp)
Jan25   | 2025-01-29 | 2025-03-19 | 4.325%       | 4.330%          | 4.350%       | -2.0
Mar25   | 2025-03-19 | 2025-05-07 | 4.200%       | 4.205%          | 4.350%       | -14.5
...
```

#### Cell Group 6 — Cut/Hike Probability Extraction

Standard probability formula:
```
P(25bp cut at meeting N) = (current_rate - implied_forward_rate_N) / 0.0025
```

Where `current_rate` = effective SOFR at the time, `implied_forward_rate_N` = curve-implied rate for meeting N's period.

- Clip to [0%, 100%] for display, but show raw values to reveal "more than one cut" expectations
- Output: "Fed Dots" style bar chart — one bar per meeting, colored by probability
- Cumulative strip: total implied cuts/hikes through next 8 meetings

#### Cell Group 7 — FOMC Curve Term Structure

- Plot implied rate per meeting on a timeline → the "FOMC curve"
- Overlay: current vs 1-week-ago vs 1-month-ago (from `curve_store` historical snapshots)
- Highlight: where has the market repriced most? (largest absolute change)
- Shape analysis: monotonically declining = easing expectations; V-shape = cut-then-hike

#### Cell Group 8 — FOMC Calendar Spreads

- Calendar spread = implied rate difference between consecutive meetings
- `spread(N, N+1) = implied_rate(N+1) - implied_rate(N)`
- Positive spread = market expects a hike at meeting N+1 relative to N
- Negative spread = market expects a cut
- Track each spread over time — which individual meeting is being repriced?
- Bar chart of all calendar spreads (current snapshot)

---

## Data Flow

```
_CENTRAL_BANK_DATES["USD-SOFR-1D"]
    │
    ├── Meeting schedule: {label: (eff_date, mat_date)}
    │
    ▼
SDR classified trades (via _sdr_common.load_classified_trades)
    │
    ├── Filter: special_tenor_type == "FOMC"
    ├── Assign meeting_label per trade
    │
    ├─── Part 1: Flow analytics (DV01 by meeting, timing, characteristics)
    │
    ▼
IRSwapsMDP + IRSwapQuery
    │
    ├── Price each meeting period: IRSwapQuery(eff_date, mat_date) → par rate
    ├── Historical curves from curve_store for time-series
    │
    ├─── Part 2: Implied rates, probabilities, FOMC curve, spreads
    │
    ▼
Notebook outputs: tables, charts, probability strips
```

## Dependencies

- `_sdr_common.py` (from the SDR notebook suite)
- `Query.IRSwaps._CENTRAL_BANK_DATES` (meeting schedule)
- `Query.IRSwaps.IRSwapQuery` (pricing)
- `MDP.IRSwaps.IRSwapsMDP` (curve source)
- `Caching.curve_store` (historical curves)
- `SDRUtils.core.tenors` (FOMC label detection)
- `SDRUtils.analytics.seasonality` (FOMC date helpers)
