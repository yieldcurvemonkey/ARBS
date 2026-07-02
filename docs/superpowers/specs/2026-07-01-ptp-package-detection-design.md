# PTP-Based Package Detection & OPA Sign Solver

**Date:** 2026-07-01
**Status:** Draft — **Revision 2026-07-02:** audit + remediation sync (commits
d5e4c618, 3929411a, 9d0053b6); all sections below reflect shipped code.
**Audience:** Global macro PM exploring edge using SDR data

## Problem

The current package detection pipeline runs 8 independent DV01-based detectors
(fly, curve, basis, invoice, MAC, MMS, spreadover, sub-package upgrade) that
operate globally across all legs. This produces three classes of error:

1. **Split packages** — Legs sharing the same PTP and execution timestamp are
   assigned to separate `package_id` groups. Example: a 12-leg butterfly block
   (4 sub-flies × 3 legs) shows as 4 independent FLY packages instead of one
   PKG-12.

2. **Mis-classified structures** — An 8-leg MAC ladder (2Y–30Y) gets carved
   into 2 curves + 4 outrights by eager curve detection, when the whole thing
   is one atomic package transaction.

3. **No OPA direction inference** — The pipeline stores `other_payment_amount`
   as an unsigned magnitude. There is no sign-solving to determine which legs
   the customer paid vs received, and no tieout between Σ(signed OPA) and
   the reported PTP.

## Solution: Hybrid PTP-Scoped Detection

### Architecture

```
Raw classified legs
  │
  ▼
[PTP Pre-Grouper]           ← NEW: partition by (exec_ts±5s, PTP, UPI, platform, pkg_ind=True)
  │                            Output: ptp_groups (≥2 legs) + non_ptp_legs
  ├─ ptp_groups ──────────┐
  │                       ▼
  │              [Scoped Structure Classifier]  ← NEW: holistic pattern match per group
  │                       │
  │                       ▼
  │              [OPA Sign Solver]              ← NEW: 2^N brute-force + economic constraint
  │                       │
  └─ non_ptp_legs ──┐     │
                    ▼     │
          [Existing global detectors]           ← UNCHANGED: fly, curve, mms, etc.
                    │     │
                    ▼     ▼
               [Merge results]
                    │
                    ▼
               [Tape enrichment + DB write]
```

### Module 1: PTP Pre-Grouper

**File:** `SDRUtils/packages/ptp_grouper.py`

**Function:** `group_by_ptp(df, *, time_tolerance_seconds=5) → (ptp_groups_df, non_ptp_df)`

**Grouping key:** All constraints must match:

| Field | Constraint |
|-------|-----------|
| `execution_timestamp` | Within ±`time_tolerance_seconds` (sort-and-merge, not rounding); legs with NaT (unparseable) timestamp are excluded from candidates and flow to the global pool |
| `package_transaction_price` | Exact match, must be finite and > 0; parsed via `numeric_like` — comma/dollar/parenthesised-negative tolerant (plain `pd.to_numeric` turns `'88,100'` into NaN, silently dropping all USD-amount packages ≥ $1,000) |
| `package_indicator` | Must be truthy — real SDR data delivers `True`, `1`, `"1"`, or the float-string `"1.0"` (NaN-padded bool columns); the grouper's truthy set is `{"true","t","1","1.0","yes"}` |
| `Unique Product Identifier` | Exact match |
| `Platform identifier` | Exact match |

**Parsing:** All numeric SDR fields in the grouper (PTP, OPA, rates, tenors,
PV01) are coerced via `numeric_like` (defined in
[`SDRUtils/packages/ptp_grouper.py`](packages/ptp_grouper.py)), which handles
thousands separators, `$`, parenthesised negatives, and blank-likes. Mirrors
`_coerce_numeric_like` in `usd_swaps.py`.

**Time clustering:** Clusters run within each (PTP, UPI, platform) partition
rather than globally. A global pass would let an unrelated trade sitting between
two same-key legs chain them into one group even when their timestamps exceed
the tolerance.

**Minimum group size:** 2 legs. Single legs with `package_indicator=True` stay in
the global pool for existing detector handling.

**Output columns:**

| Column | Type | Description |
|--------|------|-------------|
| `ptp_group_id` | str | `"PTP_{min_trade_id}"` — unique per group |
| `ptp_group_size` | int | Leg count in the PTP group; None for non-PTP legs |

Legs not matching any PTP group get `ptp_group_id = None` and flow to existing
global detectors unchanged.

