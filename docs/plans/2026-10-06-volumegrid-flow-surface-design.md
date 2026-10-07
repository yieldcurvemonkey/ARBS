# VolumeGrid Flow Surface — Design Doc

Oct 6, 2026 · @Chris

VolumeGrid is a live heatmap of interest-rate swap flow: rows are forward-start buckets, columns are tenor (or named-structure) buckets, and each cell shows gross volume in the current window, coloured by its percentile against the same window on prior days. This doc specifies the data contract, bucketing, window and baseline maths, views, APIs and acceptance tests needed to rebuild it on any data stack, with public-tape prints, RFQ data, or both as sources. Where the reference build has a known defect, the spec states the corrected behaviour and marks it **Change from reference**.

## Goals and non-goals

The grid answers one question at a glance: **where on the curve is flow concentrated right now, and is that unusual for this time of day?** A trader or salesperson should see within a few seconds which forward × tenor buckets (or named curves and flies) are running hot or cold against their own history.

**Questions it must answer**

1. Which forward-start × tenor buckets carry the most notional or DV01 in the current window?
2. How does each bucket compare with the same window on prior business days (percentile)?
3. How is each bucket's flow split by venue class (dealer-to-dealer vs dealer-to-client) and by package family (outright, curve, fly, spreadover, invoice)?
4. Which named structures (2s10s, 2s5s10s, meeting-dated, IMM-dated, swap spreads, invoice spreads) are active?
5. Which individual packages make up a cell (drill-down)?
6. With RFQ data: how much was asked for versus done, which side clients leaned, and what share we won.

**Users:** rates traders, sales, desk strategists, and automated agents that poll the API for unusual activity.

**Non-goals**

- Not a pricing or mid-market tool. Levels appear only as context in the drill-down.
- Not a P&L or position view. Cells are market flow, not the firm's inventory.
- Not a direction model. The base grid is gross and unsigned. Signed views exist only where side is known (RFQ, internal fills) or supplied by a separate direction model, and they use a separate encoding (see Views).
- Not a cross-bucket "which tenor is busiest in absolute terms" ranking from inferred-side data. Percentiles compare each bucket with its own history.

The worked examples use USD SOFR swaps; every market-specific constant (bucket edges, venue codes, calendars, session hours) is configuration.

## Architecture at a glance

![VolumeGrid architecture: 3 sources, 1 engine, 1 API](2026-10-06-volumegrid-architecture.png)

Sources feed one normalised store; the window engine is a pure function, so the grid, the drill-down and every test compute the same numbers from the same rows.

## Canonical data model

Every source is normalised into two tables, **FlowPackage** (one economic transaction or one RFQ inquiry) and **FlowLeg** (one swap leg of it). The grid aggregates legs; the drill-down lists packages. Nothing downstream reads a raw source.

**FlowPackage**

| Field | Type | Req. | Meaning |
| --- | --- | --- | --- |
| package\_id | string | yes | Stable id. Survives corrections; a correction replaces the row, never adds one. |
| source | enum | yes | PUBLIC\_TAPE, RFQ, INTERNAL\_FILL. |
| layer | enum | yes | PRINT (executed, from a tape), INQUIRY (an RFQ request, traded or not), FILL (executed, from your own records). |
| event\_ts | timestamp (UTC) | yes | Execution time for PRINT and FILL; request time for INQUIRY. For amended trades, the original execution time. |
| known\_ts | timestamp (UTC) | yes | When your system could first have seen it: dissemination time for a tape, request receipt for RFQ. Drives like-for-like baselines (see Windows and baselines). |
| package\_type | enum | yes | OUTRIGHT, CURVE, FLY, SPREADOVER, MATCHED\_MATURITY, INVOICE, INVOICE\_CALENDAR, INVOICE\_SWITCH, MEETING\_DATED, IMM\_DATED, BASIS, OTHER (and composite curve/fly variants of spreadover and matched-maturity). |
| package\_family | enum | derived | outright, curve, fly, invoice, other. Mapping in Measures. |
| structure\_key | string | derived | Canonical tenor key such as `2s10s` or `2s5s10s`; null for outrights. |
| venue\_class | enum | yes | D2D, D2C, BILATERAL, UNKNOWN. |
| venue\_id | string | no | Platform or MIC code. Mapping to venue\_class is configuration. |
| lifecycle | enum | yes | NEW, AMEND, CORRECT, CANCEL, TERMINATE, NOVATE, COMPRESS, OTHER. |
| flow\_eligible | bool | derived | Whether the package counts as market flow. Rule in Measures. |
| is\_block | bool | no | Block-size or delayed-dissemination flag. |
| label | string | derived | Human label (e.g. `SOFR 2Y10Y Curve`) used by the text filter. |
| level | number + unit | no | Fixed rate (percent) or package spread (bp). Always stored with an explicit unit field. |

**FlowLeg**

| Field | Type | Req. | Meaning |
| --- | --- | --- | --- |
| package\_id, leg\_index | string, int | yes | Parent and position. |
| currency, rate\_index | enum | yes | e.g. USD, SOFR. One grid instance per currency and index family. |
| trade\_date | date | yes | Business date of event\_ts in the session calendar. |
| effective\_date, maturity\_date | date | yes | Accrual start and end. |
| forward\_start\_years | number | derived | (effective\_date − trade\_date) / 365.25. Null only if effective\_date is missing. |
| tenor\_years | number | derived | Quoted tenor if the source gives one, else (maturity\_date − effective\_date) / 365.25. |
| notional\_abs | number | yes | Absolute notional in currency units. |
| notional\_capped | bool | yes | True when the source shows a capped size (public tape). |
| dv01\_abs | number | yes | Absolute DV01 in currency per bp. Method recorded in dv01\_method. |
| dv01\_method | enum | yes | SOURCE, ANNUITY\_APPROX, CURVE\_PRICED. |
| fixed\_rate | number | no | Percent. |
| is\_risk\_leg | bool | derived | The single leg that carries a structure's quoted risk. Rule in Measures. |
| meeting\_label | string | derived | Central-bank meeting the leg is dated to (e.g. `OCT26`), from the meeting calendar; null otherwise. |
| imm\_date | date | derived | IMM date the leg starts on, if any. |

