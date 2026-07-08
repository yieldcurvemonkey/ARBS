# Matched-Maturity (MMS) Package Propagation — Design

**Date:** 2026-07-08
**Status:** Design (pending review)
**Area:** SDRUtils USD-swaps SDR tape — package detection, tape labels, ingest, dashboard

## 1. Problem

The matched-maturity detector (`SDRUtils/packages/mms.py`) tags swaps whose
expiration date exactly ties a US Treasury coupon maturity — a swap-spread /
asset-swap where the UST cash leg defines the maturity. Today it tags **only
outright swaps**. Multi-leg packages (CURVE / FLY / PKG-N) never surface the
MMS flag or the UST CUSIP/alias, even when every leg ties a bond.

Two root causes:

1. **The wipe.** `detect_mms_trades_df` runs *after* the fly/curve detectors
   with `only_tag_outrights=True`. Packaged legs fail the outright mask, so the
   `excluded = raw_matched & ~can_tag` branch (`mms.py:180-182`) **resets
   `matched_ust_maturity=False`** on them. That single boolean drives everything
   downstream (`special_tenor_type`, the MMS chip, `tape_label_ust_alias`, the
   `MATCHED_MATURITY_CURVE/FLY` promotion), so the existing composite promotion
   is effectively dead for real packages.
2. **PTP bypass.** `group_by_ptp` pulls PTP-grouped packages out of the frame
   *before* the detectors run and concatenates them back *after*, so PKG-N /
   PTP-classified CURVE/FLY legs never pass through `detect_mms` at all.

### Empirical scale (43 cached classified days, 2026-05-11 … 2026-07-06)

Recomputing per-leg matched-maturity over the real cached tapes:

| Metric | Count |
|---|---|
| All-legs-MMS multi-leg packages | 527 |
| …currently package-flagged | **0** |
| Partial-MMS packages | 1,206 |
| Packages where the coincidence guard fired | 3,328 |
| **Guard violations** (gated-out leg that was NOT clean-tenor/forward/short) | **0** |

Zero guard violations across 3,328 coincidence packages: the clean-tenor
exclusion is an airtight coincidence guard. Preserving it verbatim guarantees
the fix cannot false-positive on coincidental spot-start-on-UST trades.

## 2. Taxonomy (why the gates are load-bearing)

Three swap-vs-UST "asset swap" flavors, separated by **tenor** (see
`reference_asset_swap_taxonomy` memory / Clarus blogs):

| Flavor | Economic definition | Swap tenor | Detector | `package_type` |
|---|---|---|---|---|
| **Spreadover** | clean-tenor spot swap vs *nearest on-the-run* UST — "optical" 5Y-vs-5Y, maturities do **not** exactly tie | clean | `detect_spreadovers` | `SPREADOVER` |
| **Matched-maturity** | swap maturity **exactly ties** a specific UST coupon date → **broken tenor** (e.g. 9Y10M) | broken | `detect_mms` | `MATCHED_MATURITY` |
| **Invoice** | swap effective = CME future delivery, maturity = future CTD | future-driven | `detect_invoice_swaps` | `INVOICE*` |

The **clean-tenor exclusion is the MMS-vs-Spreadover boundary**. A clean 10Y
spot swap landing on the on-the-run UST is a *Spreadover* (optical), never MMS —
this is the "coincidental spot-start" edge case. MMS is intrinsically
broken-tenor + exact-calendar-date tie. This gate, the exact-date-equality join,
the spot-only gate (forward + IMM excluded), and the short-dated confidence
downgrade are all **preserved unchanged**.

## 3. Model: per-leg truth, package rollups

`matched_ust_maturity` is one **per-leg** boolean. Every package behavior is a
rollup of it. Three cases:

- **(A) Homogeneous** — every leg ties the *same* bond (clips of one asset swap,
  e.g. a PKG-2/PKG-7 on cusip 91282CPZ8 maturing 2036-02-15). → package MMS flag,
  single alias `0236`.
