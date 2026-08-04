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

## The ICS anchor and the trade question (added 2026-08-02, second pass)

Mean-pinning kills the level channel by construction — but CME lists it: the
FF-vs-SR3 inter-commodity spread (for SFRZ26: `0.5·ZQF27 + 0.5·ZQG27 −
SR3Z26`, 10:6 leg ratio, $250/bp DV01-neutral both sides, quoted `SOFR rate −
FF rate`; conventions from the CME "STIR ICS on Globex" deck, reproduced in
`RVUtils/MeetingProb/ics.py` with the worked 3.5bp example under test). The
observed spread then decomposes on the lattice:

| as_of | observed ICS | basis | compounding | proxy wedge | **residual** | ZQ-chain fit |
|---|---:|---:|---:|---:|---:|---:|
| 07-28 | 5.25bp | 2.0 | 2.11 | 0.18 | **+1.31** | −0.42 |
| 07-31 | 5.25bp | 2.0 | 2.09 | 0.28 | **+1.44** | +0.45 |

The spread did not move a quarter-tick across the FOMC resolution — the
level channel is its own market, orthogonal to the meeting repricing. The
residual (+1.3–1.4bp, SR3 rich) sits on a December quarterly whose window
contains the year-end turn, so it is at least partly the turn premium; the
serff fair-value study already ran this trade class with a 3-layer model and
found costs dominate. The FF-anchored absolute overlay
(`ff_conditional_atoms`) now shows the option RND and the FF conditional
distribution on one axis with the mean gap visible instead of pinned away.

**Is there a trade?** Computed answer, both channels: (i) the LEVEL — fade
the decomposed residual (never the raw 5.25bp, ~75% of which is mechanical)
via the listed 10:6 ICS, only when it exceeds a few bp and the turn is
hedged against an adjacent non-turn quarterly; at +1.3bp it does not signal.
(ii) the SHAPE — the surface prices ~16pp more off-lattice mass than the FF
tree; selling it is the standing-insurance short the options lab already
sign-flipped on, and the convergence flavour is the meeting-prob channel-1
trade: episodic, cost-bound at EOD, best executed <60 dte with the swap
ladder as the linear leg. No standing harvest; two episodic, cost-gated
entries.

## The path ledger (added 2026-08-02, third pass)

For a quarterly whose resolved meetings all carry day-weight 1, the 2^k FOMC
orderings collapse to the move COUNT, so "hike, hike, hike" IS the terminal
425–450 bucket — an option-identified object despite exchangeability. The
ledger (notebook section F), at 07-31, ZQ tree vs options, with the
1bp-of-premium ≈ 4pp yardstick on 25bp verticals:

| bucket | path | lattice | tree (smeared) | options | gap | on the vertical |
|---|---|---:|---:|---:|---:|---:|
| 350–375 | 0 moves | 13.2% | 13.7% | 20.1% | +6.5pp | +1.6bp |
| 375–400 | 1 move | 41.0% | 40.0% | 23.3% | **−16.7pp** | −4.2bp |
| 400–425 | 2 moves | 36.3% | 35.7% | 23.9% | −11.8pp | −3.0bp |
| 425–450 | 3 moves (all hikes) | 9.4% | 10.0% | 15.7% | +5.7pp | +1.4bp |
| below lattice | intermeeting/>25bp | 0 | 0.4% | 8.2% | +7.8pp | +1.9bp |
| above lattice | intermeeting/>25bp | 0 | 0.3% | 8.8% | +8.5pp | +2.1bp |

**The user's example answers**: the all-hikes path (FedWatch ~9.7%) is
priced at 15.7% by the surface — +5.7pp ≈ +1.4bp rich on its vertical.

**Listed-vertical validation**: the two upper edges reprice from RAW listed
premiums within 0.2–0.7pp of the spline (P(rate>4.35): 24.3% listed vs
24.5% spline) — the interior gaps are real. The BELOW-lattice tail HALVES
on listed quotes (4.1% vs 8.2%) — that row is half spline artifact.

**One premium, not many edges**: probability conservation makes the modal
deficit (28.5pp at 07-31) identically the wing+tail surplus. The surface
flattens the modal paths and pays for everything the lattice cannot
represent. Selling it (buy the modal vertical, sell the wings — a fly) is
short realized dispersion around the FedWatch lattice — the channel-2
insurance short in fly clothing. It becomes a convergence trade only in the
<60-dte feasible regime with one-sided asymmetry (the meeting-prob
channel-1 gate: 5 trades/2y, cost-bound at EOD).

**Cross-expiry conditional (F3)**: SFRH27's resolved set = SFRZ26's + {jan27},
so fitting H27_counts = Z26_counts ⊛ Bernoulli(q) to the two option-implied
count distributions extracts options' own conditional P(jan27 move): 0.26 /
0.49 (07-28 / 07-31) vs ZQ's 0.17 / 0.26 and the SOFR-swap's 0.20 / 0.29.
Options put more weight on January moving — but the one-Bernoulli fit
leaves an L1 residual of 0.33–0.41 (a third of the mass), dominated by
H27's off-lattice width, so this is indicative, not tradeable. First
per-meeting number in this line derived from options alone.

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