**RFQ-only fields (on FlowPackage, layer = INQUIRY)**

| Field | Type | Meaning |
| --- | --- | --- |
| inquiry\_id | string | One id per client request. Quotes from several dealers never create several inquiries. |
| client\_side | enum | PAY\_FIXED, RECEIVE\_FIXED, UNKNOWN (two-way request for market). |
| outcome | enum | DONE\_WITH\_US, TRADED\_AWAY, NOT\_TRADED, EXPIRED, CANCELLED. |
| dealers\_in\_comp | int | Number of dealers asked. |
| fill\_package\_id | string | The FILL created when done, if any. |
| matched\_print\_id | string | The public-tape print this inquiry's execution matched, if any (see Sources). |
| client\_ref | string | Restricted. Never leaves the entitlement boundary; never in an aggregate response. |

Signed fields are optional and only on layers where side is known: `dealer_sign` ∈ {+1, −1, 0} with +1 = the dealer received fixed (long duration). An inferred side from a tape direction model is a separate field (`inferred_dealer_sign`, `inferred_confidence`) and is never merged with a known side.

## Sources: public tape, RFQ and internal fills

**Layers are never summed.** Every grid request names exactly one layer (PRINT, INQUIRY or FILL), or the explicit COMBINED\_EXECUTED layer defined below. An inquiry is interest and a print is a trade; adding them double counts every RFQ that traded.

| Property | Public tape (PRINT) | RFQ (INQUIRY) | Internal fills (FILL) |
| --- | --- | --- | --- |
| What it covers | Every reportable trade in the market | Requests sent to us only | Our executed trades |
| Side | Not disclosed; inferred only by a model | Disclosed in one-way RFQs; unknown in two-way requests | Known |
| Size | Capped above a regulatory threshold | Exact | Exact |
| Timing | Delayed: seconds for most, longer for blocks | Real time | Real time |
| Clock for windows | Execution time | Request time | Execution time |
| Counting unit | Leg, package | Inquiry (one per client request) | Leg, package |
| Bias | Complete market view, minus capped size | Panel bias: only clients who include us | Our share only |

**One inquiry, one count.** An RFQ sent to five dealers is one inquiry. If your data has one row per dealer quote, collapse to inquiry\_id before aggregating.

**Outcome drives which layer a row reaches.** Every inquiry stays in INQUIRY whatever its outcome. DONE\_WITH\_US also creates a FILL. TRADED\_AWAY should appear on the public tape as someone else's print; it never creates a FILL.

**Matching an RFQ execution to a tape print.** An executed RFQ (ours or traded away) normally also appears as a tape print. Link them when all of these hold, and only when exactly one candidate qualifies:

1. Same currency, rate index and package type.
2. Same effective and maturity dates on every leg (or tenor within one day when the tape omits dates).
3. Fixed rate within the tape's rounding (the team sets the tolerance, e.g. 0.01 bp).
4. Tape execution time within a tolerance of the RFQ execution time (the team sets it from observed reporting precision).
5. Notional equal, or the tape is capped and the RFQ notional is at or above the cap.

Ambiguous candidates stay unlinked. Track the match rate as a data-quality metric.

**COMBINED\_EXECUTED layer** (optional): all PRINTs, with each matched print's capped notional replaced by the RFQ's exact notional and its side attached as known. Unmatched FILLs (off-tape trades) are added. This is the only layer that mixes sources, and it does so by enrichment, not addition.

**Reporting lag matters for intraday comparisons.** A tape's "today so far" lacks prints not yet disseminated, while the same slice on prior days is complete. The Windows and baselines section specifies the correction. RFQ and internal data have no such lag.

**Capped sizes.** Store the cap flag on every leg and report the capped share of each cell. Imputing a size above the cap is optional, must be labelled as imputed, and must take the cap table by effective date, since caps change over time.

**Panel bias in RFQ.** A single dealer's RFQ sample moves when clients add or drop that dealer. Baselines then shift for reasons unrelated to market activity. Publish a coverage series (inquiries per day, distinct clients per day) beside RFQ views so a regime shift is visible.

**Entitlements.** RFQ and fill data identify clients. Aggregates shown outside the entitled group must suppress any cell with fewer than *k* distinct clients (the team sets *k*). Drill-down rows for those layers require the entitlement. client\_ref never appears in an API response.

## Measures

A cell value is the sum of one measure over the flow-eligible legs that fall in that cell during the window. The base measures are gross and unsigned.

| Measure | Definition | Unit | UI label |
| --- | --- | --- | --- |
| Notional | Σ notional\_abs | currency | "Notional" |
| DV01 | Σ dv01\_abs | currency per bp | "DV01" |
| Legs | count of legs | count | "legs" |
| Packages | count of distinct package\_id | count | "packages" |
| Inquiries | count of distinct inquiry\_id (INQUIRY layer) | count | "inquiries" |

Counts always carry their unit in the label. **Change from reference:** the reference labels a leg count as "trades" in the grid and a package count as "trades" in the structure strips.

**DV01.** Use the source's DV01 when it provides one. Otherwise price the leg on the trade-date curve (CURVE\_PRICED), or fall back to the annuity approximation (ANNUITY\_APPROX):

```math
\mathrm{DV01} \approx N \cdot \sum_{i} \tau_i \, DF(t_i) \cdot 10^{-4}
```

where N is notional, τᵢ the fixed-leg accrual fractions and DF the discount factors. Record the method; mixing methods within one cell is allowed but should be visible in the drill-down.

**Attribution modes** decide which legs of a multi-leg package count, and where.

| Mode | Rule | Used by |
| --- | --- | --- |
| ALL\_LEGS | Every leg counts in its own forward × tenor cell. A 2s10s curve adds to both the 2Y and 10Y columns. | Grid, FOMC strip, spreadover and invoice strips, Market Overview totals |
| RISK\_LEG | One leg per package, at the package's structure cell. | Curve and fly strips, Market Overview structure table |
| PACKAGE\_ADJUSTED | Σ \|leg DV01\| ÷ number of swap legs, assigned to the risk leg's cell. | Optional DV01 variant |

