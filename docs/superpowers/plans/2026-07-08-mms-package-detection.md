# Matched-Maturity (MMS) Package Propagation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Propagate matched-maturity (MMS) detection from outright swaps into multi-leg packages (CURVE/FLY/PKG-N) so the tape surfaces the MMS flag + UST MMYY alias per the design spec `docs/superpowers/specs/2026-07-08-mms-package-detection-design.md`.

**Architecture:** Per-leg `matched_ust_maturity` is the single source of truth. Fix the two blockers (the outright-mask wipe in `mms.py`; the PTP bypass in `_run_all_detectors`), add a full-scope idempotent package rollup, then surface it through labels → ingest schema → dashboard, and finally backfill prod + deploy.

**Tech Stack:** Python 3 / pandas (detection + labels + ingest), PostgreSQL (Supabase tape), TypeScript / React / Jest (dashboard). Tests run under `conda run -n stir`.

## Global Constraints

- Run ALL Python/pytest via `conda run -n stir python -m pytest ...` (repo requires the `stir` conda env).
- Fast gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.
- **Do NOT touch the coincidence gates** — `spot_start_mask`, `is_clean_tenor` (`_STANDARD_TENORS` ±0.1y), the exact-date-equality join, the IMM guard, the short-dated confidence downgrade. These are unchanged. The clean-tenor gate is the MMS-vs-Spreadover boundary; loosening it re-introduces the coincidental-spot false positives the spec forbids.
- Preserve precedence: SPREADOVER > MMS; INVOICE > MMS. The rollup skips `SPREADOVER_*`, `MATCHED_MATURITY_*`, `INVOICE*`, `BASIS_*` package types.
- MMYY alias format is **numeric**: `f"{month:02d}{year % 100:02d}"` → Feb 2036 = `"0236"`, May 2046 = `"0546"`. Not alphabetic.
- On ANY detector-output change bump `DETECTION_CACHE_VERSION` (`SDRUtils/products/usd/usd_swaps.py`); on ANY tape-enrichment-output change bump `TRADE_TAPE_CACHE_VERSION` (`SDRUtils/analytics/trade_tape.py`). Per `SDRUtils/CLAUDE.md`, both are mandatory when detector columns change.
- Three-places rule for a new persisted tape column: (1) the `LEG_COLUMNS`/`PACKAGE_COLUMNS` tuple, (2) the coercion loop / rec-dict, (3) the schema DDL (`CREATE` + `ADD COLUMN IF NOT EXISTS`). Missing any one silently drops the column.
- Dashboard jest: invoke via `npm test` (NOT bare `npx jest`) so ESM mocks load. New TS fields go on the `usd-swaps-tape-v2` types, never the shared `sofr-swaps-tape` base.
- Real fixtures (mined from cached tapes; use these exact CUSIP/maturity pairs — do NOT invent):
  - Case A same-bond: `91282CPZ8` @ 2036-02-15 → `0236`; `912810US5` @ 2056-02-15 → `0256`.
  - Case B curve (diff bonds): 10Y `91282CQQ7` @ 2036-05-15 → `0536` + 20Y `912810UV8` @ 2046-05-15 → `0546`.
  - Case B short: `91282CMZ1` @ 2030-04-30 → `0430` + `91282CPN5` @ 2030-11-30 → `1130`.
  - Case C partial: 3Y clean-tenor @ 2029-06-15 `91282CQV6` (excluded) + 10Y `91282CQQ7` @ 2036-05-15 → `0536` (MMS).

---

## Phase 1 — Detection (Python)

### Task 1: Unbundle the outright-mask wipe in `mms.py`

**Files:**
- Modify: `SDRUtils/packages/mms.py:178-182` (inside `detect_mms_trades_df`)
- Test: `tests/test_mms_package_propagation.py` (new)

**Interfaces:**
- Consumes: `detect_mms_trades_df(df, *, only_tag_outrights=True, ...)`, `_match_swaps_to_ust_by_maturity(df, ...)` from `SDRUtils.packages.mms`; patch target `SDRUtils.packages.mms._load_ust_reference_data`.
- Produces: after this task, a broken-tenor spot leg with `package_type` != `OUTRIGHT` retains `matched_ust_maturity=True`; a clean-tenor/forward leg is still wiped to `False`; outright behavior is unchanged.

- [ ] **Step 1: Write the failing test** — create `tests/test_mms_package_propagation.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from SDRUtils.packages.mms import detect_mms_trades_df

# Real mined UST coupons (design spec §10 / Global Constraints).
_UST = pd.DataFrame([
    {"cusip": "91282CQQ7", "maturity_date": pd.Timestamp("2036-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "10-Year",
     "security_type": "Treasury Note", "coupon": 4.0, "original_security_term": "10-Year"},
    {"cusip": "912810UV8", "maturity_date": pd.Timestamp("2046-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "20-Year",
     "security_type": "Treasury Bond", "coupon": 4.25, "original_security_term": "20-Year"},
    {"cusip": "91282CQV6", "maturity_date": pd.Timestamp("2029-06-15").date(),
     "issue_date": pd.Timestamp("2026-06-15").date(), "oi": "3-Year",
     "security_type": "Treasury Note", "coupon": 3.75, "original_security_term": "3-Year"},
])


@pytest.fixture
def fake_ust():
    with patch("SDRUtils.packages.mms._load_ust_reference_data", return_value=_UST.copy()):
        yield


def _leg(trade_id, tenor_years, expiration_date, package_type):
    # exec 2026-07-06; spot effective T+2 = 2026-07-08 (not needed exact for these gates).
    return {
        "trade_id": trade_id,
        "execution_timestamp": pd.Timestamp("2026-07-06 16:00:00", tz="UTC"),
        "effective_date": pd.Timestamp("2026-07-08"),
        "expiration_date": expiration_date,
        "product_type": "OIS_SWAP",
        "notional_currency": "USD",
        "package_type": package_type,
        "forward_label": "spot",
        "is_forward": False,
        "forward_start_years": 0.0,
        "tenor_years": tenor_years,
    }


def test_broken_tenor_packaged_leg_keeps_matched_flag(fake_ust):
    # 10Y leg @ 9.86y broken tenor tying the 2036-05-15 note, already in a CURVE.
    df = pd.DataFrame([_leg("A", 9.86, pd.Timestamp("2036-05-15"), "CURVE")])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True
    # outright_mask gates only the package rewrite, so a packaged leg is NOT retagged.
    assert out.loc[0, "package_type"] == "CURVE"


def test_clean_tenor_packaged_leg_is_still_wiped(fake_ust):
    # 3Y leg @ 2.94y is within 0.1 of clean tenor 3 -> coincidence guard wipes it,
    # even though 2029-06-15 exactly ties a UST coupon.
    df = pd.DataFrame([_leg("B", 2.94, pd.Timestamp("2029-06-15"), "CURVE")])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is False


def test_outright_broken_tenor_still_tagged(fake_ust):
    df = pd.DataFrame([_leg("C", 9.86, pd.Timestamp("2036-05-15"), "OUTRIGHT")])
    out = detect_mms_trades_df(df)
    assert bool(out.loc[0, "matched_ust_maturity"]) is True
    assert out.loc[0, "package_type"] == "MATCHED_MATURITY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_mms_package_propagation.py::test_broken_tenor_packaged_leg_keeps_matched_flag -v`
