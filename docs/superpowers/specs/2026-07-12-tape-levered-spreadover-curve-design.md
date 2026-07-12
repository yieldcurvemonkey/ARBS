# Tape follow-ups (07/12b): LEVERED tag + SPREADOVER_CURVE/FLY

Two independent USD-swaps tape enhancements, deferred from PR #346. One branch,
one PR (they can be split if review prefers). Builds on `core/pts_scale.py`
(scale-aware bp/tie-out) and the detection pipeline mapped in
[[project_tape_bugs_0712]].

Worktree/branch: new branch `feat/tape-levered-spreadover-curve` off main after
PR #346 merges (it depends on `core/pts_scale.py` and the frontend `ptsScale.ts`).

---

## Enhancement 1 — `LEVERED` tag

**Goal.** Surface forward-levered swaps — a swap whose forward start is longer
than its tenor (e.g. `10y1y`: 10Y forward, 1Y tenor). Applies to outrights and
to forward-gap curves/flies (where every leg is levered).

**Rule.** A leg is levered when `forward_start_years - tenor_years > MARGIN`,
`MARGIN = 0.05` (≈ 2.5 weeks, to avoid float noise and exclude the equal case
like `5y5y`).

**Where.**
- `SDRUtils/analytics/trade_tape.py::_tags_for_row` — add one clause:
  `if fwd_years - tenor_years > 0.05: tags.append("LEVERED")`, reading
  `forward_start_years` and `tenor_years` off the row. `tape_tags` is computed
  per trade (leg), and the package badge already aggregates leg tags, so a
  gap curve/fly whose legs are all levered shows `LEVERED` at package scope with
  no extra work.
- Frontend: register `LEVERED` in the tape-tag catalog
  (`components/TradeTapeTable/RowBadges.helpers.ts` + any tone map in
  `constants.ts`) with a distinct badge tone (proposed: amber/indigo — a
  structural descriptor, not an alert).

**Cache.** Bump `TRADE_TAPE_CACHE_VERSION` (tag output changes). No detector
change → `DETECTION_CACHE_VERSION` untouched.

**Tests.**
- Python: `10y1y` outright → `LEVERED`; `5y5y` and `spot 10Y` → no tag; a
  forward-gap fly (`IMM_U2030/U2032/U2034 2Y`, forwards 4.2/6.2/8.2 > 2Y tail)
  → all legs `LEVERED`.
- Frontend: `tapeTagBadgesFor`/`TapeTags` renders the `LEVERED` badge.

---

## Enhancement 2b — `SPREADOVER_CURVE` / `SPREADOVER_FLY`

**Problem.** A curve/fly of *spreadovers* (each leg priced vs its UST benchmark)
is not surfaced as such:
- The `Spot 10Y/30Y` example is stored `SPREADOVER_CURVE` (legs carry a uniform
  broadcast package spread `-0.00325`), but the frontend `inferBaseTypeOverride`
  collapses it to `CURVE` because the per-leg spreads are uniform — a heuristic
  that misreads a broadcast package spread as "not a real spreadover-curve".
- A fly whose legs carry **no** per-leg spread (only a package PTP/PTS, e.g. the
  `IMM_U2027/U2028/U2029 1Y` fly) is never even a candidate — `detect_sub_package_curve_fly`
  requires per-leg spreads.

**Key idea.** The authoritative signal that a curve/fly is a spreadover-structure
is that its **package PTS ties out to the differential of the legs' standalone
spreadover levels** — exactly the walkthrough: last 10Y spreadover `-42.39bp`,
last 30Y `-74.75bp`, difference `-32.36bp` ≈ package `-32.5bp` (within 5bp).

### Part A — differential detection (new)

1. **Level index.** From the classified day/window frame (standalone SPREADOVER
   prints already tagged by `detect_spreadovers`, which runs earlier), build
   `level[tenor_bucket] -> most-recent standalone spreadover PTS`, normalized to
   bp via `pts_scale` (a `-0.004239` decimal → `-42.39bp`). Key on rounded
   benchmark tenor; keep the latest by execution timestamp.