**Risk-leg rule:** curve → the longest-tenor leg; fly → the belly (middle leg by tenor); spreadover, matched-maturity and invoice → the swap leg; outright → its only leg; any other multi-leg package → the leg with the largest dv01\_abs. **Change from reference:** the reference sums all legs for structure volume in Market Overview but uses the risk leg in the strips; one rule per view is required.

**Package families** (for the family split bar and filters):

| Family | Package types |
| --- | --- |
| outright | OUTRIGHT, SPREADOVER, MATCHED\_MATURITY |
| curve | CURVE and its spreadover and matched-maturity variants |
| fly | FLY and its spreadover and matched-maturity variants |
| invoice | INVOICE, INVOICE\_CALENDAR, INVOICE\_SWITCH |
| other | everything else (basis, meeting-dated and IMM-dated packages not otherwise typed) |

**Flow eligibility.** A package counts as market flow only if its lifecycle event created new market risk. The rule is configuration with these defaults:

| Lifecycle | Default | Note |
| --- | --- | --- |
| NEW | in | The base case. |
| AMEND, CORRECT | in, as the latest version | The newer version replaces the old row; never count both. |
| CANCEL | out | Also removes the original. |
| NOVATE (incl. clearing novation) | out | Same risk, new counterparty. |
| COMPRESS, portfolio reset or optimisation | out | Risk reduction, not flow. |
| TERMINATE | out |  |
| Early termination booked as a new trade (unwind) | out, configurable | Open question for the team. |

**Splits always sum to the cell.** The venue-class split carries an UNKNOWN bucket and the family split carries "other", so D2D + D2C + BILATERAL + UNKNOWN equals the cell value exactly.

## Bucketing

One classifier assigns every leg to at most one row bucket and one column bucket, and every endpoint (grid, drill-down, overview, prefetch) calls that same classifier. Legs that land in no bucket are counted as **unbucketed** and reported, never silently dropped.

**Schema object**

| Field | Meaning |
| --- | --- |
| schema\_id, version | Stable reference. Requests carry both; dynamic schemas also carry as\_of. |
| axis | FORWARD or TENOR (row or column). |
| kind | YEARS (numeric ranges on forward\_start\_years or tenor\_years), LABEL (meeting\_label), CATEGORY (venue\_id), STRUCTURE (structure definitions). |
| buckets | Ordered list of {id, label, lo, hi}. lo is inclusive, hi exclusive, null means unbounded. |
| null\_bucket | Bucket id that receives null values (e.g. Spot for a missing effective date), or none. |

**Rules**

1. Buckets in one schema must not overlap. Validation rejects an overlapping schema at save time. **Change from reference:** the reference allows overlaps and classifies first-match in the grid but by plain range in the drill-down, so the two disagree.
2. Gaps are allowed (a strip may skip 4Y), but the response reports unbucketed volume per row and column.
3. Dynamic schemas (IMM, meeting, venue) are resolved server-side for an as\_of and returned with the bucket list the client should draw.
4. Calendars are data, not code: IMM dates are computed (third Wednesday of Mar, Jun, Sep, Dec) and meeting dates come from a maintained table. **Change from reference:** the reference hardcodes six meetings a year on the 15th of the month, and its list ends in 2027.

**Default forward rows (USD example)**

| Bucket | Range (years) |
| --- | --- |
| Spot | < 0.0192 (1 week), and null |
| 1W–3M | 0.0192 – 0.25 |
| 3M–6M | 0.25 – 0.5 |
| 6M–1Y | 0.5 – 1 |
| 1Y–2Y | 1 – 2 |
| 2Y–5Y | 2 – 5 |
| 5Y–10Y | 5 – 10 |
| 10Y+ | ≥ 10 |

**Default tenor columns (USD example).** Round-year buckets take the half year either side so a 2.4-year tenor lands in 2Y.

| Bucket | Range (years) | Bucket | Range (years) |
| --- | --- | --- | --- |
| 1M–3M | 0.083 – 0.25 | 6Y–7Y | 5.5 – 7.5 |
| 6M–12M | 0.25 – 1 | 8Y–9Y | 7.5 – 9.5 |
| 1Y–18M | 1 – 1.5 | 10Y | 9.5 – 10.5 |
| 18M–2Y | 1.5 – 1.85 | 10Y–12Y | 10.5 – 12.5 |
| 2Y | 1.85 – 2.5 | 12Y–15Y | 12.5 – 15.5 |
| 3Y | 2.5 – 3.5 | 15Y–20Y | 15.5 – 19.5 |
| 4Y | 3.5 – 4.5 | 20Y–25Y | 19.5 – 25.5 |
| 5Y | 4.5 – 5.5 | 25Y–30Y+ | ≥ 25.5 |

Tenors under one month are unbucketed in the default schema.

**Dynamic and special schemas**

| Schema | Axis | Buckets |
| --- | --- | --- |
| IMM16 | rows | The next 16 IMM dates, each ±0.125 years around its distance from as\_of (lower edge floored at 0). Labels like `Dec26`. |
| Meeting | rows | Distinct meeting\_label values from the calendar, from as\_of − 30 days onward, at most 16, in date order. Only legs with a meeting\_label count; all tenors are collapsed into one column. Aliases M1, M2… roll when a meeting's effective date passes. |
| Venue | columns | venue\_id values seen in the window: D2D venues first, then D2C, each alphabetical, then unknown codes. |
| Structure forward rows | rows | Spot (below max(1 week, IMM1 − 0.125)), IMM1–IMM4 (±0.125), 1Y, 2Y, 5Y (±0.125). A fixed row that overlaps an IMM row is clipped so rule 1 holds. |
| Structure columns | columns | Named structures (below). |
| Spreadover strip | one Spot row (< 0.125) × columns | 2Y 1.85–2.5, 3Y 2.5–3.5, 5Y 4.5–5.5, 7Y 6.5–7.5, 10Y 9.5–10.5, 20Y 19.5–21, 30Y 29.5–31. |
| Invoice strip | Front (< 0.25), Back (0.25–0.75) × columns | 2Y 1.5–3, 5Y 3–6, \~7Y 6–8, 10Y 8–12, 20Y 15–22, 30Y+ 22–35. |