### Module 2: Scoped Structure Classifier

**File:** `SDRUtils/packages/ptp_grouper.py` (same module)

**Function:** `classify_ptp_group(group_df) → group_df` (annotates in place)

For each PTP group, classify the structure **holistically** — the entire group
must fit the pattern, no carving into sub-structures:

| Leg count | Pattern | Classification |
|-----------|---------|----------------|
| 2 | DV01 balanced, **2 distinct tenor buckets** (rounded to 0.1Y); same-tenor pair → PKG-2 | CURVE |
| 3 | **3 distinct tenor buckets** (rounded to 0.1Y), belly ≈ 2× wings (±15%) | FLY |
| N ≥ 4, all form K flies | K × (belly ≈ 2× wings), same tenors | PKG-N (sub-fly annotations) |
| N ≥ 4, otherwise | Any other pattern | PKG-N |

Sub-fly detection prechecks that the group has exactly 3 DISTINCT tenor buckets after rounding to 0.1Y (matching the bucketing itself — raw-value distinctness would wrongly reject e.g. {2.01, 2.04, 5, 10}); legs within each tenor bucket are then paired across buckets by ascending `(pv01, fixed_rate)` so equal-DV01 sub-flies at different rates never cross-pair.

**PKG-N is the default.** FLY/CURVE only when the _entire_ group matches that
single pattern. No partial matching.

**Sub-structure annotations** (metadata, not primary type):
- `ptp_sub_structures` (JSONB): Array of detected sub-patterns within the group.
  Example: `[{"type": "FLY", "legs": ["id1","id2","id3"], "belly_dv01": 75000}]`
  Empty array when no sub-patterns detected (e.g., MAC ladder).

**Output columns:**

| Column | Type | Description |
|--------|------|-------------|
| `package_type` | str | `FLY`, `CURVE`, or `PKG-N` |
| `package_id` | str | Same as `ptp_group_id` |
| `package_legs` | list[str] | All trade IDs in the PTP group |
| `ptp_sub_structures` | JSONB | Sub-pattern annotations |

### Module 3: OPA Sign Solver

**File:** `SDRUtils/packages/opa_sign_solver.py`

**Function:** `solve_opa_signs(group_df, ptp_value) → dict`

**Algorithm:**

**PTP notation gate:** When `package_transaction_price_notation` (Part 43) is
present and not 1 (monetary), the PTP is a price/decimal value (e.g.
`9.9999999999`, notation 3), not a dollar amount. Grouping still occurs — the
package integrity signal is real — but the OPA dollar tieout has no meaning.
These groups report `opa_sign_confidence = UNRESOLVED`, all per-leg `opa_sign`
remain null, and the notation is persisted as `ptp_price_notation`. Notation 1
(or absent) proceeds to the solve.

For each PTP group with finite monetary PTP:

1. Extract OPA magnitudes: `[opa_1, ..., opa_N]` (all positive; null OPA legs
   treated as 0 during solve but their `opa_sign` stays null in the output)
2. **Unconstrained solve:** Exact enumeration over all 2^N sign assignments,
   minimize `min(|Σ(s_i × opa_i) - PTP|, |Σ(s_i × opa_i) + PTP|)`.
   Implementation: vectorized NumPy sweep for N ≤ 16; meet-in-the-middle
   (two 2^⌊N/2⌋ half-enumerations + binary search) for 16 < N ≤ 24 — both
   exact, with scale-aware tie tolerance. Greedy heuristic (step 4) for N > 24.
3. **Economically-constrained solve:** Group legs by
   `(round(fixed_rate, 6), round(tenor_years, 1))` — legs with identical
   rate to 0.01bp and tenor to 0.1Y must share the same sign. Exact solve
   over 2^K group-level assignments where K = number of distinct rate/tenor
   groups. For the 12-leg fly, K=6 (2 rates × 3 tenors) vs N=12 unconstrained.
4. Report both solutions.

**Fallback for N > 24:** Greedy heuristic — sort by OPA descending, assign signs
to minimize running residual vs PTP. O(N log N).

**Confidence tiers:**

| Tier | Residual | Interpretation |
|------|----------|----------------|
| EXACT | < $100 | Signs highly reliable |
| TIGHT | < $1,000 | Reliable, minor rounding/fee |
| LOOSE | < $50,000 | Directional, significant dealer spread |
| UNRESOLVED | ≥ $50,000 | Cannot determine direction |

Tier is based on the **unconstrained** solution's residual.

