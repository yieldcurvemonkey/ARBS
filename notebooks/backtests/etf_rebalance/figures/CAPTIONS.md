# Figure pack - findings and sources

21 figures, in the order they appear in `FIGURE_PACK.html`. The full writeup is `RESULTS.md`; numbers that disagree with it are listed at the bottom rather than reconciled silently.

## What the fund actually does

### `fund_01_ladder_heatmap.png`

**Finding.** TLT's active weights are large and they ride DOWN the ladder with the bond that carries them - a standing portfolio shape, not a queue of dislocations waiting to revert.

**Source.** _data/fundfig_ladder_TLT.parquet, fundfig_flow_TLT_TLH.parquet (built from MDP/ETFHoldings, 2,528 TLT documents).

### `fund_02_deletion_shed.png`

**Finding.** TLT really does shed a deleted bond - median 5% of the position left at +120 business days - in tranches over months, never on one month-end; and the price effect still refuses the flow story.

**Source.** _data/delcliff_holdings_verification.csv, raw_holdings_TLT_TLH.parquet, fundfig_active_TLT.parquet.

### `fund_03_ownership_scale.png`

**Finding.** The Fed holds a median 17.8% of a Treasury issue and TLT 1.10%: the fund's own realised trade is undetectable in the same day's price (|t| <= 0.94 on five funds), which is the feasibility test the project needed to pass.

**Source.** _data/aggown_full_panel.parquet (430,140 bond-days, 2018-2026).

### `fund_04_creation_redemption.png`

**Finding.** A creation basket is one pro-rata scaling of the whole book (median 99.9% explained) - the fund made bigger, not a set of bonds anyone picked.

**Source.** _data/raw_holdings_TLT_TLH.parquet (2,520 usable TLT document pairs).

### `fund_05_persistence.png`

**Finding.** The most overweight name is still the most overweight 86% of the time three weeks later while the richest bond holds only 59%: a near-constant cannot forecast a series with a 17-day half-life.

**Source.** _data/fundfig_active_TLT.parquet, fundfig_flow_TLT_TLH.parquet, ust_panel.parquet.

## Seasonality

### `seas_01_month_end_signal_vs_control.png`

**Finding.** The month-end tilt in the holdings spread is BACKWARDS and a maturity-matched placebo covers it; the holdings-free richness control earns 5x more per unit of spread and is still 3.4x below the round trip.

**Source.** _data/seas_cells_TLT_bd_me_h10.csv, seas_cells_control_TLT_bd_me.csv, seas_headline_numbers.json.

### `seas_02_calendar_cuts_small_multiples.png`

**Finding.** Charge the 70-cell search and no calendar cut of the holdings signal clears its placebo: family-wise p = 0.21.

**Source.** _data/seas_cells_TLT_{dom,dow,moy}_h10.csv, seas_headline_numbers.json.

### `seas_03_reconstitution_intensity.png`

**Finding.** The reconstitution IS real in the funds' own filings - the average fund trades 3.5x its own average day on the last trading day of the month - but TLT, the only fund this pack trades, is the weakest of the twelve at 1.5x.

**Source.** _data/seas_fund_intensity.csv, seas_calendar_ALL.csv (22,904 documents, 12 funds).

### `seas_04_opportunity_dispersion.png`

**Finding.** The opportunity does not swell at the reconstitution, and 0 of 12 months put a full TLT round trip of cross-sectional dispersion on the table.

**Source.** _data/seas_disp_TLT_*.csv, seas_disp_TLH_*.csv.

### `seas_05_yearly_stability_search_cost.png`

**Finding.** The strongest seasonal cell in the study is carried by one year (2016) and is beaten by a holdings-free placebo draw one time in five.

**Source.** _data/seas_yearly_best_TLT.csv, seas_placebo_null_TLT.csv.

## The signal firing

### `fig01_trigger_timeline.png`

**Finding.** 1,407 butterflies gross +6.3bp over ten years and pay 706bp of measured FedInvest spread; the control that reads no holdings file grosses eight times more per trade and also loses.

**Source.** _data/trig_closed.parquet, trig_closed_control_resid.parquet, trig_closed_null_deletion.parquet.

### `fig02_one_trade_anatomy.png`

**Finding.** The most recent trigger end to end: the signal called the direction correctly and the move it was right about was a fifth of the spread.

**Source.** _data/trig_lastday.parquet, trig_lastpath.parquet, trig_legs.parquet, trig_meta.json.

### `fig03_score_distribution.png`

**Finding.** A trigger is a rank, not a threshold: the rule takes half of the |z| > 3 tail but also 14-16% of the |z| ~ 1.5 body, whatever the cross-section looks like.

**Source.** _data/trig_scores.parquet, trig_closed.parquet.

### `fig04_edge_by_dislocation.png`

**Finding.** Gross edge does not scale with the size of the dislocation - the extreme |z| > 3 bucket is negative - and the net hit rate is 1-5% at every bucket.