**Named structures.** A structure is a set of tenors with a ±0.125-year tolerance. A package matches when its family is right, it has exactly that many swap legs, and each leg sits within tolerance of a different tenor in the set.

- Benchmark curves: 2s5s, 2s10s, 2s30s, 5s10s, 5s30s, 10s30s.
- Micro curves (adjacent): 1s2s, 2s3s, 3s4s, 4s5s, 5s6s, 6s7s, 7s8s, 8s9s, 9s10s, 10s12s, 12s15s, 15s20s, 20s25s, 25s30s.
- Wide curves: 2s7s, 2s20s, 3s5s, 3s7s, 3s10s, 3s30s, 4s10s, 5s7s, 5s20s, 7s10s, 7s20s, 7s30s, 10s15s, 10s20s, 10s25s, 15s30s, 20s30s.
- Benchmark flies: 2s5s10s, 2s5s30s, 2s10s30s, 5s10s30s.
- Micro flies: 1s2s3s through 20s25s30s along the adjacent tenor ladder (13 flies).
- Wide flies: 25 further combinations; the set is configuration.

**Custom schemas.** Users build a grid (forwards × tenors) or a strip (an explicit list of forward × tenor cells) from chips. A tenor or forward chip of *x* years becomes a bucket of ±0.125 when *x* ≤ 1, ±0.5 when *x* ≤ 5, and ±1.0 beyond; a forward chip of 0 becomes Spot. IMM and meeting chips are stored as references (IMM2, M3), not as frozen year bounds. **Change from reference:** the reference freezes those bounds at save time, so they drift, and its strip mode draws the full cross product instead of the chosen cells.

## Windows and baselines

Every cell compares the current window with *n* earlier windows of the same shape, ending at the same point in the business day, including the windows where nothing traded. The percentile of the current value among those samples sets the cell's colour.

**Session parameters** (per currency, configuration):

| Parameter | USD example | Note |
| --- | --- | --- |
| Time zone | America/New\_York | Elapsed time is measured on the local wall clock, so DST days line up. |
| Session open | 00:00 local | The reference uses midnight. A desk wanting an Asia open can move it. |
| Business calendar | Market holiday calendar for the currency | Holidays and weekends are not samples. |
| Effective session | The current business day, or the last one if today is not a business day | A weekend shows the last business day in full and says so in the header. |

**Periods**

| Period | Current window | Baseline samples |
| --- | --- | --- |
| today | \[session open, now) | Each prior business day in the lookback: \[open, open + elapsed) |
| 1h | \[now − 1h, now) | The same clock slice on each prior business day |
| 24h, 1w, 2w, 3w, 1m, 3m | The last D business days up to now: from the same clock time D business days ago, to now. D = 1, 5, 10, 15, 21, 63. | k non-overlapping windows of the same length, stepping back D business days at a time. k = max(floor(lookback / D), k\_min), with k\_min = 4. |

**Change from reference:** the reference forms rolling baselines from calendar day, week, month and quarter buckets, including partial buckets at both ends, so its samples are not the same length as the current window.

**Zero-filled samples.** A sample with no eligible legs contributes 0, and n counts samples, not active samples. **Change from reference:** the reference samples only windows with activity, which moves quiet buckets' percentiles downward.

**Like-for-like with reporting lag.** For a delayed source, a print counts in a window only if it was known by that window's end: the condition is `known_ts ≤ window_end` for the current window and for every baseline sample alike. Without this, today's slice is missing undisseminated blocks while prior days are complete, so the current window reads low near now. For RFQ and internal fills, known\_ts equals event\_ts and the filter has no effect. Corrections apply to history (the latest version of each package is used).

**Percentile (mid-rank).** With baseline samples b₁…bₙ and current value x:

```math
P = 100 \cdot \frac{\#\{b_j < x\} + \tfrac{1}{2}\,\#\{b_j = x\}}{n}
```

If n < n\_min (the team sets it; 5 is a reasonable start) the percentile is null and the cell shows "insufficient history". The mid-rank matters once zeros are filled: under the reference's "count of samples ≤ x" rule, a bucket with five zero samples and a zero current window scores P100 (hot); mid-rank scores it P50.

Worked checks for the test suite:

| Baseline samples | Current | Mid-rank P | "≤" rule P |
| --- | --- | --- | --- |
| 0, 0, 0, 0, 0 | 0 | 50 | 100 |
| 0, 0, 10, 20, 30 | 15 | 60 | 60 |
| 0, 10, 20, 30, 40 | 40 | 90 | 100 |
| 10, 20, 30 (n = 3, n\_min = 5) | 25 | null | 67 |

**Baseline statistics returned per cell:** p25, p50, p75, min, max, mean, n and n\_active (samples with any activity), computed over the zero-filled samples.

**Totals have their own baseline.** Row, column and grand totals are windowed sums with their own samples and percentile; never an average of cell percentiles. **Change from reference:** the reference returns a null percentile for every total.

**Optional second statistic.** A z-score on log volume, z = (ln(1 + x) − mean ln(1 + b)) / sd ln(1 + b), computed over the same samples. It powers the Flow Activity colouring and is shown in the tooltip. The reference's Flow Activity view instead compares a 1h, 4h or 5-day window with a 20-day mean of full days; that mismatch is not carried over.

## Cell encoding

A cell shows its value as text and its percentile as background colour on a diverging blue–grey–red ramp: blue is quieter than usual, grey is typical, red is busier than usual.

**Colour ramp** (linear interpolation between stops, on the percentile 0–100):

| Percentile | RGB | Reads as |
| --- | --- | --- |
| 0 | 59, 76, 192 | much quieter than usual |
| 25 | 141, 176, 254 | quieter |
| 50 | 221, 221, 221 | typical |
| 75 | 244, 152, 122 | busier |
| 100 | 180, 4, 38 | much busier than usual |
| null | 30, 41, 59 | insufficient history |