**Output columns on `arbs_usd_swap_tape_legs_v2`:**

| Column | Type | Description |
|--------|------|-------------|
| `opa_sign` | smallint | +1 / -1 / null; null when `other_payment_amount` is null for that leg, or when the group is UNRESOLVED (non-monetary PTP notation) |
| `opa_signed_amount` | numeric | `opa_sign × other_payment_amount` |

**Output columns on `arbs_usd_swap_tape_packages_v2`:**

| Column | Type | Description |
|--------|------|-------------|
| `ptp_group_id` | text | Links to child legs' ptp_group_id |
| `ptp_group_size` | int | Leg count in PTP group |
| `opa_signed_net` | numeric | Best Σ(signed OPA) |
| `opa_ptp_residual` | numeric | Gap to PTP (dollars) |
| `opa_sign_confidence` | text | EXACT / TIGHT / LOOSE / UNRESOLVED |
| `opa_constrained_net` | numeric | Best economically-constrained Σ |
| `opa_constrained_residual` | numeric | Constrained gap to PTP |
| `dealer_spread_est` | numeric | Unconstrained residual (dollars) |
| `dealer_spread_bps` | numeric | Residual / total_dv01 (true bp; residual in $, total_dv01 in $/bp). Examples: 12-leg fly $216.29 on ~$803K DV01 → ~0.0003 bp; 8-leg MAC $10,999 on ~$54.7K DV01 → ~0.20 bp. |
| `ptp_price_notation` | smallint | Part 43 price notation code persisted from the PTP field (1 = monetary; others = UNRESOLVED tieout) |
| `ptp_sub_structures` | jsonb | Sub-pattern annotations |

### Module 4: Orchestration Changes

**File:** `SDRUtils/products/usd/usd_swaps.py` — modify `_run_all_detectors()`

Current flow:
```python
def _run_all_detectors(df, ...):
    df = detect_invoice_swaps(df, ...)
    df = detect_fly_trades_df(df, ...)
    df = detect_curve_trades_df(df, ...)
    # ... remaining detectors
    return df
```

New flow:
```python
def _run_all_detectors(df, ...):
    # Phase 0: PTP pre-grouping
    ptp_df, non_ptp_df = group_by_ptp(df, time_tolerance_seconds=5)
    
    # Phase 1: Classify PTP groups holistically
    if not ptp_df.empty:
        ptp_df = classify_ptp_groups(ptp_df)
    
    # Phase 2: Existing detectors on non-PTP legs (unchanged)
    non_ptp_df = detect_invoice_swaps(non_ptp_df, ...)
    non_ptp_df = detect_fly_trades_df(non_ptp_df, ...)
    non_ptp_df = detect_curve_trades_df(non_ptp_df, ...)
    # ... remaining detectors
    
    # Phase 3: Merge
    df = pd.concat([ptp_df, non_ptp_df], ignore_index=True)
    
    # Phase 4: OPA sign solver on all PTP groups
    df = solve_all_opa_signs(df)
    
    return df
```

### Module 5: Dashboard Enhancements

**Files:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`

#### 5a. Super-package grouping

When rows share `ptp_group_id`, render a collapsible parent row:

```
▸ PKG-8  19:03:07  IMM_U2026 2Y/.../30Y  PTP: $1,537,032  [TIGHT]  Spread: $10,999 (~0.20bp)
  └─ 8 legs expandable below
```

For packages with sub-structures:
```
▸ PKG-12  14:30:59  IMM_U2026 2Y/5Y/10Y  PTP: $88,100  [EXACT]  Spread: $216 (~0.0003bp)
  ├─ Sub-FLY (A,sm): 2Y/5Y/10Y  75K DV01
  ├─ Sub-FLY (A,lg): 2Y/5Y/10Y  130K DV01
  ├─ Sub-FLY (B,lg): 2Y/5Y/10Y  130K DV01
  └─ Sub-FLY (B,sm): 2Y/5Y/10Y  75K DV01
