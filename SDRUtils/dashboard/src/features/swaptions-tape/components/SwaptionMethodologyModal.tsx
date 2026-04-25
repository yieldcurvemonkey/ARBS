"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpenText, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

type MethodologySection = {
  id: string;
  label: string;
  markdown: string;
};

const METHODOLOGY_SECTIONS: MethodologySection[] = [
  {
    id: "overview",
    label: "Overview",
    markdown: String.raw`
# Swaption Trade Tape Methodology

This modal documents the implementation-level methodology behind the USD swaption trade tape so a quant/dev team can reproduce the full stack (classification, package detection, pricing, risk, and dashboard derivations).

## Primary implementation sources

- SDRUtils/products/usd/usd_swaptions.py
  - USD_Swaptions.detect
  - USD_Swaptions.classify_trade
  - USD_Swaptions.build_classification_dataframe
- SDRUtils/packages/swaption_packages.py
  - detect_and_link_swaption_packages_df
  - phase runners (_run_*_phase) and pricer calls (_price_*)
- SDRUtils/dashboard/src/features/swaptions-tape/components/SwaptionTradeTape.tsx
  - live polling/pagination behavior
  - frontend assumptions, derived metrics, and inferred incomplete straddles

## End-to-end pipeline (actual implementation order)

1. Ingest SDR rows and detect USD swaptions from UPI + description/maturity filters.
2. Classify each trade leg (event action, forward/tenor labels, notional, strike, premium, exercise style).
3. Run swaption package waterfall in deterministic order:
   1. Risk reversals + customer RR/strangles
   2. Straddles
   3. Ladders
   4. Vertical spreads
   5. Vega-curve pairings (straddle-on-straddle)
   6. Outrights
4. Run package pricing/risk enrichments (QuantLib/Bachelier) where enabled.
5. Merge package legs to one display row and optionally merge vega-curve linked rows.
6. Serve rows through /api/swaptions-tape with cursor pagination and filter pushdown.
7. Dashboard polls/increments data, then applies extra UI-side inference and derived metrics (notably incomplete straddle inference and bpvol/day scaling).

## Data shape notes

- The dashboard table is package-level (package_id), with nested legs_json preserving leg detail.
- Most risk fields are written into package_metrics, while leg-level fields remain under legs_json[*].leg_metrics.
- Server query reads arbs_swaption_display_items_v2 if present, else falls back to arbs_swaption_display_items_v1.
`,
  },
  {
    id: "classification",
    label: "Classification",
    markdown: String.raw`
# Raw Data Fetch + Trade Classification

## Raw filtering (USD_Swaptions.detect)

A row survives initial filtering only if all are true:

- Unique Product Identifier is in swaption UPI universe (_build_upi_df(...))
- generated description contains USD
- Maturity date of the underlier is non-null

## Field construction (USD_Swaptions.classify_trade)

For each row, the classifier computes:

- execution_timestamp := Event timestamp
- effective_date := Effective Date
- expiration_date := Expiration Date
- underlying_expiration_date := Maturity date of the underlier

Forward and tenor are derived by calculate_tenor_years(...):

$$
\text{tenor\_years} = Y(\text{expiration\_date},\ \text{underlying\_expiration\_date})
$$

$$
\text{forward\_start\_years} = Y(\text{effective\_date},\ \text{expiration\_date})
$$

Then:

- tenor_label = tenor_to_label(tenor_years, ...)
- forward_label = forward_to_label(forward_years, ...)

Other key fields:

- notional, is_notional_capped := parse_notional(...)
- strike := Strike Price
- premium := Option Premium Amount, fallback Package transaction price
- exercise_style := EUROPEAN|BERMUDAN|AMERICAN inferred from UPI FISN

Event action override:

$$
\text{event\_action} =
\begin{cases}
\text{"TERM-ETRM"}, & \text{if } forward\_label = \text{"OD"} \\
\text{Action type} + \text{"-"} + \text{Event type}, & \text{otherwise}
\end{cases}
$$

## Daily build + package detect call

build_classification_dataframe(...) processes by execution date and calls:

~~~python
package_df = detect_and_link_swaption_packages_df(
    package_df,
    config=swaption_package_config,
    pricer=mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": exec_date}),
)
~~~

After detection it filters to [start, end], sorts by execution timestamp, then merges leg rows into package rows.
`,
  },
  {
    id: "detection",
    label: "Detection",
    markdown: String.raw`
# Package Detection Logic (Waterfall + Thresholds)

detect_and_link_swaption_packages_df(...) runs on unpackaged rows in strict order, so earlier phases consume candidate legs before later phases.

## Default phase parameters

| Phase | Function | Core defaults |
|---|---|---|
| Inter-dealer risk reversal | detect_risk_reversals_packages | time_window_seconds=3600, strike_tolerance=0.0001, notional_tolerance_pct=0.05, same expiry/tenor/forward required |
| Customer RR/strangle | detect_customer_rr_strangles_packages | timestamp_window_seconds=3600, notional_tolerance_pct=0.01, width_tolerance_bps=3.0 |
| Straddles (reported package) | detect_straddles_packages | timestamp_tolerance=30s, strike/notional tolerance = 0, must have package_indicator=True |
| Straddles (separate customer legs) | detect_straddles_packages | timestamp_tolerance=60s, platforms_filter=[XXXX, XSEF, XOFF, BILT] |
| Ladders | detect_ladder_packages | min_legs=3, min_strikes=2, min_strike_width_bps=10, notional_ratio_tolerance=0.15 |
| Vertical spreads | detect_vertical_spreads_packages | time_window_seconds=300, min strike width from config (0.001) |
| Vega curve | detect_vega_curve_packages | time_window_seconds=300, vega_tolerance_pct=0.10, min expiry diff 0.08y, min tail diff 0.333y |
| Outrights | detect_outright_swaptions | offset tolerance 7.5 bps |

## Structure rules (high level)

### 1) Risk reversal (inter-dealer)

Requires 4 legs satisfying:

- exactly 3 strike clusters with multiplicities [1,1,2]
- exactly 2 notional clusters with multiplicities [2,2]
- middle strike corresponds to smaller notional cluster
- exactly 2 unique UPIs
- same event_action across all legs
- wing directions opposite

### 2) Customer RR/strangle (2-leg)

- one payer + one receiver
- same expiry/forward/tenor and near-equal notionals
- strike width must match benchmark list (10, 15, 20, ..., 200 bps) within tolerance

### 3) Straddle (2-leg)

- payer + receiver
- same strike/expiry/tenor
- time proximity
- optionally package-indicator constrained

### 4) Vertical spread

- 2 legs, same option type (payer/payer or receiver/receiver)
- same expiry/forward/tenor
- strike separation above minimum
- notional ratio matches configured templates (1x1, 1x1.5, 1x2, ...)

### 5) Ladder

- 3+ legs, same option type
- same expiry/forward/tenor
- multiple strikes with minimum spacing
- asymmetric notionals (not all effectively equal)

### 6) Vega curve pairing

Applied only on already detected straddles.

- needs QuantLib vega availability
- pair straddles in time window
- match by vega similarity (or configured misweight multipliers)
- classify into VEGA_EXPIRY_SPREAD, VEGA_TAIL_SPREAD, or VEGA_DIAGONAL

## Confidence scoring (as implemented)

- Straddle: 0.8 base, +0.1 if time < 5s, +0.1 if strike almost exact
- Risk reversal: 0.8 base, +0.1 if max leg delta <= 5s
- Customer RR/strangle: 0.8 base, +0.1 if < 2s, +0.05 for common widths (25/50/100)
- Vertical spread: 0.7 base, +0.1 if < 5s, +0.1 with package indicator
- Ladder: platform/structure-based base (0.6-0.9) + up to 0.1 for tight timing

Every detector writes deterministic package_id, package_legs, package_confidence, and package_reason.
`,
  },
  {
    id: "pricing",
    label: "Pricing + Greeks",
    markdown: String.raw`
# Pricing and Risk Calculations

The pricing stack uses QuantLib and solves normal (Bachelier) implied volatility from forward premium.

## Single-leg pricer (usd_swaption_leg_pricer_from_row)

For each leg:

1. Build underlying OIS swap (curve: USD-SOFR-1D, effective = option expiry, maturity = underlier maturity).
2. Price a European swaption with BachelierSwaptionEngine.
3. Invert premium to implied normal vol:

$$
\sigma_N = \operatorname*{arg\,solve}_{\sigma} \; V_{\text{Bach}}(\sigma) = P_{\text{fwd}}
$$

4. Convert to bpvol/year:

$$
\text{bpvol}_{yr} = 10^4 \cdot \sigma_N
$$

5. Greeks and roll metrics:

$$
DV01 = \frac{\Delta}{10^4},\qquad Vega01 = \frac{Vega}{10^4}
$$

$$
Gamma01 = \frac{\Delta(K-dK)-\Delta(K+dK)}{2\,dK\,100}
$$

with dK = 1.0 in swap fixed-rate percentage units.

$$
\Theta_{1d} = V(t) - V(t+1\text{ day})
$$

ATMF is computed from a no-fixed-rate query and strike offsets are rounded to benchmark buckets.

## Straddle pricer (usd_swaption_straddle_pricer_from_row)

Uses half premium per payer/receiver leg:

$$
P_{leg} = \frac{P_{straddle}}{2}
$$

Aggregation:

$$
\sigma_{straddle} = \frac{\sigma_{payer}+\sigma_{receiver}}{2}
$$

$$
DV01 = DV01_p + DV01_r
$$

$$
Vega01 = Vega01_p + Vega01_r
$$

$$
Gamma01 = |Gamma01_p + Gamma01_r|,
\qquad
\Theta_{1d} = -|\Theta_{1d,p} + \Theta_{1d,r}|
$$

Guardrail: if implied bpvol <= 35, it raises SingleStraddleLegException; caller retries by doubling premium for single-leg style payloads.

## Vertical spread pricer (usd_swaption_vertical_spread_pricer_from_row)

After identifying ATM vs OTM leg:

$$
DV01_{spread} = DV01_{ATM} - DV01_{OTM}
$$

$$
Vega01_{spread} = Vega01_{ATM} - Vega01_{OTM}
$$

$$
Gamma01_{spread} = Gamma01_{ATM} - Gamma01_{OTM}
$$

$$
\Theta_{spread} = \Theta_{ATM} - \Theta_{OTM}
$$

Also outputs vol spread and strike-width diagnostics:

$$
\Delta \sigma_{bpvol} = \sigma_{OTM} - \sigma_{ATM},
\qquad
\text{width}_{bps} = |K_{OTM}-K_{ATM}|\cdot 10^4
$$

## Dealer risk reversal pricer (usd_swaption_dealer_risk_reversal_skew_from_row)

Structure parsed as ATM straddle + two wings.

Core skew metric:

$$
\text{skew}_{bpvol} = \sigma_{OTM,payer} - \sigma_{OTM,receiver}
$$

ATM reference:

$$
\sigma_{ATM} = \frac{\sigma_{ATM,payer}+\sigma_{ATM,receiver}}{2}
$$

Wing width:

$$
\text{wing width}_{bps} = (K_{high}-K_{low})\cdot 10^4
$$

Greeks are aggregated leg-wise with sign conventions in the implementation; reproduce exactly from source when validating.

## Merge-price-unmerge workflow

Risk reversals and vertical spreads are temporarily merged by package_id for pricing, then metrics are joined back to each leg row. Row counts are asserted unchanged.
`,
  },
  {
    id: "frontend",
    label: "Frontend Assumptions",
    markdown: String.raw`
# Dashboard Derivations and UI-Side Assumptions

## Real-time fetch behavior

SwaptionTradeTape.tsx runtime constants:

- poll interval: POLL_INTERVAL_MS = 5000
- initial replace fetch: up to TODAY_BACKFILL_FETCH_LIMIT = 500
- same-day backfill cap: TODAY_BACKFILL_MAX_PAGES = 40

## Display metric transforms

### Premium in bps

$$
\text{premium bps} = \frac{\text{premium}}{\text{notional}}\cdot 10^4
$$

### Daily bpvol proxy

$$
\text{bpvol/day} = \frac{\text{bpvol/year}}{15.87}
$$

(BPVOL_DAY_DIVISOR = 15.87)

## Incomplete straddle inference (UI-side)

The UI can relabel certain IDB ATM outrights as STRADDLE with assumed_incomplete_straddle=true.

Required gating includes:

- original package type is OUTRIGHT
- single leg only
- IDB platform (BGCD, DWSF, IGDL, ISWV, TPSE, TSEF)
- leg appears ATM by offset checks
- leg style text matches EURO VANILLA PHYS
- signature does not already have a complete straddle pair

Ratio trigger against recent/median straddle bpvol for same tenor key:

$$
1.45 \le \frac{\text{outright bpvol}}{\text{reference straddle bpvol}} \le 2.95
$$

Fallback trigger uses forward-dependent thresholds:

$$
\text{fallback}(fwd) =
\begin{cases}
130,& fwd\le0.5\\
125,& 0.5 < fwd\le1\\
120,& 1 < fwd\le2\\
112,& 2 < fwd\le5\\
100,& 5 < fwd\le10\\
90,& fwd>10
\end{cases}
$$

For inferred straddles the UI applies extra transforms when package metrics are missing:

- bpvol ~= outright_bpvol * 0.5
- vega01 ~= outright_vega01 * 2
- gamma01 ~= outright_gamma01 * 4
- theta1d ~= -abs(outright_theta1d)

## Action/platform assumptions

- Safe lifecycle actions: NEWT, TRAD, MODI
- Active actions for many analytics: NEWT-TRAD, MODI-TRAD, CORR-TRAD
- Unknown/blank MICs are treated as customer-side in several views
`,
  },
  {
    id: "api",
    label: "API + SQL",
    markdown: String.raw`
# API Fetch Methodology (/api/swaptions-tape)

## View selection

Server checks for arbs_swaption_display_items_v2 (resolveDisplayView) and falls back to v1. The result is cached for 60 seconds.

## Query characteristics

- cursor pagination: execution_start < cursor
- incremental updates: execution_start > since
- mutual exclusion guard (cursor and since cannot both be set)
- server fetches limit + 1 to derive hasMore
- nextCursor is last row execution_start

A lateral join computes modal platform/action from arbs_swaption_legs_v1:

~~~sql
LEFT JOIN LATERAL (
  SELECT mode() WITHIN GROUP (ORDER BY platform_identifier) AS platform_identifier,
         mode() WITHIN GROUP (ORDER BY event_action) AS event_action
  FROM arbs_swaption_legs_v1 l
  WHERE l.package_id = d.package_id
) plat ON TRUE
~~~

## Filter pushdown

Column-filter metadata is converted into SQL predicates for:

- action
- package type
- time (UTC + America/New_York parsing modes)
- platform
- notional
- label-level text fields

This keeps large-table filtering server-side before client rendering.
`,
  },
  {
    id: "repro",
    label: "Repro Steps",
    markdown: String.raw`
# Reproducible Build Recipe

## 1) Python environment

Minimum stack implied by code path:

- pandas, numpy, pyarrow
- QuantLib + Query.IRSwaps stack
- SDRUtils package modules in this repo

## 2) Deterministic daily build

~~~python
import pandas as pd
from SDRUtils.products.usd.usd_swaptions import USD_Swaptions

product = USD_Swaptions()

start = pd.Timestamp("2026-02-20 00:00:00", tz="UTC")
end = pd.Timestamp("2026-02-21 00:00:00", tz="UTC")

df = product.build_classification_dataframe(
    start=start,
    end=end,
    cache_path="<your_cache_path>",
    detect_swaption_packages=True,
    merge_package_legs=True,
    curve_source="ERIS_EOD_LIVE-QL_BASIC",
)

# df now includes package_type/package_id, package_confidence/reason,
# and pricing/risk enrichments where available.
~~~

## 3) Validation checklist

- Verify package type counts by day and platform.
- Spot-check each package family against detector rules and confidence.
- Reprice sampled rows and compare:
  - straddle_bpvol_yr, straddle_vega01, straddle_gamma01, straddle_theta1d
  - rr_* fields for risk reversals
  - vs_* fields for vertical spreads
  - outright_* moneyness/offset fields
- Confirm merge invariants:
  - row count unchanged after merge-price-unmerge phases
  - package_legs_count matches actual package_legs cardinality

## 4) Dashboard parity checks

- API endpoint returns stable nextCursor/hasMore behavior under load.
- UI inferred incomplete straddles are tagged with assumed_straddle_reason and can be traced back to explicit ratio/fallback triggers.
- Notional/Vega toggle and premium-bps math produce expected units.

## Known caveats explicitly present in code

- The dashboard warns that vol/Greeks are still in development.
- Frontend straddle inference is heuristic and may reclassify valid outrights.
- Vega curve pairing requires QuantLib pricing availability.
- Confidence is rule-based, not probabilistic calibration.
`,
  },
];