2. **Match.** For each plain `CURVE` (2 legs) / `FLY` (3 legs) at spot benchmark
   tenors carrying a finite package PTS, compute the expected differential from
   the index:
   - CURVE: `level[back] - level[front]`
   - FLY:   `2*level[belly] - level[front] - level[back]`
   If every required level exists and `|package_PTS_bp - differential_bp| <= 5bp`
   → upgrade `package_type` to `SPREADOVER_CURVE` / `SPREADOVER_FLY`.

3. **Placement.** A new pass immediately after `detect_sub_package_curve_fly`
   (which handles the per-leg-spread case) in `_run_all_detectors`, on both the
   PTP and non-PTP frames. Only upgrades `CURVE`/`FLY` (never re-labels an
   existing composite). Records nothing new beyond `package_type`/`trade_type`.

**Level-source decision: the tape's own recent standalone SPREADOVER prints**
(the option above). Rationale: self-contained (no new data dependency), matches
the "last printed spreadover" framing, and benchmark tenors (2/5/10/30) print
frequently intraday. *Limitation:* fires only when a recent standalone spreadover
exists for each leg's tenor — a fly at 1Y-IMM (no such prints) stays a plain FLY.
A dedicated swap-vs-UST spread series would close the gap but adds a data
dependency and wiring; **deferred** unless the coverage gap proves material in
practice.

### Part B — stop the UI downgrade + relabel

Make the differential the authoritative signal and remove the lossy frontend
heuristic:

- **Detection precision (source of truth).** Tighten the existing
  `detect_sub_package_curve_fly` Phase-1 uniform-spread upgrade: when all legs
  carry the *same* spread (= a broadcast package spread), only keep
  `SPREADOVER_CURVE/_FLY` if Part A's differential confirms it; distinct per-leg
  spreads remain sufficient on their own (genuine individual spreadovers). Net:
  Python only emits a composite type when it is genuinely one.
- **Frontend.** Remove `inferBaseTypeOverride` (packageConfidence.ts) and the
  `displayedType = inferredType ?? package_type` collapse in `columns.tsx` /
  `LegsSubTable.tsx` / `MobileTradeCards.tsx` / `useFocusedTrade.ts` — the badge
  now trusts the stored `package_type`. Mirror the deletion in the server port
  `analytics/package_confidence.py` so the two stay in sync (the confidence
  *score* itself is unaffected; only the type-override is removed).
- **Label.** `_build_enriched_label` structure step renders `SPREADOVER_CURVE` /
  `SPREADOVER_FLY` (and, consistently, `MATCHED_MATURITY_CURVE/_FLY`) instead of
  the bare `CURVE`/`FLY` for composite types. Leg-scope stays `Outright`.

**Cache.** Bump both `DETECTION_CACHE_VERSION` (new upgrade path changes detector
output) and `TRADE_TAPE_CACHE_VERSION` (label output changes).

**Tests.**
- Python: differential match at `10000×` scale (Spot 10Y/30Y, uniform per-leg
  spread) → `SPREADOVER_CURVE`; no-per-leg-spread curve/fly whose package PTS
  matches a synthetic level index → composite; differential outside 5bp → stays
  `CURVE`/`FLY`; missing level → stays `CURVE`/`FLY`; distinct per-leg spreads
  still upgrade without a level index (Phase-1 unchanged).
- Python label: composite `package_type` → label ends `…SPREADOVER_CURVE PHYS`.
- Frontend: badge/label show `SPREADOVER_CURVE` (no downgrade); confidence score
  unchanged; `packageConfidence.test.ts` updated for the removed override.

---

## Cross-cutting

- **Verification.** Python fast gate green; frontend jest + `tsc` green; Chrome
  MCP against the dev server (reads prod DB) to confirm the `LEVERED` badge on a
  known 10y1y and `SPREADOVER_CURVE` on the Spot 10Y/30Y once re-enriched. NOTE:
  the classification/label changes only surface after a re-enrichment — do NOT
  run the destructive prod backfill; verify via faithful unit tests + a local
  re-enrichment if one is stood up. See [[reference_dashboard_worktree_verify]].
- **Sequencing.** Enh 1 is small and independent — land it first. Enh 2b is the
  larger piece; Part A (detection) and Part B (display) land together so the DB
  and UI never disagree.
- **Out of scope.** The dedicated spread-series level source; SPREADOVER
  detection for non-benchmark/IMM-dated tenors; any change to the confidence
  *scoring* logic (only the type-override is removed).
