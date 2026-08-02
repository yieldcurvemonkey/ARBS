# Linear-vs-Vol Implied Distributions — Findings

**Date:** 2026-08-02
**Branch:** `feat/impdist-linear-vs-vol` (stacked on `feat/zq-sr3-meeting-prob`)
**Design:** `2026-08-02-impdist-linear-vs-vol-design.md`
**Executed notebook:** `notebooks/rv/linear_vs_vol_distributions.ipynb`
(10 cells, 2 figures, 0 errors, 0 unrun)

Dates 2026-07-28 → 2026-07-31 straddle the July FOMC decision (hold, ~1/3 of
a hike priced on the eve). Contracts SFRZ26 (136 dte, the meeting-prob
frontier's saturated band) and SFRU26 (45 dte, the feasible band).

## The linear legs agree on the path, disagree on attribution

Per-meeting jumps from ZQ, the MIX23 OIS swap curve, and the Q12xM12 SOFR
swap curve: cumulative post-Sep move 24 / 23 / 23 bp — the mean path ties out
to ~1bp — while single-meeting attribution differs by up to 3.8–4.1bp
(e.g. July eve: ZQ says 8.0bp pending-July + 16.0 Sep; the swap curves say
10.4–10.6 + 12.2–12.8). The exchangeability/attribution degeneracy from the
meeting-prob study is therefore a property of *measurement*, visible between
two LINEAR markets — not something options introduced. The two swap curves
agree with each other to ≤2.0bp; ZQ is the outlier leg.

The composed FedWatch matrix from ZQ on 07-31 reads 35.6/63.7 for the Sep
meeting vs the published CME tool's 33/67 — the bootstrap reproduces the
screen to ~3pp, and the swap curves produce the same table with no bootstrap.

## The swap ladder is the sturdier linear source

The ZQ ladder silently lost the *pending July meeting for its entire event
window* because the just-expired front contract (ZQN26) had dropped out of
the serff staleness refresh — the same silent-drop failure PR #374/#375 fixed
once already, recurring through a different door (contract expiry, not month
range). `force_refresh` recovered it. The FOMC-swap curve carries the full
meeting-dated strip on every build date: no bootstrap, no month-end weight
dilution (a 07-29 meeting has 2/31 weight in July's ZQ average), no expiry
seam. New module `RVUtils/MeetingProb/swap_ladder.py` (+9 synthetic tests)
emits the same `MeetingLattice`, so atoms/pricer/refit are source-blind.

## Width and tails carry the signal; modes do not

On the settlement-rate axis (both trees mean-pinned to the option forward):

| contract | dte | BL std | tree std | off-lattice premium |
|---|---:|---:|---:|---:|
| SFRZ26 | 136 | 52.5bp | 24.2bp | **+28bp** |
| SFRU26 | 45 | 32.3bp | 18.5bp | **+14bp** |

Both off-lattice tails are rich on every (symbol, date) cell — below-lattice
+7.2 to +10.3pp, above-lattice +3.1 to +8.5pp against the strict-smear tree —
the channel-2 signature, re-derived through a third, bootstrap-free market,
shrinking toward expiry exactly as the meeting-prob frontier measured.

**The Taboga check came back subtler than hoped:** mode COUNT flips with the
strike filter (the OI-gated 07-28 density is unimodal mid-lattice; the
ungated 07-31 density is bimodal with a mode 0.9bp off an atom), while the
recovered WIDTH moves only ~1bp between extraction variants. Even where
multi-modality is structurally real, jaggedness is extraction-fragile —
Taboga's warning operating as designed. With 6–14bp of unresolved-meeting
smear, on-atom modes can only crystallize robustly inside the final month
(<30 dte — the frontier's 0%-saturation region).

## Across the resolution

July's ZQ jump collapses −7.7bp (to 0.3 ≈ hold confirmed) while every later
meeting's jump inflates +1 to +4bp: the priced hike probability migrated out
the strip rather than vanishing. The BL mean follows the forward on both
contracts (parity; the mean channel stays dead), SFRZ26 width compresses
52.5 → 43.5bp.

## Honest limits

- The 07-31 session has no published open interest, so both 07-31 densities
  use the OI-gate-free raw-premium variant (disclosed per date in-notebook;
  the SABR-model fallback is asserted away). SFRU26 07-31 diagnostics are
  the weakest (fwd residual −4.3bp, pre-norm mass 1.053).
- Two dates, one meeting, two contracts — a demonstration instrument, not a
  study. History + the <60-dte region (where the convergence channel opens
  and the swap ladder replaces ZQ as the hedge leg) is the follow-up.
- The FedWatch matrix composes meetings as independent Bernoullis — the same
  modelling convention CME uses, inherited, not tested.
