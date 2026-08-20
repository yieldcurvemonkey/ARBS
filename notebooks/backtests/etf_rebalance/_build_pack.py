"""Assemble figures/FIGURE_PACK.html and figures/CAPTIONS.md from what is on disk.

Self-contained by construction: every PNG is inlined as a base64 data URI, there is no
external stylesheet, no font download and no script. The page is the deliverable, so it
has to survive being copied to a machine with no access to this repo.

Order is fixed here rather than derived from the filenames: (i) what the fund actually
does, (ii) seasonality, (iii) the signal firing, (iv) real versus null, (v) the cost wall.
"""
from __future__ import annotations

import base64
import html
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
FIGS = HERE / "figures"

COST = 0.535
GROSS = 0.0045

# fig stem -> (one-line finding, data source)
META: dict[str, tuple[str, str]] = {
    "fund_01_ladder_heatmap": (
        "TLT's active weights are large and they ride DOWN the ladder with the bond that "
        "carries them - a standing portfolio shape, not a queue of dislocations waiting "
        "to revert.",
        "_data/fundfig_ladder_TLT.parquet, fundfig_flow_TLT_TLH.parquet "
        "(built from MDP/ETFHoldings, 2,528 TLT documents)."),
    "fund_02_deletion_shed": (
        "TLT really does shed a deleted bond - median 5% of the position left at +120 "
        "business days - in tranches over months, never on one month-end; and the price "
        "effect still refuses the flow story.",
        "_data/delcliff_holdings_verification.csv, raw_holdings_TLT_TLH.parquet, "
        "fundfig_active_TLT.parquet."),
    "fund_03_ownership_scale": (
        "The Fed holds a median 17.8% of a Treasury issue and TLT 1.10%: the fund's own "
        "realised trade is undetectable in the same day's price (|t| <= 0.94 on five "
        "funds), which is the feasibility test the project needed to pass.",
        "_data/aggown_full_panel.parquet (430,140 bond-days, 2018-2026)."),
    "fund_04_creation_redemption": (
        "A creation basket is one pro-rata scaling of the whole book (median 99.9% "
        "explained) - the fund made bigger, not a set of bonds anyone picked.",
        "_data/raw_holdings_TLT_TLH.parquet (2,520 usable TLT document pairs)."),
    "fund_05_persistence": (
        "The most overweight name is still the most overweight 86% of the time three "
        "weeks later while the richest bond holds only 59%: a near-constant cannot "
        "forecast a series with a 17-day half-life.",
        "_data/fundfig_active_TLT.parquet, fundfig_flow_TLT_TLH.parquet, "
        "ust_panel.parquet."),
    "seas_01_month_end_signal_vs_control": (
        "The month-end tilt in the holdings spread is BACKWARDS and a maturity-matched "
        "placebo covers it; the holdings-free richness control earns 5x more per unit of "
        "spread and is still 3.4x below the round trip.",
        "_data/seas_cells_TLT_bd_me_h10.csv, seas_cells_control_TLT_bd_me.csv, "
        "seas_headline_numbers.json."),
    "seas_02_calendar_cuts_small_multiples": (
        "Charge the 70-cell search and no calendar cut of the holdings signal clears its "
        "placebo: family-wise p = 0.21.",
        "_data/seas_cells_TLT_{dom,dow,moy}_h10.csv, seas_headline_numbers.json."),
    "seas_03_reconstitution_intensity": (
        "The reconstitution IS real in the funds' own filings - the average fund trades "
        "3.5x its own average day on the last trading day of the month - but TLT, the "
        "only fund this pack trades, is the weakest of the twelve at 1.5x.",
        "_data/seas_fund_intensity.csv, seas_calendar_ALL.csv "
        "(22,904 documents, 12 funds)."),
    "seas_04_opportunity_dispersion": (
        "The opportunity does not swell at the reconstitution, and 0 of 12 months put a "
        "full TLT round trip of cross-sectional dispersion on the table.",
        "_data/seas_disp_TLT_*.csv, seas_disp_TLH_*.csv."),
    "seas_05_yearly_stability_search_cost": (
        "The strongest seasonal cell in the study is carried by one year (2016) and is "
        "beaten by a holdings-free placebo draw one time in five.",
        "_data/seas_yearly_best_TLT.csv, seas_placebo_null_TLT.csv."),
    "fig01_trigger_timeline": (
        "1,407 butterflies gross +6.3bp over ten years and pay 706bp of measured "
        "FedInvest spread; the control that reads no holdings file grosses eight times "
        "more per trade and also loses.",
        "_data/trig_closed.parquet, trig_closed_control_resid.parquet, "
        "trig_closed_null_deletion.parquet."),
    "fig02_one_trade_anatomy": (
        "The most recent trigger end to end: the signal called the direction correctly "
        "and the move it was right about was a fifth of the spread.",
        "_data/trig_lastday.parquet, trig_lastpath.parquet, trig_legs.parquet, "
        "trig_meta.json."),
    "fig03_score_distribution": (
        "A trigger is a rank, not a threshold: the rule takes half of the |z| > 3 tail "
        "but also 14-16% of the |z| ~ 1.5 body, whatever the cross-section looks like.",
        "_data/trig_scores.parquet, trig_closed.parquet."),
    "fig04_edge_by_dislocation": (
        "Gross edge does not scale with the size of the dislocation - the extreme "
        "|z| > 3 bucket is negative - and the net hit rate is 1-5% at every bucket.",
        "_data/trig_closed.parquet."),
    "fig05_pnl_waterfall": (
        "Execution is 112x the entire gross P&L of the strategy, and the price leg - the "
        "part a signal is supposed to drive - is NEGATIVE over ten years.",
        "_data/trig_closed.parquet."),
    "contrast_01_raw_vs_partial_ic": (
        "Remove the bond's own richness and five of the six holdings signals change sign; "
        "the sixth collapses to zero.",
        "_data/partial_ic.parquet, ic_surface.parquet."),
    "contrast_02_naive_vs_hac_t": (
        "Counting the overlapping windows deletes most of the significance in the study: "
        "69 of 147 naively-significant points land inside |t| < 2 under Newey-West.",
        "_data/partial_ic.parquet, bivariate.parquet, deletion_control.csv, "
        "audit_ladder_newey_west.csv, adv_newey_west_tstats.csv."),
    "contrast_03_double_sort": (
        "Sort on richness first and the fund's active weight adds nothing - and does not "
        "add it monotonically.",
        "_data/realized_double_sort.csv, ladder2_double_sort_held.csv."),
    "contrast_04_placebo_distribution": (
        "A matched placebo boundary at 28 years, where no index does anything at all, "
        "produces a LARGER statistic than the real 20-year deletion boundary.",
        "_data/deletion_control.csv."),
    "contrast_05_calendar_beats_scrape": (
        "On five funds of six a calendar rule that reads no holdings file beats the best "
        "signal from 22,904 scraped documents: placebo > calendar > holdings.",
        "_data/adv_calnull_recheck.csv."),
    "contrast_06_cost_wall": (
        "Of 5,192 grid configurations, not one covers its own measured round trip on 50 "
        "trades or more.",
        "_data/grid_league.csv, grid_TLT.parquet, grid_TLH.parquet, grid_IEF.parquet."),
}