```

Implementation: new `PtpPackageRow` component wrapping existing `LegsSubTable`.
Parent row reads from packages table; expansion renders legs grouped by
`ptp_sub_structures` if present, flat list otherwise.

#### 5b. OPA tieout column

New column on the parent package row (and in the `LegsSubTable` summary):

| Display | Source |
|---------|--------|
| `Σ OPA: +$87,884` | `opa_signed_net` |
| `PTP: $88,100` | `package_transaction_price` |
| `Gap: $216` | `opa_ptp_residual` |
| `EXACT` (green badge) | `opa_sign_confidence` |

#### 5c. Sign direction badges

In the expanded legs table, OPA column shows:
- `+$677,255` (green up-arrow) when `opa_sign = +1`
- `−$314,119` (red down-arrow) when `opa_sign = -1`
- `?$13,268` (gray question mark) when `opa_sign = null` (UNRESOLVED)

#### 5d. Dealer spread estimate

Parent row header shows:
```
PTP: $88,100  |  Spread: $216 (~0.0003bp)
```

#### 5e. Filter and sort

New filter options in the tape table toolbar:
- **Confidence filter:** Dropdown multi-select for EXACT / TIGHT / LOOSE / UNRESOLVED
- **Sort by dealer spread:** Ascending/descending sort on `dealer_spread_bps`
- **PTP package filter:** Toggle to show only PTP-grouped packages (hides outrights)

### Schema Changes

**`arbs_usd_swap_tape_legs_v2` — new columns:**

```sql
ALTER TABLE arbs_usd_swap_tape_legs_v2
  ADD COLUMN ptp_group_id text,
  ADD COLUMN opa_sign smallint,
  ADD COLUMN opa_signed_amount numeric;
```

**`arbs_usd_swap_tape_packages_v2` — new columns:**

```sql
ALTER TABLE arbs_usd_swap_tape_packages_v2
  ADD COLUMN ptp_group_id text,
  ADD COLUMN ptp_group_size integer,
  ADD COLUMN opa_signed_net numeric,
  ADD COLUMN opa_ptp_residual numeric,
  ADD COLUMN opa_sign_confidence text,
  ADD COLUMN opa_constrained_net numeric,
  ADD COLUMN opa_constrained_residual numeric,
  ADD COLUMN dealer_spread_est numeric,
  ADD COLUMN dealer_spread_bps numeric,
  ADD COLUMN ptp_price_notation smallint,
  ADD COLUMN ptp_sub_structures jsonb;
```

Display view updated to expose new columns (`ptp_price_notation` included;
constrained-solve columns `opa_constrained_net` / `opa_constrained_residual`
are table-only).

### Testing

1. **12-leg fly case** (2026-06-25): Verify all 12 legs grouped under one
   `ptp_group_id`, classified as PKG-12 with 4 sub-fly annotations, sign
   solver produces EXACT confidence with ~$216 residual.

2. **8-leg MAC ladder** (2026-07-01): Verify all 8 legs grouped as PKG-8,
   no sub-structures, sign solver produces LOOSE with ~$11K residual.

3. **Standard 3-leg fly** (no PTP group): Verify existing fly detection is
   unchanged — leg flows through global detectors, gets FLY classification.

4. **2-leg curve with PTP**: Verify PTP pre-grouper catches it, classifies
   as CURVE (entire group fits pattern).

5. **Edge: N > 24 legs**: Verify greedy fallback produces a result.

6. **Edge: PTP = null but package_indicator = True**: Verify leg stays in
   global pool for existing spreadover/MMS detection.

7. **Regression**: All existing fly/curve/basis tests pass unchanged on
   non-PTP legs.

### Not in scope

- Modifying existing fly/curve/basis detectors
- Historical backfill of OPA signs (run on next tape rebuild)
- Cross-currency PTP grouping (future: requires currency normalization)
- Real-time sign solving in the service loop (batch only initially)

### Accepted behaviors

- **PTP groups bypass holistic detection:** Legs grouped by PTP (≥ 2 legs) skip
  invoice, MMS, MAC, and spreadover detection entirely — a 2-leg PTP pair that
  would previously have been tagged INVOICE now comes out CURVE or PKG-2. This
  is the spec's intent (holistic classification) and a deliberate behavior
  change on real tapes; bear it in mind when eyeballing package labels.
- **Non-monetary PTP grouping:** Price-notation PTP clusters (e.g.
  `9.9999999999`, Part 43 notation 3) still form groups because the SDR fields
  genuinely match; their OPA tieout is UNRESOLVED and per-leg `opa_sign` stays
  null. If mega-groups (PKG-50+) from compression blobs prove noisy, a future
  pass can optionally gate grouping on notation 1 only.
- **Null-OPA legs in solved groups:** A leg with null `other_payment_amount`
  inside a monetary-PTP group retains null `opa_sign`; it is treated as 0 OPA
  during solving and does not perturb the tieout. DB consumers should read
  `opa_sign` only where `other_payment_amount` is non-null.
