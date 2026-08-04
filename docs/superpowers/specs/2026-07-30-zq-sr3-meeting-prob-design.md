# ZQ-vs-SR3 Meeting-Probability RV — Design

**Date:** 2026-07-30
**Branch:** `feat/zq-sr3-meeting-prob` (worktree `ARBS-xm`)
**Predecessors:** `2026-07-29-sfr-rv-lab-findings.md` (why fly-vs-vol had no second price),
`BT/serff` (the linear ZQ-vs-SR3 basis), `RVUtils/SR3ZQDistributionScreener/_fedwatch.py`
(the CME FedWatch tree, committed and fixture-tested).

## The one structural fact this framework stands on

In the options lab, every "options-implied fair value of a futures structure" was the
futures structure itself — parity pins each surface's mean, so there was one price and a
magnifying glass. Here there are **two prices of the same number**:

- **ZQ prices P_m** (per-meeting move probabilities) through its *means* — the FedWatch
  bootstrap is just arithmetic on monthly averages, and the mantissa two-point lattice is
  the minimum-variance reading of a meeting's jump.
- **SR3 options price P_m(1−P_m)** through their *variance* (and the node CDF through
  verticals). The SR3 option **mean** is pinned to the SR3 future by parity — that channel
  is dead — but nothing pins the SR3 **variance** to the ZQ strip.

Same Fed, same lattice, two independent markets, two different payoff transforms of the
same P. That is the second quote fly-vs-vol never had. Both settle to realized fixings
that step ~1:1 on a policy move, so a per-meeting disagreement has a delivery date: the
meeting itself.

## Objects

For SR3 contract C with reference window [S, E), option expiry X (Friday before 3rd Wed;
X < S for quarterlies), and FOMC meetings with decision d_m, effective e_m = d_m + 1:

- **resolved-by-expiry** meetings (d_m ≤ X): outcome known at option expiry.
  Weight w_m = 1 if e_m ≤ S (shifts the whole window), else (E − e_m)/(E − S).
  For a quarterly SR3 option, X < S, so every resolved meeting has w_m = 1.
- **unresolved** meetings (d_m > X, e_m < E): at expiry they sit in the price as
  conditional expectations — a **smear** around each atom (mean = day-weighted
  ZQ-implied jump, width fitted), never as outcomes. This is the resolution-mismatch
  correction from the design conversation: without it, expectation variance masquerades
  as flattened P's.

**Q_ZQ** = push the ZQ tree through this transform: atoms at
`anchor + Σ_resolved w_m·J_m(outcome)`, probabilities = products of per-meeting two-point
probs (independence — the FedWatch assumption, inherited deliberately: it is the null).

## The anchoring decision (important, deliberate)

Atoms are displaced around **today's SR3 forward**, not around a bootstrapped
EFFR-plus-spread level:

```
anchor = F_sr3(today) − Σ_m w_m · E_zq[J_m]        (sum over resolved-by-expiry meetings)
```

so that `mean(Q_ZQ) = F_sr3(today)` **by construction**. Rationale: parity pins the option
surface's mean to the same forward, so with this anchor the two distributions share their
mean identically and every divergence is *shape* — which is the only thing this framework
claims to trade. The SOFR−EFFR spread, the turn, and the windowing algebra all drop out of
the comparison entirely.