SECTIONS = [
    ("What the fund actually does",
     "Five panels of measured, verified fund behaviour. Everything here is read straight "
     "out of the iShares documents and every one of these effects is real. None of them "
     "is a signal, and each panel says so on its own face.",
     ["fund_01_ladder_heatmap", "fund_02_deletion_shed", "fund_03_ownership_scale",
      "fund_04_creation_redemption", "fund_05_persistence"]),
    ("Seasonality",
     "The funds' trading is emphatically seasonal. The PRICE is not: every calendar cut "
     "of the holdings signal is matched by a maturity-matched placebo that reads no "
     "holdings file, and the ceiling on the whole trade does not widen at the "
     "reconstitution.",
     ["seas_01_month_end_signal_vs_control", "seas_02_calendar_cuts_small_multiples",
      "seas_03_reconstitution_intensity", "seas_04_opportunity_dispersion",
      "seas_05_yearly_stability_search_cost"]),
    ("The signal firing",
     "What the rule actually does when it is run: every trigger over ten years, one "
     "trade end to end, what it takes to fire, whether the edge scales with the "
     "dislocation, and where the money went.",
     ["fig01_trigger_timeline", "fig02_one_trade_anatomy", "fig03_score_distribution",
      "fig04_edge_by_dislocation", "fig05_pnl_waterfall"]),
    ("Real versus null",
     "Each holdings result against the control that explains it and the null that beats "
     "it. The ranking this study ends with is placebo > calendar > holdings.",
     ["contrast_01_raw_vs_partial_ic", "contrast_02_naive_vs_hac_t",
      "contrast_03_double_sort", "contrast_04_placebo_distribution",
      "contrast_05_calendar_beats_scrape"]),
    ("The cost wall",
     "The measuring stick, stated before the result and applied to everything: a "
     "DV01-neutral 20-30y butterfly costs a median 0.535bp per round trip on FedInvest's "
     "own published bid and offer.",
     ["contrast_06_cost_wall"]),
]