Use light text when P ≤ 15 or P ≥ 90 and dark text otherwise. Insufficient-history cells also get a hatch pattern so they are not mistaken for a colour.

**Colour modes**

| Mode | Colour basis | Sub-label |
| --- | --- | --- |
| Activity (default) | Cell percentile vs its own history | `P73` |
| Grid | Cell value ÷ largest **visible** cell value × 100 | `G41` |
| Z (optional) | Log-volume z-score mapped to the same ramp, clamped at ±3 | `+1.8σ` |

Grid mode answers "where is the volume" and activity mode answers "where is it unusual"; the header says which is on.

**Cell contents**

- Main text: compact value (`1.2B`, `845K` DV01).
- Sub-label: the colour-mode tag above.
- Venue split bar (optional, bottom edge, 1.5 px): D2D share then D2C share, plus BILATERAL and UNKNOWN when present. The bar's colours must not reuse the ramp's.
- Family bar (when the package filter is "all", top edge, 1 px): outright, curve, fly, invoice, other shares.
- Tooltip and accessible label: value with unit, count with its unit (legs or packages), window, comparison text ("vs the same 09:00–14:32 slice on 21 prior business days"), baseline p25, p50, p75, min, max, n, n\_active, venue split in value and percent, capped share for tape layers.

**Zero cells are information.** A cell with no flow this window but a busy history is cold: it gets its percentile colour, shows `0`, and stays clickable for its history. A cell with no flow and no history renders blank and disabled. **Change from reference:** the reference blanks every zero cell, hiding "nothing traded where something usually does".

**Total cells** (row, column, grand) use the same ramp with their own percentile, drawn with a heavier border.

**Signed views use a different palette.** When a view shows net side (RFQ, fills, or a direction model), colour by sign, not by the activity ramp: sky for dealer received fixed (long duration), amber for dealer paid, slate for neutral or abstained, with intensity from |net| ÷ gross. Red and blue already mean busy and quiet in this product. Known-side and inferred-side layers carry different legends: inferred side is labelled "model" and never compared across buckets on absolute level.

## Views

All views sit in one card with shared controls and a tab switcher; each view is a different bucket layout or summary over the same engine.

**Shared card controls** (persisted per user; a version key resets them when defaults change):

| Control | Values | Default |
| --- | --- | --- |
| Layer | PRINT, INQUIRY, FILL, COMBINED\_EXECUTED (only the layers the user is entitled to) | PRINT |
| Measure | Notional, DV01 | DV01 |
| Window | today, 1h, 24h, 1w, 2w, 3w, 1m, 3m | today |
| Lookback | 1w to 2y | 1m |
| Package group | all, outright, curve, fly, spreadover, invoice variants, meeting, IMM | all |
| Venue class | all, D2D, D2C | all |
| Text filter | Substring on package or leg label, same scope on every endpoint | empty |
| Colour mode | Activity, Grid, Z | Activity |
| Split | Volume, Venue split | Volume |

Every view honours every shared control, or shows the control disabled with a reason. **Change from reference:** the reference's Flow Activity view ignores the card's measure, window, lookback and filter.

**View catalogue**

| View | Question | Rows × columns | Attribution | View-specific controls | Cell click |
| --- | --- | --- | --- | --- | --- |
| Grid | Where on the surface is flow concentrated, and is it unusual? | Forward schema × tenor schema (Default, IMM16, Meeting rows; Default, Venue columns) | ALL\_LEGS | Schema pickers, hide-bucket popover | Drill-down |
| Market Overview | How busy is the whole market and what is it made of? | Panels (below) | ALL\_LEGS for totals, RISK\_LEG for structures | Structure picker, intraday bin size | Structure row → drill-down |
| Meeting strip | How much flow references each upcoming central-bank meeting? | One row of meeting cells, all tenors collapsed | ALL\_LEGS on legs with a meeting\_label | Absolute or M1/M2 labels | Drill-down on that meeting |
| Curve strip | Which named curves trade, and at which forward start? | Structure forward rows × curves | RISK\_LEG (longest leg) | Benchmark, Micro, All; column picker | Drill-down |
| Fly strip | Same for flies | Structure forward rows × flies | RISK\_LEG (belly) | Benchmark, Micro, All; column picker | Drill-down |
| Spreadover strip | How much swap-spread and matched-maturity flow is there per benchmark tenor? | Spot × seven benchmark tenors | ALL\_LEGS on spreadover packages | none | Drill-down with spread chart |
| Invoice strip | Where is invoice-spread flow, front vs back contract? | Front, Back × six tenor buckets | ALL\_LEGS on invoice packages | Outright, Calendar, Switch, All | Drill-down |
| Custom | Whatever layout the user defines | User grid, or an explicit list of cells (strip) | ALL\_LEGS | Schema builder, list, edit, delete | Drill-down |
| Flow Activity | Which buckets are hot or cold right now, in σ terms? | Default forward × default tenor | ALL\_LEGS | none (Z colour preset) | Drill-down |

Hidden buckets and hidden structure columns are removed from totals and from grid-mode scaling, or the totals are labelled "all buckets". **Change from reference:** the reference keeps hidden buckets in both.

**Market Overview panels**

1. KPI strip: total, its percentile, legs and packages, ADV, pace, DV01-weighted average tenor, block share, capped share. ADV is the mean full-session daily total over the lookback's business days, zero-filled. Pace is the current value ÷ the average value at the same elapsed time. **Change from reference:** the reference labels the mean of prior windows of the active period "ADV" and draws it across full-day bars.
2. Structure activity table: one row per spot structure\_key (e.g. `2s10s Curve`, `5Y Spreadover`), with last trade time, venue, last level with its unit, today's volume, ADV over 1 week and 1 month (zero-filled, risk leg), and today ÷ ADV coloured from cold to hot.
3. Daily stacked bars over the lookback, by family, with the ADV line.
4. Package mix: current share vs historical average share per family.
5. Venue-class split: current vs historical.
6. Cumulative intraday curve: today vs the average cumulative curve over the full session.
7. Intraday bars at a chosen bin (1, 5, 10, 15, 30 or 60 minutes) with optional average bars.
8. Tenor distribution: current vs historical average per default tenor bucket.

