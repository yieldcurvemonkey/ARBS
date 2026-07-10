"""MMS detection-depth research — empirical analysis of three gate relaxation scenarios.

Reads the classified cache (no network, no DB — except a cached, non-network read of
the UST reference-data snapshot via ``_load_ust_reference_data``, which reuses whatever
snapshot is already on disk for today's business day). Outputs a Markdown report to
docs/superpowers/research/2026-07-09-mms-detection-depth.md.

This is a read-only research script: it does not modify any detection code, gate
logic, or cache version. Per each section's literal check (mirroring the Task 8 brief),
where that check turns out to be structurally uninformative against the *post-gate*
cache (the pipeline clears the very columns we'd need to see what a gate excluded), a
clearly-labeled "Supplementary" subsection reconstructs the pre-gate signal using only
existing, already-shipped helper functions (``_load_ust_reference_data``,
``_build_maturity_to_ust_map``, ``get_imm_label``) — still read-only, still no gate
logic touched.

Run: conda run -n stir python scripts/mms_detection_research.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(
    os.getenv(
        "MMS_CACHE_DIR",
        "sdr_cache/classification_cache/usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
        "curve1_fly1_mms1_invoice1_mac1_spreadover1_basis1_ptp3-mms-pkg",
    )
)
OUTPUT = Path("docs/superpowers/research/2026-07-09-mms-detection-depth.md")

# Mirrors the `_STANDARD_TENORS` list in SDRUtils.packages.mms.detect_mms_trades_df.
# That name is defined *inside* the function body there (not at module level), so it
# is not importable as-is. Duplicated here for this read-only research script; kept in
# sync manually with mms.py (the try/except below picks up a module-level export
# automatically if a future refactor promotes it).
_FALLBACK_STANDARD_TENORS = [
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27, 28, 29, 30,
]


def _standard_tenors() -> list:
    try:
        from SDRUtils.packages.mms import _STANDARD_TENORS  # type: ignore[attr-defined]

        return list(_STANDARD_TENORS)
    except ImportError:
        return list(_FALLBACK_STANDARD_TENORS)


def load_corpus() -> pd.DataFrame:
    """Load all per-date classified parquets into one frame."""
    files = sorted(CACHE_DIR.rglob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquets in {CACHE_DIR}")
    frames = [pd.read_parquet(f) for f in files]
    print(f"Loaded {len(frames)} day-files, {sum(len(f) for f in frames)} total rows")
    return pd.concat(frames, ignore_index=True)


def research_imm_start(df: pd.DataFrame) -> str:
    """4a: How many trades does the IMM gate currently exclude?"""
    required = {"ust_cusip", "forward_label", "expiration_date", "effective_date"}
    missing = required - set(df.columns)
    if missing:
        print(f"[4a] Skipping IMM-start analysis: missing columns {sorted(missing)}")
        return "## 4a. IMM-Start MMS False-Positive Analysis\n\nInsufficient columns in cache.\n"

    has_ust = df["ust_cusip"].notna() & (df["ust_cusip"].astype(str) != "")
    is_imm_label = df["forward_label"].fillna("").astype(str).str.upper().str.startswith("IMM_")
    imm_excluded = is_imm_label & has_ust
    n_excluded = int(imm_excluded.sum())

    lines = [
        "## 4a. IMM-Start MMS False-Positive Analysis",
        "",
        f"**IMM-labeled trades (`forward_label` starts with `IMM_`) with a UST maturity "
        f"match in the cached (post-gate) data:** {n_excluded}",
        "",
    ]
    if n_excluded > 0:
        sample_cols = [
            c for c in ["trade_id", "forward_label", "tenor_years", "ust_cusip", "expiration_date"]
            if c in df.columns
        ]
        sample = df.loc[imm_excluded].head(10)[sample_cols]
        lines.append("**Sample (first 10):**")
        lines.append("")
        lines.append(sample.to_markdown(index=False))
        lines.append("")
    lines.append(
        "This literal count is expected to be 0 (or near it) by construction: "
        "`_match_swaps_to_ust_by_maturity` clears `ust_cusip` / `matched_ust_maturity` "
        "for every row the IMM guard excludes, so the post-gate cache cannot show what "
        "the gate discarded — it can only confirm the gate isn't leaking. The "
        "supplementary analysis below reconstructs the excluded population "
        "independently to answer the actual research question."
    )
    lines.append("")

    # --- Supplementary: reconstruct what the gate discards, bypassing it -------------
    # Read-only: reuses the existing _load_ust_reference_data / _build_maturity_to_ust_map
    # helpers (no detection code touched) to redo the maturity join for the population the
    # IMM guard excludes -- forward_label starting with IMM_, OR both effective_date and
    # expiration_date independently landing on IMM dates (the gate's own "both_imm"
    # secondary condition in mms.py).
    lines.append("### Supplementary: reconstructing the gate's exclusion set")
    lines.append("")
    try:
        from SDRUtils.core.tenors import get_imm_label
        from SDRUtils.packages.mms import _build_maturity_to_ust_map, _load_ust_reference_data

        eff = pd.to_datetime(df["effective_date"], errors="coerce")
        exp = pd.to_datetime(df["expiration_date"], errors="coerce")
        # get_imm_label is a per-scalar-date check; cache it per unique date instead of
        # calling it once per row (175k rows -> ~6.6k unique dates in this corpus).
        uniq_dates = pd.Index(eff.dropna().unique()).union(pd.Index(exp.dropna().unique()))
        imm_date_cache = {d: get_imm_label(pd.Timestamp(d)) is not None for d in uniq_dates}
        eff_is_imm = eff.map(lambda d: imm_date_cache.get(d, False) if pd.notna(d) else False)
        exp_is_imm = exp.map(lambda d: imm_date_cache.get(d, False) if pd.notna(d) else False)
        both_imm = eff_is_imm & exp_is_imm
        is_imm_forward = is_imm_label | both_imm
        n_candidates = int(is_imm_forward.sum())

        ust_ref = _load_ust_reference_data()
        maturity_map = _build_maturity_to_ust_map(ust_ref)
        candidates = df.loc[is_imm_forward].copy()
        candidates["_swap_maturity_date"] = pd.to_datetime(
            candidates["expiration_date"], errors="coerce", utc=True
        ).dt.date
        joined = candidates.merge(
            maturity_map,
            left_on="_swap_maturity_date",
            right_on="maturity_date",
            how="left",
            suffixes=("", "_ref"),
        )
        ref_cusip_col = "ust_cusip_ref" if "ust_cusip_ref" in joined.columns else "ust_cusip"
        would_match = joined[ref_cusip_col].notna()
        n_would_match = int(would_match.sum())

        lines.append(
            f"**Trades caught by the gate's exclusion rule** (`forward_label` starts "
            f"with `IMM_`, OR both `effective_date` and `expiration_date` independently "
            f"land within 1 business day of an IMM date): {n_candidates} "
            f"({n_candidates / len(df):.1%} of the {len(df)}-row corpus)"
        )
        lines.append("")
        lines.append(
            f"**Of those, trades whose `expiration_date` independently ties a UST "
            f"maturity** (gate bypassed via a direct join against the maturity map): "
            f"{n_would_match}"
        )
        lines.append("")

        if n_would_match > 0:
            wm = joined.loc[would_match].copy()
            if "is_forward" in wm.columns:
                fwd_counts = wm["is_forward"].fillna(False).value_counts()
                lines.append("**Split by `is_forward`:**")
                lines.append("")
                lines.append(
                    fwd_counts.rename_axis("is_forward").rename("n_trades").to_frame().to_markdown()
                )
                lines.append("")
            if "forward_label" in wm.columns:
                spot_share = (wm["forward_label"].astype(str).str.lower() == "spot").mean()
                lines.append(
                    f"**Share labeled `forward_label == 'spot'`:** {spot_share:.1%} — a "
                    "spot-starting trade's `effective_date` is simply T+2 from execution, "
                    "not a deliberate IMM anchor, so a 'both dates near IMM' hit is much "
                    "more likely coincidental execution timing than a genuine IMM-to-IMM "
                    "roll."
                )
                lines.append("")
            sample_cols = [
                c for c in ["trade_id", "forward_label", "is_forward", "tenor_years", "package_type"]
                if c in wm.columns
            ]
            lines.append("**Sample (first 10, gate-bypass matches):**")
            lines.append("")
            lines.append(wm.head(10)[sample_cols].to_markdown(index=False))
            lines.append("")
    except Exception as exc:  # pragma: no cover - defensive; must not crash the run
        print(f"[4a] Supplementary gate-bypass analysis skipped: {exc!r}")
        lines.append(f"_Supplementary analysis unavailable: {exc!r}_")
        lines.append("")

    lines.append(
        "**Recommendation:** [Fill based on data — if n_excluded is small and "
        "all are standard IMM rolls, keep the gate. If some are off-the-run "
        "broken-tenor, consider a relaxed guard.]"
    )
    return "\n".join(lines)


def research_near_clean(df: pd.DataFrame) -> str:
    """4b: How many packages go partial→all-MMS with near-clean inclusion?"""
    required = {"package_id", "package_type", "matched_ust_maturity", "ust_cusip", "tenor_years"}
    missing = required - set(df.columns)
    if missing:
        print(f"[4b] Skipping near-clean analysis: missing columns {sorted(missing)}")
        return "## 4b. Near-Clean Broken-Tenor Quantification\n\nInsufficient columns in cache.\n"

    standard_tenors = _standard_tenors()

    # Find packaged legs that were wiped by is_clean_tenor but had a UST match
    has_ust = df["ust_cusip"].notna() & (df["ust_cusip"].astype(str) != "")
    mms_flag = df["matched_ust_maturity"].fillna(False).astype(bool)
    in_package = df["package_id"].notna() & (df["package_type"] != "OUTRIGHT")

    # Near-clean: within 0.1y of a standard tenor
    tenor = pd.to_numeric(df["tenor_years"], errors="coerce")
    is_near_clean = pd.Series(False, index=df.index)
    for t in standard_tenors:
        is_near_clean |= (tenor - t).abs() < 0.1

    # These are the legs that WOULD match but were excluded
    excluded_near_clean = in_package & has_ust & ~mms_flag & is_near_clean
    n_excluded = int(excluded_near_clean.sum())

    lines = [
        "## 4b. Near-Clean Broken-Tenor Quantification",
        "",
        f"**Packaged legs excluded by clean-tenor gate but with UST match:** {n_excluded}",
        "",
    ]

    # For each package, check if including near-clean legs would flip it to all-MMS.
    # The brief's literal question is "partial -> all-MMS", so we also split out
    # promotions that start from a genuinely-partial package (>=1 leg already matched
    # on a broken tenor) from "none -> all" cases, where a package with ZERO current
    # evidence would only look fully-matched because every leg happens to be a
    # near-clean/UST coincidence -- much weaker support for a real MMS structure.
    excluded_idx = excluded_near_clean[excluded_near_clean].index
    n_all = n_partial = n_none = 0
    promotions_naive = 0
    promotions_strict = 0
    none_to_all = 0
    for _pkg_id, grp in df.loc[in_package].groupby("package_id"):
        if len(grp) < 2:
            continue
        matched_bool = grp["matched_ust_maturity"].fillna(False).astype(bool)
        n_true = int(matched_bool.sum())
        n_tot = len(grp)
        if n_true == n_tot:
            n_all += 1
            continue  # already fully matched -- not a promotion candidate
        elif n_true == 0:
            n_none += 1
        else:
            n_partial += 1

        would_match = matched_bool | grp.index.isin(excluded_idx)
        if would_match.all():
            promotions_naive += 1
            if n_true > 0:
                promotions_strict += 1
            else:
                none_to_all += 1

    lines.append(
        f"**Package census** (packaged, non-OUTRIGHT, size >= 2): all-MMS={n_all}, "
        f"partial={n_partial}, none-matched={n_none}"
    )
    lines.append("")
    lines.append(
        f"**Packages that would flip to fully-matched if near-clean legs were "
        f"included** (any starting state, i.e. the brief's literal check): "
        f"{promotions_naive}"
    )
    lines.append("")
    lines.append(
        f"**...of which, genuinely partial -> all-MMS** (>=1 leg already matched on a "
        f"broken tenor before near-clean inclusion): {promotions_strict} "
        f"(of {n_partial} currently-partial packages)"
    )
    lines.append("")
    lines.append(
        f"**...and \"none -> all\"** (zero currently-matched legs; the promotion would "
        f"rest entirely on coincidental near-clean/UST overlaps with no corroborating "
        f"broken-tenor evidence anywhere in the package): {none_to_all}"
    )
    lines.append("")

    if n_excluded > 0:
        sample_cols = [
            c for c in ["trade_id", "package_id", "package_type", "tenor_years", "ust_cusip", "expiration_date"]
            if c in df.columns
        ]
        sample = df.loc[excluded_near_clean].head(10)[sample_cols]
        lines.append("**Sample (first 10):**")
        lines.append("")
        lines.append(sample.to_markdown(index=False))
        lines.append("")
    lines.append(
        "**Recommendation:** [Fill based on data — if promotions is small, "
        "keep the gate strict. If substantial, consider context-aware relaxation "
        "with a dedicated false-positive guard.]"
    )
    return "\n".join(lines)


def research_tbill(df: pd.DataFrame) -> str:
    """4c: Among short-dated matches, how many are T-bills vs coupon notes?"""
    required = {"matched_ust_maturity", "tenor_years", "ust_cusip"}
    missing = required - set(df.columns)
    if missing:
        print(f"[4c] Skipping T-bill analysis: missing columns {sorted(missing)}")
        return "## 4c. T-Bill vs Short-Note Data Study\n\nInsufficient columns in cache.\n"

    mms_flag = df["matched_ust_maturity"].fillna(False).astype(bool)
    tenor = pd.to_numeric(df["tenor_years"], errors="coerce")
    short = mms_flag & (tenor < 1.0)
    n_short = int(short.sum())

    lines = [
        "## 4c. T-Bill vs Short-Note Data Study",
        "",
        f"**Short-dated (<1Y) MMS matches:** {n_short}",
        "",
    ]

    if n_short == 0:
        lines.append("No short-dated MMS matches found.")
        lines.append("")
        lines.append(
            "**Recommendation:** [Fill based on data — if all short-dated matches "
            "are T-bills, add an exclusion gate. If some are short-dated notes, "
            "keep the low-confidence tag.]"
        )
        return "\n".join(lines)

    try:
        from SDRUtils.packages.mms import _load_ust_reference_data

        ust_ref = _load_ust_reference_data()
    except Exception as exc:  # pragma: no cover - defensive; must not crash the run
        print(f"[4c] Could not load UST reference data: {exc!r}")
        ust_ref = None

    short_cusips = df.loc[short, "ust_cusip"].dropna().unique()
    if ust_ref is not None and len(short_cusips) > 0 and "cusip" in ust_ref.columns:
        matched = ust_ref[ust_ref["cusip"].isin(short_cusips)]
        if "security_type" in matched.columns:
            type_counts = matched.groupby("security_type").size()
            lines.append("**Matched UST security types (distinct CUSIPs):**")
            lines.append("")
            lines.append(type_counts.to_markdown())
            lines.append("")
        else:
            print("[4c] 'security_type' not present in UST reference data; skipping that breakdown")
        cusip_prefix = pd.Series(short_cusips, dtype=str)
        n_bills_cusip = int(cusip_prefix.str.startswith("912797").sum())
        n_notes_cusip = len(cusip_prefix) - n_bills_cusip
        lines.append(
            f"**By CUSIP prefix (distinct CUSIPs, not trade-weighted):** 912797* "
            f"(bills): {n_bills_cusip}, other (notes/bonds): {n_notes_cusip}"
        )
        lines.append("")

    # Supplementary: `ust_oi` (original-issue term, e.g. "26-Week" vs "2-Year") is
    # already merged onto every trade row in the cache -- no extra reference-data
    # join needed, and unlike the CUSIP-prefix count above it is trade-weighted (a
    # heavily-reused bill CUSIP counts once above, N times here).
    if "ust_oi" in df.columns:
        oi_counts = df.loc[short, "ust_oi"].value_counts(dropna=False)
        lines.append("### Supplementary: trade-weighted breakdown via `ust_oi`")
        lines.append("")
        lines.append(oi_counts.rename_axis("ust_oi").rename("n_trades").to_frame().to_markdown())
        lines.append("")

        is_bill = df.loc[short, "ust_oi"].astype(str).str.contains("Week", na=False)
        n_bills = int(is_bill.sum())
        n_notes = n_short - n_bills
        lines.append(
            f"**Trade-weighted bill vs. note split:** {n_bills} bills "
            f"({n_bills / n_short:.1%}), {n_notes} notes/bonds with <1Y remaining "
            f"({n_notes / n_short:.1%})"
        )
        lines.append("")

        if "matched_ust_maturity_trade_confidence" in df.columns:
            conf_x_type = pd.crosstab(
                df.loc[short, "matched_ust_maturity_trade_confidence"],
                is_bill.map({True: "bill", False: "note/bond"}),
            )
            lines.append(
                "**Existing `matched_ust_maturity_trade_confidence` tag vs. bill/note** "
                "(does the existing soft-confidence tag already discriminate the two?):"
            )
            lines.append("")
            lines.append(conf_x_type.to_markdown())
            lines.append("")
    else:
        print("[4c] 'ust_oi' column not present; skipping trade-weighted bill/note breakdown")

    sample_cols = [
        c for c in ["trade_id", "tenor_years", "ust_cusip", "ust_oi", "matched_ust_maturity_trade_confidence"]
        if c in df.columns
    ]
    lines.append("**Sample (first 10, short-dated matches):**")
    lines.append("")
    lines.append(df.loc[short].head(10)[sample_cols].to_markdown(index=False))
    lines.append("")

    lines.append(
        "**Recommendation:** [Fill based on data — if all short-dated matches "
        "are T-bills, add an exclusion gate. If some are short-dated notes, "
        "keep the low-confidence tag.]"
    )
    return "\n".join(lines)


def main():
    df = load_corpus()

    if "execution_date" in df.columns:
        n_days = df["execution_date"].nunique()
    elif "execution_timestamp" in df.columns:
        n_days = pd.to_datetime(df["execution_timestamp"], errors="coerce", utc=True).dt.date.nunique()
    else:
        n_days = "?"

    sections = [
        "# MMS Detection Depth — Empirical Research",
        "",
        "**Date:** 2026-07-09",
        f"**Corpus:** {len(df)} rows across {n_days} days",
        "**Cache version:** ptp3-mms-pkg",
        "",
        "This document reports empirical data for three detection-depth gaps. "
        "No detection code was changed; these are read-only analyses. Each section "
        "reproduces the literal check from the Task 8 brief and, where that check is "
        "structurally uninformative against the post-gate cache (the pipeline clears "
        "the very columns needed to see what a gate excluded), adds a clearly-labeled "
        "supplementary analysis that reconstructs the pre-gate signal using existing, "
        "already-shipped helper functions — still read-only, still no gate logic "
        "touched.",
        "",
        research_imm_start(df),
        "",
        research_near_clean(df),
        "",
        research_tbill(df),
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"Research doc written to {OUTPUT}")


if __name__ == "__main__":
    main()