CSS = """
:root{
  --bg:#fbfbf9; --panel:#ffffff; --ink:#1a1a1a; --ink2:#4d4d4d; --muted:#7a7a7a;
  --rule:#e2e2dd; --accent:#0072b2; --warn:#d55e00; --good:#009e73;
  --shadow:0 1px 3px rgba(0,0,0,.07);
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#14161a; --panel:#1c1f25; --ink:#e9e9e6; --ink2:#b6b6b2; --muted:#8b8b88;
    --rule:#2c3038; --accent:#5cb3e8; --warn:#ef8b4a; --good:#3fc9a3;
    --shadow:0 1px 3px rgba(0,0,0,.4);
  }
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;max-width:100%;overflow-x:hidden}
body{
  background:var(--bg); color:var(--ink);
  font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px;margin:0 auto;padding:44px 22px 96px}
header h1{font-size:29px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:14px;margin:0 0 30px}
h2{font-size:21px;margin:0 0 6px;letter-spacing:-.005em}
h3{font-size:16px;margin:0 0 4px}
p{margin:0 0 12px}
a{color:var(--accent)}
.verdict{
  background:var(--panel); border:1px solid var(--rule); border-left:4px solid var(--warn);
  border-radius:8px; padding:20px 22px; margin:0 0 26px; box-shadow:var(--shadow);
}
.verdict .num{
  font-size:22px; font-weight:650; letter-spacing:-.01em; margin:14px 0 2px;
}
.verdict .num b{color:var(--warn)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin:14px 0 0}
.cols h3{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.cols ul{margin:0;padding-left:19px}
.cols li{margin:0 0 7px;font-size:14.5px;line-height:1.5}
.yes li::marker{color:var(--good)}
.no li::marker{color:var(--warn)}
section{margin:0 0 12px;padding:30px 0 0;border-top:1px solid var(--rule)}
section > .lede{color:var(--ink2);font-size:15px;max-width:74ch;margin:0 0 22px}
figure{
  margin:0 0 30px; background:var(--panel); border:1px solid var(--rule);
  border-radius:8px; padding:16px 16px 4px; box-shadow:var(--shadow);
}
figure img{display:block;width:100%;max-width:100%;height:auto;border-radius:3px}
@media (prefers-color-scheme: dark){
  /* The PNGs are drawn on white. A gentle knock-back keeps them from glaring
     without inverting colours that carry meaning. */
  figure img{filter:brightness(.92) contrast(1.02)}
}
figcaption{padding:14px 2px 12px;font-size:13.6px;line-height:1.58;color:var(--ink2)}
figcaption .finding{display:block;color:var(--ink);font-weight:600;margin:0 0 8px}
figcaption .src{display:block;margin:9px 0 0;font-size:12.4px;color:var(--muted)}
.tag{
  display:inline-block;font-size:11.5px;letter-spacing:.02em;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--muted);border:1px solid var(--rule);border-radius:99px;padding:1px 9px;
  margin:0 0 9px;
}
figcaption b.lead{
  display:block;font-size:11.8px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--muted);margin:2px 0 3px;font-weight:650;
}
footer{margin:38px 0 0;padding:22px 0 0;border-top:1px solid var(--rule);
  color:var(--muted);font-size:13px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.8px;
  background:var(--bg);border:1px solid var(--rule);border-radius:4px;padding:1px 5px}
"""