**RFQ-native views** (shown only for entitled users; every cell below the minimum client count is suppressed):

| View | Cell value | Colour | Note |
| --- | --- | --- | --- |
| Inquiry grid | Requested DV01 or inquiry count (INQUIRY layer) | Activity ramp | Interest, whether or not it traded |
| Conversion grid | Executed ÷ inquired, by DV01 | Sequential, plus percentile vs own history in the tooltip | Show n next to every ratio |
| Win share | DONE\_WITH\_US ÷ (DONE\_WITH\_US + TRADED\_AWAY) | Sequential | Excludes NOT\_TRADED and EXPIRED |
| Client lean | (pay-fixed − receive-fixed) ÷ (pay-fixed + receive-fixed) on one-way inquiries | Signed palette | Two-way requests excluded and counted separately |
| Market share | Our FILL DV01 ÷ COMBINED\_EXECUTED DV01 | Sequential | Needs the print-matching rule; shows match rate |
| Competition | Median dealers\_in\_comp | Sequential | Context for win share |

A coverage strip (inquiries per day and distinct clients per day over the lookback) sits above every RFQ view so panel changes are visible.

## Drill-down

Clicking a cell opens a panel that explains that one cell: its history, its intraday shape, and the packages inside it. The drill-down must reproduce the cell's number exactly.

**Shared-predicate rule.** The drill-down request is the grid request plus a cell id. It carries the same layer, filters, measure, window and the full schema reference (schema\_id, version, as\_of, or the custom bucket list). The server classifies with the same classifier. The client never rebuilds a schema and the server never falls back to a default. **Change from reference:** the curve and fly strips open the drill-down with the default forward schema, so every row except Spot is rejected as an unknown bucket, and Spot silently uses the wrong edge.

**Panel contents**

1. **Header:** row label × column label, view name, window, as-of, and the cell's value and percentile as shown in the grid.
2. **Daily history:** one bar per business day over a selectable range (1M, 3M, 6M, 1Y), zero-filled, with a dashed median line. Today's bar is marked partial. The spreadover and invoice views add a spread chart (DV01-weighted spread per day, in bp, with the unit in the axis title).
3. **Intraday shape:** today's cumulative curve against the average cumulative curve of the baseline days (zero-filled), with a marker at the last update. A date picker overlays any past session. The session comes from the same effective-session resolver as the grid, so on a weekend both show the last business day.
4. **Packages in the cell:** newest first, default 50. Columns: time in the session time zone, package type, label, level with its unit, package notional and DV01, **in-cell contribution** (the part of the package that lands in this cell), venue, block and capped flags. Multi-leg rows expand to their legs, with an in-cell marker and the risk leg highlighted. Clicking a row opens or filters to that package in the host application's blotter.
5. **Layer extras:** INQUIRY rows show outcome, side (if entitled) and dealers in competition. PRINT rows that matched an RFQ show a matched badge.

**Parity.** For the current window, the sum of in-cell contributions across all packages in the cell equals the grid cell value. If the package list is truncated, the panel shows "showing 50 of N" and the full sum still matches.

**Bin convention.** Intraday bins are \[start, end) and are plotted at their start time. The convention is written into the API response (`bin_anchor: "start"`) so a chart cannot shift trades by one bin.

**Hover prefetch** is optional. If built, it calls the exact request builder that the click uses, so the cached entry is the one the click reads.

## API contracts

Six operations serve every view. Transport (REST, gRPC, GraphQL) is the team's choice; the shapes below are JSON, and every request is a single object so the same builder serves click, poll and prefetch.

| Operation | Input | Output | Notes |
| --- | --- | --- | --- |
| `schemas.list` | currency, as\_of | Resolved schemas with bucket lists | Dynamic schemas (IMM, meeting, venue) resolved for as\_of |
| `schemas.saveCustom` | Custom schema object | schema\_id, version | Rejects overlaps and empty bucket lists |
| `grid.query` | GridRequest | GridResponse | One call per view render or poll |
| `grid.cell` | CellRequest | CellResponse | Drill-down |
| `grid.overview` | GridRequest without axes | OverviewResponse | Market Overview panels |
| `watermark.get` | none | Per-source ingested-through and known-through times | Cheap poll; refetch a view only when it moves |

**GridRequest**

```json
{
  "currency": "USD",
  "index_family": "SOFR",
  "layer": "PRINT",
  "measure": "dv01",
  "window": "today",
  "lookback_days": 30,
  "rows": { "schema_id": "fwd_default", "version": 3 },
  "cols": { "schema_id": "tenor_default", "version": 2 },
  "collapse": null,
  "package_group": "all",
  "venue_class": "all",
  "text": null,
  "as_of": null
}
```

`as_of: null` means now; a fixed as\_of makes the response reproducible and is what tests use. Custom schemas may be sent inline as `{ "inline": { "buckets": [...] } }` instead of a schema\_id.

**GridResponse**

```json
{
  "as_of": "2026-10-06T14:32:05Z",
  "watermark": { "PUBLIC_TAPE": { "known_through": "2026-10-06T14:31:58Z" } },
  "session": { "date": "2026-10-06", "tz": "America/New_York", "fallback_reason": null },
  "window": { "kind": "time_of_day", "start": "...", "end": "...", "n_samples": 21 },
  "units": { "value": "USD per bp", "count": "legs" },
  "axes": {
    "rows": { "schema_id": "fwd_default", "version": 3, "buckets": [{ "id": "spot", "label": "Spot" }] },
    "cols": { "schema_id": "tenor_default", "version": 2, "buckets": [{ "id": "10y", "label": "10Y" }] }
  },
  "cells": [{
    "row": "spot", "col": "10y",
    "value": 845000, "legs": 42, "packages": 31,
    "percentile": 81.0, "z": 1.4,
    "baseline": { "p25": 310000, "p50": 520000, "p75": 700000, "min": 0, "max": 1900000, "mean": 560000, "n": 21, "n_active": 19 },
    "split": {
      "venue_class": { "D2D": 400000, "D2C": 430000, "BILATERAL": 0, "UNKNOWN": 15000 },
      "family": { "outright": 600000, "curve": 200000, "fly": 45000, "invoice": 0, "other": 0 }
    },
    "capped_share": 0.12,
    "last_event_ts": "2026-10-06T14:30:41Z"
  }],
  "totals": { "rows": {}, "cols": {}, "grand": { "value": 0, "percentile": null, "baseline": {} } },
  "unbucketed": { "value": 0, "legs": 0 },
  "suppressed_cells": 0
}
```