export function SwaptionMethodologyModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [activeSectionId, setActiveSectionId] = useState(
    METHODOLOGY_SECTIONS[0].id,
  );

  useEffect(() => {
    if (!isOpen) return;
    setActiveSectionId(METHODOLOGY_SECTIONS[0].id);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const activeSection = useMemo(
    () =>
      METHODOLOGY_SECTIONS.find((section) => section.id === activeSectionId) ??
      METHODOLOGY_SECTIONS[0],
    [activeSectionId],
  );

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[70] bg-slate-950/85 p-4 md:p-6"
      onClick={onClose}
    >
      <div
        className="mx-auto flex h-[calc(100vh-2rem)] w-full max-w-[1460px] overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl md:h-[calc(100vh-3rem)]"
        onClick={(event) => event.stopPropagation()}
      >
        <aside className="hidden w-64 shrink-0 border-r border-slate-800 bg-slate-950/60 md:flex md:flex-col">
          <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-300">
            <BookOpenText className="h-4 w-4 text-sky-300" />
            Methodology
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {METHODOLOGY_SECTIONS.map((section) => {
              const active = section.id === activeSectionId;
              return (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => setActiveSectionId(section.id)}
                  className={`mb-1 w-full rounded border px-3 py-2 text-left text-xs transition ${
                    active
                      ? "border-sky-400/70 bg-sky-500/15 text-sky-100"
                      : "border-slate-800 text-slate-300 hover:border-slate-600 hover:bg-slate-800/70"
                  }`}
                >
                  {section.label}
                </button>
              );
            })}
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <BookOpenText className="h-4 w-4 shrink-0 text-sky-300" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-100">
                  Swaption Trade Tape Methodology
                </div>
                <div className="truncate text-[11px] text-slate-400">
                  {activeSection.label}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
              aria-label="Close methodology modal"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 md:px-6 md:py-5">
            <div className="mb-3 flex flex-wrap gap-2 md:hidden">
              {METHODOLOGY_SECTIONS.map((section) => {
                const active = section.id === activeSectionId;
                return (
                  <button
                    key={section.id}
                    type="button"
                    onClick={() => setActiveSectionId(section.id)}
                    className={`rounded border px-2 py-1 text-[11px] transition ${
                      active
                        ? "border-sky-400/70 bg-sky-500/15 text-sky-100"
                        : "border-slate-700 text-slate-300 hover:border-slate-500"
                    }`}
                  >
                    {section.label}
                  </button>
                );
              })}
            </div>

            <div className="methodology-markdown text-slate-200">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
              >
                {activeSection.markdown}
              </ReactMarkdown>
            </div>
          </div>
        </section>
      </div>

      <style jsx global>{`
        .methodology-markdown h1,
        .methodology-markdown h2,
        .methodology-markdown h3 {
          margin-top: 1.1rem;
          margin-bottom: 0.55rem;
          font-weight: 700;
          color: #f8fafc;
        }
        .methodology-markdown h1 {
          font-size: 1.1rem;
        }
        .methodology-markdown h2 {
          font-size: 0.95rem;
          text-transform: uppercase;
          letter-spacing: 0.03em;
          color: #cbd5e1;
        }
        .methodology-markdown h3 {
          font-size: 0.86rem;
          color: #e2e8f0;
        }
        .methodology-markdown p,
        .methodology-markdown li {
          font-size: 0.8rem;
          line-height: 1.45;
          color: #d1d5db;
        }
        .methodology-markdown ul,
        .methodology-markdown ol {
          margin-top: 0.3rem;
          margin-bottom: 0.5rem;
          padding-left: 1.2rem;
        }
        .methodology-markdown code {
          border: 1px solid rgba(71, 85, 105, 0.8);
          background: rgba(2, 6, 23, 0.55);
          border-radius: 0.25rem;
          padding: 0.1rem 0.3rem;
          font-size: 0.72rem;
          color: #e2e8f0;
        }
        .methodology-markdown pre {
          border: 1px solid rgba(51, 65, 85, 0.9);
          background: rgba(2, 6, 23, 0.9);
          border-radius: 0.5rem;
          padding: 0.75rem;
          overflow-x: auto;
          margin: 0.7rem 0;
        }
        .methodology-markdown pre code {
          border: 0;
          background: transparent;
          padding: 0;
          color: #dbeafe;
          font-size: 0.72rem;
        }
        .methodology-markdown table {
          width: 100%;
          border-collapse: collapse;
          margin: 0.7rem 0;
          font-size: 0.74rem;
        }
        .methodology-markdown th,
        .methodology-markdown td {
          border: 1px solid rgba(51, 65, 85, 0.95);
          padding: 0.4rem 0.45rem;
          text-align: left;
          vertical-align: top;
        }
        .methodology-markdown th {
          background: rgba(15, 23, 42, 0.85);
          color: #e2e8f0;
          font-weight: 700;
        }
        .methodology-markdown tr:nth-child(even) td {
          background: rgba(2, 6, 23, 0.3);
        }
        .methodology-markdown .katex-display {
          margin: 0.65rem 0;
          overflow-x: auto;
          overflow-y: hidden;
        }
        .methodology-markdown hr {
          border: 0;
          border-top: 1px solid rgba(71, 85, 105, 0.65);
          margin: 0.9rem 0;
        }
      `}</style>
    </div>
  );
}