- **(B) Heterogeneous all-MMS** — every leg ties its *own, different* bond = a
  matched-maturity CURVE/FLY (Clarus "SpreadCurve/SpreadFly"). → package MMS flag,
  joined alias `0236/0246`; CURVE→`MATCHED_MATURITY_CURVE`, FLY→`MATCHED_MATURITY_FLY`,
  PKG-N stays PKG-N.
- **(C) Partial** — some legs tie a bond, others are clean-tenor hedges / unmatched.
  → per-leg annotations only; package stays its base type (matches existing
  `test_partial_mms_does_not_upgrade_curve` semantics).

## 4. Locked decisions

| # | Decision | Choice |
|---|---|---|
| Q1 | Delivery scope | **Full stack**: detection → labels → ingest schema → prod backfill → dashboard |
| Q2 | PKG-N matched-maturity type | **Keep `PKG-N`**; MMS is an orthogonal flag + alias (no `MATCHED_MATURITY_PKG-N` composite) |
| Q3 | Package-level flag rule | **A + B**: package is MMS when *every* leg ties its own UST (same or different bond); partial = per-leg only |
| — | Rollout | **Autonomous incl. prod backfill + deploy**, with one explicit go/no-go gate immediately before the destructive delete+rewrite backfill |
| — | Spot-only boundary | **Unchanged** — IMM-start MMS remains excluded (false-positive shield); separate task if ever wanted |

## 5. Detection design (`mms.py`, `usd_swaps.py`)

### 5a. Unbundle the wipe (`mms.py:177-182`)

Separate "is this really MMS" (coincidence gates — apply to every leg) from
"don't clobber package identity" (outright-only):

```python
raw_matched = out["matched_ust_maturity"].fillna(False).values
# MMS-ness gates (coincidence guards) apply to EVERY candidate leg, packaged or not:
is_mms_leg  = raw_matched & spot_start_mask & ~is_clean_tenor
# outright_mask governs ONLY whether we overwrite package identity:
can_tag     = is_mms_leg & outright_mask
# Clear the flag ONLY on legs that fail the real MMS gates — not merely for being packaged:
excluded    = raw_matched & ~is_mms_leg
if excluded.any():
    out.loc[excluded, "matched_ust_maturity"] = False
```

**Invariant:** for outright legs `is_mms_leg == can_tag`, so outright behavior
is byte-identical. New effect: a broken-tenor spot packaged leg retains the flag
(and now gets a confidence); a clean-tenor / forward packaged leg is still wiped.
Numpy-array ops only — no in-place `&=` (respects the CoW gotcha at `mms.py:334`).

### 5b. Feed PTP legs through the matcher (`_run_all_detectors`)

Immediately after `classify_ptp_groups(ptp_df)`:

```python
ptp_df = detect_mms_trades_df(ptp_df)   # legs already PKG-N/CURVE/FLY → outright_mask False → flag only, no clobber
```

Gives PTP legs `matched_ust_maturity` + confidence + `ust_*` fields without
touching their `package_type`/`package_id`/`package_legs`.

### 5c. Full-scope idempotent rollup (new `_rollup_matched_maturity_packages`, post-concat)

Runs **after** `pd.concat([ptp_df, df])`, before `solve_all_opa_signs`. Groups by
`package_id` (≥2 legs); for each package where **all** legs are `matched_ust_maturity`:

- base `CURVE`/`FLY` → `MATCHED_MATURITY_CURVE`/`_FLY` (also mirror `trade_type`) —
  covers PTP-grouped and any DV01-detected package the earlier pass missed;
- `PKG-N` → **type unchanged** (Q2); the package-level MMS surfaces via the
  per-leg `special_tenor_type` rollup at ingest;
- **skip** packages already `SPREADOVER_*`, `MATCHED_MATURITY_*`, `BASIS_*`, or
  `INVOICE*` — preserves SPREADOVER-wins and INVOICE-wins precedence.

Idempotent (skips already-composite), so it coexists with the untouched
`detect_sub_package_curve_fly` (whose direct behavior is pinned by
`test_sub_package_detection.py`): that pass still promotes non-PTP CURVE/FLY
early, and this rollup is a full-scope superset that guarantees coverage of
everything it misses (PTP packages + PKG-N package-level signal) while being a
no-op over anything already promoted.

