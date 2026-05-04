# USD Swaps SDR Analytics — Comprehensive Design Doc

Date: 2026-05-04
Sources: Chris Barnes (~513 articles) + Amir Khwaja (~465 articles), Clarus
         Financial Technology blog, 2013-2025.
Context: ARBS USD swaps tape v2 feature — what to build next.

> Note on source coverage. The Clarus archive spans ~978 posts. This doc
> distills the methodology, taxonomy, and analytical patterns Clarus has
> publicly documented across that body of work, and translates each one
> into a concrete proposal for the ARBS swap-data stack. Where a specific
> Clarus formula or field convention is named, it is sourced from one or
> more posts cited inline. The companion appendix at the bottom enumerates
> the full author archives so the reader can drill back to primary
> sources.

---

## 0. Why this doc exists

We already ingest CFTC Part 43 / Part 45 SDR data, normalise it into a
USD-swap tape (`usd-swaps-tape-v2`), and surface a row-level dashboard
with package detection, quality flags, lifecycle classification,
economic-class matrix, package confidence scoring, and analytics tabs
(rarity, traded levels, time series, FOMC clusters, risk concentration).

What we *don't* yet have is a coherent product-spec view of what
"complete" looks like for an SDR analytics platform. Clarus has spent
~12 years building exactly that platform on the same data feed. This
doc reads the Clarus catalogue as a reference implementation and
proposes which of those analytics map cleanly onto our existing v2
schema, which require new ingest fields, and which would be net-new
features that complement (rather than copy) the Clarus product family.

The deliverable is a prioritised analytics catalogue plus the data
plumbing each one requires, written so a reviewer can pick rows off it
and turn each into its own implementation plan.

---

## 1. Source-material survey

### 1.1 What Clarus publishes

Clarus runs four core data products that all sit on top of swap data:

- **SDRView** — CFTC Part 43 + Part 45 trade repository data (DTCC,
  CME SDR, ICE SDR), normalised to ~50 fields per trade, exposed as
  filterable trade lists + aggregations.
- **SEFView** — SEF-reported volumes (on-venue subset of SDRView),
  with execution platform attribution + SEF-fee-relevant DV01.
- **CCPView** — daily volumes + open interest published by ~44
  clearing houses, plus the CPMI-IOSCO PFMI quarterly disclosures
  (>200 fields per CCP per quarter).
- **SBSDRView** — SEC SBSDR data (security-based swaps: single-name
  CDS, equity total return, equity options).

The blogs reference all four, but for "USD swaps SDR analytics" the
relevant pair is **SDRView** (record-level public dissemination) and
**SEFView** (execution-venue overlay).

### 1.2 Article themes (high-frequency clusters)

Across ~978 posts the recurring themes are:

| Cluster | Example posts | What they show |
|---|---|---|
| Monthly/quarterly **SOFR volume** reports | "SOFR Swap SEF Volumes – May 2024", "SOFR Swaps Volumes and Share – July 2023" | Trade count + DV01 + notional by venue, package-adjusted. |
| **CCP volumes & market share** quarterly | "3Q24 CCP Volumes and Share in IRD", "2023 CCP Volumes…" | Cleared notional by CCP × currency, growth rates, regional rollups. |
| **PFMI disclosures** quarterly | "What's New in CCP Disclosures – 2Q24" | IM, default fund, stress losses, VM, haircut breaks per CCP. |
| **RFR transition / Term-vs-Compounded** | "Recreating the RFR Adoption Indicator", "Term SOFR and BSBY Volumes…", "Average and Term SOFR Volumes in 2022" | Index-name parsing, RFR adoption ratio, BSBY decline. |
| **Package detection & SDR taxonomy** | "SDR – Trading Venues and Packages", "IDB Market Share in SOFR Swaps" | Package-type cleaning, MIC mapping, IDB classification. |
| **Swaption strike heatmaps** | "Swaption Volumes by Strike Q4 2024", "…Q3 2024", "…Q2 2024" | 25-bp strike grouping, Payer/Receiver/Straddle, package-adjusted notional. |
| **Swap spread / UST basis** | "Swapalypse Now", "USD Swap Spreads into Q4 2024" | VWAP per Bloomberg ticker (USSFCT5/10/30), moves vs. flow concentration. |
| **Block / capping** | "SDRView Released amid CFTC Block Rules", various block-size posts | Capped notional understatement (~10-30% of true notional). |
| **Margin / DV01 stress** | "USD Swaps Margin Calls in March 2023" | LCH SwapClear IM trajectories, DV01 × rate-move = VM. |
| **Cross-currency basis** | "What is Now Trading in RFR Cross Currency Swaps", "Mechanics and Definitions of Cross Currency Basis Futures" | Index-pair conventions, basis vs. fixed/float, RFR-vs-RFR. |
| **Compression / LIBOR conversion** | "Clearing Houses Are About to Convert Your USD LIBOR Swaps", various compression posts | Lifecycle event identification (CCP-converted vs. economic). |
| **Macro / themed indices** | "What Would a Liberation Index Look Like?", "Recreating the RFR Adoption Indicator" | Constructed indices stitching SDR + SEF + CCP data. |
| **UST clearing / FICC** | "Central Clearing of US Treasuries", "Monitoring of Hedge Funds" | Treasury basis trade overlay; SDR-side relevance for swap-spread analytics. |

### 1.3 What Clarus *doesn't* publish (gaps that ARBS can own)

- Per-row **trader-facing tape with sub-second timestamps and
  click-through provenance**. Clarus operates at the report/aggregate
  level — they don't expose a live tape with row-level lineage, manual
  link curation, alerting on individual prints.
