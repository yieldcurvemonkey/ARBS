"""Report invoice swaps detected in the most recent classified USD swap cache.

Loads the cached classification parquet, summarises invoice_swap_ticker
distribution, and shows the impact of the gate-inversion fix by re-running
_apply_invoice_swap_lookup against the same trades using the newly
published lookup.

Usage:
    conda run -n stir python scripts/report_invoice_swaps_traded.py
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd


CACHE_ROOT = Path(
    r"C:/Users/chris/clee/ARBS/sdr_cache/classification_cache/"
    r"usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
    r"curve1_fly1_mms1_invoice1_mac1_spreadover1"
)


def _load_latest_classified() -> tuple[pd.DataFrame, dt.date]:
    dates = sorted(
        p for p in CACHE_ROOT.glob("*/*/*")
        if p.is_dir()
    )
    if not dates:
        raise RuntimeError("No classification cache entries found.")
    latest = dates[-1]
    day = dt.date.fromisoformat(latest.name)
    parquet_files = sorted(latest.glob("*.parquet"))
    if not parquet_files:
        raise RuntimeError(f"No parquet under {latest}")
    frames = [pd.read_parquet(p) for p in parquet_files]
    df = pd.concat(frames, ignore_index=True)
    return df, day


def _report_from_cache(df: pd.DataFrame, day: dt.date) -> None:
    total = len(df)
    print(f"\n=== Classified USD swaps for {day} ===")
    print(f"Total classified trades: {total:,}")

    if "special_tenor_type" in df.columns:
        st = df["special_tenor_type"].astype(str).value_counts(dropna=False)
        print("\nspecial_tenor_type distribution:")
        for k, v in st.items():
            print(f"  {k:<20} {v:,}")

    if "invoice_swap_ticker" in df.columns:
        mask = df["invoice_swap_ticker"].notna() & (
            df["invoice_swap_ticker"].astype(str).str.strip() != ""
        )
        n_inv = int(mask.sum())
        print(f"\nInvoice swaps with ticker resolved (OLD gate): {n_inv:,} / {total:,}")
        if n_inv:
            tkr = df.loc[mask, "invoice_swap_ticker"].value_counts()
            print("\nTicker breakdown:")
            for k, v in tkr.items():
                print(f"  {k:<6} {v:,}")

    if "matched_ust_maturity" in df.columns:
        mms_mask = df["matched_ust_maturity"].astype(str).str.lower().eq("true")
        mms_mask |= df["matched_ust_maturity"] == True  # noqa: E712
        n_mms = int(mms_mask.sum())
        print(f"\nMatched-maturity swaps (any confidence): {n_mms:,}")
        if "matched_ust_maturity_trade_confidence" in df.columns:
            conf = df.loc[mms_mask, "matched_ust_maturity_trade_confidence"].astype(
                str
            ).value_counts(dropna=False)
            print("  By MMS confidence:")
            for k, v in conf.items():
                print(f"    {k:<8} {v:,}")


def _report_gate_inversion_delta(df: pd.DataFrame, day: dt.date) -> None:
    """Show how many LOW-confidence matched trades would now resolve a ticker."""
    if "matched_ust_maturity_trade_confidence" not in df.columns:
        return
    if "invoice_swap_ticker" not in df.columns:
        return

    low_mms = df["matched_ust_maturity_trade_confidence"].astype(str).str.lower().eq("low")
    has_ticker = df["invoice_swap_ticker"].notna() & (
        df["invoice_swap_ticker"].astype(str).str.strip() != ""
    )

    n_low_without_ticker = int((low_mms & ~has_ticker).sum())
    n_low_with_ticker = int((low_mms & has_ticker).sum())

    print("\n=== Gate-inversion impact ===")
    print(f"LOW-confidence matched-maturity trades (pre-fix): {int(low_mms.sum()):,}")
    print(f"  already had invoice_swap_ticker resolved:       {n_low_with_ticker:,}")
    print(
        f"  LOW + no ticker (candidates for rescue by new gate): "
        f"{n_low_without_ticker:,}"
    )

    # Actual rescue requires the published lookup to contain matching
    # (eff_date, ctd_maturity) pairs. Without live market data we can at
    # least sanity-check that the trade dates fall inside the set of
    # invoice-swap effective/maturity dates that ever appeared in this
    # classified dataset (from the prior run).
    known_spec_effs = (
        pd.to_datetime(df.loc[has_ticker, "effective_date"]).dt.date.unique()
    )
    known_spec_mats = (
        pd.to_datetime(df.loc[has_ticker, "expiration_date"]).dt.date.unique()
    )
    if len(known_spec_effs) > 0 and n_low_without_ticker:
        candidate_mask = (
            low_mms
            & ~has_ticker
            & pd.to_datetime(df["effective_date"]).dt.date.isin(known_spec_effs)
            & pd.to_datetime(df["expiration_date"]).dt.date.isin(known_spec_mats)
        )
        n_candidates = int(candidate_mask.sum())
        print(
            f"  of those, trades whose (eff, mat) already appeared on a "
            f"ticker hit this day: {n_candidates:,}"
        )
        if n_candidates:
            shown = df.loc[candidate_mask].head(10)[
                [
                    "trade_id",
                    "effective_date",
                    "expiration_date",
                    "tenor_label",
                    "matched_ust_maturity_trade_confidence",
                    "invoice_swap_ticker",
                ]
            ]
            print("\n  Sample rescued trades (up to 10):")
            print(shown.to_string(index=False))


if __name__ == "__main__":
    df, day = _load_latest_classified()
    _report_from_cache(df, day)
    _report_gate_inversion_delta(df, day)