Expected: FAIL — today the packaged leg's `matched_ust_maturity` is wiped to `False` (asserts True).

- [ ] **Step 3: Unbundle the wipe** — in `SDRUtils/packages/mms.py`, replace the block at lines 178-182:

```python
    # Tag matched trades (with forward-start and clean-tenor gates)
    raw_matched = out["matched_ust_maturity"].fillna(False).values
    can_tag = raw_matched & outright_mask & spot_start_mask & ~is_clean_tenor
    excluded = raw_matched & ~can_tag
    if excluded.any():
        out.loc[excluded, "matched_ust_maturity"] = False
```

with:

```python
    # Tag matched trades. The MMS-ness gates (spot-start + clean-tenor) are
    # coincidence guards that apply to EVERY candidate leg, packaged or not:
    # a clean-tenor spot swap landing on a UST is an optical Spreadover, not
    # matched-maturity. outright_mask gates ONLY the package-identity rewrite
    # below, so a genuine broken-tenor match inside a CURVE/FLY/PKG-N keeps
    # matched_ust_maturity=True for the package rollup instead of being wiped
    # merely for being packaged.
    raw_matched = out["matched_ust_maturity"].fillna(False).values
    is_mms_leg = raw_matched & spot_start_mask & ~is_clean_tenor
    can_tag = is_mms_leg & outright_mask
    excluded = raw_matched & ~is_mms_leg
    if excluded.any():
        out.loc[excluded, "matched_ust_maturity"] = False
```

