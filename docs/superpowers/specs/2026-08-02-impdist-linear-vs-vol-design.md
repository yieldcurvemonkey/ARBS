# Linear-vs-Vol Implied Distributions — the three-way triangle

**Date:** 2026-08-02
**Branch:** `feat/impdist-linear-vs-vol` (stacked on `feat/zq-sr3-meeting-prob`, worktree `ARBS-xm`)
**Requested by:** user — "create a notebook that compares the distributions from
linear futures (ZQ) and fomc swaps using curve USD-OIS-Q12xM12STIRT-SERFFX-MIX23
and SFR vol distribution"

## The idea

Three markets carry a distribution of the policy path, and only one of them
prices its shape:

1. **ZQ futures** — monthly EFFR averages → FedWatch bootstrap → per-meeting
   jump lattice (`RVUtils/MeetingProb/ladder.py`, already built).
2. **FOMC-dated swaps** — meeting-to-meeting forwards read off two purpose-built
   STIR curves: `USD-OIS-Q12xM12STIRT-SERFFX-MIX23` (EFFR leg — the ZQ
   cross-check) and `USD-SOFR-1D-Q12xM12STIRT` (SOFR leg — basis-free input to
   anything SR3). Same mantissa-lattice reduction. **New module.**
3. **SR3 options** — Breeden–Litzenberger RND from the SABR smile
   (`RVUtils/ImpliedDistribution`, already built) — the full continuous shape.

Sources 1 and 2 are both linear: they identify only the MEAN path, and their
per-meeting lattices are a modelling convention on top of it. Source 3 prices
the whole distribution but parity pins its mean to the same forward. So the
triangle splits cleanly: **linear-vs-linear differences are measurement noise +
FF/SOFR basis** (this is exactly the un-priced ZQ-side error that PR #375's
tie-out gate defended against — the FOMC-swap curve is a second, independent
linear read), and **linear-vs-option differences are shape** — the only thing
options add, and the only candidate RV.

Taboga (2016, IREF) frames the punchline: in equities, multi-modality in
option-implied RNDs is usually an over-fitting artifact. SR3 is the one
underlying where multi-modality is structurally REAL — the FOMC lattice — and
the linear tree independently predicts where the modes must sit. Mode agreement
validates the BL extraction; mode disagreement is the signal.

## Deliverables

### 1. `RVUtils/MeetingProb/swap_ladder.py`

- `fomc_period_rates(as_of, pricer, schedule)` — fair rate of each
  meeting-period swap (effective_k → effective_{k+1}) off one curve pricer
  (`IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer`), meetings with
  maturity > as_of only. No `date.today()` anywhere — as_of-clean, unlike
  `SDRUtils.analytics.fomc.price_fomc_meetings`.
- `jumps_from_period_rates(period_rates_bp, base_rate_bp)` — pure: per-meeting
  jump_k = period_rate_k − period_rate_{k−1}, with the pre-first-meeting level
  = base (current fixing / forward-only level of the in-progress period).
  Testable without any curve.
- `swap_meeting_ladder(...)` — wraps the two into `List[MeetingLattice]` (the
  exact dataclass the ZQ ladder emits), via the same `mantissa_probs`
  reduction. Plugs directly into `MeetingProb.atoms`/`AtomEngine`.

Jumps difference out any static overnight basis; levels do not. All atom
anchoring stays mean-pinned to the SR3 forward (PR #375 convention), so basis
level drops out of the terminal-distribution comparison by construction.

### 2. `notebooks/rv/linear_vs_vol_distributions.ipynb` (executed, committed)

Contract SFRZ26, dates 2026-07-28 → 2026-07-31 (the user's own pair).

- **A. Per-meeting table** — FedWatch-style: for each upcoming meeting, the
  implied jump and lattice P from ZQ, from the OIS swap curve, from the SOFR
  swap curve, side by side; tie-out stats (max |Δjump|, per-meeting spread).
  Renders the CME-screenshot view from three sources at once.
- **B. Terminal overlay** — BL RND (continuous) vs the two atom trees pushed
  through the settlement transform, on the SR3 settlement-rate axis; moments
  table (mean/std/skew/kurt), BL diagnostics (forward_residual_bp,
  pre_normalization_mass, ghost_mass_fraction) printed, lattice variance
  ceiling marked. Mode-alignment check: BL local maxima vs atom locations.
- **C. The change** — 07-28 → 07-31 through all three: Δmean must agree
  (parity/martingale); Δshape exists only in the options. `plot_distribution_change`
  for the option leg, jump-table delta for the linear legs.
- **D. Divergence** — per-25bp-bin P_opt − P_tree under the strict smear
  (baseline-null convention from PR #375), CDF gaps at the boundary strikes —
  the channel-1/channel-2 read for this date, tied back to the meeting-prob
  findings.

### 3. Tests (synthetic, no network)

Jump extraction from planted period rates (incl. in-progress base handling),
lattice equivalence: identical jumps → identical `MeetingLattice` as the ZQ
path, and atoms built from a swap ladder == atoms from an equal ZQ ladder.

## Non-goals

No backtest here — this is the comparison instrument the user asked for.
History/backtest, if the pictures warrant it, is a follow-up. No new RND
extraction method; the BL implementation and its documented caveats are used
as-is. No intraday.

## Risks

- MIX23 curve build for 07-28/07-31 may need network/cache warm-up (memory:
  429-storm history; the daily cache warmer covers it). Fallback: nearest
  dates that build.
- `fair_rate` unit convention (percent vs decimal) verified empirically in the
  probe before wiring anything.