The numbers are illustrative. Cells absent from the list have value 0 and no history.

**CellRequest** = GridRequest + `{ "cell": { "row": "spot", "col": "10y" }, "range": "3M", "intraday_date": null, "recent_limit": 50 }`. Structure views put the structure id in `col`.

**CellResponse** carries `header` (the grid cell as above), `daily` (array of {date, value, legs, packages, spread\_bp?, partial}), `intraday` ({bin\_minutes, bin\_anchor: "start", today: \[...\], average: \[...\], overlay: \[...\]}), and `packages` (array with in-cell contribution and legs), plus `packages_total` for the untruncated count.

**Errors** return a machine code and the offending field, e.g. `{ "code": "unknown_bucket", "field": "cell.row", "schema_id": "fwd_default" }`. The UI shows every error in the view; it never keeps drawing stale data silently.

## Computation and freshness

Start with leg-level facts queried per request, and keep all window and percentile maths in one pure module; add a pre-aggregated cube only if measured latency demands it.

**Pipeline**

1. Ingest each source into its raw store.
2. Normalise to FlowPackage and FlowLeg.
3. Enrich: trade\_date and session, forward\_start\_years, tenor\_years, dv01\_abs, package\_family, structure\_key, is\_risk\_leg, meeting\_label, imm\_date, venue\_class, flow\_eligible, RFQ-to-print match.
4. Upsert by package\_id, so a correction replaces its row.
5. Advance the source's watermark (ingested-through and known-through).

**Two ways to aggregate**

| Approach | How | Strength | Limit |
| --- | --- | --- | --- |
| A. Query leg facts per request | Columnar engine scans legs over lookback + current window, classifies with the schema, groups by sample | Any schema, including custom, with no precomputation | Cost grows with lookback × volume; size it from your own data |
| B. Minute cube | Pre-sum by (session date, minute of session, layer, venue class, family, package group, fine forward bin, fine tenor bin, meeting label, structure key) | Sub-second for fixed schemas | Fine bins must contain every schema edge; custom edges that cut a fine bin fall back to A |

Both paths call the same module: `compute(legs_or_cube_rows, request, as_of) → response`. It is a pure function with no clock or I/O inside, so a fixed as\_of reproduces any past screen.

**Freshness**

- Cache key = the canonical request + the watermark of every source the layer reads. A new print moves the watermark, so the next poll recomputes; nothing else expires the cache.
- Any HTTP cache lifetime must not exceed the poll interval; prefer validators (an ETag equal to the cache key). **Change from reference:** the reference serves a 30-second poll from responses cached for up to 300 seconds, plus stale-while-revalidate, so the grid can be minutes old.
- Clients poll `watermark.get` on a short interval (the team sets it), refetch the visible view only when the watermark moves, pause while the tab is hidden, and discard any response older than the newest one already drawn.
- The response header shows the as-of time and each source's known-through time, and turns amber when a source lags beyond a threshold.

**Late and changed data**

- Incremental ingestion advances on an ingest sequence or known\_ts, never on event\_ts. A late-reported trade has an old event\_ts and would be skipped by an event-time cursor.
- Corrections and cancels update history. The watermark moves, so baselines recompute on the next poll.
- An RFQ inquiry is windowed by request time. Its outcome can change later (to done or expired); that changes conversion and win-share views but never moves the inquiry to another window.

**Determinism checks:** the same request, as\_of and data version must give a byte-identical response. Responses carry the schema versions and calendar version used.

## Pitfalls from the reference build

Twenty-two defects in the reference build each map to a requirement in this spec; the first seven change what users see most often. "Code" means the behaviour was confirmed in source; "review" means it was found by code review and not re-run.

| # | Reference behaviour | Effect | Requirement here | Basis |
| --- | --- | --- | --- | --- |
| 1 | Curve and fly strip drill-downs send the default forward schema | Every row but Spot is rejected; Spot uses the wrong edge | Shared-predicate rule; parity test for every view × bucket | Code |
| 2 | Grid responses cached up to 300 s (plus stale-while-revalidate) under a 30 s poll | Screen can be minutes old while looking live | Cache keyed by watermark; lifetime ≤ poll interval | Code |
| 3 | Baselines sample only windows with activity | Quiet buckets read hotter than they are | Zero-filled samples over business days | Code |
| 4 | Percentile = share of samples ≤ current | With zeros, a dead bucket scores P100 | Mid-rank percentile, n\_min | Code |
| 5 | Rolling baselines use calendar day/week/month/quarter buckets with partial ends | Samples differ in length from the current window | Non-overlapping, equal-length business-day windows | Code |
| 6 | Row, column and grand totals return a null percentile | Totals are never coloured | Totals get their own baselines | Code |
| 7 | Meeting calendar hardcoded: six a year on the 15th, ending 2027 | Wrong meeting aliases; real meetings unlabelled | Maintained calendar table | Code |
| 8 | "Trades" is a leg count in the grid and a package count in the strips | Counts compared across views disagree | Explicit unit on every count | Code |
| 9 | Market Overview "ADV" is the mean of prior windows of the active period | Wrong unit against full-day bars | ADV = mean full-session daily total | Code |
| 10 | Drill-down shows spread × 10,000, Market Overview × 100, both labelled bp | 100× disagreement on one field | Store spread with an explicit unit; tie out | Code |
| 11 | Flow Activity uses a UTC date, compares 1h or 5d windows with a full-day mean, ignores card controls | z-scores biased by window length | Same engine and samples as the grid | Code |
| 12 | Zero cells rendered blank and disabled | "Nothing where something usually trades" is invisible | Cold colour, clickable | Code |
| 13 | Strip bucket gaps (e.g. 4Y, 12–15Y) drop legs silently | Totals understate flow | Report unbucketed volume | Code |
| 14 | Structure volume sums all legs in Market Overview but the risk leg in strips | Two numbers for one structure | One attribution rule per measure | Review |
| 15 | Overlapping custom buckets: first match in grid, plain range in drill-down | Drill-down includes legs the grid gave to a neighbour | Reject overlaps; one classifier | Review |
| 16 | Custom strip mode draws the cross product of chosen rows and columns | Cells the user did not pick appear | Strip = explicit cell list | Review |
| 17 | Hidden buckets stay in totals and in grid-mode scaling | "% of max visible" is wrong | Recompute or label totals | Review |
| 18 | Weekend: grid shows Friday, drill-down intraday uses the calendar date | Empty intraday chart on weekends | One effective-session resolver | Review |
| 19 | Hover prefetch omits the text filter and custom buckets | Cache misses; errors on every hover in Custom | Prefetch uses the click's request builder | Review |
| 20 | Picking "Custom" with no buckets sends an invalid request and the view keeps old data | Silent failure | Never send incomplete schemas; show errors | Review |
| 21 | The trade-tape poll advances on execution time | Late-reported trades never appear until reload | Ingest cursor on known\_ts or sequence | Review |
| 22 | Text filter matches package and leg labels on one endpoint, package label only on another | Filtered totals disagree across views | One filter scope everywhere | Review |