(Leave the `if can_tag.any():` package-rewrite block below unchanged — it now fires only for outright MMS legs, exactly as before.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_mms_package_propagation.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Confirm no MMS regressions**

Run: `conda run -n stir python -m pytest tests/test_mms_imm_to_imm_exclusion.py tests/test_trade_tape_mms_secondary_label.py -v`
Expected: PASS (outright behavior + IMM/CoW guards unchanged).

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/packages/mms.py tests/test_mms_package_propagation.py
git commit -m "fix(mms): preserve matched_ust_maturity on packaged legs (unbundle wipe)"
```

---

### Task 2: PTP feed + full-scope rollup + cache bump in `usd_swaps.py`

**Files:**
- Modify: `SDRUtils/products/usd/usd_swaps.py` — add `_rollup_matched_maturity_packages` (module-level, next to `detect_sub_package_curve_fly` ~717); wire two lines into `_run_all_detectors` (~1731-1764); bump `DETECTION_CACHE_VERSION` (line 191).
- Test: `tests/test_sub_package_detection.py` (extend)

**Interfaces:**
- Consumes: per-leg `matched_ust_maturity` (Task 1), `package_id`, `package_type`, optional `trade_type`.
- Produces: `_rollup_matched_maturity_packages(df: pd.DataFrame) -> pd.DataFrame` — promotes all-legs-MMS base `CURVE`/`FLY` (any origin) to `MATCHED_MATURITY_CURVE`/`_FLY`; leaves `PKG-N` and any already-composite/`SPREADOVER_*`/`INVOICE*`/`BASIS_*` unchanged.

- [ ] **Step 1: Write the failing test** — append to `tests/test_sub_package_detection.py`:

```python
from SDRUtils.products.usd.usd_swaps import _rollup_matched_maturity_packages


def _ptp_curve(*, matched_ust_maturity: bool, package_type: str = "CURVE",
               package_id: str = "PTP_1") -> pd.DataFrame:
    """A PTP-grouped CURVE (bypasses detect_sub_package_curve_fly today)."""
    return pd.DataFrame([
        {"trade_id": "L1", "tenor_years": 9.86, "package_type": package_type,
         "package_id": package_id, "matched_ust_maturity": matched_ust_maturity},
        {"trade_id": "L2", "tenor_years": 19.87, "package_type": package_type,
         "package_id": package_id, "matched_ust_maturity": matched_ust_maturity},
    ])


def test_rollup_promotes_ptp_all_mms_curve():
    out = _rollup_matched_maturity_packages(_ptp_curve(matched_ust_maturity=True))
    assert set(out["package_type"].tolist()) == {"MATCHED_MATURITY_CURVE"}


def test_rollup_leaves_pkg_n_type_unchanged():
    df = _ptp_curve(matched_ust_maturity=True, package_type="PKG-3", package_id="PTP_2")
    out = _rollup_matched_maturity_packages(df)
    assert set(out["package_type"].tolist()) == {"PKG-3"}


def test_rollup_partial_stays_base():
    df = _ptp_curve(matched_ust_maturity=False)
    df.loc[0, "matched_ust_maturity"] = True
    out = _rollup_matched_maturity_packages(df)
    assert set(out["package_type"].tolist()) == {"CURVE"}


def test_rollup_skips_spreadover_and_invoice():
    for ptype in ("SPREADOVER_CURVE", "INVOICE_SWITCH", "MATCHED_MATURITY_CURVE"):
        df = _ptp_curve(matched_ust_maturity=True, package_type=ptype, package_id=f"P_{ptype}")
        out = _rollup_matched_maturity_packages(df)
        assert set(out["package_type"].tolist()) == {ptype}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_sub_package_detection.py::test_rollup_promotes_ptp_all_mms_curve -v`
Expected: FAIL — `ImportError: cannot import name '_rollup_matched_maturity_packages'`.

- [ ] **Step 3: Add the rollup function** — in `SDRUtils/products/usd/usd_swaps.py`, immediately after `detect_sub_package_curve_fly` (find its `return out` near ~810), add:

```python
def _rollup_matched_maturity_packages(df: pd.DataFrame) -> pd.DataFrame:
    """Full-scope, idempotent package-level matched-maturity rollup.

    Runs post-concat over the whole (PTP + non-PTP) frame. For every
    package_id whose legs are ALL matched_ust_maturity, promote a base
    CURVE/FLY to MATCHED_MATURITY_CURVE/_FLY. PKG-N keeps its type (the
    package-level MMS signal surfaces via per-leg special_tenor_type at
    ingest). Already-composite / SPREADOVER_* / INVOICE* / BASIS_* packages
    are skipped so SPREADOVER-wins and INVOICE-wins precedence hold. Idempotent:
    a no-op over anything detect_sub_package_curve_fly already promoted.
    """
    if df.empty or "package_id" not in df.columns or "package_type" not in df.columns:
        return df
    out = df.copy()
    if "matched_ust_maturity" not in out.columns:
        return out
    leg_mms = out["matched_ust_maturity"].astype(str).str.lower().isin({"true", "t", "1"})
    base = out["package_type"].astype(str).str.upper()
    promotable = base.isin({"CURVE", "FLY"}) & out["package_id"].notna()
    if not promotable.any():
        return out
    for pkg_id, group_idx in out.loc[promotable].groupby("package_id").groups.items():
        idx = list(group_idx)
        if len(idx) < 2:
            continue
        if not bool(leg_mms.loc[idx].all()):
            continue
        base_type = str(out.loc[idx[0], "package_type"]).upper()
        new_type = f"MATCHED_MATURITY_{base_type}"
        out.loc[idx, "package_type"] = new_type
        if "trade_type" in out.columns:
            out.loc[idx, "trade_type"] = new_type
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_sub_package_detection.py -v`
Expected: PASS (existing tests + 4 new; existing `detect_sub_package_curve_fly` tests untouched).

- [ ] **Step 5: Wire into `_run_all_detectors`** — in `SDRUtils/products/usd/usd_swaps.py`:

(a) After `ptp_df = classify_ptp_groups(ptp_df)` (inside `if not ptp_df.empty:`, 24-space indent), add:

```python
                        ptp_df = detect_mms_trades_df(ptp_df)
```

(b) Replace the tail:

```python
                    df = pd.concat([ptp_df, df], ignore_index=True)
                    df = solve_all_opa_signs(df)
                    return df
```

with:

```python
                    df = pd.concat([ptp_df, df], ignore_index=True)
                    df = _rollup_matched_maturity_packages(df)
                    df = solve_all_opa_signs(df)
                    return df
```

- [ ] **Step 6: Bump the detection cache version** — in `SDRUtils/products/usd/usd_swaps.py:191` change:

```python
DETECTION_CACHE_VERSION = "ptp2"
```

to:

```python
DETECTION_CACHE_VERSION = "ptp3-mms-pkg"
```

- [ ] **Step 7: Add `_rollup_matched_maturity_packages` to `__all__`** if the module defines one (search near the end of the file, ~1883). Append the name to the list if present; skip if there is no `__all__`.

- [ ] **Step 8: Run the detection test suite**

Run: `conda run -n stir python -m pytest tests/test_sub_package_detection.py tests/test_mms_package_propagation.py tests/test_ptp_grouper.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add SDRUtils/products/usd/usd_swaps.py tests/test_sub_package_detection.py
git commit -m "feat(mms): PTP-leg matching + full-scope package rollup; bump DETECTION_CACHE_VERSION"
```

---

## Phase 2 — Labels

### Task 3: `package_ust_aliases` in `_enrich_packages`

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py` — `_enrich_packages` default (~762) + numpy array hoist (~778) + loop accumulator (~840-887).
- Test: `tests/test_trade_tape_mms_secondary_label.py` (extend)

**Interfaces:**
- Produces: a `package_ust_aliases` string column: collapse-if-identical MMYY per package (case A `"0236"`, case B `"0536/0546"`, tenor-sorted), `""` when no leg alias resolves.

- [ ] **Step 1: Write the failing test** — append to `tests/test_trade_tape_mms_secondary_label.py`:

```python
def _pkg_legs(package_type, package_id, legs):
    """legs: list of (trade_id, tenor_years, expiration_date)."""
    tids = [t for t, _, _ in legs]
    rows = []
    for tid, ten, exp in legs:
        rows.append({
            "trade_id": tid, "tenor_years": ten, "expiration_date": pd.Timestamp(exp),
            "package_type": package_type, "package_id": package_id, "package_legs": tids,
            "special_tenor_type": "MATCHED_MATURITY", "matched_ust_maturity": True,
            "forward_label": "spot", "product_type": "OIS_SWAP",
            "upi_underlier_name": "USD-SOFR-OIS Compound", "upi_reset_freq": "1D",
            "upi_notional_schedule": "Constant", "upi_delivery_type": "PHYS",
            "trade_type": package_type, "tenor_label": f"{int(round(ten))}Y",
            "tenor_display": f"{int(round(ten))}Y",
        })
    return rows


def test_package_ust_aliases_case_a_collapses_to_single():
    rows = _pkg_legs("PKG-2", "P1", [("L1", 9.86, "2036-02-15"), ("L2", 9.86, "2036-02-15")])
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert set(out["package_ust_aliases"].tolist()) == {"0236"}


def test_package_ust_aliases_case_b_joins_distinct():
    rows = _pkg_legs("CURVE", "C1", [("L1", 9.86, "2036-05-15"), ("L2", 19.87, "2046-05-15")])
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_packages(df.copy())
    assert set(out["package_ust_aliases"].tolist()) == {"0536/0546"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_trade_tape_mms_secondary_label.py::test_package_ust_aliases_case_a_collapses_to_single -v`
Expected: FAIL — `KeyError: 'package_ust_aliases'`.

- [ ] **Step 3: Add the default** — in `_enrich_packages`, after `df["package_tenors"] = df[tenor_src].astype(str)` (~762) add:

```python
        df["package_ust_aliases"] = ""
```

- [ ] **Step 4: Hoist a per-leg MMYY array** — near the other pre-materialized arrays (where `tenor_years_arr` / `tenor_src_arr` are built, ~778-779), add:

```python
            if "expiration_date" in df.columns:
                _exp_dt = pd.to_datetime(df["expiration_date"], errors="coerce")
                mmyy_arr = np.array(
                    [f"{d.month:02d}{d.year % 100:02d}" if pd.notna(d) else "" for d in _exp_dt],
                    dtype=object,
                )
            else:
                mmyy_arr = np.full(len(df), "", dtype=object)
```

- [ ] **Step 5: Accumulate + assign aliases in the loop** — in the batched block (~840-887): (a) beside `tenors_arr: list[str] = []` add `ust_aliases_arr: list[str] = []`; (b) inside the loop, after `sorted_tenors = tenor_src_arr[leg_pos_arr[sort_order]]`, add:

```python
                leg_aliases = [a for a in mmyy_arr[leg_pos_arr[sort_order]] if a]
                if not leg_aliases:
                    pkg_alias_str = ""
                elif len(set(leg_aliases)) == 1:
                    pkg_alias_str = leg_aliases[0]
                else:
                    pkg_alias_str = "/".join(leg_aliases)
```

and where `tenors_arr.append(pkg_tenors_str)` is called, add alongside it `ust_aliases_arr.append(pkg_alias_str)` (append for EVERY appended package so lengths stay aligned); (c) in the `if valid_indices:` block add:

```python
                df.loc[valid_indices, "package_ust_aliases"] = ust_aliases_arr
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_trade_tape_mms_secondary_label.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py tests/test_trade_tape_mms_secondary_label.py
git commit -m "feat(tape): package_ust_aliases (collapse-if-identical MMYY) in _enrich_packages"
```

---

### Task 4: Label rendering — PKG-N alias slot, package-scope alias, per-leg alias column, cache bump

**Files:**
- Modify: `SDRUtils/analytics/trade_tape.py` — `_label_for_row` section 4 (~1375-1381); `_build_enriched_label` materialization (~1522-1532); `TRADE_TAPE_CACHE_VERSION` (line 66).
- Test: `tests/test_trade_tape_mms_secondary_label.py` (extend)

**Interfaces:**
- Consumes: `package_ust_aliases` (Task 3), `_is_pkg_n`, `pkg_type`, `_ust_maturity_alias(row)`.
- Produces: package-scope `tape_label_ust_alias` renders `…Spot 0236 PKG-3 MMS PHYS` (PKG-N) / `…Spot 0536/0546 CURVE MMS PHYS` (CURVE); new `leg_tape_label_ust_alias` column (leg-scope + alias).

- [ ] **Step 1: Write the failing test** — append to `tests/test_trade_tape_mms_secondary_label.py`:

```python
def _enrich_and_label(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    out = tape._enrich_packages(out)
    out = tape._build_enriched_label(out)
    return out


def test_pkg_n_alias_label_shows_alias_and_structure():
    rows = _pkg_legs("PKG-3", "P3", [
        ("L1", 9.86, "2036-02-15"), ("L2", 9.86, "2036-02-15"), ("L3", 9.86, "2036-02-15")])
    out = _enrich_and_label(rows)
    alt = out.loc[0, "tape_label_ust_alias"]
    assert "0236" in alt
    assert "PKG-3" in alt
    assert "MMS" in alt
    assert "PHYS" in alt


def test_curve_alias_label_joins_maturities():
    rows = _pkg_legs("CURVE", "C1", [("L1", 9.86, "2036-05-15"), ("L2", 19.87, "2046-05-15")])
    out = _enrich_and_label(rows)
    alt = out.loc[0, "tape_label_ust_alias"]
    assert "0536/0546" in alt
    assert "CURVE" in alt and "MMS" in alt


def test_leg_tape_label_ust_alias_present_per_leg():
    rows = _pkg_legs("CURVE", "C1", [("L1", 9.86, "2036-05-15"), ("L2", 19.87, "2046-05-15")])
    out = _enrich_and_label(rows)
    assert "leg_tape_label_ust_alias" in out.columns
    # each expanded leg shows its OWN maturity alias
    assert "0536" in out.loc[0, "leg_tape_label_ust_alias"]
    assert "0546" in out.loc[1, "leg_tape_label_ust_alias"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_trade_tape_mms_secondary_label.py::test_pkg_n_alias_label_shows_alias_and_structure -v`
Expected: FAIL — PKG-N alias label currently drops the structure token / doesn't show `0236`.

- [ ] **Step 3: Rewrite the section-4 alias substitution** — in `_label_for_row`, replace the existing block (~1375-1381):

```python
                if use_ust_alias and (
                    str(row.get("special_tenor_type", "")).upper() == "MATCHED_MATURITY"
                    or bool(row.get("matched_ust_maturity", False))
                ):
                    alias = _ust_maturity_alias(row)
                    if alias:
                        tenors = alias
```

with:

```python
                if use_ust_alias and (
                    str(row.get("special_tenor_type", "")).upper() == "MATCHED_MATURITY"
                    or bool(row.get("matched_ust_maturity", False))
                ):
                    if leg_as_outright:
                        # Single expanded leg -> its own maturity alias.
                        alias = _ust_maturity_alias(row)
                        if alias:
                            tenors = alias
                    else:
                        # Package scope -> collapsed multi-leg alias (e.g. "0236" or
                        # "0536/0546"); fall back to the single-row date if absent.
                        pkg_alias = str(row.get("package_ust_aliases", "") or "").strip()
                        alias = pkg_alias if pkg_alias else _ust_maturity_alias(row)
                        if alias:
                            if _is_pkg_n and pkg_type.startswith("PKG-"):
                                tenors = f"{alias} {pkg_type}"
                            else:
                                tenors = alias
```

- [ ] **Step 4: Add the `leg_tape_label_ust_alias` column** — in `_build_enriched_label`, after the `tape_label_ust_alias` apply (~1522-1524) add:

```python
        df["leg_tape_label_ust_alias"] = df.apply(
            lambda r: _label_for_row(r, leg_scope=True, use_ust_alias=True), axis=1
        )
```

and after the existing whitespace-cleanup stanzas (~1526-1532) add a matching one:

```python
        df["leg_tape_label_ust_alias"] = (
            df["leg_tape_label_ust_alias"].str.replace(r"\s+", " ", regex=True).str.strip()
        )
```

- [ ] **Step 5: Bump the tape cache version** — in `SDRUtils/analytics/trade_tape.py:66` change:

```python
TRADE_TAPE_CACHE_VERSION = "v10-ptp-truebp-notation"
```

to:

```python
TRADE_TAPE_CACHE_VERSION = "v11-ust-alias-pkg"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_trade_tape_mms_secondary_label.py -v`
Expected: PASS (new + existing, incl. non-MMS invariant `tape_label == tape_label_ust_alias`).

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/analytics/trade_tape.py tests/test_trade_tape_mms_secondary_label.py
git commit -m "feat(tape): package + per-leg MMYY alias labels; bump TRADE_TAPE_CACHE_VERSION"
```

---

## Phase 3 — Ingest + schema

### Task 5: Persist per-leg MMS columns

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` — `LEG_COLUMNS` (~173-177), bool loop (~802-821), text loop (~822-841).
- Modify: `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` — legs `CREATE` (~125) + new `ADD COLUMN IF NOT EXISTS` block (after ~345).
- Test: `tests/test_ingest_mms_columns.py` (new)

**Interfaces:**
- Produces: legs table columns `matched_ust_maturity` BOOL, `special_tenor_type`/`ust_cusip`/`tape_label_ust_alias`/`leg_tape_label_ust_alias`/`matched_ust_maturity_trade_confidence` TEXT. All auto-flow into the display view via `jsonb_agg(to_jsonb(l))` — no view edit for leg columns.

- [ ] **Step 1: Write the failing test** — create `tests/test_ingest_mms_columns.py`:

```python
from __future__ import annotations

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import LEG_COLUMNS, PACKAGE_COLUMNS
from SDRUtils._swappulse_scripts import _tape_schema_v2 as schema

_NEW_LEG = [
    "matched_ust_maturity", "special_tenor_type", "ust_cusip",
    "tape_label_ust_alias", "leg_tape_label_ust_alias",
    "matched_ust_maturity_trade_confidence",
]


def test_new_leg_columns_in_tuple():
    for c in _NEW_LEG:
        assert c in LEG_COLUMNS, c


def test_new_leg_columns_in_ddl():
    sql = schema.TAPE_SCHEMA_SQL_V2
    for c in _NEW_LEG:
        assert f"ADD COLUMN IF NOT EXISTS {c}" in sql, c
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_ingest_mms_columns.py::test_new_leg_columns_in_tuple -v`
Expected: FAIL — names not yet in `LEG_COLUMNS`.

- [ ] **Step 3: Add to `LEG_COLUMNS`** — before the closing `)` of the tuple (~177, after `"opa_signed_amount",`) add:

```python
    # Matched-UST-maturity / special-tenor enrichment
    "matched_ust_maturity",
    "special_tenor_type",
    "ust_cusip",
    "tape_label_ust_alias",
    "leg_tape_label_ust_alias",
    "matched_ust_maturity_trade_confidence",
```

- [ ] **Step 4: Coerce them** — in `build_leg_rows`, add `"matched_ust_maturity"` to the inline **bool** tuple (~802-821, after the Phase-5 block); add `"special_tenor_type", "ust_cusip", "tape_label_ust_alias", "leg_tape_label_ust_alias", "matched_ust_maturity_trade_confidence"` to the inline **text** tuple (~822-841, after `"ptp_group_id",`).

- [ ] **Step 5: Schema DDL** — in `_tape_schema_v2.py`, (a) in the `LEGS_TABLE_V2` `CREATE TABLE` after `leg_tape_label TEXT,` (~125) add:

```sql
    matched_ust_maturity BOOLEAN,
    special_tenor_type TEXT,
    ust_cusip TEXT,
    tape_label_ust_alias TEXT,
    leg_tape_label_ust_alias TEXT,
    matched_ust_maturity_trade_confidence TEXT,
```

(b) after the last existing `ADD COLUMN IF NOT EXISTS` block (~345) add:

```sql
-- Matched-UST-maturity / special-tenor enrichment (leg)
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS matched_ust_maturity BOOLEAN;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS special_tenor_type TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS ust_cusip TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS tape_label_ust_alias TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS leg_tape_label_ust_alias TEXT;
ALTER TABLE {LEGS_TABLE_V2} ADD COLUMN IF NOT EXISTS matched_ust_maturity_trade_confidence TEXT;
```

(Keep `{LEGS_TABLE_V2}` placeholders literal — the SQL is an f-string.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_ingest_mms_columns.py -v`
Expected: PASS (leg tests; package tests added next task).

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py SDRUtils/_swappulse_scripts/_tape_schema_v2.py tests/test_ingest_mms_columns.py
git commit -m "feat(ingest): persist per-leg MMS columns (legs_v2 + DDL)"
```

---

### Task 6: Persist package-level MMS columns

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` — `PACKAGE_COLUMNS` (~248-261), add `_rep_tape_label_ust_alias` (near ~595), add nested `_all` (after `_any` ~1187), rec dict (~1280).
- Modify: `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` — packages `CREATE` (~85), `ADD COLUMN` block, `DISPLAY_VIEW_V2` SELECT (~419).
- Test: `tests/test_ingest_mms_columns.py` (extend)

**Interfaces:**
- Produces: packages table columns `special_tenor_type` TEXT, `tape_label_ust_alias` TEXT, `is_matched_maturity_all` BOOL; all three added to the display-view SELECT.

- [ ] **Step 1: Write the failing test** — append to `tests/test_ingest_mms_columns.py`:

```python
_NEW_PKG = ["special_tenor_type", "tape_label_ust_alias", "is_matched_maturity_all"]


def test_new_package_columns_in_tuple():
    for c in _NEW_PKG:
        assert c in PACKAGE_COLUMNS, c


def test_new_package_columns_in_ddl_and_view():
    sql = schema.TAPE_SCHEMA_SQL_V2
    for c in _NEW_PKG:
        assert f"ADD COLUMN IF NOT EXISTS {c}" in sql, c
    # package columns must be hand-listed in the display view SELECT
    for c in _NEW_PKG:
        assert f"p.{c}" in sql, c
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stir python -m pytest tests/test_ingest_mms_columns.py::test_new_package_columns_in_tuple -v`
Expected: FAIL.

- [ ] **Step 3: Add to `PACKAGE_COLUMNS`** — before the closing `)` (~261, after `"package_metrics",`) add:

```python
    # Matched-UST-maturity / special-tenor enrichment (package)
    "special_tenor_type",
    "tape_label_ust_alias",
    "is_matched_maturity_all",
```

- [ ] **Step 4: Add `_rep_tape_label_ust_alias`** — after `_rep_tape_label` (~595) add:

```python
def _rep_tape_label_ust_alias(group: pd.DataFrame) -> str | None:
    labels = group.get("tape_label_ust_alias")
    if labels is None:
        return None
    non_null = [l for l in (_str_or_none(x) for x in labels) if l]
    if not non_null:
        return None
    return max(non_null, key=len)
```

- [ ] **Step 5: Add nested `_all`** — in `build_package_rows`, right after the `_any` closure (~1187) add:

```python
        def _all(flag: str) -> bool | None:
            if flag not in g.columns:
                return None
            normalized = g[flag].map(_bool_or_none)
            non_null = normalized.dropna()
            if non_null.empty:
                return None
            return bool(non_null.eq(True).all())
```

- [ ] **Step 6: Add the rec-dict keys** — in the `rec` dict near `"tape_label": _rep_tape_label(g),` (~1280) add:

```python
            "special_tenor_type": _consistent_str(g, "special_tenor_type"),
            "tape_label_ust_alias": _rep_tape_label_ust_alias(g),
            "is_matched_maturity_all": _all("matched_ust_maturity"),
```

- [ ] **Step 7: Schema DDL + view** — in `_tape_schema_v2.py`: (a) packages `CREATE TABLE` after `tape_label TEXT,` (~85) add `special_tenor_type TEXT,` / `tape_label_ust_alias TEXT,` / `is_matched_maturity_all BOOLEAN,`; (b) in the new `ADD COLUMN` block add:

```sql
-- Matched-UST-maturity / special-tenor enrichment (package)
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS special_tenor_type TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS tape_label_ust_alias TEXT;
ALTER TABLE {PACKAGES_TABLE_V2} ADD COLUMN IF NOT EXISTS is_matched_maturity_all BOOLEAN;
```

(c) in `DISPLAY_VIEW_V2`, after `p.tape_label,` (~419) add `p.special_tenor_type,` / `p.tape_label_ust_alias,` / `p.is_matched_maturity_all,`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_ingest_mms_columns.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py SDRUtils/_swappulse_scripts/_tape_schema_v2.py tests/test_ingest_mms_columns.py
git commit -m "feat(ingest): persist package-level MMS columns + display view"
```

---

## Phase 4 — Dashboard

### Task 7: TS types + package badge/label maps

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts` — add fields to `UsdSwapTapeRow` (~141) and `UsdSwapTapeLeg` (~41).
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.helpers.ts` — `PACKAGE_BADGE_TONES` (~14-21), `PACKAGE_LABELS` (~23-30).
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts` (extend)

**Interfaces:**
- Produces: `packageTypeDisplayLabel('MATCHED_MATURITY')` → `'MMS'`, `'MATCHED_MATURITY_CURVE'` → `'MMS Curve'`, `'MATCHED_MATURITY_FLY'` → `'MMS Fly'`; non-slate badge tones; new row fields `special_tenor_type`, `tape_label_ust_alias`, `matched_ust_maturity`; new leg fields `special_tenor_type`, `tape_label_ust_alias`, `leg_tape_label_ust_alias`.

- [ ] **Step 1: Write the failing test** — append to `columns.test.ts`:

```typescript
import { packageTypeDisplayLabel, packageTypeBadgeClassName } from '../columns.helpers'

describe('MMS package badges', () => {
  it('labels matched-maturity package types', () => {
    expect(packageTypeDisplayLabel('MATCHED_MATURITY')).toBe('MMS')
    expect(packageTypeDisplayLabel('MATCHED_MATURITY_CURVE')).toBe('MMS Curve')
    expect(packageTypeDisplayLabel('MATCHED_MATURITY_FLY')).toBe('MMS Fly')
  })
  it('gives matched-maturity a non-default tone', () => {
    expect(packageTypeBadgeClassName('MATCHED_MATURITY')).not.toBe(
      packageTypeBadgeClassName('OUTRIGHT'),
    )
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `SDRUtils/dashboard`): `npm test -- columns.test.ts`
Expected: FAIL — labels return raw enum; tone equals OUTRIGHT.

- [ ] **Step 3: Add label + tone map entries** — in `columns.helpers.ts`, before the closing `}` of `PACKAGE_BADGE_TONES` (~21):

```typescript
  MATCHED_MATURITY: 'border-teal-500/40 bg-teal-900/40 text-teal-200',
  MATCHED_MATURITY_CURVE: 'border-sky-500/40 bg-sky-900/40 text-sky-200',
  MATCHED_MATURITY_FLY: 'border-indigo-500/40 bg-indigo-900/40 text-indigo-200',
```

and before the closing `}` of `PACKAGE_LABELS` (~30):

```typescript
  MATCHED_MATURITY: 'MMS',
  MATCHED_MATURITY_CURVE: 'MMS Curve',
  MATCHED_MATURITY_FLY: 'MMS Fly',
```

- [ ] **Step 4: Add TS fields** — in `usd-swaps-tape-v2/types/trade.types.ts`, add to the `UsdSwapTapeRow` intersection (~141 block):

```typescript
  special_tenor_type?: string | null
  tape_label_ust_alias?: string | null
  is_matched_maturity_all?: boolean | null
  matched_ust_maturity?: boolean | null
```

and to the `UsdSwapTapeLeg` intersection (~41 block):

```typescript
  special_tenor_type?: string | null
  tape_label_ust_alias?: string | null
  leg_tape_label_ust_alias?: string | null
```

- [ ] **Step 5: Run tests + typecheck**

Run (from `SDRUtils/dashboard`): `npm test -- columns.test.ts` then `npx tsc --noEmit`
Expected: PASS; no type errors.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/
git commit -m "feat(dashboard): MMS package badge labels/tones + TS type fields"
```

---

### Task 8: Prefer alias label + bold MMYY

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.helpers.ts` — `displayTapeLabel` (~40), `TENOR_SEGMENT_RE` (~59).
- Test: `.../__tests__/TapeLabelCell.test.ts` (extend)

**Interfaces:**
- Consumes: `row.tape_label_ust_alias` (Task 7 type).
- Produces: `displayTapeLabel` renders the alias when present; `parseTapeLabelSegments` bolds the numeric MMYY token(s).

- [ ] **Step 1: Write the failing test** — append to `TapeLabelCell.test.ts`:

```typescript
import { displayTapeLabel, parseTapeLabelSegments } from '../TapeLabelCell.helpers'

it('prefers the UST alias label when present', () => {
  const row: any = {
    tape_label: 'USD-SOFR-OIS Compound 1D Constant Spot 9Y10M CURVE MMS PHYS',
    tape_label_ust_alias: 'USD-SOFR-OIS Compound 1D Constant Spot 0536/0546 CURVE MMS PHYS',
    n_package_legs: 2,
  }
  expect(displayTapeLabel(row)).toContain('0536/0546')
})

it('bolds the numeric MMYY alias token', () => {
  const segs = parseTapeLabelSegments('Spot 0536/0546 CURVE MMS PHYS')
  expect(segs.some((s) => s.isTenor && s.text.includes('0536'))).toBe(true)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `SDRUtils/dashboard`): `npm test -- TapeLabelCell.test.ts`
Expected: FAIL.

- [ ] **Step 3: Prefer the alias** — in `displayTapeLabel` change the `labels` array (~40):

```typescript
  const labels = [row.tape_label, row.legs_json?.[0]?.tape_label]
```

to:

```typescript
  const labels = [row.tape_label_ust_alias, row.tape_label, row.legs_json?.[0]?.tape_label]
```

- [ ] **Step 4: Bold the MMYY token** — in `TENOR_SEGMENT_RE`, add a numeric-MMYY alternative. Append `|(\b\d{2}\d{2}(?:\/\d{2}\d{2})*\b)` to the alternation (a 4-digit MMYY, optionally `/`-joined), placed AFTER the existing `FOMC` / `IMM_` alternatives so those still win. The full source becomes:

```typescript
const TENOR_SEGMENT_RE =
  /(PKG-\d+)|(FOMC\s+[A-Z]{3,4}\d{2})|(\bIMM_[A-Z]\d{4}\b)|(\bSpot\b)|(\b\d+D\b(?!\s+Constant))|(\b\d{2}\d{2}(?:\/\d{2}\d{2})*\b)|(\b\d+(?:\.\d+)?[YMW](?:\d+[YMW])?(?:\/\d+(?:\.\d+)?[YMW](?:\d+[YMW])?)*)/g
```

Update the leading comment block to document the MMYY UST-alias anchor (e.g. `"0536"`, `"0536/0546"`). Note the MMYY alternative sits before the `IMM_[A-Z]\d{4}` — verify `IMM_M2026` still matches the IMM branch (it does: the `IMM_` prefix is consumed by the earlier alternative before the digits are reached).

- [ ] **Step 5: Run tests to verify they pass**

Run (from `SDRUtils/dashboard`): `npm test -- TapeLabelCell.test.ts`
Expected: PASS. Confirm the existing IMM/FOMC/tenor segment tests still pass.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/
git commit -m "feat(dashboard): prefer UST-alias tape label + bold MMYY token"
```

---

### Task 9: Widen the per-leg tooltip gate

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.tsx` — `pkgLegsLines` gate (~15).
- Test: `.../__tests__/TapeLabelCell.test.ts` (extend, if `pkgLegsLines` is exported; else assert via component render).

**Interfaces:**
- Produces: the per-leg hover tooltip now fires for CURVE / FLY / `MATCHED_MATURITY*` / `*_CURVE` / `*_FLY`, not just `PKG-`.

- [ ] **Step 1: Write the failing test** — if `pkgLegsLines` is not exported, export it, then append to `TapeLabelCell.test.ts`:

```typescript
import { pkgLegsLines } from '../TapeLabelCell'

it('produces leg lines for a MATCHED_MATURITY_CURVE', () => {
  const row: any = {
    package_type: 'MATCHED_MATURITY_CURVE',
    legs_json: [
      { tenor_years: 10, leg_tape_label: 'USD-SOFR 0536 Outright' },
      { tenor_years: 20, leg_tape_label: 'USD-SOFR 0546 Outright' },
    ],
  }
  expect(pkgLegsLines(row)?.length).toBe(2)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `SDRUtils/dashboard`): `npm test -- TapeLabelCell.test.ts`
Expected: FAIL — gate returns null for non-`PKG-` types.

- [ ] **Step 3: Widen the gate** — in `pkgLegsLines`, replace (~14-15):

```typescript
  const kind = String(row.package_type ?? '').toUpperCase()
  if (!kind.startsWith('PKG-')) return null
```

with:

```typescript
  const kind = String(row.package_type ?? '').toUpperCase()
  const isMultiLeg =
    kind.startsWith('PKG-') ||
    kind === 'CURVE' ||
    kind === 'FLY' ||
    kind.startsWith('MATCHED_MATURITY') ||
    kind.endsWith('_CURVE') ||
    kind.endsWith('_FLY')
  if (!isMultiLeg) return null
```

(The `legs.length < 2` and `lines.length >= 2` guards below already prevent degenerate tooltips.)

- [ ] **Step 4: Run tests to verify they pass**

Run (from `SDRUtils/dashboard`): `npm test -- TapeLabelCell.test.ts` then `npx tsc --noEmit`
Expected: PASS; no type errors.

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TapeLabelCell.tsx
git commit -m "feat(dashboard): show per-leg tooltip for CURVE/FLY/MMS packages"
```

---

## Phase 5 — Integration, backfill, deploy

### Task 10: End-to-end verification on real cached data

**Files:**
- Test: `tests/test_mms_package_e2e.py` (new)

**Interfaces:**
- Consumes: the full `_run_all_detectors` → `_resolve_special_tenor_priority` path. This is a `db`/`network`-free check against a synthetic multi-leg frame; it exercises Tasks 1-2 end-to-end.

- [ ] **Step 1: Write the test** — create `tests/test_mms_package_e2e.py` chaining the real module-level detectors (`detect_mms_trades_df` → `_rollup_matched_maturity_packages`, the same order `_run_all_detectors` uses post-concat) on a real-cusip multi-leg frame:

```python
from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from SDRUtils.packages.mms import detect_mms_trades_df
from SDRUtils.products.usd.usd_swaps import _rollup_matched_maturity_packages

_UST = pd.DataFrame([
    {"cusip": "91282CQQ7", "maturity_date": pd.Timestamp("2036-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "10-Year",
     "security_type": "Treasury Note", "coupon": 4.0, "original_security_term": "10-Year"},
    {"cusip": "912810UV8", "maturity_date": pd.Timestamp("2046-05-15").date(),
     "issue_date": pd.Timestamp("2026-05-15").date(), "oi": "20-Year",
     "security_type": "Treasury Bond", "coupon": 4.25, "original_security_term": "20-Year"},
    {"cusip": "91282CPZ8", "maturity_date": pd.Timestamp("2036-02-15").date(),
     "issue_date": pd.Timestamp("2026-02-15").date(), "oi": "10-Year",
     "security_type": "Treasury Note", "coupon": 4.0, "original_security_term": "10-Year"},
])


def _leg(tid, ten, exp, ptype, pid):
    return {
        "trade_id": tid, "execution_timestamp": pd.Timestamp("2026-07-06 16:00:00", tz="UTC"),
        "effective_date": pd.Timestamp("2026-07-08"), "expiration_date": pd.Timestamp(exp),
        "product_type": "OIS_SWAP", "notional_currency": "USD", "package_type": ptype,
        "package_id": pid, "forward_label": "spot", "is_forward": False,
        "forward_start_years": 0.0, "tenor_years": ten,
    }


def test_ptp_curve_promotes_and_pkg3_stays():
    df = pd.DataFrame([
        # PTP all-MMS CURVE (diff bonds) -> MATCHED_MATURITY_CURVE
        _leg("C1", 9.86, "2036-05-15", "CURVE", "PTP_C"),
        _leg("C2", 19.87, "2046-05-15", "CURVE", "PTP_C"),
        # all-MMS same-bond PKG-3 -> stays PKG-3, every leg matched
        _leg("P1", 9.86, "2036-02-15", "PKG-3", "PTP_P"),
        _leg("P2", 9.86, "2036-02-15", "PKG-3", "PTP_P"),
        _leg("P3", 9.86, "2036-02-15", "PKG-3", "PTP_P"),
    ])
    with patch("SDRUtils.packages.mms._load_ust_reference_data", return_value=_UST.copy()):
        tagged = detect_mms_trades_df(df)
    out = _rollup_matched_maturity_packages(tagged)
    curve = out[out["package_id"] == "PTP_C"]
    pkg3 = out[out["package_id"] == "PTP_P"]
    assert set(curve["package_type"]) == {"MATCHED_MATURITY_CURVE"}
    assert set(pkg3["package_type"]) == {"PKG-3"}
    assert bool(pkg3["matched_ust_maturity"].astype(str).str.lower().isin({"true", "t", "1"}).all())
```

- [ ] **Step 2: Run it**

Run: `conda run -n stir python -m pytest tests/test_mms_package_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full fast gate**

Run: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
Expected: PASS (no regressions across the suite).

- [ ] **Step 4: Dashboard test + build**

Run (from `SDRUtils/dashboard`): `npm test` then `npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add tests/test_mms_package_e2e.py
git commit -m "test(mms): end-to-end package propagation on real cusips"
```

---

### Task 11: Prod schema migration, backfill, dashboard verify + deploy

**Files:** none (operational). Requires `DATABASE_URL` (or `SWAPPULSE_DB_*`) for the remote prod tape.

- [ ] **Step 1: Regenerate a local classified day + eyeball**

Run the pipeline against one recent day with `ignore_cache=True` (new `DETECTION_CACHE_VERSION` forces recompute) into `sdr_cache/`, then re-run `scratchpad/mine_mms.py`-style checks to confirm all-legs-MMS packages now carry `package_type`/`special_tenor_type` and the alias labels render. Expected: the 10 all-MMS packages on 2026-07-06 now flagged (was 0).

- [ ] **Step 2: Apply the schema migration to prod**

Run `ensure_schema` against the prod tape DB (idempotent `ADD COLUMN IF NOT EXISTS` + view rebuild). Confirm the new leg/package columns and view columns exist.

- [ ] **Step 3: Local dashboard chrome-MCP verification**

Start the dashboard (`npm run dev`, localhost:3000) against a DB that has the new columns. Via chrome-MCP: confirm an MMS package row shows the `MMS`/`MMS Curve` badge, the `0236`-style alias in the tape label (bolded), and the per-leg hover tooltip. Capture a screenshot.

- [ ] **Step 4: GO/NO-GO gate — prod backfill (destructive)**

STOP and surface an explicit go/no-go before running `run_usdswaps_pipeline` backfill: it deletes+rewrites the remote prod tape. On GO, run the backfill.

- [ ] **Step 5: Deploy the dashboard** and re-verify the deployed tape shows MMS packages.

- [ ] **Step 6: Finalize** — use `superpowers:finishing-a-development-branch` to open the PR for `feat/mms-package-detection`.

---

## Self-review notes

- **Spec coverage:** §5a→Task1; §5b/§5c + cache bump→Task2; §6 package alias→Task3, PKG-N/leg alias + cache bump→Task4; §7 legs→Task5, packages+view→Task6; §8 badges/types→Task7, alias+bold→Task8, tooltip→Task9; §10 tests distributed + e2e Task10; §9 rollout→Task11. §11 resolved (no work). §12 fragility contract enforced by Task1 coincidence tests + untouched gates.
- **Type consistency:** column names identical across tuple/coercion/DDL/view/TS (`matched_ust_maturity`, `special_tenor_type`, `ust_cusip`, `tape_label_ust_alias`, `leg_tape_label_ust_alias`, `matched_ust_maturity_trade_confidence`, `is_matched_maturity_all`); `package_ust_aliases` is an internal enrichment column (not persisted; feeds the label only). `_rollup_matched_maturity_packages` name matches import in Task 2 test.
- **Known verify-at-implementation points:** confirm `_run_all_detectors` indentation (16/20/24 spaces); confirm `build_package_rows` signature for any direct test; confirm `pkgLegsLines` export for Task 9; confirm `_enrich_context`/`_enrich_packages` call order for Task 3-4 tests (tests call `_enrich_packages` explicitly to be robust).