**Precedence** is preserved on two axes: SPREADOVER > MMS (rollup skips
`SPREADOVER_*`); INVOICE > MMS (invoice legs already resolve to
`special_tenor_type='INVOICE_SWAP'` via `SPECIAL_TENOR_PRIORITY`, outranking
`MATCHED_MATURITY`, so the label MMS-flag guard never fires; rollup skips
`INVOICE*` types).

**Short-dated (<1Y) ties** (e.g. clips tying a T-bill): preserved as-is — per-leg
low confidence, package confidence = worst leg. No new exclusion gate. *(Review
point — see §11.)*

**Determinism under incremental re-detection** (`usd_swaps.py:1770-1827`, ±10min
neighborhoods): 5a/5b/5c are pure functions of per-leg data + the UST reference
snapshot; packages cluster within seconds, so a 10-min window always contains a
package's full leg set.

Bump `DETECTION_CACHE_VERSION` (detector output changes).
`_resolve_special_tenor_priority` already turns surviving per-leg
`matched_ust_maturity` into `special_tenor_type='MATCHED_MATURITY'` — no change.

## 6. Label design (`analytics/trade_tape.py`)

- **Package joined alias** — in `_enrich_packages`, add `package_ust_aliases`:
  per-leg MMYY (`_ust_maturity_alias`) in tenor-sorted order, **collapse-if-identical**
  → case A `0236`, case B `0236/0246`.
- **Package-scope alias slot** — in `_label_for_row` `use_ust_alias` branch, at
  package scope prefer `package_ust_aliases` over the single-row helper. For a
  `PKG-N` MMS package set `tenors = f"{alias} {pkg_type}"` (→ `…Spot 0236 PKG-3 MMS PHYS`)
  so both the alias and the structure token render; the non-alias PKG-N label is
  unchanged. CURVE/FLY composites already render structure `CURVE`/`FLY`.
- **Per-leg alias column** — add `leg_tape_label_ust_alias`
  (`_label_for_row(leg_scope=True, use_ust_alias=True)`), whitespace-collapsed
  like its siblings. This is how case-C per-leg annotations surface.
- Existing MMS-flag gate (`special_tenor_type=='MATCHED_MATURITY'`, non-invoice)
  and single-date fallback (NaT → raw tenor) are unchanged.

Bump `TRADE_TAPE_CACHE_VERSION`.

## 7. Ingest + schema (`ingest_usdswaps_tape.py`, `_tape_schema_v2.py`)

Additive `ADD COLUMN IF NOT EXISTS`:

- **legs_v2**: `matched_ust_maturity` BOOL, `special_tenor_type` TEXT,
  `ust_cusip` TEXT, `tape_label_ust_alias` TEXT, `leg_tape_label_ust_alias` TEXT,
  `matched_ust_maturity_trade_confidence` TEXT. (Register in `LEG_COLUMNS` +
  bool/text coercion loops.)
- **packages_v2**: `special_tenor_type` TEXT (`_consistent_str`),
  `tape_label_ust_alias` TEXT (longest-picker à la `_rep_tape_label`),
  `is_matched_maturity_all` BOOL (`_all` over legs). `package_type` already
  carries `MATCHED_MATURITY_CURVE/FLY`.

Package-level MMS predicate = `package_type LIKE 'MATCHED_MATURITY%'` **OR**
`special_tenor_type = 'MATCHED_MATURITY'` — covers CURVE/FLY (composite) and
PKG-N (special_tenor). Leg columns auto-surface via `jsonb_agg(to_jsonb(l))`;
new package columns hand-added to `DISPLAY_VIEW_V2` SELECT.

## 8. Dashboard (`usd-swaps-tape-v2`)

- `PACKAGE_LABELS`/`PACKAGE_BADGE_TONES` (`columns.helpers.ts`): add
  `MATCHED_MATURITY`→"MMS", `_CURVE`→"MMS Curve", `_FLY`→"MMS Fly" (reuse the
  "MMS" alias already in the mobile Package filter).