**Source.** _data/trig_closed.parquet.

### `fig05_pnl_waterfall.png`

**Finding.** Execution is 112x the entire gross P&L of the strategy, and the price leg - the part a signal is supposed to drive - is NEGATIVE over ten years.

**Source.** _data/trig_closed.parquet.

## Real versus null

### `contrast_01_raw_vs_partial_ic.png`

**Finding.** Remove the bond's own richness and five of the six holdings signals change sign; the sixth collapses to zero.

**Source.** _data/partial_ic.parquet, ic_surface.parquet.

### `contrast_02_naive_vs_hac_t.png`

**Finding.** Counting the overlapping windows deletes most of the significance in the study: 69 of 147 naively-significant points land inside |t| < 2 under Newey-West.

**Source.** _data/partial_ic.parquet, bivariate.parquet, deletion_control.csv, audit_ladder_newey_west.csv, adv_newey_west_tstats.csv.

### `contrast_03_double_sort.png`

**Finding.** Sort on richness first and the fund's active weight adds nothing - and does not add it monotonically.

**Source.** _data/realized_double_sort.csv, ladder2_double_sort_held.csv.

### `contrast_04_placebo_distribution.png`

**Finding.** A matched placebo boundary at 28 years, where no index does anything at all, produces a LARGER statistic than the real 20-year deletion boundary.

**Source.** _data/deletion_control.csv.

### `contrast_05_calendar_beats_scrape.png`

**Finding.** On five funds of six a calendar rule that reads no holdings file beats the best signal from 22,904 scraped documents: placebo > calendar > holdings.

**Source.** _data/adv_calnull_recheck.csv.

## The cost wall

### `contrast_06_cost_wall.png`

**Finding.** Of 5,192 grid configurations, not one covers its own measured round trip on 50 trades or more.

**Source.** _data/grid_league.csv, grid_TLT.parquet, grid_TLH.parquet, grid_IEF.parquet.


## Numbers that disagree with RESULTS.md

A figure that contradicts the writeup is a defect in one of the two. Each row below gives
both values and, where it was checked against the underlying file, which side is faithful.
None of them changes a conclusion.

| where | figure says | RESULTS.md says | verdict |
|---|---|---|---|
| `contrast_03` lower bars (high-minus-low `active_w` by richness quintile, 63d, composition held) | +0.028, +0.010, -0.021, -0.033, +0.030 | §3.6: +0.029, +0.012, -0.019, -0.033, +0.030 | **The figure is faithful.** `_data/ladder2_double_sort_held.csv`, row `width=0.25, bucket_active, h=63`, carries `{0: 0.0277, 1: 0.01, 2: -0.0211, 3: -0.0325, 4: 0.0297}`. RESULTS.md's row is stale. Non-monotone and sign-flipping either way. |
| `fund_02` event count | 33 crossings identified, 23 drawn (TLT held no position in the other 10) | §4.4: "32 usable crossings" | Different filters: the figure counts crossings identified, the writeup counts those usable for the price event study. Neither is wrong; the figure states its own denominator. |
| `fund_02` shed by day +120 | 95% shed (5% of the pre-event position left), median over 23 events, **business**-day offsets | §4.4: "85-90% by day +120", 20 events, **calendar**-day offsets | Same shed on two different axes - 120 business days is about 172 calendar days. Disclosed in the figure's own caption. |
| `fig03` left panel denominator | n = 80,912 gated TLT bond-days | §3.1: 80,953 gated bond-days | 41 bond-days, 0.05%. Measured: `_data/trig_scores.parquet` holds 80,915 gated rows of which 80,912 carry a finite score, so the figure counts scored bond-days and the writeup counts gated ones on a slightly different gate. Not reconciled; flagged. |
| `contrast_05` GOVT `deletion` partial IC | +0.015 | §4.2 table: 0.016 | Rounding of the same number in `_data/adv_calnull_recheck.csv`. |
| `contrast_06` configuration count | 5,192 configurations over 4 grids (TLT league + wide TLT/TLH/IEF) | §3.7 quotes 152 scored configurations in the TLT league and 3,360 in the two wide grids that completed | Different scopes, not a contradiction: the figure pools every cell that carries a gross, including cells the league table did not score. The verdict (0 alive) is the same in both. |
| `seas_01` / `seas_04` cost line | 0.54bp TLT round trip | 0.535bp median | Rounding for a chart label. |

### One inconsistency inside RESULTS.md itself, surfaced by this audit

§4.7 attributes a `bucket_active` IC of **-0.056** to **GOVT** ("GOVT's apparent signal was a
curve-fit artifact"), but §4.2's per-fund table lists **IEI** at -0.056 and GOVT at +0.050 -
which is what `_data/adv_calnull_recheck.csv` carries and what `contrast_05` draws. The
figure follows the data; the §4.7 sentence appears to have picked up the wrong fund's
number. RESULTS.md was not edited as part of this audit.