SUMMARY_REAL = [
    "TLT really sheds a deleted bond: 85-90% of the position gone by day +120 "
    "(95% on a business-day axis), verified in the holdings files, over 32 crossings, "
    "in two tranches rather than one month-end cliff.",
    "Aggregate ETF ownership co-moves with richness CONTEMPORANEOUSLY: +0.032bp per "
    "percentage point of float owned, Newey-West t = 8.8.",
    "The bond's own richness residual mean-reverts strongly: cross-sectional IC 0.35 at "
    "63 days, lag-1 autocorrelation 0.958, OU half-life 17 business days. Real, strong, "
    "and nothing to do with ETFs.",
    "The fund's active weights are large and persistent: neighbouring bonds run +173bp "
    "and -185bp of active weight at the same time, and the same bond is still the most "
    "overweight name three weeks later.",
    "The funds' trading is genuinely seasonal: the average scraped fund trades 3.5x its "
    "own average day on the last trading day of the month, 12 of 12 funds.",
]

SUMMARY_NOT = [
    "A predictive edge from the holdings. Raw IC on active weight is strong and "
    "BACKWARDS (-0.065, t -14.4 at 63d); control for richness and every sign flips and "
    "collapses to 0.003-0.005bp per unit z; under Newey-West nothing reaches t = 2; and "
    "a double sort does not reproduce it.",
    "The deletion effect as an ETF-FLOW story. Amplitude does not scale with TLT's "
    "ownership (corr 0.002), and the 10-year boundary - where the flow direction "
    "REVERSES - gives the same sign and size (+0.52bp t 2.31 against +0.47bp t 2.93).",
    "The calendar signal as a discovery. Its HAC t of 2.40 is beaten by a matched "
    "placebo boundary at 2.74, and its best seasonal cell (2.92) sits at family-wise "
    "p = 0.21 against holdings-free draws.",
]


DISAGREEMENTS = """
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
""".splitlines()