- `displayTapeLabel`: prefer `tape_label_ust_alias` when present (renders `0236`);
  add an MMYY token to `TENOR_SEGMENT_RE` bolding, scoped so it doesn't match years.
- Widen the leg-tooltip gate (`pkgLegsLines`, currently `PKG-`-only) to include
  CURVE / FLY / `MATCHED_MATURITY*`, rendering per-leg lines from
  `leg_tape_label_ust_alias`.
- (Optional) add `MATCHED_MATURITY*` to `formatReportedLvl` `isMultiLeg` for
  per-leg rates. *(Review point — §11.)*
- Verify locally via chrome-MCP (localhost:3000) before deploy.

## 9. Rollout (autonomous, gated)

1. Bump `DETECTION_CACHE_VERSION` + `TRADE_TAPE_CACHE_VERSION`.
2. `ensure_schema` (DDL migration) on prod.
3. **Go/no-go gate** → `run_usdswaps_pipeline` backfill (delete+rewrite remote
   prod tape).
4. Deploy dashboard.

## 10. Testing (TDD, `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`)

Regression guards **first**:

- Clean-tenor spot leg inside a package must **not** be tagged MMS (coincidence guard).
- Forward packaged leg must **not** be tagged MMS.
- Outright behavior byte-identical (before/after unbundle).

Then, using real fixtures mined from the cached tapes:

| Case | Real example | Assertion |
|---|---|---|
| A same-bond PKG-N | cusip 91282CPZ8 @ 2036-02-15 clips (PKG-2 5/12; PKG-7 5/13) | package MMS, alias `0236`, type stays `PKG-N` |
| A same-bond 30Y | cusip 912810US5 @ 2056-02-15 (PKG-3 5/12) | package MMS, alias `0256` |
| B curve diff bonds | 10Y@2036-05-15 (91282CQQ7) + 20Y@2046-05-15 (912810UV8) | `MATCHED_MATURITY_CURVE`, alias `0536/0546` |
| B curve short diff | 4Y@2030-04-30 (91282CMZ1) + 4Y@2030-11-30 (91282CPN5) | `MATCHED_MATURITY_CURVE`, alias `0430/1130` |
| B PKG-3 diff bonds | 17.5/19.5/19.3y @ 2043-11-15 / 2045-08-15 / 2045-11-15 | all-MMS PKG-3, stays PKG-3, joined alias |
| C partial | 3Y@2.94y (clean, excluded) + 10Y@9.86y@2036-05-15 | stays CURVE; only 10Y leg per-leg annotated |
| coincidence | any of 3,328 clean-tenor gated-out legs | `matched_ust_maturity` False |

Plus: PTP leg gets the flag; PTP all-MMS CURVE→composite; label cases A/B/C +
NaT-expiration fallback + non-MMS invariant (`tape_label == tape_label_ust_alias`);
existing `test_sub_package_detection.py`, `test_trade_tape_mms_secondary_label.py`,
`test_mms_imm_to_imm_exclusion.py` stay green.

## 11. Resolved review points

1. **Short-dated bill packages** — clips of ~0.2y swaps tying a T-bill get
   package-MMS (low confidence). **Resolved: keep** — no new exclusion gate;
   confidence (worst-leg) carries the caveat and the dashboard can filter on it.
2. **Per-leg rates in Reported LvL** — **Resolved: no work needed.**
   `MATCHED_MATURITY_CURVE/FLY` already satisfy `formatReportedLvl`'s
   `kind.endsWith('_CURVE')` / `('_FLY')` branch, so per-leg rates render
   automatically. Base `MATCHED_MATURITY` and `PKG-N` keep `weighted_fixed_rate`
   (single economic level).

## 12. Edge-case guarantees (the fragility contract)

- Clean-tenor gate, exact-date join, spot-only gate, IMM guard, short-dated
  downgrade: **all unchanged**.
- Unbundle preserves outright behavior byte-identical.
- Empirically 0 coincidence-guard violations over 43 days / 3,328 packages.
- Precedence SPREADOVER > MMS and INVOICE > MMS preserved.
- No context-dependent gate relaxation (a near-clean leg is never "promoted" to
  MMS because a sibling leg matched).
