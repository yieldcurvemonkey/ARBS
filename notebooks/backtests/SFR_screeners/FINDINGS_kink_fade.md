# SFR butterfly "fade-the-kink": naive vs implied-distribution — findings

**Question.** Does the options-implied variance signal (`adj_signal` =
sqrt(T)-adjusted variance-excess / fly) predict subsequent butterfly
normalization **better than naively fading by fly magnitude — net of the fly
level itself and net of costs**?

**Data.** Full-year *curve* panel (250 biz days, 2025-05-22→2026-05-22, 44 flies,
28/day across 3/6/9/12mo spacings) supplies the forward-return target Δfly and
the naive signal. *Options* panel (BKM moments → `adj_signal`) currently covers
**250 dates (2025-05-22→2026-05-22) — FULL YEAR, COMPLETE.**
Forward Δfly is the SAME fixed-contract fly h biz days later (global biz-day
ordinal; NaN on roll-off). All analyses are **within-gap** (cross-gap scale
differs ~20×, so ranking across gaps just sorts by maturity).

## Verdict: **RED** — options signal is *not* additive, does *not* beat naive net of costs.

The framework's *directional* intuition survives; its *economic* claim does not.

| Handover GREEN criterion | Result |
|---|---|
| Fly normalizes (fade works at all) | ✅ strong — within-gap IC(bf,Δfly): h21 **−0.27** (t=−8.3), h63 **−0.66** (t=−30) |
| adj_signal IC concentrates in gap flies | ~ directionally yes at h63 only; **decayed with sample** (12mo h21: −0.43 @87d → **−0.07 @250d**) |
| …survives controlling for fly level | ❌ **no** — Fama-MacBeth + Newey-West marginal t **\|t\|≤0.2** at every horizon; gap-flies-only h21 = **+1.0** (wrong sign) |
| …concentrates in symmetric-FOMC | ~ symmetric-FOMC L/S is the only gate that stays positive (IR +0.69 @h21) but only 88 dates |
| …beats naive net of costs | ❌ **no** — adj L/S h21 **IR −1.82** (actively loses money) vs naive **+1.35**; −3.50 after 0.75bp cost |

## Why the nuance matters
- **It is NOT "a noisier proxy for fly magnitude."** Entanglement ρ(adj_signal, |bf|) ≈ −0.04 — `adj_signal` is genuinely *independent* of the fly level. The problem is it is independently **uninformative once tested honestly**, not redundant.
- **The headline inflation.** Pooled-OLS marginal t for adj_signal looked decisive (h21 **t=−7.5**). That is pseudo-replication: ~28 correlated flies/day × overlapping h-day forward returns. The honest Fama-MacBeth (date = unit) + Newey-West(lag=h) t is **−0.8**. The apparent edge is an artifact of treating 87 overlapping months as ~2,000 independent observations. *(See bottom-left panel of the PNG — red bars collapse to blue.)*
- **The naive fade is the real, robust effect.** The fly mean-reverts; ranking flies within their maturity bucket and fading the extremes earns a credible non-overlapping Sharpe ~1.3–2.0 at 5–21d. Options add nothing on top.
- **It decays as the sample grows** — the overfitting tell. From 87→157→250 dates: 12mo h21 bucket-ρ went −0.43→−0.25→**−0.07**; inflated pooled marginal t went −7.5→−3.8→**+6.7 (wrong sign!)**; honest FM t stayed ~0 throughout. A real structural edge firms up with more data; an in-sample artifact washes out. This one washed out completely.
- **adj_signal L/S now actively loses money** (h21 IR −1.82). At 87 dates it was +0.56, giving false hope. The full year killed it — classic out-of-sample decay of an overfit signal.

This is exactly the a-priori caveat in the handover: the variance→richness link runs only through the convexity wedge, "a few bps and smallest in the short end." It is real in *direction* (gap flies carry the sign) but **too small/noisy to extract net of the level and transaction costs.**

## On the sign question (tested, not assumed)
The competing reading — *excess variance = a genuine binary pivot that persists,
not a fade* — gets partial support: raw `adj_excess` (std-excess in bps, no /fly)
has **positive** unconditional IC at h63 (+0.22), i.e. high-variance-excess flies
get *more* curved near-term. But that too vanishes/flips under level controls.
Neither "fade" nor "persist" dominates once the fly level is removed.

## Honest caveats
- **Full-year coverage (250/250 dates)** — but still a single mild-easing regime.
  h63 stats rest on ~4 independent 63-day windows — discount them vs h5/h21.
- Single mild-easing regime in sample.
- Naive **h63 IR +15** is an overlap artifact (~3 windows) — discount it; the
  h5/h21 figures are the credible ones.

## Artifacts
- `butterfly_rv_backfill.py` — screener-parity panel builder (all spacings, sqrt(T)
  `adj_signal`, FOMC gap windows, upsert parquet). Validated vs screener on 2026-05-27.
- `_curve_panel.py` → `butterfly_curve_panel.parquet` — fast full-year Δfly target + naive signal.
- `kink_fade_backtest.py` — the harness. `python kink_fade_backtest.py` (report) /
  `--charts` (PNG). Re-runnable; refreshes as options coverage grows.
- `kink_fade_framework_results.png` — 4-panel summary.