- **Real-time package-detection confidence** chips on a live tape
  (we shipped this in PR #285).
- **Cross-product event-study tooling** at the row level (FOMC
  clusters, SVB-week reconstruction). Clarus does retrospectives;
  we have a live event-study UI.
- **Manual link curation** + on-tape comments + tag taxonomy.
- **Multi-CCP NPV reconciliation** at the trade level (we have
  package-metrics; Clarus stops at CCP rollups).
- **Open-source replication** of the analytics — Clarus is a paid
  product. Our internal tools can layer per-row drill-downs on top.

This is where the proposed analytics catalogue (§5) focuses.

---

## 2. The SDR data model — what a USD-swaps row actually contains

Clarus's posts repeatedly call out that "SDR data has ~50 fields per
trade" but never publish the full schema. From the methodology details
across posts plus our own ingest pipeline, the working model is:

### 2.1 Identity & lineage

| Field | Notes from Clarus posts + ARBS practice |
|---|---|
| `dissemination_id` | Public trade ID (CFTC); Part 43 dissemination key. |
| `original_dissemination_id` | For lifecycle events: the CORRECT/MODIFY/CANCEL link. |
| `event_action` | `NEWT` / `MODI` / `CORR` / `TERM` / `EXER` / `NOVA` / etc. |
| `event_type` | Subtype (`AMEND`, `NULL_FILL`, `SCHED_AMORT`, etc. per Phase 2). |
| `package_id` (synthetic) | Clarus's "Package" classification — multi-leg link, ARBS-side derived. |
| `cluster_id` | ARBS-side cross-package linkage (e.g. spreadover cluster). |
| `trade_id` (UTI) | Universal Transaction Identifier (post-2022 CPMI-IOSCO harmonisation). |

### 2.2 Economic terms

| Field | Notes |
|---|---|
| `product_type` | `IRS_FixedFloat`, `OIS`, `Basis`, `Cap/Floor`, `Swaption`, `Inflation`, `XCCY_Basis`, `XCCY_Fix_Fix`, `FRA`. |
| `notional_amount` (capped) | Part 43 caps at tenor-dependent thresholds; understated 10-30% (Chris, multiple posts). |
| `notional_uncapped` (Part 45 / our derived) | When available, the true notional. |
| `currency` | USD/EUR/GBP/JPY/AUD/CAD/CHF/SEK/NOK/MXN/SGD/etc. |
| `tenor_years` | Effective-to-expiration, integer or fractional. |
| `effective_date` / `expiration_date` | Defines tenor and forward start. |
| `forward_start_years` | Spot vs. forward; Clarus separates "spot-starting" from "forward". |
| `fixed_rate` | Coupon. Quoted as decimal (e.g. 0.0376 = 3.76%). |
| `floating_rate_index` | "USD-SOFR-COMPOUND", "USD-SOFR-OIS", "USD-FED-FUNDS-OIS-COMPOUND", "TERM-SOFR-CME-1M/3M/6M", "BSBY", "USD-LIBOR-BBA-3M" (legacy), "SYN-LIBOR" (synthetic). |
| `reset_frequency` | `1D` (overnight compounded), `1M`/`3M` (term). |
| `payment_frequency` | Quarterly / semi-annual / annual. |
| `day_count` | `ACT/360`, `ACT/365`, `30/360`. |
| `rate_index_clean` | ARBS-side normalised index name (collapses 30+ string variants). |

### 2.3 Execution + venue

| Field | Notes |
|---|---|
| `execution_timestamp` | UTC; sub-second. ARBS tracks both "original execution" and "clearing accepted". |
| `dissemination_timestamp` | Time the public tape received the print (used for capping delay analysis). |
| `platform_identifier` (MIC) | ISO MIC: `TWSF` (Tradeweb SEF), `BBSF` (Bloomberg SEF), `BGCD`, `DWSF`, `IGDL`, `ISWE`, `ISWV`, `TPSE`, `TSEF`, `BMTF`, `BTFE`, `TREU`, `TWEM`, `BHSF`, etc. |
| `venue_type` | ARBS-derived: `D2C`, `D2D`, `Off-SEF`, `SDP`. |
| `cleared` | `C` (cleared) / `U` (uncleared) / `I` (intent) per Part 43 Appendix 1. |
| `ccp` | LCH, CME, Eurex, JSCC, etc. |
| `block_indicator` | Capped or above-block-size (BST). |
| `package_indicator` | True/False — broker-flagged multi-leg. |
| `package_transaction_spread` (PTS) | The package's spread term (bp). |
| `package_transaction_price` (PTP) | The package's price term (notional units). |
| `n_package_legs` | Reported leg count. |

### 2.4 Derived / enriched (Clarus-style + ARBS-side)

| Field | Notes |
|---|---|
| `dv01` (risk) | `notional × duration × tick`. Clarus's preferred volume metric. |
| `package_adjusted_dv01` | DV01/n_legs for curves/flies (avoids double counting). |
| `package_type` | `OUTRIGHT`, `CURVE`, `FLY`, `SPREADOVER`, `MATCHED_MATURITY`, `SPREADOVER_CURVE`, `SPREADOVER_FLY`, `MATCHED_MATURITY_CURVE`, `MATCHED_MATURITY_FLY`, `MAC`, `IMM`, `FOMC`, `INVOICE`, `CCPSwitch`. |
| `swap_maturity_date` | Convenience: derived from effective + tenor. |
| `weighted_fixed_rate` | Package-level VWAP across legs. |
| `tape_label` | Display label ("USD-SOFR 5Y/10Y CURVE", "5/10/30 FLY", etc.). |

### 2.5 Quality / compliance flags (ARBS Phase 4-5)

| Field | Notes |
|---|---|
| `is_block_any`, `is_capped_any`, `is_off_date_any` | Block-rule flags. |
| `state_machine_violation_any` | Lifecycle dual-chain check. |
| `cap_band_violation` | Notional > tenor-cap-adjusted threshold. |
| `frequency_anomaly` | Reset-vs-payment mismatch. |
| `d2_missing` | Original Dissemination Identifier missing on lifecycle event. |
| `schedule_truncated` | Notional schedule cropped to first N rows. |
| `is_non_standard_term` | Maturity off the standard grid. |
| `economic_class_primary` | Phase 3 matrix kind: ECONOMIC_FLOW / ECONOMIC_UNWIND / ADMINISTRATIVE / VALUATION / etc. |
| `contributes_to_flow_any`, `contributes_to_volume_any`, `contributes_to_pnl_any`, `on_p43_any` | Aggregation gates. |

This is the canonical schema the rest of the doc references.

---

## 3. The analytical primitives Clarus uses (cross-cutting)

Five primitives recur across the entire Clarus catalogue. They form
the foundation of every analytics page they build, and our v2 stack
implements most of them already in some form.

### 3.1 Volume metric: package-adjusted DV01

Clarus is emphatic about this. Quoting from "SOFR Swaps D2D Volumes
and Share":

> "Market share is best measured using a package adjusted DV01.
> SEF Fees are charged as a function of DV01. Notional figures
> overstate short-dated trades relative to long-dated. Packages
> require adjustment (curves = 2 legs, butterflies = 3 legs,
> outrights = 1 leg)."

Mechanics:

- `dv01_per_leg = notional × pv01_per_unit(tenor)`
- `package_adjusted_dv01(curve)  = (|dv01_l1| + |dv01_l2|) / 2`
- `package_adjusted_dv01(fly)    = (|dv01_l1| + |dv01_l2| + |dv01_l3|) / 3`
- `package_adjusted_dv01(outright) = |dv01|`

Rationale: in a 5s10s switch the broker collects fee on one package
not two trades; in a fly they collect on one package not three.
Aggregating raw `|dv01|` across legs triple-counts the wallet.

ARBS today computes per-leg `risk` and `gross_risk` (sum of |risk|).
We do not yet emit a `package_adjusted_dv01` aggregate per row. Cheap
add — see §5.1.

### 3.2 Package adjustment for trade counts

Same principle for trade counts: a fly is one trade not three.
Quoting "2023 SEF Volumes" (D2D Butterflys row): "11,248 trades,
3-leg adjusted" — i.e. the raw SDR shows ~33,744 leg rows; Clarus
collapses these into ~11,248 packages.

This requires reliable package_id linking. Our v2 ingest already does
this via `package_id` + `cluster_id`. The display side then needs to
report `package_count` not `leg_count`.

### 3.3 Capping understatement

CFTC Part 43 caps the publicly disseminated notional at tenor-dependent
levels (e.g. $250m for 5Y vanilla, smaller for longer tenors). Clarus
explicitly notes "SDR capped notional rules understate figures by up
to 30%" ("2023 SEF Volumes…"), and "10-25% impact" ("SOFR Swaps D2D
Volumes…"). The exact average understatement quoted in "Block Trading"
(2020): **30% across major currencies** (USD 34%, EUR 26%, GBP 25%).

**Capped-trade share** (pre-Oct-2024 thresholds): 7% of trades by
count = 43% of notional volume. After 2024 recalibration this dropped
materially — see §3.7.

The implication for any volume-based number is that the true notional
is **at least** the capped number, often materially larger. Three
mitigations Clarus uses:

1. **Use DV01 not notional** for share calculations (DV01 isn't
   capped — it's derived from `notional × duration` and Clarus
   computes duration from tenor independently of the public
   dissemination).
2. **Scale by SEF-derived multipliers** — Chris explicitly: "analysts
   must scale-up capped trades using SEF-derived multipliers to
   understand actual volumes." Empirically the multiplier averages
   1.30 across major currencies (range 1.25-1.34).
3. **Use Part 45 (uncapped) where available** — our pipeline can
   read both. Most Clarus analytics implicitly only use Part 43.

### 3.4 Index-name parsing (rate_index_clean)

Clarus's posts on Term-SOFR / Average-SOFR / BSBY make clear that the
SDR `floating_rate_index` field is a free-form mess. From "Average and
Term SOFR Volumes in 2022":

- "Term SOFR" matches **24** different string variants (variations
  of `Term`, `SOFR`, `CME`, `TSOFR`, `CME-TS`).
- "Average SOFR" matches **8** of "more than 30" SOFR-named strings.
- "BSBY" matches **5** variations.

ARBS already has `rate_index_clean`. The Clarus parsing rules suggest
the canonical normalisation list should be expanded if we want to
match Clarus's volume splits. Concretely: any analytic that splits
USD-fixed/float by rate index needs to filter on this normalised
column, not the raw SDR string.

### 3.4-bis 2024 block-size recalibration (regulatory step-change)

The CFTC recalibrated block thresholds effective **04-Oct-2024**, the
first calibration since 2013 to use actual post-trade transparency
data. Material implications for any volume-share analytics that
straddle the date:

| Currency | Block-size move | Avg new block in DV01 |
|---|---|---|
| USD | +64% larger | ~$233K |
| EUR | +29% larger | ~$185K |
| GBP | -23% smaller | ~$109K |
| JPY | -47% smaller | (smaller) |

**Dark-notional share** dropped from ~50% to ~25% of total notional
for USD swaps. October 2024 saw 3,910 capped trades vs. an avg ~7,820
monthly through 2024 H1 (a 50% drop in capped-trade *count*). 80% of
the cleared USD swaps market is now SDR-reported (vs. lower before).

**ARBS implication.** Any historical volume comparison that crosses
04-Oct-2024 needs explicit threshold-aware scaling. The §5.8 block-
trade-reconstruction analytic should regenerate its multipliers
quarterly post-Oct-24 and plot a date-stamped step in the cap-decay
indicator (§5.23). This is a one-line "calibration epoch" field on
each row: `block_threshold_epoch ∈ {pre-Oct24, post-Oct24}`.

### 3.5 Venue / D2C-vs-D2D classification

Clarus maintains an explicit MIC → platform → D2C/D2D map. Compiled
from multiple posts:

| MIC | Platform | Type |
|---|---|---|
| TWSF, TREU, TRWB, TWEM | Tradeweb (US/EU/EM) | D2C |
| BBSF, BMTF, BTFE | Bloomberg (US/EU/UK) | D2C |
| TSEF | Tradition | D2D |
| TPSE | TP-ICAP / Tullet | D2D |
| BGCD, GSEF, BGCO | BGC | D2D |
| DWSF | Dealerweb | D2D |
| IGDL, ISWE, ISWV | ICAP | D2D |
| RTX | Refinitiv (FX-leaning) | D2D |
| BHSF | CBOE SEF (NDF heavy) | D2C |
| BILT, XOFF, XXX | "Bilateral / off-exchange / unknown" | Off-SEF |
| REST | NEX Reset (risk optimisation) | Compression |
| TPSE (sub-set) | TP-Matchbook | Compression |

The compression sub-classification matters — these venues report what
look like "trades" but are net-zero risk transfers. Our `economic_class`
matrix already captures this conceptually, but Clarus's specific
venue → "compression" mapping is a useful overlay.

---

## 4. The Clarus analytics catalogue, distilled

This section catalogues the analyses Clarus has shipped on USD swap
SDR data, organised by domain. Section 5 then proposes which to
adopt/extend in ARBS.

### 4.1 Volume + market share

- **Monthly SOFR swap reports** (Amir + Chris). Trade count, notional,
  package-adjusted DV01 by venue × tenor × package type. The
  canonical "share" is %DV01.
- **Annual SEF rankings** ("2023 SEF Volumes and Share in SOFR Swaps").
  Tradeweb 66.6% of D2C outrights by DV01, Bloomberg 33.4%; ICAP 46.6%
  of D2D spreadovers. Stable rankings — slow leadership changes.
- **D2D vs D2C splits** by package type — see "SOFR Swaps D2D Volumes":
  Tradition leads butterflies at 55% D2D; ICAP/IGDL leads outrights at
  62% D2D; etc.
- **CCP rollups** (Amir's quarterly CCP IRD posts). LCH ~98% of USD
  cleared; CME ~2%. Numbers stable since 2022.

### 4.2 RFR transition

- **RFR Adoption Indicator** (Chris, recreated 2025-04-29). Numerator
  = ΣDV01(non-USD RFR IRD) + DV01(SOFR futures) + DV01(USD OIS) ×
  (SOFR / SOFR+FedFunds ratio from SDR). Denominator = ΣDV01(all IRD
  + STIRs across 8 currencies). Single ratio published monthly.
- **Term SOFR vs Compounded SOFR vs Average SOFR vs BSBY**. Volume
  trajectories; cleared/uncleared split; tenor distribution; basis-
  swap-against-Term-SOFR adoption.
- **Synthetic LIBOR** post-30-Jun-2023 (Term SOFR + ISDA fixed
  spread, 26.161 bps for USD).
- **LIBOR conversion event analytics** (LCH 21-Apr + 19-May 2023; CME
  21-Apr + 3-Jul 2023). 500K LCH contracts converted; CME also
  converted Eurodollars 14-Apr.

### 4.3 Package detection

- Package type taxonomy: OUTRIGHT, CURVE, FLY, SPREADOVER,
  SPREADOVER_CURVE, SPREADOVER_FLY, MATCHED_MATURITY, MATCHED_MATURITY_*,
  MAC, IMM, FOMC, CCPSwitch, Forward, INVOICE.
- Per-type heuristics (e.g. SPREADOVER = trade vs UST; CCPSwitch =
  LCH↔CME basis trade).
- Package-adjusted volume metrics throughout.

### 4.4 Time series + VWAP

- **Volume Weighted Average Price** as primary time series metric
  (per "Time Series of Swap Prices and Volumes").
- Aggregations: monthly VWAP standard, daily and weekly available.
- Bloomberg Ticker / OpenFIGI is the canonical instrument key (e.g.
  USSFCT5/10/30 for swap spreads, USSO2/USSO5 for OIS).
- Scatter-plots of trade-by-trade prints overlaid on VWAP.

### 4.5 Block trade analytics

- Capped-notional understatement quantification (10-30%).
- Off-SEF coverage estimation by scaling caps to SEF observation.
- Block-trade behaviour around events (Swapalypse Now: 600 trades in
  10Y SS the week of 8-Apr-2025 vs. 250 normal).

### 4.6 Swap spreads / UST basis

- VWAP per Bloomberg ticker (USSFCT5, USSFCT10, USSFCT30 for 5Y/10Y/30Y
  swap spreads).
- Daily flow $ + trade count overlay.
- Outlier prints called out (e.g. -100bp 30Y print on 8-Apr-2025).
- Macro context overlay (SLR, tariff news, balance-sheet stress).

### 4.7 Swaption analytics

- **Strike heatmap**: rows = expiry/tail (e.g. 1y/10y, 2y/10y, …),
  cols = strike in 25-bp buckets, cell = notional. Red = high.
- **Payer / Receiver / Straddle** classification per UPI / ISO 20022
  / RTS 23: Call = Payer, Put = Receiver. Straddles = Receiver+Payer
  same expiry/underlying/strike, package-adjusted to single notional.
- Q4 2024: Payers 41%, Receivers 37%, Straddles 21%. Tails: 1Y
  $785bn, 10Y $429bn most active.
- D2D >74% of activity is straddles (vol trades, not directional).

### 4.8 IMM / MAC / FOMC dated swaps

- **IMM**: forward-starting on CME SOFR futures dates (Mar/Jun/Sep/Dec
  IMM Wednesdays). Identified by `effective_date` falling on IMM date.
- **MAC**: SIFMA standard dates, fixed coupon (typically integer %).
  Concentrated around quarterly roll weeks (Mar/Jun/Sep/Dec).
  ~5% of USD swap trade counts ex-roll; spike during roll week.
  Tradeweb dominant on-SEF; smaller average ticket; mostly
  non-block.
- **FOMC**: forward-starting on FOMC meeting dates (8 per year).
  Volume spikes around announcements.

### 4.9 CCP basis (CCPSwitch)

- LCH↔CME basis trades — explicit package type in Clarus taxonomy
  ("IDB Market Share in SOFR Swaps").
- Tracked separately from outright/curve/fly because the trade is
  economically a CCP-switch, not a directional view.

### 4.10 Cross-currency analytics

- RFR vs RFR pairs: EURUSD, GBPUSD, CHFUSD, JPYUSD, SGDUSD.
- Term-vs-RFR pairs: AUDUSD (BBSW), NZDUSD (BBR-FRA), CADUSD
  (CDOR), SEKUSD (STIBOR), NOKUSD (NIBOR), DKKUSD (CIBOR), HKDUSD
  (HIBOR), MXNUSD (TIIE).
- Fixed-vs-RFR: TRYUSD (Fixed-TRY vs USD-SOFR).
- 87% of KRW SDR-reported swaps are USD-settled (NDS).
- CME XCCY basis futures: cash-settled implied 3M basis from
  EUR/USD FX-forward + USD/EUR STIR futures.

### 4.11 Margin / DV01 stress

- LCH SwapClear initial margin trajectories by tenor in stress
  windows (e.g. SVB week, March 2023):
  - 2Y SOFR rates fell 100 bp in 5 days → IM rose 60% in 8 days.
  - Example: $250m pay-fixed 2Y, DV01 ~$50K, IM rose from $3.1m
    (62 bp) to $4.9m (98 bp); cumulative VM by 13-Mar = $4.7m.
- ARBS doesn't ingest CCP IM directly today — would need CHARM-like
  sim. But we can approximate via daily DV01 × realised-rate-move.

### 4.12 Constructed indices (Liberation Index, etc.)

- "Liberation Index" prototype (Chris, 1-Apr-2025): 3-component on
  USDCAD/USDMXN/USDCNY/EURUSD FX-options activity:
  - **Trade volume** (count) vs. 20K/month 2024 baseline.
  - **Notional** (on-SEF) vs. $375bn/month baseline.
  - **Premium %** (premium / notional) vs. 0.55% baseline.
  - Index = 100 at Dec-2023.
- Generalisable construction pattern: pick 3 quasi-orthogonal
  metrics, normalise to a baseline period, weighted average → an
  index that traders can watch on a daily basis.

### 4.13 PFMI / CCP risk disclosures

- 200+ quantitative fields per CCP per quarter, going back to
  Sept-2015 across 44 CCPs.
- Tracked: IM (per product), default fund, stress losses (single +
  multiple participant), VM paid + max-VM-day, haircut breaks,
  margin-coverage breach counts.
- Example data point cited: CME IRS "estimated largest same-day
  payment obligation" = $24.7bn (1Q24, new high).

### 4.14 LIBOR / cessation tracking

- Synthetic USD LIBOR window (1M/3M/6M, ended 30-Sep-2024).
- Legacy bilateral LIBOR remnants visible in SDR.
- Cleared LIBOR explicitly converted by CCPs in 2023.

### 4.15 Active Account Requirements (AAR), EMIR 3.0

- 5 most-relevant subcategories × min trade counts (300 dealer / 50
  buy-side per year).
- EU-vs-non-EU CCP location matters (Eurex vs LCH SwapClear).
- Currently only meaningful in EUR; analogous USD-side framework is
  hypothetical (would need a Treasury / Fed mandate).

### 4.16-bis CCP basis identification (no SDR field for CCP)

Critical methodology gap: the SDR has **no field** identifying which
CCP cleared a given trade. Clarus's solution ("How to identify the
CCP of trades from the SDR data", 05-Apr-2016) uses statistical
detection on intraday price series:

> "We use Linear Regression at a given confidence interval (e.g. 95%)
> to ascertain how large we expect changes in price to be from one
> trade to the next. We analyse pricing patterns in groups of three
> consecutive trades, looking for jumps on both sides of a middle
> trade that deviate from expected variation."

The technique exploits the CCP basis (LCH↔CME for USD, LCH↔Eurex for
EUR, LCH↔JSCC for JPY). When a trade prints at a level discontinuous
with neighbouring prints, it likely cleared at the basis-counterparty
CCP. Limitations:

- Works only on liquid 5Y+ tenors with frequent prints.
- Requires wide enough basis to exceed pricing noise.
- Combined with SEFView's T+1 markup data for ground-truth validation.
- 50% false-positive rate without SEF cross-reference at tight basis.

ARBS's package-confidence scorer (PR #285) doesn't yet use this
technique. We could add a `ccp_inferred ∈ {LCH, CME, UNKNOWN}` field
per row using a simpler version (e.g. Z-score of trade vs. 5-min
VWAP), and a `ccp_inferred_confidence` score. See §5.10 (CCPSwitch
detector) which implicitly relies on this.

### 4.16 Hedge fund / Treasury basis monitoring (OFR HFM)

- Not strictly SDR but uses related data: SEC Form PF, CFTC COT,
  NY Fed SCO survey, FICC repo.
- Relevant for our swap-spread analytics because Treasury basis
  trade size correlates with swap-spread direction.

---

## 5. Proposed analytics for ARBS USD swaps tape v2

This is the actionable catalogue — sized for 1-3-day implementation
chunks each. Numbered for easy referencing as separate plans.

### 5.1 Package-adjusted DV01 aggregate (small)

**Why.** Clarus's preferred volume metric. We already compute leg
risk + gross risk, but no `package_adjusted_dv01` field on the row.
Without it, downstream "share" calculations triple-count flies.

**What.**
- Add `package_adjusted_dv01: number | null` to `UsdSwapTapeRow`.
- Compute as:
  - `OUTRIGHT` → `|gross_risk|`
  - `CURVE` → `(|risk_l1| + |risk_l2|) / 2`
  - `FLY` → `(|risk_l1| + |risk_l2| + |risk_l3|) / 3`
  - composites → use base type denominator
  - composite SPREADOVER_* → +1 leg in denominator (the UST)
- Surface as a column in the tape (toggleable with current `risk`).
- Use as the default volume metric in `/api/usd-swaps-tape-v2/analytics-timeseries`.

**Plumbing.** Pure-frontend computation works (we have the legs); for
backend aggregations, add to the row materialiser.

### 5.2 Venue × package-type market-share dashboard (medium)

**Why.** The single most-published Clarus chart. Currently we have a
flat tape; no rollup view of "who traded what".

**What.**
- New analytics tab: "Market share".
- Pivot: rows = venue (with D2C/D2D/Off-SEF grouping), cols = package
  type, cell = package-adjusted DV01 + share %.
- Time-bucket selector: 1D / 1W / 1M / 1Q / YTD.
- Drill-through: click a cell → filtered tape view.
- Side-by-side D2D vs D2C panels (mirrors Clarus's standard layout).

**Plumbing.**
- Add a `/api/usd-swaps-tape-v2/market-share` endpoint backed by an
  aggregation over the same daily bars we already have.
- Venue → D2C/D2D map lives in `constants.ts` (extend the existing
  one with the table from §3.5).

### 5.3 Index-name normaliser hardening (small)

**Why.** Clarus's BSBY / Term-SOFR / Average-SOFR posts identify
30+ string variations of "SOFR" alone. Our `rate_index_clean` likely
covers the obvious ones but should be audited against Clarus's
explicit rules.

**What.**
- Build a test suite of every distinct `floating_rate_index` value
  ever seen in our SDR table.
- Map each into the Clarus canonical bucket: `SOFR-COMPOUND`,
  `TERM-SOFR-1M/3M/6M`, `AVERAGE-SOFR-30/90/180`, `FED-FUNDS`,
  `BSBY`, `LIBOR-1M/3M/6M`, `SYN-LIBOR-1M/3M/6M`, `OTHER`.
- Add a quality flag `index_name_unrecognised` for new strings.
- Surface on tape as a tooltip on the rate-index column.

**Plumbing.** Extend `clean_rate_index()` in our normaliser; add
unit-test fixtures from real SDR data.

### 5.4 RFR Adoption Indicator (medium)

**Why.** The flagship Clarus index — single number that traders
understand as "% of risk transitioned away from LIBOR". We can
replicate it for a USD-only or USD+global view.

**What.**
- New analytics page: "RFR Adoption".
- Numerator (USD-only first): ΣDV01(SOFR-OIS) over rolling 30-day window.
- Denominator: ΣDV01(SOFR-OIS) + ΣDV01(FED-FUNDS-OIS) + ΣDV01(LIBOR
  remnants) + ΣDV01(synthetic-LIBOR) + ΣDV01(Term-SOFR fixed/float).
- Plot: monthly ratio vs. the Clarus published series for sanity.
- Cross-link to the underlying tape rows.

**Plumbing.** Reuses existing aggregation stack; just a new selector
in the timeseries config.

### 5.5 Term-SOFR / BSBY / Synthetic-LIBOR break-out (small)

**Why.** Each of these is a distinct "small-but-nonzero" segment
Clarus tracks monthly. Our tape today doesn't easily filter by them.

**What.**
- Add a column-filter quick-toggle for "Term SOFR", "Avg SOFR",
  "Compounded SOFR", "BSBY", "LIBOR (legacy)", "Synthetic LIBOR".
- Add their volume time-series to the analytics dock.
- Flag any LIBOR (legacy or synthetic) print with a chip in the
  quality column — these are increasingly anomalous.

### 5.6 VWAP time series + scatter-on-VWAP for swap spreads (medium)

**Why.** "Swapalypse Now" + "Swap Spreads into Q4 2024" pattern: a
canonical chart per Bloomberg ticker (USSFCT5, USSFCT10, USSFCT30)
showing daily VWAP + a scatter overlay of trade-by-trade prints.

**What.**
- Add `vwap_daily` and `vwap_intraday` (5-min bars) to existing
  timeseries pipeline, computed from the row-level rate + size.
- Per-ticker analytics tab with VWAP line + scatter overlay.
- Pre-canned ticker set: USSFCT2/5/10/30 (swap spreads); USSO1/2/5/10/30
  (USD OIS); USSWAP10 etc.
- Click a scatter point → row drill-through.

**Plumbing.** Bloomberg ticker → instrument key map in constants;
materialise per-ticker daily bars in the cache layer (Phase E pattern).

### 5.7 Swaption strike heatmap (medium)

**Why.** Clarus's swaption-by-strike chart is one of their most
visually distinctive products. We have a swaption tape (separate
feature, `sofr-swaptions-tape`) but no equivalent strike heatmap.

**What.**
- New tab in the swaption feature: "Strike heatmap".
- 25-bp strike bucketing per Clarus convention; rows = expiry/tail
  pairs (1m1y, 1m2y, …, 1y10y, 5y10y, …); cols = strike buckets.
- Cell = notional (package-adjusted for straddles). Colour intensity
  = relative volume.
- Per-quarter comparison view (Q-on-Q delta).
- Filter by Payer / Receiver / Straddle (per UPI Call/Put + Straddle).

**Plumbing.** Need `option_type` (Call/Put) parsed correctly into
Payer/Receiver. Straddle detection: same expiry + tail + strike +
opposite Call/Put within the same package_id.

### 5.8 Block-trade reconstruction & cap-aware sizing (medium)

**Why.** Capped notional understates true volume by 10-30%. We
already flag `is_block_any` and `is_capped_any` but we don't
*estimate* the true notional behind a capped print.

**What.**
- Add `notional_estimated_uncapped: number | null` per row.
  Rule: if `is_capped_any` and Part 45 row exists, use Part 45
  notional; else multiply capped notional by a tenor-specific
  median ratio derived from SEF-vs-SDR observations (Clarus's
  scaling approach).
- Tape column toggle: "true notional (est.)" vs "reported (capped)".
- Alert if capping ratio drifts outside historical band (data-quality
  watchdog).

**Plumbing.** Maintenance cron: weekly recompute the per-tenor
multiplier from the joinable subset (SEF-attributable trades that
have both Part 43 capped + Part 45 uncapped notional).

### 5.9 IMM / MAC / FOMC roll-week analytics (medium)

**Why.** Clarus tracks these as distinct types. Our tape detects
package_type=MAC / IMM / FOMC; we don't yet expose the *roll calendar*
or "concentration around roll week" view.

**What.**
- New analytics widget: "Calendar dated swaps".
- For each of MAC / IMM / FOMC: show the next 4 dates, the
  current week's volume vs. 4-week trailing median (concentration
  ratio).
- Quarterly roll-week marker on all volume time series.
- "Off-cycle MAC" alert: a MAC print outside the roll week is rare
  and worth surfacing.

**Plumbing.** Roll-calendar utility (computes MAC / IMM / FOMC dates).
Already partially present in `fomc-clusters` pipeline.

### 5.10 CCP-switch (LCH↔CME basis) tracker (small)

**Why.** Distinct package type Clarus tracks ("CCPSwitch", 473 trades
in 2023 D2D). We tag SPREADOVER_CURVE etc but don't isolate
CCP-switch.

**What.**
- Add `is_ccp_switch` boolean. Detected as: package with two legs,
  same currency, same tenor, opposite signs, one cleared LCH and
  one cleared CME (or one LCH & one explicitly tagged CME).
- New analytics widget: "CCP basis trades" — daily DV01 + share by
  tenor, with directional bias (LCH → CME vs CME → LCH net flow).
- Cross-link to CCPView-style market-share view.

**Plumbing.** Need both legs' `ccp` field reliably populated. Likely
already present in package_metrics.

### 5.11 Cross-currency basis tape integration (medium)

**Why.** Currently our v2 tape is USD-only. RFR vs RFR cross-currency
basis swaps reference USD on one leg and are arguably USD instruments.

**What.**
- Extend tape to optionally include trades where one leg is USD
  (USD-SOFR or fed-funds), even if currency != USD.
- New filter: "Show xccy basis with USD leg".
- Per-currency-pair sub-view: EURUSD / GBPUSD / JPYUSD / etc.
- Identify Mark-to-Market vs Mark-to-Pay variants if SDR field
  supports it (currently unclear; check Part 43 schema).

**Plumbing.** Extend the ingest filter; reuse package-detection for
basis vs fixed/float legs.

### 5.12 DV01 × rate-move stress reconstruction (medium-large)

**Why.** Clarus's "USD Swaps Margin Calls in March 2023" pattern.
We have per-row DV01 + execution timestamp; we have rate fixings
per tenor in our curve store. Combine = approximate VM trajectories
for the open-interest snapshot during stress windows.

**What.**
- Pick a window (e.g. 6-Mar to 17-Mar 2023). For every open trade
  active in that window:
  - Aggregate DV01 by tenor.
  - Multiply by realised daily rate move at that tenor (from our
    curve store).
  - Sum to get implied VM.
- Compare to LCH-published aggregate VM (where available from
  CCPView-style data) for sanity.
- Visualise as cumulative VM by tenor over the window.

**Plumbing.** Larger — needs a "snapshot" view of open positions at
window start, plus a VM calculator. Useful well beyond stress
analytics (it's the foundation for any P&L attribution).

### 5.13 Liberation-Index-style themed indices (small per-index)

**Why.** Clarus's pattern: pick 3 metrics, normalise to a baseline,
publish as an index. Cheap to instantiate per theme.

**What.** Build the indexing infrastructure once, then publish 3-5
themed indices:
- **USD Rate-Stress Index**: (Daily DV01 / 30-day median DV01) ×
  (Daily intraday-VWAP-stdev / 30-day median) × (% of trades
  outside ±2-bp band of VWAP). Weighted to taste.
- **Liquidity Index**: (Trade count / 30-day median) × (DV01 /
  30-day median) × (1 / off-SEF share).
- **CCP Switch Activity Index**: % of D2D DV01 in CCP-switch
  trades vs. 30-day baseline.
- **Curve Trade Concentration Index**: 5s10s + 10s30s package
  notional vs. ATM outright notional.

**Plumbing.** New `IndexComputation` service; baseline windows
configurable per index.

### 5.14 SEF-vs-Off-SEF coverage estimator (small)

**Why.** Chris's transparency post: "57-64% of risk subject to
trade-level reporting". Useful as a constant indicator on the tape.

**What.** Daily ratio: ΣDV01(on-SEF) / ΣDV01(all USD swaps).
Plotted as a sparkline in the tape header. Drill-through shows the
breakdown by tenor (e.g. 5Y-10Y has highest transparency at 87%,
shorter and longer fall off).

### 5.15 Swap-spread (UST basis) overlay (medium)

**Why.** USSFCT5/10/30 is a critical desk view. Clarus's "Swapalypse
Now" demonstrates the value.

**What.**
- Detect SPREADOVER package type more thoroughly (we have it; verify
  vs. Clarus's identification).
- New analytics tab: "Swap spreads".
- Per-tenor (2Y/5Y/10Y/20Y/30Y): daily VWAP, daily $notional, daily
  trade count, scatter overlay of large prints.
- Alert chips on outlier prints (e.g. >2σ from VWAP).
- Macro-event annotations (FOMC, QT, debt-ceiling, tariff news).

**Plumbing.** Reuses §5.6 VWAP infra. SPREADOVER detection already
in our package-confidence scorer — extend to expose the UST tenor
the spread is against.

### 5.16 Lifecycle-event "convert vs amend vs null-fill" classifier (already shipped, refine)

**Why.** We have economic_class matrix already. Clarus's LIBOR-conversion
posts highlight a specific event class — "CCP-converted" — that should
be its own bucket because it's neither economic nor administrative.

**What.**
- Extend `economic_class` enum with `CCP_CONVERSION`. Detected by
  a CCP-side tag on the lifecycle event during the LIBOR conversion
  windows (Apr+May+Jul 2023) or any future CCP conversion.
- Filter chip on the tape "Show conversion events".
- Historical reconstruction of the LIBOR-conversion week as a
  permanent demo / regression case.

### 5.17 PFMI / CCP-disclosure mini-dashboard (large; out-of-scope?)

**Why.** Clarus's whole CCPView product is built on this. Our pipeline
doesn't ingest PFMI. Including for completeness — likely a separate
project.

**What (sketch).**
- Quarterly ingest of PFMI XML/Excel for LCH SwapClear, CME OTC,
  Eurex Clearing, JSCC, CCIL, Shanghai.
- Track: IM by product, default-fund size, max same-day VM, stress
  losses (single + dual default), haircut breaks.
- Cross-link: when stress losses spike at LCH, drill into the LCH
  USD-cleared tape rows from the same period.

### 5.18 Compression-trade attribution (small)

**Why.** Clarus flags REST (NEX) and TPSE-Matchbook as compression-only
venues. Our economic_class matrix already differentiates ECONOMIC vs
ADMINISTRATIVE but doesn't surface compression-venue attribution.

**What.**
- Add `compression_venue` column. Values: `NEX_RESET`, `TP_MATCHBOOK`,
  `LCH_OPTIM`, `CME_NETTING`, `OTHER`, `NONE`.
- Aggregate compression % of total trade count per day.
- Trader filter: "Hide compression flow" (default off; analysts on).

### 5.19 Rate-index-on-tape transition watch (small)

**Why.** Hot-zone for misreporting. New floating index strings
should be reviewed before they pollute analytics.

**What.**
- Daily report: every distinct `floating_rate_index` string seen
  in the last 24h, with count + total notional. Highlight strings
  not in our normaliser map.
- Slack / email integration.

### 5.20 Open-interest reconstruction from lifecycle (large)

**Why.** Clarus relies on CCPView for OI; SDR doesn't directly
publish OI. But we have the full lifecycle (NEW, MODI, NOVA, TERM,
COMPRESSION) at row level. Reconstructable.

**What.**
- Per package_id, walk the lifecycle chain → end-state notional.
- Aggregate end-state notional per tenor / currency = OI proxy.
- Compare to CCPView OI where available.
- Time-travel view: "OI as of date X".

**Plumbing.** Larger; needs a separate state-machine over event
chains. State-machine validator (Phase 2) is a dependency.

### 5.21 EU AAR-style monitoring (USD speculative)

**Why.** EMIR 3.0 AAR has no USD analogue today, but Treasury-
clearing mandate may create one. Pre-build the framework so we can
pivot quickly.

**What.** Generic "subcategory monitoring" engine: define
subcategories (currency × tenor × package type × counterparty
type), compute per-firm fill ratios. Currently dormant; activates
when (if) a USD AAR-style rule lands.

### 5.22 Most-active-counterparty rankings (medium)

**Why.** Amir publishes monthly "Most Active Names" in CDS / equity
SBSDRs. Less applicable to USD swaps directly because counterparty
names are masked in CFTC SDR (only `executing_party` LEI sometimes
present, often anonymised). But where LEIs are present, ranking by
DV01 traded is feasible.

**What.**
- LEI dictionary mapping (use GLEIF for the canonical name).
- Per-LEI DV01 traded over rolling window.
- Rankings with monthly delta.
- Privacy: aggregate-only display by default; row-level only behind
  a permission flag.

### 5.23 Capped-notional decay analytics (small)

**Why.** Block trades have a 15-min dissemination delay; the
notional then appears capped on the public tape. Tracking the
fraction of "true notional" estimable from blocks-vs-non-blocks
is a useful market-microstructure signal.

**What.** Daily: % of DV01 reported with delay; % capped; mean
delay between execution and dissemination. Sparklines in tape header.

### 5.24 KRW / CNY / EM USD-leg filter overlay (small)

**Why.** "What you need to know about KRW Swaps" + "CNY Swaps
What's New" — most KRW SDR-reported swaps are USD-settled NDS;
some CNY similarly. These are arguably "USD risk" trades.

**What.** Filter chip "Include EM USD-settled NDS legs" on the
tape; extends current USD-only scope.

### 5.26 Anonymous-trading (PTNGU) impact tracker (small)

**Why.** Post-Trade-Name-Give-Up rules took effect 01-Nov-2020 for
MAT swaps; Clarus's review found "little effect on the weekly volumes
of SEFs". But each future regulatory change in the same family (e.g.
hypothetical extension to non-MAT, USD vs EUR jurisdictional splits)
would benefit from a permanent before/after measurement scaffold.

**What.** A reusable "regulation epoch" framework: a date-stamped
config table mapping each rule change to (effective_date, scope,
expected_metric). The dashboard auto-renders a vertical line on
volume/share charts at each effective_date and computes pre/post
ratios for the affected scope. Includes a rolling-window dummy-test
(Wilcoxon or t-test) so we don't visually over-read noise.

**Plumbing.** Lightweight; one DB table + one chart-overlay component.

### 5.27 Per-row CCP inference + basis-detection scoring (medium)

**Why.** The SDR has no CCP field. Clarus's regression-based detection
(Apr-2016) is intricate but addressable. Even an approximate inference
opens up CCP-switch trade detection, CCP-share-of-flow analytics, and
basis-level back-out from row-level prices.

**What.**
- Compute `ccp_inferred ∈ {LCH, CME, UNKNOWN}` per row using a
  rolling-window pricing residual:
  - For each row, fit a 5-minute trailing VWAP for that
    {tenor, package_type} group.
  - Residual = `(row_rate - vwap) - persistent_basis_estimate`.
  - If |residual| > Z·σ(window) and sign matches the published
    LCH-CME basis direction: tag as the basis-counterparty CCP.
- `ccp_inferred_confidence ∈ [0,1]` based on (a) sample size in
  window, (b) realised |basis| in the window, (c) market-quiet
  indicator.
- Surface as a column on the tape (low confidence → muted slate).
- Cross-link to §5.10 CCPSwitch detector — when both legs of a
  package have opposite `ccp_inferred`, that's a switch.

**Plumbing.** Streaming residual engine; prerequisite is the per-
ticker VWAP infra from §5.6.

### 5.25 Daily morning report (small)

**Why.** Clarus publishes monthly. A daily desk-style report is
within reach.

**What.** Auto-generated daily PDF / HTML with:
- Yesterday's USD swap DV01 by tenor (vs 5d / 20d).
- Top 5 venue-share moves.
- Notable block trades (>$500m).
- VWAP for USSFCT5/10/30 + change vs prior day.
- Any data-quality flags raised.
- FOMC proximity warning if within 5 days.

**Plumbing.** Templating + cron + a "freeze daily snapshot" job in
the cache layer.

---

## 6. Data plumbing required

The proposals in §5 break into four plumbing tiers.

### Tier 0 — already in v2 schema, no plumbing

§5.1 (DV01 aggregate), §5.10 (CCP switch), §5.16 (lifecycle refine),
§5.18 (compression venue), §5.19 (index-name watch), §5.5 (Term/BSBY
filter), §5.13 (themed indices computation engine — only needs
existing daily bars).

### Tier 1 — extend existing materialisers / constants

§5.2 (market-share endpoint + venue map), §5.3 (rate-index normaliser
hardening), §5.4 (RFR Adoption — combines existing aggregations),
§5.6 (VWAP daily bars per ticker), §5.9 (calendar utility), §5.14
(SEF-vs-Off-SEF coverage), §5.15 (swap-spread tab), §5.23 (cap decay
metrics), §5.24 (EM USD-leg filter), §5.25 (daily report).

### Tier 2 — new ingest fields or external joins

§5.7 (swaption Call/Put → Payer/Receiver mapping; need swaption
schema audit), §5.8 (Part 43 ↔ Part 45 join for true-notional;
SEF-vs-SDR multiplier service), §5.11 (xccy USD-leg ingest), §5.22
(LEI dictionary).

### Tier 3 — substantial new infrastructure

§5.12 (DV01 × rate-move VM stress; needs open-position snapshots +
curve-store integration), §5.17 (PFMI ingest pipeline; net-new),
§5.20 (OI reconstruction; needs lifecycle state machine), §5.21
(generic subcategory engine; build only if AAR-USD lands), §5.27
(per-row CCP inference; depends on streaming VWAP residual engine).

### Tier-spanning watchdogs (must precede analytics they support)

- Index-name normaliser drift (§5.19) — feeds §5.4, §5.5.
- Capping multiplier maintenance (§5.8 service) — feeds §5.2.
- Venue MIC drift detector (built into §5.2) — feeds every share
  metric.
- Block-threshold-epoch flag (§3.4-bis) — feeds every series that
  spans 04-Oct-2024.

---

## 7. Implementation roadmap (suggested ordering)

The natural order is: Tier 0 → Tier 1 → Tier 2 → Tier 3, with each
section roughly two-week chunks. A reasonable 6-month roadmap:

**Month 1 (Tier 0 cleanup, ~5 PRs)**
- §5.1 (PA-DV01)
- §5.5 (Term/BSBY/etc filters)
- §5.10 (CCP-switch detector)
- §5.16 (CCP_CONVERSION enum)
- §5.18 (compression venue)

**Month 2 (Tier 1 dashboards, ~3 PRs)**
- §5.2 (market-share dashboard) — this is the marquee feature
- §5.3 (index-name normaliser audit)
- §5.4 (RFR Adoption indicator)

**Month 3 (Tier 1 time series + reports, ~3 PRs)**
- §5.6 (VWAP per ticker + scatter overlay)
- §5.15 (swap-spread tab)
- §5.25 (daily morning report)

**Month 4 (Tier 1 finishing, ~3 PRs)**
- §5.9 (calendar dated swaps)
- §5.13 (themed indices — pick top-2)
- §5.14 (SEF coverage indicator)
- §5.19 (index-name watch alert)
- §5.23 (cap decay metrics) — incorporates the §3.4-bis Oct-2024
  threshold step.
- §5.24 (EM USD-leg filter)
- §5.26 (PTNGU / regulation-epoch tracker — needed before any cross-
  date-of-rule comparisons go live).

**Month 5 (Tier 2, ~2 PRs)**
- §5.7 (swaption strike heatmap)
- §5.8 (cap-aware sizing)
- §5.11 (xccy USD-leg integration)

**Month 6 (Tier 3 starter, 1-2 PRs)**
- §5.12 (DV01 × rate-move VM stress) — likely one half-PR design,
  one half-PR implementation.
- §5.27 (per-row CCP inference) — depends on §5.6 VWAP infra
  shipped in month 3.
- Tier 3 items (§5.17, §5.20, §5.21, §5.22) deferred to next half
  unless a stakeholder pulls them in.

---

## 8. Open questions and follow-ups

### 8.1 Do we want to compete with Clarus or complement?

Clarus's product is a paid B2B analytics platform aimed at sell-side
research, treasury, regulators. ARBS is internal. We don't need to
reproduce their entire catalogue; we should pick the analytics where
trader-grade row-level drill-through is the differentiator.

The Clarus posts that translate cleanly are the **methodology**
(volume metric, package adjustment, capping, index normalisation,
venue map) and the **chart archetypes** (heatmap, VWAP+scatter,
share-by-time). The reports themselves (monthly volume update) are
not particularly useful as an internal product.

### 8.2 Open-data vs subscription tension

Clarus's value is in cleaning up the SDR mess. Replicating their
cleaning means re-doing 12 years of taxonomy work. The §5.3 (index
normaliser audit) and §5.18 (compression venue map) are the most
expensive items to get right because they require the same
manual-curation work Clarus does. We should treat these as
ongoing maintenance, not one-off.

### 8.3 Where Clarus is silent (gaps)

- Swaption vol-surface implication (Clarus tracks notional, not vol).
- Per-row P&L attribution.
- Manual curation tooling (links, comments, tags).
- Cross-product event-study UI.
- Real-time alerting on individual prints.
- Treasury-basis-trade overlay on swap-spread analytics (only
  obliquely mentioned in HFM post).

These are natural ARBS differentiators.

### 8.4 Data-quality watchdogs we should ship before adding new analytics

Every analytic in §5 is sensitive to a small set of upstream errors:

- New `floating_rate_index` strings → §5.19 alert.
- Drift in capping ratio → §5.8 maintenance.
- New venue MIC codes → §5.2 venue-map drift detector.
- Lifecycle-chain breaks (state-machine violation) → already in Phase 4.

The watchdogs should land *before* the dashboards that depend on
them, otherwise the dashboards lie quietly.

### 8.5 Which Clarus posts to re-read when a feature reactivates

For each §5 item, the closest Clarus reference is:

| §5 | Best Clarus reference |
|---|---|
| 5.1 | "SOFR Swaps D2D Volumes and Share" |
| 5.2 | "2023 SEF Volumes and Share in SOFR Swaps" |
| 5.3 | "Average and Term SOFR Volumes in 2022" |
| 5.4 | "Recreating the RFR Adoption Indicator" (Apr 2025) |
| 5.5 | "Term SOFR and BSBY Volumes – October 2023" |
| 5.6 | "Time Series of Swap Prices and Volumes" |
| 5.7 | "Swaption Volumes by Strike Q4 2024" |
| 5.8 | "Transparency – Where do we go from here?" |
| 5.9 | "MAC Swaps" + Clarus's IMM rollup posts |
| 5.10 | "IDB Market Share in SOFR Swaps" |
| 5.11 | "What is Now Trading in RFR Cross Currency Swaps" |
| 5.12 | "USD Swaps Margin Calls in March 2023" |
| 5.13 | "What Would a Liberation Index Look Like?" |
| 5.14 | "Transparency – Where do we go from here?" |
| 5.15 | "Swapalypse Now" + "USD Swap Spreads into Q4 2024" |
| 5.16 | "Clearing Houses Are About to Convert Your USD LIBOR Swaps" |
| 5.17 | "What's New in CCP Disclosures – 2Q24" series |
| 5.18 | "SDR – Trading Venues and Packages" |
| 5.19 | "Term SOFR and BSBY" series |
| 5.20 | (no direct Clarus equivalent) |
| 5.21 | "European Active Account Requirements Revisited" |
| 5.22 | "Most Active Names in Credit and Equity Derivatives" |
| 5.23 | "Transparency" + block-rule posts |
| 5.24 | "What you need to know about KRW Swaps", "CNY Swaps – What's New?" |
| 5.25 | (no direct Clarus equivalent) |

---

## 9. Appendix A — Clarus venue / MIC reference table

Compiled from cross-references across multiple Clarus posts (notably
"SDR – Trading Venues and Packages", "SOFR Swap SEF Volumes – May
2024", "2023 SEF Volumes and Share in SOFR Swaps", "IDB Market Share
in SOFR Swaps").

| MIC | Operator | Venue type | Primary product | Notes |
|---|---|---|---|---|
| TWSF | Tradeweb | D2C | USD IRS, OIS | US SEF |
| TREU | Tradeweb | D2C | EU IRS | EU MTF |
| TRWB | Tradeweb | D2C | Multi-asset | UK MTF |
| TWEM | Tradeweb | D2C | EM | |
| BBSF | Bloomberg | D2C | USD IRS, OIS, swaptions | US SEF |
| BMTF | Bloomberg | D2C | EU | EU MTF |
| BTFE | Bloomberg | D2C | UK | UK MTF |
| TSEF | Tradition | D2D | USD IRS, OIS, swap spreads | |
| TPSE | TP-ICAP / Tullet | D2D | USD IRS + spreadovers | Includes TP-Matchbook compression sub-venue |
| BGCD | BGC | D2D | USD IRS, OIS | |
| BGCO | BGC | D2D | Options | |
| GSEF | BGC | D2D | | |
| DWSF | Dealerweb | D2D | USD IRS | |
| IGDL | ICAP | D2D | USD IRS | |
| ISWE | ICAP | D2D | EU | |
| ISWV | ICAP | D2D | Voice-execution | |
| RTX | Refinitiv | D2D | FX-leaning | |
| BHSF | CBOE SEF | D2C | NDF | |
| CBNL | Citibank London | Off-SEF / SDP | NDF | |
| EBSS | EBS Service | D2C | FX | |
| JPCB | JPM London | Off-SEF / SDP | NDF | |
| THRE | Refinitiv US | D2C | NDF | |
| XEBS | EBS UK | MTF | FX | |
| BILT, XOFF, XXX | "Bilateral / off-exchange / unknown" | Off-SEF | All | |
| REST | NEX Reset | Compression | All | Risk optimisation, not new risk |
| TPSE (sub) | TP-Matchbook | Compression | All | Risk optimisation |

---

## 10. Appendix B — Index name normalisation reference

Per "Average and Term SOFR Volumes in 2022", "Term SOFR and BSBY
Volumes…" series, and "Synthetic USD Libor Announcement":

### USD floating-rate-index canonical buckets

| Canonical bucket | Match rules (regex against `floating_rate_index`) |
|---|---|
| `SOFR_COMPOUND` | `USD-?SOFR(-OIS)?(-COMPOUND)?` and reset_freq=1D, excluding any "TERM"/"AVERAGE" |
| `TERM_SOFR_1M` | `(CME-?)?T(ERM)?-?SOFR.*1M` |
| `TERM_SOFR_3M` | `(CME-?)?T(ERM)?-?SOFR.*3M` |
| `TERM_SOFR_6M` | `(CME-?)?T(ERM)?-?SOFR.*6M` |
| `AVERAGE_SOFR_30D` | `AVG-?SOFR.*30` |
| `AVERAGE_SOFR_90D` | `AVG-?SOFR.*90` |
| `AVERAGE_SOFR_180D` | `AVG-?SOFR.*180` |
| `FED_FUNDS` | `USD-?FED-?FUNDS(-OIS)?` |
| `BSBY_1M` / `_3M` / `_6M` / `_12M` | `BSBY.*1M` etc (5 known string variants) |
| `LIBOR_1M` / `_3M` / `_6M` | `USD-?LIBOR-?BBA-?[136]M` |
| `SYN_LIBOR_1M` / `_3M` / `_6M` | `(SYN(THETIC)?)-?LIBOR-?[136]M` (post-30-Jun-2023, ended 30-Sep-2024) |
| `OTHER` | Anything else — flag for review |

Per Clarus, Term-SOFR alone has **24** observed string variants;
Average-SOFR has **8** of "30+ SOFR-named strings"; BSBY has **5**.
The normaliser must match aggressively to avoid splintering volume
across unrecognised buckets.

---

## 11. Appendix C — Package-type taxonomy reference

Per "SDR – Trading Venues and Packages", "IDB Market Share in SOFR
Swaps", and ARBS's existing package-confidence scorer (PR #285):

| Type | n_legs | Detection rules (Clarus-aligned) |
|---|---|---|
| `OUTRIGHT` | 1 | `package_indicator=false`, `n_package_legs=1`. |
| `CURVE` | 2 | `package_indicator=true`, n=2, opposite-sign DV01s, derived spread (Δrate × 100) ≈ reported `package_transaction_spread` ± 0.5bp. |
| `FLY` | 3 | n=3, belly DV01 ≈ -2× wings, derived `2·rB - rF - rK` ≈ reported PTS ± 0.5bp. |
| `SPREADOVER` | 1+UST | `has_spread=true`, PTS non-zero, package_indicator=true. UST leg often implicit. |
| `SPREADOVER_CURVE` | 2+UST | Base CURVE + per-leg PTS present. |
| `SPREADOVER_FLY` | 3+UST | Base FLY + per-leg PTS present. |
| `MATCHED_MATURITY` | 2+ | All legs same maturity, distinct floating indices (basis swap). |
| `MATCHED_MATURITY_CURVE` / `_FLY` | 2+ / 3+ | Base CURVE/FLY + per-leg same-maturity check. |
| `MAC` | 1 | SIFMA standard date + integer % coupon + concentrated to roll week. |
| `IMM` | 1 | `effective_date` = 3rd-Wed of Mar/Jun/Sep/Dec. |
| `FOMC` | 1+ | `effective_date` = next FOMC meeting date (8 per year). |
| `INVOICE` | 2 | UST-vs-swap futures invoice spread (CME convention). |
| `CCPSwitch` | 2 | Same currency, same tenor, opposite signs, one LCH leg + one CME leg. |

---

## 12. Appendix D — Curated source-article inventory

The full enumeration returned **978 articles** (Chris Barnes 513,
Amir Khwaja 465). Below is the curated subset (~150) organised by
topic, picked for direct relevance to USD swaps SDR analytics. The
full enumerated lists are stored alongside this doc; cite them when
the analytic-specific article isn't in this curated list.

### D.1 Foundational SDR / SEF mechanics

| Date | Title | Author |
|---|---|---|
| 14-Aug-2013 | [Capped Notional Changes](https://www.clarusft.com/sdr-view-capped-notional-changes/) | Amir |
| 11-Sep-2013 | [SDRFIX, a new index for a post-reform world](https://www.clarusft.com/sdrfix-a-new-index-for-a-post-reform-world/) | Amir |
| 04-Sep-2013 | [Real-time reporting of Swap transactions](https://www.clarusft.com/real-time-reporting-of-swap-transactions/) | Amir |
| 12-May-2014 | [EMIR and CFTC SDR Cross Currency Swap Volumes](https://www.clarusft.com/emir-and-cftc-sdr-cross-currency-swap-volumes/) | Amir |
| 13-May-2014 | [Bloomberg SDR and SEF: What can we now see?](https://www.clarusft.com/bloomberg-sdr-and-sef-what-can-we-now-see/) | Amir |
| 20-May-2014 | [Tick Data for Swaps: What is now available?](https://www.clarusft.com/tick-data-for-swaps/) | Amir |
| 18-Sep-2019 | [CME Swap Data Repository](https://www.clarusft.com/cme-swap-data-repository/) | Amir |
| 05-Jan-2023 | [SDR – Trading Venues and Packages](https://www.clarusft.com/sdr-trading-venues-and-packages/) | Amir |
| 26-Mar-2025 | [Transparency – Where do we go from here?](https://www.clarusft.com/transparency-where-do-we-go-from-here/) | Chris |

### D.2 Package detection / curve / fly / spreadover mechanics

| Date | Title | Author |
|---|---|---|
| 14-Oct-2014 | [Mechanics and Definitions of Spread and Butterfly Swap Packages](https://www.clarusft.com/mechanics-and-definitions-of-spread-and-butterfly-swap-packages/) | Chris |
| 16-Feb-2015 | [Swap Curve and Fly Trades: A quarter of all trades are not what they first seem](https://www.clarusft.com/swap-curve-and-fly-trades-a-quarter-of-all-trades-are-not-what-they-first-seem/) | Chris |
| 23-Feb-2015 | [Swap Curve and Fly Trading: What goes in, must come out](https://www.clarusft.com/swap-curve-and-fly-trading-what-goes-in-must-come-out/) | Chris |
| 23-Mar-2015 | [Spreadovers: US Treasury Spreads in the Swaps Data](https://www.clarusft.com/spreadovers-us-treasury-spreads-in-the-swaps-data/) | Chris |
| 11-May-2015 | [Mechanics and Definitions of Spreadovers (Swap Spreads)](https://www.clarusft.com/mechanics-and-definitions-of-spreadovers-swap-spreads/) | Chris |
| 09-Aug-2016 | [Spreads and Butterflies – what is trading?](https://www.clarusft.com/spreads-and-butterflies-what-is-trading/) | Chris |
| 03-Jan-2017 | [Spreadovers](https://www.clarusft.com/spreadovers/) | Chris |
| 22-Aug-2017 | [Curve Trading in USD Swaps](https://www.clarusft.com/curve-trading-in-usd-swaps/) | Chris |
| 14-Aug-2018 | [USD Spreadovers and SEF Market Share](https://www.clarusft.com/usd-spreadovers-and-sef-market-share/) | Chris |
| 23-Sep-2020 | [Spreadovers vs SOFR](https://www.clarusft.com/spreadovers-vs-sofr/) | Chris |
| 16-Jun-2021 | [SOFR SpreadOvers are now starting to trade](https://www.clarusft.com/sofr-spreadovers-are-starting-to-trade/) | Amir |
| 24-Nov-2015 | [A sideways look at Swap Spreads](https://www.clarusft.com/a-sideways-look-at-swap-spreads/) | Chris |
| 11-Nov-2015 | [Negative Swap Spreads – Prices and Volume](https://www.clarusft.com/negative-swap-spreads-prices-and-volume/) | Chris |

### D.3 CCP basis (LCH / CME / Eurex / JSCC switches)

| Date | Title | Author |
|---|---|---|
| 20-May-2015 | [CME-LCH Basis Spread](https://www.clarusft.com/cme-lch-basis-spreads/) | Amir |
| 26-May-2015 | [CME-LCH Basis – What does the Term Structure tell us?](https://www.clarusft.com/cme-lch-basis-what-does-the-term-structure-tell-us/) | Chris |
| 30-Jun-2014 | [LCH-CME Switch Trades and Margin Management](https://www.clarusft.com/lch-cme-switch-trades/) | Amir |
| 18-Nov-2015 | [CME-LCH Basis Spreads Blow Out](https://www.clarusft.com/cme-lch-basis-spreads-blow-out/) | Amir |
| 09-Dec-2015 | [CCP Basis Spreads: What Next?](https://www.clarusft.com/ccp-basis-spreads-what-next/) | Amir |
| 30-Mar-2016 | [Identifying CCP Basis Trades in the SDR](https://www.clarusft.com/identifying-ccp-basis-trades-in-the-sdr/) | Chris |
| 05-Apr-2016 | [How to identify the CCP of trades from the SDR data](https://www.clarusft.com/how-to-identify-the-ccp-of-trades-from-the-sdr-data/) | Chris |
| 13-Apr-2016 | [CME Compression and CCP Basis](https://www.clarusft.com/cme-compression-and-ccp-basis/) | Chris |
| 18-Apr-2016 | [LCH-JSCC Basis in JPY Swaps](https://www.clarusft.com/lch-jscc-basis-in-jpy-swaps/) | Amir |
| 12-Apr-2017 | [LCH-Eurex Basis in EUR IR Swaps](https://www.clarusft.com/lch-eurex-basis-in-eur-ir-swaps/) | Amir |
| 16-May-2018 | [CCP Basis and Volume in Major Currencies](https://www.clarusft.com/ccp-basis-and-volume-in-major-currencies/) | Amir |
| 30-Jul-2019 | [CCP Basis – The Cost of Clearing Fragmentation](https://www.clarusft.com/ccp-basis-the-cost-of-clearing-fragmentation/) | Chris |
| 05-May-2020 | [CME-LCH Basis Spreads Turn Negative](https://www.clarusft.com/cme-lch-basis-spreads-turn-negative/) | Amir |

### D.4 Block trades / capping / dissemination delay

| Date | Title | Author |
|---|---|---|
| 21-Jun-2013 | [SDR Block Trade Rule – the Bad News](https://www.clarusft.com/swap-data-repository-block-trade-rule-the-bad-news/) | Amir |
| 01-Aug-2013 | [SDR, Block Trade Rule, 30 July Update](https://www.clarusft.com/sdr-block-trade-rule-30-july-update/) | Amir |
| 12-Oct-2015 | [Performance of Block Trades on RFQ Platforms](https://www.clarusft.com/performance-of-block-trades-on-rfq-platforms/) | Chris |
| 07-Oct-2015 | [Identifying Customer Block Trades in the SDR Data](https://www.clarusft.com/identifying-customer-block-trades-in-the-sdr-data/) | Chris |
| 23-Sep-2015 | [What's the story behind Tradeweb block trading?](https://www.clarusft.com/whats-the-story-behind-tradeweb-block-activity/) | Chris |
| 12-May-2020 | [CFTC Block Trading Consultation May 2020](https://www.clarusft.com/cftc-block-trading-consultation-may-2020/) | Chris |
| 30-Sep-2020 | [New Block Trading Rules for Derivatives](https://www.clarusft.com/new-block-trading-rules-for-derivatives/) | Chris |
| 10-Feb-2020 | [Block Trading](https://www.clarusft.com/block-trading/) | Chris |
| 25-Feb-2020 | [Block Trades in HKD Derivative Markets](https://www.clarusft.com/block-trades-in-hkd-derivative-markets/) | Chris |
| 19-Jul-2023 | [New Block Trading Rules Will Now Start in December 2023](https://www.clarusft.com/new-block-trading-rules-will-now-start-in-december-2023/) | Chris |
| 25-Jul-2023 | [Even More on Blocks and new rules for FX](https://www.clarusft.com/even-more-on-blocks-and-new-rules-for-fx/) | Chris |
| 13-Nov-2024 | [We Have New Block Sizes](https://www.clarusft.com/we-have-new-block-sizes/) | Chris |
| 03-Dec-2024 | [New: Kids on the Block (Sizes)](https://www.clarusft.com/new-kids-on-the-block-sizes/) | Chris |

### D.5 SOFR / RFR transition / Term-vs-Compounded

| Date | Title | Author |
|---|---|---|
| 16-May-2018 | [SOFR – What you need to know](https://www.clarusft.com/sofr-what-you-need-to-know/) | Chris |
| 17-Jul-2018 | [SOFR Swaps Are Trading!](https://www.clarusft.com/sofr-swaps-are-trading/) | Chris |
| 11-Sep-2019 | [Four Things to Understand about USD SOFR](https://www.clarusft.com/four-things-to-understand-about-usd-sofr/) | Chris |
| 16-Sep-2020 | [SOFR Swap Nuances](https://www.clarusft.com/sofr-swap-nuances/) | Chris |
| 18-Nov-2020 | [SOFR Swaps on SEFs](https://www.clarusft.com/sofr-swaps-on-sefs/) | Amir |
| 26-Jul-2021 | [SOFR First – LIVE Blog](https://www.clarusft.com/sofr-first-live-blog/) | Chris |
| 19-Oct-2021 | [SOFR Now 78% of Interdealer Market](https://www.clarusft.com/sofr-now-78-of-interdealer-market/) | Chris |
| 10-Nov-2021 | [SOFR First in Swaptions](https://www.clarusft.com/sofr-first-in-swaptions/) | Chris |
| 16-Feb-2022 | [BSBY and Term SOFR Swap Volumes](https://www.clarusft.com/bsby-and-term-sofr-swap-volumes/) | Amir |
| 22-Nov-2022 | [What's New in Term SOFR?](https://www.clarusft.com/whats-new-in-term-sofr/) | Chris |
| 21-Feb-2023 | [Average and Term SOFR Volumes in 2022](https://www.clarusft.com/average-and-term-sofr-volumes-in-2022/) | Amir |
| 24-Oct-2023 | [Term SOFR and BSBY Volumes – October 2023](https://www.clarusft.com/term-sofr-and-bsby-volumes-october-2023/) | Amir |
| 04-Apr-2023 | [Synthetic USD Libor Annoucement](https://www.clarusft.com/synthetic-usd-libor-annoucement/) | Amir |
| 04-Jul-2023 | [Bollinger, Greenspan and The Millennium Bug: LIBOR Is Now Dead](https://www.clarusft.com/bollinger-greenspan-and-the-millennium-bug-libor-is-now-dead/) | Chris |
| 29-Jul-2020 | [ISDA-Clarus RFR Adoption Indicator](https://www.clarusft.com/isda-clarus-rfr-adoption-indicator/) | Chris |
| 11-Nov-2020 | [ISDA-Clarus RFR Indicator: SOFR, So Good](https://www.clarusft.com/isda-clarus-rfr-indicator-sofr-so-good/) | Chris |
| 03-Mar-2021 | [Monitoring your own RFR Adoption Indicators](https://www.clarusft.com/monitoring-your-own-rfr-adoption-indicators/) | Amir |
| 19-Aug-2020 | [Calculate your own RFR Adoption Indicators](https://www.clarusft.com/calculate-your-own-rfr-adoption-indicators/) | Amir |
| 29-Apr-2025 | [Recreating the RFR Adoption Indicator](https://www.clarusft.com/recreating-the-rfr-adoption-indicator/) | Chris |
| 21-Oct-2024 | [RFR Adoption Q3 2024](https://www.clarusft.com/rfr-adoption-q3-2024/) | Chris |

### D.6 LIBOR conversion + cessation

| Date | Title | Author |
|---|---|---|
| 18-Apr-2018 | [USD Libor is changing!](https://www.clarusft.com/rfrs-libor-is-changing/) | Chris |
| 25-Jul-2018 | [LIBOR Fallbacks](https://www.clarusft.com/libor-fallbacks/) | Chris |
| 19-Nov-2019 | [Mechanics and Definitions of ISDA IBOR fallbacks](https://www.clarusft.com/mechanics-and-definitions-of-isda-libor-fallbacks/) | Chris |
| 27-Nov-2018 | [RFRs – ISDA announce LIBOR fallback methodology](https://www.clarusft.com/rfrs-isda-announce-libor-fallback-methodology/) | Chris |
| 08-Mar-2023 | [Clearing Houses are about to convert your USD LIBOR swaps](https://www.clarusft.com/clearing-houses-are-about-to-convert-your-usd-libor-swaps-what-do-you-need-to-know/) | Chris |
| 18-Apr-2023 | [The Eurodollar is no more…](https://www.clarusft.com/the-eurodollar-is-no-more/) | Chris |
| 03-May-2023 | [CME converted your Eurodollars. This is what happened next.](https://www.clarusft.com/cme-converted-your-eurodollars-this-is-what-happened-next/) | Chris |
| 31-May-2023 | [Now LCH Have Converted Your USD Swaps too!](https://www.clarusft.com/now-lch-have-converted-your-usd-swaps-too/) | Chris |
| 17-May-2023 | [Do you know how much now trades in RFRs after the CME conversion exercises?](https://www.clarusft.com/do-you-know-how-much-now-trades-in-rfrs-after-the-cme-conversion-exercises/) | Chris |

### D.7 IMM / MAC / FOMC dated swaps

| Date | Title | Author |
|---|---|---|
| 10-Sep-2014 | [USD MAC Swaps: A Closer Look](https://www.clarusft.com/usd-mac-swaps-a-closer-look/) | Amir |
| 22-Sep-2014 | [USD MAC Swaps: How Large is the market?](https://www.clarusft.com/usd-mac-swaps-how-large-is-the-market/) | Amir |
| 31-Mar-2015 | [The IMM Roll for Swaps – What is it and what are the volumes?](https://www.clarusft.com/the-imm-roll-for-swaps-what-is-it-and-what-are-the-volumes/) | Chris |
| 16-Aug-2017 | [MAC Swap Trading](https://www.clarusft.com/mac-swap-trading/) | Chris |
| 07-Jun-2016 | [Fed meetings and OIS Volumes](https://www.clarusft.com/fed-meetings-and-ois-volumes/) | Chris |
| 21-Dec-2015 | [Fed Surprise Indicators](https://www.clarusft.com/fed-surprise-indicators/) | Chris |
| 05-Jan-2016 | [Fed Surprises in the USD OIS Data](https://www.clarusft.com/fed-surprises-in-the-usd-ois-data/) | Chris |

### D.8 Cross-currency swaps

| Date | Title | Author |
|---|---|---|
| 22-Oct-2013 | [Cross Currency Swap trades in Swap Data Repositories](https://www.clarusft.com/cross-currency-swap-trades-in-swap-data-repositories/) | Amir |
| 03-Mar-2014 | [SDRFix – On SEF & Cross Currency Swaps](https://www.clarusft.com/sdrfix-an-update-on-sef-cross-currency-swaps/) | Amir |
| 17-Mar-2015 | [Cross Currency Swaps: SEFs enjoy QE-fueled volume boost](https://www.clarusft.com/cross-currency-swaps-sefs-enjoy-qe-fueled-volume-boost/) | Chris |
| 18-Apr-2017 | [Mechanics of Cross Currency Swaps](https://www.clarusft.com/mechanics-of-cross-currency-swaps/) | Chris |
| 30-Oct-2017 | [Cross Currency Swap Volumes](https://www.clarusft.com/cross-currency-swap-volumes/) | Chris |
| 27-Feb-2018 | [All time record volumes in Cross Currency Swaps](https://www.clarusft.com/all-time-record-volumes-in-cross-currency-swaps/) | Chris |
| 09-Apr-2018 | [Cross Currency Swaps and Libor-OIS](https://www.clarusft.com/cross-currency-swaps-and-libor-ois/) | Chris |
| 02-Oct-2018 | [Cross Currency Basis and Turn of the Year](https://www.clarusft.com/cross-currency-basis-and-turn-of-the-year/) | Chris |
| 18-Mar-2020 | [Cross Currency Swaps Trading During a Crisis](https://www.clarusft.com/cross-currency-swaps-trading-during-a-crisis/) | Chris |
| 06-Oct-2021 | [Mechanics and Definitions of RFR Cross Currency Swaps](https://www.clarusft.com/mechanics-and-definitions-of-rfr-cross-currency-swaps/) | Chris |
| 02-Feb-2022 | [What is now Trading in RFR Cross Currency Swaps?](https://www.clarusft.com/what-is-now-trading-in-rfr-cross-currency-swaps/) | Chris |
| 18-Jan-2023 | [Cross Currency Swap Review 2022](https://www.clarusft.com/cross-currency-swap-review-2022/) | Chris |
| 17-Jan-2024 | [Cross Currency Swaps Review 2023](https://www.clarusft.com/cross-currency-swaps-review-2023/) | Chris |
| 08-Jan-2025 | [Cross Currency Swaps Review 2024](https://www.clarusft.com/cross-currency-swaps-review-2024/) | Chris |
| 04-Feb-2025 | [Mechanics and Definitions of Cross Currency Basis Futures](https://www.clarusft.com/mechanics-and-definitions-of-cross-currency-basis-futures/) | Chris |

### D.9 Swaptions

| Date | Title | Author |
|---|---|---|
| 15-Jan-2014 | [Swaptions trading on SEF platforms](https://www.clarusft.com/swaptions-trading-on-sef-platforms/) | Amir |
| 28-Jan-2015 | [Swaption Volumes in 2014](https://www.clarusft.com/swaption-volumes-in-2014/) | Amir |
| 17-Nov-2021 | [SOFR Swaptions – Week One Update](https://www.clarusft.com/sofr-swaptions-week-one-update/) | Amir |
| 01-Dec-2021 | [SOFR Swaptions – Month One Update](https://www.clarusft.com/sofr-swaptions-month-one-update/) | Amir |
| 16-Feb-2021 | [SOFR Swaptions and CapsFloors are now trading regularly](https://www.clarusft.com/sofr-swaptions-and-capsfloors-are-now-trading-regularly/) | Amir |
| 05-May-2021 | [Swaption Volumes by Strike Q1 2021](https://www.clarusft.com/swaption-volumes-by-strike-q1-2021/) | Amir |
| 05-Apr-2022 | [Swaption Volumes by Strike Q1 2022](https://www.clarusft.com/swaption-volumes-by-strike-q1-2022/) | Chris |
| 22-Nov-2023 | [Swaption Volumes by Strike Q3 2023](https://www.clarusft.com/swaption-volumes-by-strike-q3-2023/) | Chris |
| 28-May-2024 | [Swaption Volumes by Strike Q1 2024](https://www.clarusft.com/swaption-volumes-by-strike-q1-2024/) | Chris |
| 03-Jul-2024 | [Swaption Volumes by Strike Q2 2024](https://www.clarusft.com/swaption-volumes-by-strike-q2-2024/) | Chris |
| 19-Nov-2024 | [Swaption Volumes by Strike Q3 2024](https://www.clarusft.com/swaption-volumes-by-strike-q3-2024/) | Chris |
| 11-Mar-2025 | [Swaption Volumes by Strike Q4 2024](https://www.clarusft.com/swaption-volumes-by-strike-q4-2024/) | Chris |
| 27-Aug-2024 | [Volumes in EUR Swaptions](https://www.clarusft.com/volumes-in-eur-swaptions/) | Chris |
| 12-Jun-2024 | [SOFR Options – How Healthy Is The Market?](https://www.clarusft.com/sofr-options-how-healthy-is-the-market/) | Chris |

### D.10 Stress events / margin / VM

| Date | Title | Author |
|---|---|---|
| 14-Apr-2020 | [Swaps Data: How the market responded to Covid-19](https://www.clarusft.com/swaps-data-how-the-market-responded-to-covid-19/) | Amir |
| 11-Mar-2020 | [Crashing Rates and Swap Margins](https://www.clarusft.com/crashing-rates-and-swap-margins/) | Amir |
| 25-Mar-2020 | [USD Swap Markets during COVID-19 Pandemic](https://www.clarusft.com/usd-swap-markets-during-covid-19-pandemic/) | Chris |
| 07-Apr-2020 | [Swap Markets see Record Trading Volumes in response to COVID-19](https://www.clarusft.com/swap-markets-see-record-trading-volumes-in-response-to-covid19-market-turmoil/) | Chris |
| 27-Sep-2022 | [The GBP Financial Meltdown – what is still trading?](https://www.clarusft.com/the-gbp-financial-meltdown-what-is-still-trading/) | Chris |
| 21-Nov-2022 | [GBP Swaps variation margin in a financial crisis](https://www.clarusft.com/gbp-swaps-variation-margin-in-a-financial-crisis/) | Amir |
| 22-Mar-2023 | [USD Swaps Margin Calls in March 2023](https://www.clarusft.com/usd-swaps-margin-calls-in-march-2023/) | Amir |
| 14-Mar-2023 | [How to Trade A Bank Run](https://www.clarusft.com/how-to-trade-a-bank-run/) | Chris |
| 14-Apr-2025 | [Swapalypse Now](https://www.clarusft.com/swapalypse-now/) | Chris |
| 11-Jun-2018 | [Swaps Data: Anatomy of a Wild Week in USD Swaps](https://www.clarusft.com/swaps-data-anatomy-of-a-wild-week-in-usd-swaps/) | Amir |
| 16-Oct-2014 | [Swaps and the Flash Crash 15th October 2014](https://www.clarusft.com/swaps-and-the-flash-crash-15th-october-2014/) | Chris |

### D.11 Liquidity / venue / SEF rankings

| Date | Title | Author |
|---|---|---|
| 27-Jan-2015 | [Liquidity in USD Swaps](https://www.clarusft.com/liquidity-in-usd-swaps/) | Chris |
| 02-Dec-2014 | [USD Swaps Liquidity](https://www.clarusft.com/usd-swaps-liquidity/) | Chris |
| 25-Jul-2016 | [Liquidity Conditions in USD Swaps](https://www.clarusft.com/liquidity-conditions-in-usd-swaps/) | Chris |
| 01-Mar-2016 | [Liquidity Variables in the Swaps Market](https://www.clarusft.com/liquidity-variables-in-the-swaps-market/) | Chris |
| 24-Jun-2015 | [Liquidity](https://www.clarusft.com/liquidity/) | Chris |
| 24-Nov-2020 | [Anonymous Trading on SEFs](https://www.clarusft.com/anonymous-trading-on-sefs/) | Chris |
| 27-Apr-2021 | [SEF Liquidity In RFRs](https://www.clarusft.com/you-need-to-see-this-sef-liquidity-in-rfrs-now/) | Chris |
| 12-Feb-2019 | [What Traded On-SEF in 2018?](https://www.clarusft.com/what-traded-on-sef-in-2018/) | Chris |
| 06-Feb-2019 | [What Traded Off-SEF in 2018?](https://www.clarusft.com/what-traded-off-sef-in-2018/) | Chris |
| 04-Jun-2024 | [SOFR Swap SEF Volumes – May 2024](https://www.clarusft.com/sofr-swap-sef-volumes-may-2024/) | Amir |
| 14-Feb-2024 | [2023 SEF Volumes and Share in SOFR Swaps](https://www.clarusft.com/2023-sef-volumes-and-share-in-sofr-swaps/) | Amir |
| 01-Aug-2023 | [SOFR Swaps Volumes and Share – July 2023](https://www.clarusft.com/sofr-swaps-volumes-and-share-july-2023/) | Amir |
| 01-Feb-2023 | [SOFR Swaps D2D Volumes and Share](https://www.clarusft.com/sofr-swaps-d2d-volumes-and-share/) | Amir |
| 10-May-2023 | [IDB Market Share in SOFR Swaps](https://www.clarusft.com/idb-market-share-in-sofr-swaps/) | Amir |
| 25-Jan-2022 | [2021 SEF Volumes and Share – CRD and FXD](https://www.clarusft.com/2021-sef-volumes-and-market-share-crd-and-fxd/) | Amir |
| 09-Jan-2018 | [2018 SEF Market Share Statistics](https://www.clarusft.com/2018-sef-market-share-statistics/) | Amir |

### D.12 CCP volumes (annual / quarterly)

| Date | Title | Author |
|---|---|---|
| 16-Oct-2024 | [3Q24 CCP Volumes and Share in IRD](https://www.clarusft.com/3q24-ccp-volumes-and-share-in-ird/) | Amir |
| 10-Jul-2024 | [2Q24 CCP Volumes and Share in IRD](https://www.clarusft.com/2q24-ccp-volumes-and-share-in-ird/) | Amir |
| 15-Apr-2024 | [1Q24 CCP Volumes and Share in IRD](https://www.clarusft.com/1q24-ccp-volumes-and-share-in-ird/) | Amir |
| 09-Jan-2024 | [2023 CCP Volumes and Share in IRD](https://www.clarusft.com/2023-ccp-volumes-and-share-in-ird/) | Amir |
| 17-Jan-2023 | [2022 CCP Volumes and Market Share in IRD](https://www.clarusft.com/2022-ccp-volumes-and-market-share-in-ird/) | Amir |
| 11-Jan-2022 | [2021 CCP Volumes and Market Share in IRD](https://www.clarusft.com/2021-ccp-volumes-and-market-share-in-ird/) | Amir |
| 13-Jan-2021 | [2020 CCP Volumes and Market Share in IRD](https://www.clarusft.com/2020-ccp-volumes-and-market-share-in-ird/) | Amir |

### D.13 PFMI quarterly disclosures

| Date | Title | Author |
|---|---|---|
| 17-Sep-2024 | [What's New in CCP Disclosures – 2Q24?](https://www.clarusft.com/whats-new-in-ccp-disclosures-2q24/) | Amir |
| 19-Jun-2024 | [What's New in CCP Disclosures – 1Q24?](https://www.clarusft.com/whats-new-in-ccp-disclosures-1q24/) | Amir |
| 12-Mar-2024 | [What's New in CCP Disclosures – 4Q23?](https://www.clarusft.com/whats-new-in-ccp-disclosures-4q23/) | Amir |
| 13-Dec-2023 | [What's New in CCP Disclosures – 3Q23?](https://www.clarusft.com/whats-new-in-ccp-disclosures-3q23/) | Amir |
| 05-Sep-2023 | [What's New in CCP Disclosures – 2Q23?](https://www.clarusft.com/whats-new-in-ccp-disclosures-2q23/) | Amir |
| 14-Mar-2023 | [What's New in CCP Disclosures – 4Q22?](https://www.clarusft.com/whats-new-in-ccp-disclsoures-4q22/) | Amir |
| 09-Oct-2019 | [CPMI-IOSCO Quantitative Disclosures 2Q 2019](https://www.clarusft.com/cpmi-iosco-quantitative-disclosures-2q-2019/) | Amir |

### D.14 Compression / lifecycle

| Date | Title | Author |
|---|---|---|
| 12-Dec-2013 | [Compression, SDR and TrueEx SEF](https://www.clarusft.com/compression-sdr-and-trueex-sef/) | Amir |
| 22-Jul-2014 | [Swaps Compression and Compaction on trueEX and Tradeweb SEFs](https://www.clarusft.com/swaps-compression-and-compaction-on-trueex-and-tradeweb-sefs/) | Amir |
| 05-Aug-2014 | [Swaps Compression: Clearing Fees and Margin](https://www.clarusft.com/swaps-compression-clearing-fees-and-margin/) | Amir |
| 09-Sep-2015 | [TriOptima Compression at CME](https://www.clarusft.com/trioptima-compression-at-cme/) | Amir |
| 24-Mar-2015 | [Compression List Trading On SEFs](https://www.clarusft.com/compression-list-trading-on-sefs/) | Amir |
| 16-Dec-2015 | [Compression in Swaps](https://www.clarusft.com/compression-in-swaps/) | Chris |
| 27-Feb-2019 | [Compression Auctions for RFRs](https://www.clarusft.com/compression-auctions-for-rfrs/) | Chris |

### D.15 Capital / margin / risk frameworks (context)

| Date | Title | Author |
|---|---|---|
| 26-Jan-2022 | [Mechanics and Definitions of SA-CCR (Part 1)](https://www.clarusft.com/mechanics-and-definitions-of-sa-ccr-part-1/) | Chris |
| 22-Feb-2022 | [Mechanics and Definitions of SA-CCR (Part 2)](https://www.clarusft.com/mechanics-and-definitions-of-sa-ccr-part-2/) | Chris |
| 14-Jun-2022 | [Mechanics and Definitions of SA-CCR (Part 3)](https://www.clarusft.com/mechanics-and-definitions-of-sa-ccr-part-3/) | Chris |
| 07-Aug-2017 | [FRTB – Simplified Standardised Approach](https://www.clarusft.com/frtb-simplified-standardised-approach/) | Amir |
| 12-Sep-2017 | [ISDA SIMM 2.0 – What You Need to Know](https://www.clarusft.com/isda-simm-2-0/) | Chris |
| 19-Sep-2023 | [ISDA SIMM – What changes in v2.6?](https://www.clarusft.com/isda-simm-what-changes-in-v2-6/) | Amir |
| 13-Mar-2024 | [Mechanics and Definitions of the ISDA Credit Support Annex (CSA)](https://www.clarusft.com/mechanics-and-definitions-of-the-isda-credit-support-annex-csa/) | Chris |
| 13-Jun-2018 | [Settle To Market – What You Need To Know about STM](https://www.clarusft.com/settle-to-market-what-you-need-to-know-about-stm/) | Chris |

### D.16 Single-currency country deep-dives

| Date | Title | Author |
|---|---|---|
| 08-Apr-2025 | [What You Need to Know About KRW Swaps](https://www.clarusft.com/what-you-need-to-know-about-krw-swaps/) | Chris |
| 17-Mar-2025 | [CNY Swaps – What's New?](https://www.clarusft.com/cny-swaps-whats-new/) | Chris |
| 30-Nov-2023 | [What You Need to Know About INR Swaps](https://www.clarusft.com/what-you-need-to-know-about-inr-swaps/) | Chris |
| 18-Dec-2024 | [INR Swaps – What's New?](https://www.clarusft.com/inr-swaps-whats-new/) | Chris |
| 27-Nov-2024 | [MXN Swaps – What's New?](https://www.clarusft.com/mxn-swaps-whats-new/) | Chris |
| 30-Aug-2023 | [What You Need to Know about BRL Swaps](https://www.clarusft.com/what-you-need-to-know-about-brl-swaps/) | Chris |
| 10-Jun-2020 | [What You Need to Know About CNY Swaps](https://www.clarusft.com/what-you-need-to-know-about-cny-swaps/) | Chris |
| 08-Jan-2020 | [What You Need to Know about MXN Swaps](https://www.clarusft.com/what-you-need-to-know-about-mxn-swaps/) | Chris |
| 24-Jan-2019 | [JPY Swaps – A Market Overview](https://www.clarusft.com/jpy-swaps-a-market-overview/) | Chris |
| 05-Jul-2017 | [GBP Swaps for Dummies](https://www.clarusft.com/gbp-swaps-for-dummies/) | Chris |
| 04-Sep-2024 | [USD Rates – What's New?](https://www.clarusft.com/usd-rates-whats-new/) | Chris |
| 21-Jan-2025 | [USD Rates 2024 Review](https://www.clarusft.com/usd-rates-2024-review/) | Chris |
| 31-Jan-2024 | [USD Rates Overview in 2024](https://www.clarusft.com/usd-rates-overview-in-2024/) | Chris |
| 07-May-2024 | [What's New in AUD Swaps in 2024?](https://www.clarusft.com/whats-new-in-aud-swaps-in-2024/) | Chris |
| 10-Apr-2024 | [What's New in JPY Swaps in 2024?](https://www.clarusft.com/whats-new-in-jpy-swaps-in-2024/) | Chris |

### D.17 Time-series / VWAP / pricing

| Date | Title | Author |
|---|---|---|
| 04-Feb-2014 | [Intra-Day Swap Prices – What Can We See?](https://www.clarusft.com/intra-day-swap-prices-what-can-we-see/) | Amir |
| 25-Mar-2013 | [Swaps, actual traded prices and size](https://www.clarusft.com/swaps-actual-traded-prices-and-size/) | Amir |
| 11-Oct-2013 | [USD Swap Prices on SEF platforms](https://www.clarusft.com/usd-swap-prices-on-sef-platforms/) | Amir |
| 03-Feb-2016 | [SDR Prices, Python and plotly](https://www.clarusft.com/sdr-prices-python-and-plotly/) | Chris |
| 21-Mar-2016 | [Swaps Price Data – Painting the full Liquidity Picture](https://www.clarusft.com/swaps-price-data-painting-the-full-liquidity-picture/) | Chris |
| 02-Dec-2014 | [IR Swap Prices on Reuters, Bloomberg and SDR](https://www.clarusft.com/ir-swap-prices-rcm19901-swappx-and-sdr/) | Amir |
| 29-Nov-2023 | [Time Series of Swap Prices and Volumes](https://www.clarusft.com/time-series-of-swap-prices-and-volumes/) | Amir |
| 03-Jul-2017 | [Swaps Data Review: A Day in the Life of a Swap](https://www.clarusft.com/swaps-data-review-a-day-in-the-life-of-a-swap/) | Amir |
| 12-Nov-2014 | [Price Making in Swaps and Sharpening your Axe](https://www.clarusft.com/price-making-in-swaps-and-sharpening-your-axe/) | Amir |
| 08-Dec-2015 | [Is that a fair price? Measuring Swap Execution](https://www.clarusft.com/is-that-a-fair-price-measuring-swap-execution/) | Chris |
| 03-Feb-2021 | [Have You Seen This New Idea for Execution Analysis?](https://www.clarusft.com/have-you-seen-this-new-idea-for-execution-analysis/) | Chris |

### D.18 Themed indices / event studies / specials

| Date | Title | Author |
|---|---|---|
| 01-Apr-2025 | [What Would a Liberation Index Look Like?](https://www.clarusft.com/what-would-a-liberation-index-look-like/) | Chris |
| 30-Nov-2021 | [What is a Consolidated Tape?](https://www.clarusft.com/what-is-a-consolidated-tape/) | Chris |
| 24-Nov-2021 | [Consolidated Tape: Don't let perfection be the enemy of good for derivatives](https://www.clarusft.com/consolidated-tape-dont-let-perfection-be-the-enemy-of-good-for-derivatives/) | Chris |
| 08-Oct-2024 | [Pre-Hedging in Swaps](https://www.clarusft.com/pre-hedging-in-swaps/) | Chris |
| 11-Mar-2014 | [Trade Surveillance in Swaps Trading](https://www.clarusft.com/trade-surveillance-in-swaps-trading/) | Amir |
| 16-Jan-2019 | [Mechanics and Definitions of Carry in Swap Markets](https://www.clarusft.com/mechanics-and-definitions-of-carry-in-swap-markets/) | Chris |
| 18-May-2015 | [Mechanics of Asset Swaps and Government Bond Swap Spreads](https://www.clarusft.com/mechanics-of-asset-swaps-and-government-bond-swap-spreads/) | Chris |
| 19-Jul-2016 | [Mechanics and Definitions of Bond Futures](https://www.clarusft.com/mechanics-and-definitions-of-bond-futures/) | Chris |
| 06-Jul-2016 | [Mechanics and Definitions of Short Term Interest Rate Futures](https://www.clarusft.com/mechanics-definitions-and-volumes-for-short-term-interest-rate-futures/) | Chris |
| 04-Sep-2018 | [Mechanics of FRA Risks](https://www.clarusft.com/mechanics-of-fra-risks/) | Chris |
| 02-May-2018 | [Swaps Regulations Are Changing – Part One, SEFs](https://www.clarusft.com/swaps-regulations-are-changing-part-one-sefs/) | Chris |
| 09-May-2018 | [Swaps Regulations Are Changing – Part Two, Capital and CCPs](https://www.clarusft.com/swaps-regulations-are-changing-part-two-capital-and-ccps/) | Chris |

### D.19 Macro / TON-of-USD-only retrospectives

| Date | Title | Author |
|---|---|---|
| 13-Jan-2015 | [A Review of 2014 US Swap Volumes](https://www.clarusft.com/a-review-of-2014-us-swap-volumes/) | Amir |
| 12-Jan-2016 | [Review of 2015 US Swap Volumes in SDRs](https://www.clarusft.com/review-of-2015-us-swap-volumes-in-sdrs/) | Amir |
| 16-Dec-2013 | [2013, The Year The Swap Market Changed](https://www.clarusft.com/2013-the-year-the-swap-market-changed/) | Amir |
| 11-Dec-2019 | [Four Trends in Swaps Data 2019](https://www.clarusft.com/four-trends-in-swaps-data-2019/) | Chris |

### D.20 Full archive (raw enumeration)

The full enumerated lists (Chris 513 + Amir 465) are archived inline
in the conversation transcript that produced this doc and can be
re-enumerated via the canonical entry points:

- https://www.clarusft.com/author/chris/
- https://www.clarusft.com/author/amir/

Both author archives render the full post list on a single HTML page
(the `?page=N` URLs all return the same full archive); a single
WebFetch per author is sufficient to reproduce the enumeration.

---

## 13. Appendix E — Block size thresholds reference

### Pre-Oct-2024 thresholds (ABT regime)

Source: "Block Trading" (10-Feb-2020), citing CFTC 2013-12133a.

5-Year IRS (representative; thresholds varied by tenor, similar
across major currencies):

| Currency | 5-Year Capped Notional |
|---|---|
| USD | $240m |
| EUR | $240m equivalent |
| GBP | $240m equivalent |
| JPY | $240m equivalent |

True average ticket exceeded the cap by ~30% (USD 34%, EUR 26%, GBP
25%). Capped trades were 7% of trade count = 43% of notional volume.

### Post-Oct-2024 thresholds (recalibrated)

Source: "We Have New Block Sizes" (13-Nov-2024), "New: Kids on the
Block (Sizes)" (03-Dec-2024).

Recalibration multipliers vs. prior regime:

| Currency | Block-size multiplier | Avg block in DV01 |
|---|---|---|
| USD | ×1.64 (larger) | ~$233K |
| EUR | ×1.29 (larger) | ~$185K |
| GBP | ×0.77 (smaller) | ~$109K |
| JPY | ×0.53 (smaller) | (smaller) |

Dark-notional share dropped ~50% → ~25% for USD. October 2024 capped
trade count: 3,910 (vs. ~7,820 monthly average through 2024 H1).
Cleared-USD-swap SDR coverage rose to 80%.

**ARBS guidance.** All historical volume series spanning 04-Oct-2024
must apply pre/post scaling (or display the threshold change as a
visible step) to avoid spurious "volume drop" interpretations.

---

## 14. Appendix F — Spreadover / curve / fly formal mechanics

### Spreadover

Source: "Mechanics and Definitions of Spreadovers (Swap Spreads)"
(11-May-2015).

- **Price**:  P(0,t₁) = S(0,t₁) − B(0,t₁)
  where S = swap rate to maturity t₁, B = bond yield to t₁ (or
  nearest available UST tenor — exact maturity match not required
  since UST refunds at predictable cycles).
- **DV01-neutral hedge**:  D_S(0,t₁) = D_B(0,t₁)
- **Convention**: direction is referenced from the *bond* leg.
  Buying the bond = paying swap fixed.
- **Composition**: ~15% of daily swap risk traded; 5Y and 10Y
  dominate; 89% on-SEF as of mid-2015 (regulatory mandate since
  Jun-2014).

### Curve (spread)

Source: "Mechanics and Definitions of Spread and Butterfly Swap
Packages" (14-Oct-2014).

- **Price**:  P_curve = R_long − R_short  (in bp)
- **Sign convention**: pay-fixed long = "buying the curve".
  Long maturity pays fixed, short maturity receives fixed.
- **DV01 ratio**:
  N_short = (D_long / D_short) × N_long, ⇒ Σ DV01 = 0
- **NPV**: each leg priced at market = zero NPV at inception
  (no convexity complication).

### Fly (butterfly)

- **Price**:  P_fly = 2·R_belly − R_front − R_back  (in bp)
- **Sign convention**: belly opposite the wings.
  Buying the fly = receiving fixed on belly + paying fixed on wings
  (or the inverse).
- **DV01 ratio**:
  N_wing = (D_belly / D_wing) × (N_belly / 2), ⇒ Σ DV01 = 0
- **Equivalent re-expression**: fly = (belly − front spread) −
  (back − belly spread) — i.e. a spread of spreads.

### ARBS implication

Our package-confidence scorer (PR #285) implements both the DV01-sum
and price-derivation checks for CURVE and FLY at ±0.5bp default
tolerance. The Clarus mechanics confirm both checks are correct;
the per-leg sign convention check we already have is the standard
"belly opposite wings" rule.

---

## 15. Appendix G — Cross-currency conventions

Sources: "Mechanics of Cross Currency Swaps" (18-Apr-2017),
"Mechanics and Definitions of RFR Cross Currency Swaps" (06-Oct-2021),
"What is now Trading in RFR Cross Currency Swaps?" (02-Feb-2022).

### Float-vs-Float MTM resettable basis (D2D market standard)

- USD leg: 3M USD-SOFR (post-2022; previously USD-LIBOR), zero
  spread.
- Foreign-currency leg: foreign 3M (formerly IBOR, now RFR) +
  basis spread (bp).
- Mark-to-Market reset: every 3M, USD notional cash-settles
  (FX_today × N_FCY × df_FCY/df_USD vs prior period's USD notional).
  Eliminates accumulated FX risk between coupon dates.
- Final notional exchange occurs on maturity date itself; coupons
  carry a 2-day payment lag.

### RFR-vs-RFR pairs (≥95% adoption since 21-Sep-2021)

EURUSD, GBPUSD, USDJPY, USDCHF, USDSGD — all legs are RFR (€STR /
SONIA / TONA / SARON / SORA + USD-SOFR).

### Term-vs-RFR pairs (still IBOR-side)

AUDUSD (BBSW), NZDUSD (NZ-BBR-FRA), CADUSD (CDOR → CORRA in
transition), SEKUSD (STIBOR), NOKUSD (NIBOR), DKKUSD (CIBOR),
HKDUSD (HIBOR), MXNUSD (TIIE).

### Fixed-vs-RFR pairs

TRYUSD: Fixed-TRY vs USD-SOFR.

### Non-deliverable swaps (USD-settled)

KRW: 87% of KRW SDR-reported swaps are USD-settled NDS.
Some CNY non-deliverable similarly.

### 2024 XCCY summary

Total XCCY volume >$7tn, +12% trade counts YoY. EURUSD +18%
notional, +23% trades; mat compressed 10Y → 8Y. JPYUSD +43% (record).
AUDUSD +17%. GBPUSD flat-to-down. On-SEF share dropped from 79%
(Jan-2024) to 65% (Dec-2024).

---

## 16. Appendix H — IMM / MAC / FOMC date detection rules

### IMM (3rd Wed Mar/Jun/Sep/Dec)

Source: "The IMM Roll for Swaps" (31-Mar-2015).

- Detection: `effective_date` falls on 3rd Wednesday of Mar/Jun/
  Sep/Dec for the next 4 quarters, OR the package_type is
  pre-tagged `IMM`.
- Roll concentration: Friday before expiration accounts for ~21%
  of identified roll DV01.
- Identification heuristic: matching benchmark maturities + identical
  timestamp on package legs.

### MAC (SIFMA standard dates)

Source: "USD MAC Swaps: A Closer Look" (10-Sep-2014), "MAC Swap
Trading" (16-Aug-2017), inferred from later articles.

- IMM start dates (3rd Wed of MAR/JUN/SEP/DEC).
- Coupon: integer-quarter % (0.25 increment); e.g. 5Y MAC at 2.25%
  for one cycle.
- Tenors: 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y, 30Y (standard set).
- MAT (first 2 IMM dates): on-SEF mandatory.
- Detection in SDR: `effective_date` ∈ MAC calendar AND fixed_rate
  is integer-multiple of 0.25 AND (optional) Tradeweb venue.
  Concentration: spike around quarterly roll week.

### FOMC

Source: "Fed meetings and OIS Volumes" (07-Jun-2016), "Fed Surprise
Indicators" (21-Dec-2015), "Fed Pulse – A New OIS Index"
(20-Jan-2016).

- Detection: `effective_date` falls on next FOMC meeting date.
- 8 FOMC meetings per year (calendar known months ahead).
- Historical pattern: volume spike during the week of meetings.
- "Fed Surprise" indicator: Fed-Funds OIS rate moves on meeting day
  vs. prior day's implied rate.

### ARBS implication

Our `economic_class` matrix already captures lifecycle classes; the
ARBS roll-calendar utility for FOMC clusters (Phase E) covers FOMC
detection. MAC/IMM detection requires the integer-coupon + IMM-date
rules above; partly present in `package_type` enrichment.

---

## 17. Appendix I — Recent USD-rates summary (2024 baseline)

Source: "USD Rates 2024 Review" (21-Jan-2025).

- Cleared OIS volume: $264tn (+11% YoY).
- LCH SwapClear: 97.9% USD share; CME OTC: 2.1%.
- USD rates total >$1 quadrillion (only 2nd time ever):
  - Exchange-traded futures: 55%
  - OTC swaps: 24%
  - Cash bonds: 20%
- D2D SEF share by package type (DV01 basis):

| Package | Top venue | Share | Runner-up | Share |
|---|---|---|---|---|
| Spreadovers | ICAP | 43% | BGC | 23% |
| Butterflies | Tradition | 63% | Dealerweb | 38% |
| Curves | ICAP | 34% | Tradition | 22% |
| CCP Switches | Tradition | 68% | ICAP | 17% |

(BGC is also material in curves at 20%; the top-2 in butterflies
sums to >100% because of the analytic perspective — Tradition is
quoted ex-Dealerweb in some cuts.)

Average portfolio maturity by package: 6.6 to 7.84 years across
products. These are useful baselines for §5.2 market-share dashboard
calibration.

---

## 13. Out of scope for this doc

- Implementation of any one analytic — each §5 item should spawn its
  own design + plan pair under the existing `docs/plans/` cadence.
- Pricing / curve-construction methodology (covered by `eris-curvestore`
  + curve plans).
- Swaption-vol-surface modelling (covered by `sofr-swaptions-tape`
  feature plans).
- Treasury / repo / bond data pipelines (own product line).

---

## 14. Recommended next step

Pick one of: §5.1 (PA-DV01, half-day) for a quick win, or §5.2
(market-share dashboard, ~1-2 weeks) for the marquee feature.
Either spawns a dedicated design + implementation plan pair and we
proceed from the existing TDD cadence used in PR #285.