def _img(p: pathlib.Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("ascii")


#: The fund captions are deliberately long and carry their own structure. Rendered as one
#: block they become a wall nobody reads, which defeats the point of putting the null in
#: the caption at all -- so the structure is honoured as paragraph breaks.
_LEADS = ("WHAT IT PROVES.", "WHAT IT DOES NOT PROVE.", "NOTE ON CONSTRUCTION.",
          "WHAT IT PROVES", "WHAT IT DOES NOT PROVE", "NOTE ON CONSTRUCTION",
          "LEFT:", "RIGHT,", "LEFT,", "RIGHT:", "MIDDLE:", "TOP:", "BOTTOM:",
          "CONTEXT:", "MEASURED, not inferred:")


def _caption_html(body: str) -> str:
    if not body:
        return ""
    paras: list[str] = []
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split before each structural lead-in, longest first so the "." variants win.
        chunks = [line]
        for lead in sorted(_LEADS, key=len, reverse=True):
            out: list[str] = []
            for c in chunks:
                i = c.find(lead, 1)
                while i > 0:
                    out.append(c[:i].strip())
                    c = c[i:]
                    i = c.find(lead, 1)
                out.append(c.strip())
            chunks = [c for c in out if c]
        paras.extend(chunks)

    html_parts: list[str] = []
    for p in paras:
        for lead in sorted(_LEADS, key=len, reverse=True):
            if p.startswith(lead):
                rest = p[len(lead):].strip()
                html_parts.append(
                    f"<p><b class='lead'>{html.escape(lead.rstrip(':.'))}</b>"
                    f"{html.escape(rest)}</p>")
                break
        else:
            html_parts.append(f"<p>{html.escape(p)}</p>")
    return "".join(html_parts)


def build() -> tuple[str, int]:
    seen: list[str] = []
    parts: list[str] = []

    parts.append("<div class='wrap'>")
    parts.append(
        "<header><h1>US Treasury ETF rebalancing: what is real, and why none of it "
        "is tradeable</h1>"
        "<p class='sub'>iShares daily holdings 2016-2026 &middot; 22,904 documents, 12 "
        "funds &middot; TLT 20-31y butterflies marked on FedInvest's published bid and "
        "offer</p></header>")

    real = "".join(f"<li>{html.escape(x)}</li>" for x in SUMMARY_REAL)
    notr = "".join(f"<li>{html.escape(x)}</li>" for x in SUMMARY_NOT)
    parts.append(f"""
<div class='verdict'>
  <p>There are real, measured phenomena in this dataset. There is no tradeable predictive
  edge from the holdings. Both are in the figures below, and every panel that shows an
  effect carries its null or its control beside it.</p>
  <p class='num'>The baseline book grosses <b>+{GROSS:.4f}bp per trade</b> against a
  <b>{COST:.3f}bp</b> measured round trip.</p>
  <p style='color:var(--muted);font-size:14px;margin:0'>That is a break-even cost multiple
  of 0.0089 &mdash; the strategy would need execution to be 112 times cheaper than it
  measurably is. Everything else on this page is an elaboration of that one ratio.</p>
  <div class='cols'>
    <div><h3>What is real</h3><ul class='yes'>{real}</ul></div>
    <div><h3>What is not</h3><ul class='no'>{notr}</ul></div>
  </div>
</div>""")

    for title, lede, stems in SECTIONS:
        parts.append(f"<section><h2>{html.escape(title)}</h2>"
                     f"<p class='lede'>{html.escape(lede)}</p>")
        for stem in stems:
            png = FIGS / f"{stem}.png"
            cap_p = FIGS / f"{stem}.caption.txt"
            if not png.exists():
                raise FileNotFoundError(png)
            finding, _src = META[stem]
            src = _src
            body = cap_p.read_text(encoding="utf-8").strip() if cap_p.exists() else ""
            # Several caption.txt files end with their own "Source: ..." sentence. The
            # page renders the source as its own line, so the trailing copy is dropped
            # rather than printed twice.
            j = body.rfind("Source: ")
            if j > 0 and len(body) - j < 320:
                body = body[:j].rstrip()
            body_html = _caption_html(body)
            parts.append(
                f"<figure><span class='tag'>{html.escape(stem)}</span>"
                f"<img alt='{html.escape(finding)}' "
                f"src='data:image/png;base64,{_img(png)}'>"
                f"<figcaption><span class='finding'>{html.escape(finding)}</span>"
                f"{body_html}"
                f"<span class='src'>Source: {html.escape(src)}</span>"
                f"</figcaption></figure>")
            seen.append(stem)
        parts.append("</section>")

    parts.append(
        "<footer>Every figure on this page is generated by a script in "
        "<code>notebooks/backtests/etf_rebalance/</code> and every number traces to a file "
        "in <code>_data/</code>. The full writeup is <code>RESULTS.md</code>; where a "
        "figure and the writeup disagree, the disagreement is listed in "
        "<code>CAPTIONS.md</code> rather than reconciled silently.</footer>")
    parts.append("</div>")

    doc = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           "<title>ETF rebalance RV - figure pack</title>"
           f"<style>{CSS}</style></head><body>{''.join(parts)}</body></html>")

    out = FIGS / "FIGURE_PACK.html"
    out.write_text(doc, encoding="utf-8")
    return str(out), len(seen)


def captions_md(n: int) -> str:
    lines = ["# Figure pack - findings and sources",
             "",
             f"{n} figures, in the order they appear in `FIGURE_PACK.html`. The full "
             "writeup is `RESULTS.md`; numbers that disagree with it are listed at the "
             "bottom rather than reconciled silently.",
             ""]
    for title, _lede, stems in SECTIONS:
        lines += [f"## {title}", ""]
        for stem in stems:
            finding, src = META[stem]
            lines += [f"### `{stem}.png`", "",
                      f"**Finding.** {finding}", "",
                      f"**Source.** {src}", ""]
    lines += DISAGREEMENTS
    return "\n".join(lines)


if __name__ == "__main__":
    path, n = build()
    size = pathlib.Path(path).stat().st_size / 1e6
    print(f"{path}  ({n} figures, {size:.1f} MB)")
    md = FIGS / "CAPTIONS.md"
    md.write_text(captions_md(n), encoding="utf-8")
    print(str(md))