## Testing and acceptance

The engine is accepted when three kinds of check pass: invariants that hold for any data, fixtures whose answers were computed by hand, and mutation checks that prove each test can fail.

**Invariants** (property tests over generated legs and random as\_of values)

1. Partition: every eligible leg lands in exactly one cell or in unbucketed, so Σ cells + unbucketed = Σ eligible legs.
2. Venue and family splits sum to their cell exactly.
3. Totals equal the sum of the cells they claim to cover.
4. Percentile lies in \[0, 100\] and never falls as the current value rises with the baseline fixed.
5. Grid–drill-down parity, for **every view and every bucket**, including dynamic ones: the drill-down header equals the grid cell, and in-cell contributions sum to it. This one test catches pitfall 1.
6. Determinism: identical request, as\_of and data version give an identical response.
7. Layer isolation: no response mixes INQUIRY with PRINT or FILL; COMBINED\_EXECUTED volume ≤ PRINT volume with exact sizes + unmatched FILL volume.
8. Lag safety: for a fixed window, evaluating it at an earlier as\_of never increases its value.

**Known-answer fixtures** (small synthetic datasets with expected outputs written by hand before the code runs)

| Area | Case | Expected |
| --- | --- | --- |
| Percentile | The four rows in Windows and baselines | As tabled there |
| Bucket edges | Leg at exactly 0.25y forward; leg at 1.85y tenor | 3M–6M row; 2Y column (lower edge inclusive) |
| Nulls | Leg with no effective date | Spot row |
| Session | as\_of on a Saturday | Last business day in full, fallback\_reason set |
| Session | DST start and end days in the lookback | Slices aligned on local clock time |
| Session | Holiday in the lookback | Holiday is not a sample; n drops by one |
| Lifecycle | Correction, cancel, clearing novation | Corrected version once; cancelled removed; novation excluded |
| Structures | 2s10s with legs at 2.1y and 9.9y; legs at 2.2y and 10y; fly with two legs near the same tenor | Match; no match (tolerance 0.125); no match |
| Reporting lag | Block executed 10:00, known 10:20 | Excluded at as\_of 10:10, included at 10:30; same on a baseline day |
| RFQ | One inquiry quoted by five dealers | One inquiry |
| RFQ | Inquiry done with us, matching a capped tape print | COMBINED\_EXECUTED counts it once at the exact size |
| RFQ | Two tape prints equally close to one fill | Left unlinked; match rate falls |
| Calendars | Meeting calendar fixture with an October meeting | M1 aliases to the October label until its effective date passes |

**Mutation checks.** For each rule below, break it on purpose and confirm at least one test fails. A test that still passes with its rule removed is not testing that rule.

- Remove zero-filling.
- Replace mid-rank with "≤".
- Compute sessions in UTC instead of the session time zone.
- Allow overlapping buckets with first-match classification.
- Drop the known\_ts filter.
- Let the drill-down fall back to a default schema.
- Sum INQUIRY into PRINT.

**Golden responses.** Store full API responses for a handful of fixed as\_of values on real data, and review diffs in code review whenever the engine changes.

## Delivery plan

Fourteen work packages in five phases; packages within a phase share no code and can go to separate teams or agents, and no phase starts until the gate above it passes.

![Delivery plan: 14 work packages, 5 gates](2026-10-06-volumegrid-delivery-plan.png)

The test harness (WP3) starts first and gates every phase. The RFQ adapter (WP13) depends only on the data contract, so it can start right after G1 if RFQ is the priority.

**Handoff to each agent:** the data contract, the calendar version, the fixture file for its package, and the exact request and response shapes from API contracts. An agent's package is done when its gate's checks pass, not when its code compiles.

## Open questions

These decisions belong to the implementing team; the spec works with the stated default until each is settled.

- [ ] Session open: midnight local (default), or an earlier open to capture the Asia session?
- [ ] Unwinds and early terminations booked as new trades: flow or not? Default: not flow.
- [ ] Capped tape sizes: show capped share only (default), or impute sizes above the cap, and from which distribution?
- [ ] Is the COMBINED\_EXECUTED layer needed in the first release, or do layers stay separate?
- [ ] Minimum client count *k* for RFQ aggregates, and which groups are entitled to RFQ and fill layers.
- [ ] Default sign for signed views: dealer perspective (+1 = dealer received fixed, the default) or client perspective?
- [ ] DV01 source: which curve and as-of for CURVE\_PRICED, and is ANNUITY\_APPROX acceptable for display?
- [ ] n\_min (default 5), default lookback (default one month) and the longest supported lookback, which sets data retention.
- [ ] Currencies and indices beyond USD SOFR, and their bucket sets and calendars.
- [ ] Poll interval, latency targets and the source-lag threshold that turns the header amber.