The **level tie-out** (ZQ-implied window mean + fitted spread vs SR3 forward) is still
computed daily — as a *gate and diagnostic*, exactly like `forward_residual_bp` in the
options lab. If it blows out, the day's shape comparison is suspect. It is not the trade
(that is SERFF's linear basis, explicitly out of scope here).

Consequence for identification, stated honestly: because both sides are mean-pinned, a
**mean-preserving reallocation** across meetings (P_1 up, P_2 down, weighted) is the only
kind of per-meeting disagreement this construction can see, and it is identified through
the *variance/shape fingerprint* of each meeting's day-weight — not through levels. The
primary channel-1 statistic is therefore reported in **variance space**
(`v_m = (25 w_m)² P_m(1−P_m)`, option-implied vs ZQ-implied) alongside the P-space gap.

## Channels

1. **Per-meeting P gap** (two-sided, convergence): refit the lattice P-vector to listed
   SR3 premiums (mean-constrained, smear included); compare to ZQ's vector. Expression:
   the boundary vertical (digital on n ≥ k) on the SR3 side, delta-hedged with the
   tree-delta-weighted ZQ meeting basket, rebalanced at each meeting resolution.
   Multilinearity of any payoff on {0,1}^M makes the lattice replication exact —
   *on the lattice*; off-lattice outcomes (50bp, intermeeting) are the tail risk.
2. **Fit residual** (one-sided, harvest): the part of the surface no independent-P vector
   reproduces — coupling, >25bp mass, tails. Cross-market twin of `tail_rent`.
   Measured and z-scored; no convergence claim.
3. **Two-digital classifier** (from the design conversation, kept verbatim): if only one
   boundary digital is rich → genuine P disagreement (channel 1). If both are rich →
   overdispersion/coupling (channel 2). Two premium quotes, executable test.

## What must be measured before anything is believed

- **Identification.** With listed strikes at 12.5–25bp spacing and 25bp atoms, is the
  refit conditioned? Per (date, contract): count boundary-straddling verticals; Jacobian
  conditioning; and **half-tick bootstrap** (perturb every premium ±0.125bp, refit) →
  σ(P_opt). If σ(P) is comparable to typical gaps, channel 1 is
  measurement-bound and the honest verdict is DEAD-by-measurement.
- **Smear degeneracy.** A wide smear mimics P→½ dispersion. The no-meeting control
  bracket and the bootstrap must show the two are separable, or the smear is fixed
  ex-ante from ZQ (not fitted) and that choice documented.
- **ZQ staleness.** Adjacent contracts printing identical prices is a dead quote
  (the ZQM7/ZQN7 case); gate on it. Tree probabilities from stale prints are fiction.
- **The tie-out gate through time**, per contract, with the fitted flat spread — the
  cross-market `forward_residual`.

## Honesty rules (inherited wholesale from the two prior labs)

Lag-1 fills; listed premium marks only (BL splines are diagnostics); costs per CONTRACT
(SR3 option legs and ZQ futures legs both at half-tick scenarios, maker/taker grid);
grid distribution + deflated Sharpe + median config; sign test both directions; verdicts
ALIVE / SELECTION-ARTIFACT / MARGINAL-maker-only / DEAD via `SFRRVLab.stats.verdict`;
regime/meeting-era splits; every notebook executed and verified programmatically.

## Data (all committed infra, no new fetch paths)

- ZQ settles: `BT/serff/futures_data.backfill_settles` cache (2018→; forward strip
  refreshed by `notebooks/rv/backfill_zq_forward.py`).
- SR3 option premiums: `notebooks/data/sfr_rv_lab/quotes.parquet` (2024-07→2026-07,
  199k listed quotes) + `contracts.parquet` forwards, read from the main tree.
- FedWatch tree: `SR3ZQDistributionScreener._fedwatch.build_fedwatch_tree`.
- FOMC schedule: `SDRUtils.analytics.fomc.load_fomc_schedule`.
- Day weights: window algebra above (tested against `SFRRVLab.lattice`).

## Modules

`RVUtils/MeetingProb/`:
- `ladder.py` — ZQ prices → per-meeting jumps and two-point lattices (wraps the committed
  tree builder; staleness gates).
- `atoms.py` — the settlement transform: meetings × windows × expiry → resolved/unresolved
  split, weights, atoms, smear; `mean(Q_ZQ) = F` anchoring.
- `pricer.py` — closed-form pricing of listed structures over smeared atoms.
- `refit.py` — mean-constrained P-vector fit to listed premiums + half-tick bootstrap.
- `monitor.py` — channel decomposition, two-digital classifier, gap z-scores.

Tests: CME Sep-2022 fixture through the ladder; hand-computed two-meeting atom examples;
pricer vs closed forms; refit recovery of planted P's; mean constraint; multilinear
replication exactness on the lattice and its failure off-lattice; smear separability.

## Deliverables

Executed notebooks (`# %%` → `_py2nb` → nbconvert → `_verify_nb`): tie-out gate,
P-extraction history with identification honesty panel, channel-1 backtest, summary with
league rows and verdicts; findings doc; memory update; PR.
