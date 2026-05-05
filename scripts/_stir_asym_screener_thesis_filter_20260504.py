"""Filter the 2026-05-04 hold-thesis screener output to thesis-aligned trades.

Real-world context (fixings as of 2026-05-01):
    EFFR: 3.6400%
    SOFR: 3.6400%
    Spot Fed funds target: ~3.50-3.75% (midpoint ~3.625%)

SR3 forwards on 2026-05-04:
    SFRM26 (Jun, 44 DTE):  96.345  →  implied 3.6550%  ≈ spot
    SFRU26 (Sep, 135 DTE): 96.295  →  implied 3.7050%  +5.5bp vs spot
    SFRZ26 (Dec, 226 DTE): 96.205  →  implied 3.7950%  +15.5bp vs spot

Strip prices a *modest hawkish drift* into back-end 2026: ~16bp of hikes
priced by Dec'26. Front (Jun'26) is essentially fair to spot.

THESIS: FOMC holds rates FLAT at ~3.64% through 2026 (no cuts, no hikes).
→ futures need to RALLY toward 96.36 (= spot) by their respective expiries.
→ payoff: SFRM26 ~+1 tick, SFRU26 ~+6 ticks, SFRZ26 ~+16 ticks.

Aligned structures:
    - LONG CALLS / CALL SPREADS / CALL RATIOS (rally trade)
    - PUT spreads to FADE the cut narrative are *not* the dominant edge
      because the market isn't pricing cuts on this date; it's pricing hikes.
    - Range-bound CONDORS centered on 96.36 (~spot) also align (bet on
      rates staying flat = futures staying near spot).
"""

from __future__ import annotations

import datetime
import json as _json
import sys
from pathlib import Path

import pandas as pd

from RVUtils.STIRAsymmetricScreener._market_data import _default_smile_loader


# Spot Fed-funds proxy (EFFR fixing 2026-05-01)
SPOT_RATE = 0.0364
SPOT_PRICE = 100.0 - SPOT_RATE * 100.0  # 96.36


def main():
    sys.stdout.reconfigure(line_buffering=True)
    parquet_path = Path("data/screener_results/stir_asymmetric_screener/2026-05-04/snapshot.parquet")
    df = pd.read_parquet(parquet_path)

    fwds = {}
    for contract in ["SFRM26", "SFRU26", "SFRZ26"]:
        try:
            smile = _default_smile_loader(
                contract=contract,
                as_of=datetime.date(2026, 5, 4),
                options_source="BARCHART_STIRFO-QL",
            )
            fwds[contract] = float(smile.params.forward_price)
            implied = 100.0 - fwds[contract]
            drift = (implied - SPOT_RATE * 100.0) * 100.0
            print(
                f"{contract}: forward={fwds[contract]:.4f}  implied={implied:.4f}%  "
                f"drift_vs_spot={drift:+.1f}bp",
                flush=True,
            )
        except Exception as e:
            print(f"{contract}: smile fetch failed: {e}", flush=True)
    print(f"\nSpot SOFR/EFFR (2026-05-01): {SPOT_RATE * 100:.4f}%  → futures-equivalent {SPOT_PRICE:.4f}", flush=True)
    print(f"Thesis: futures rally toward {SPOT_PRICE:.4f} by each expiry", flush=True)

    # --- Decoders -------------------------------------------------------------
    def _decode_legs(legs_raw):
        if isinstance(legs_raw, str):
            try:
                return _json.loads(legs_raw)
            except Exception:
                return []
        return legs_raw if isinstance(legs_raw, list) else []

    def _legs_str(legs):
        parts = []
        for leg in legs:
            qty = leg.get("quantity", 0)
            sign = "+" if qty > 0 else ""
            parts.append(f"{sign}{qty}{leg['right']}{leg['strike']:.4f}".rstrip("0").rstrip("."))
        return " | ".join(parts)

    def _is_call_thesis_aligned(legs):
        """Aligned: structure pays when futures rally toward spot price ~96.36.

        Rules:
        - Pure call structures with net long calls, long-strike-avg < short-strike-avg
          (long near-OTM, short further-OTM call → debit call spread / call ratio).
        - Single long call.
        - Reject pure-put structures (different thesis).
        """
        if not legs:
            return False
        rights = {leg.get("right") for leg in legs}
        if "P" in rights:
            return False  # pure call structures only
        long_strike_sum = 0.0
        long_qty_sum = 0
        short_strike_sum = 0.0
        short_qty_sum = 0
        for leg in legs:
            qty = leg.get("quantity", 0)
            k = leg.get("strike", 0.0)
            if qty > 0:
                long_strike_sum += qty * k
                long_qty_sum += qty
            else:
                short_strike_sum += abs(qty) * k
                short_qty_sum += abs(qty)
        if long_qty_sum == 0:
            return False
        if short_qty_sum == 0:
            return True
        long_avg = long_strike_sum / long_qty_sum
        short_avg = short_strike_sum / short_qty_sum
        # Long call wins when long_avg < short_avg (debit call spread)
        return long_avg < short_avg

    def _is_range_bound_aligned(legs):
        """Condor / fly centered near spot (96.36 ± 25bp): bet on rates staying flat."""
        if not legs:
            return False
        if len({l.get("right") for l in legs}) > 1:
            return False
        strikes = sorted(l["strike"] for l in legs)
        if not strikes:
            return False
        center = 0.5 * (strikes[0] + strikes[-1])
        return abs(center - SPOT_PRICE) <= 0.30

    df["legs_decoded"] = df["legs"].apply(_decode_legs)
    df["legs_str"] = df["legs_decoded"].apply(_legs_str)
    df["call_aligned"] = df["legs_decoded"].apply(_is_call_thesis_aligned)
    df["range_aligned"] = df["legs_decoded"].apply(_is_range_bound_aligned)

    # Filter: realistic premium / asymmetry
    real = (
        (df["net_premium"].abs() >= 0.25)
        & (df["net_premium"].abs() <= 50.0)
        & (df["asymmetry_ratio"] >= 4.0)
        & (df["asymmetry_ratio"] <= 100.0)
        & (df["max_loss"] < -0.25)
    )
    debit_only = df["net_premium"] > 0

    cols = [
        "structure_type", "underlying", "dte", "asymmetry_ratio",
        "max_payoff", "max_loss", "net_premium", "legs_str",
    ]

    pd.set_option("display.max_colwidth", 220)
    pd.set_option("display.width", 240)

    # --- Bucket 1: directional CALL plays (futures rally to spot) -----------
    call_aligned = df[real & debit_only & df["call_aligned"]].copy()
    call_aligned = call_aligned.sort_values("asymmetry_ratio", ascending=False)
    print("\n" + "=" * 100, flush=True)
    print(f"BUCKET 1 — DIRECTIONAL CALL STRUCTURES (futures rally to {SPOT_PRICE:.4f})", flush=True)
    print(f"  → SFRZ26 has the widest mispricing ({(SPOT_RATE - 0.03795) * 10000:+.1f}bp tail);"
          f" front-end is closer to fair", flush=True)
    print("=" * 100, flush=True)
    print(f"Total: {len(call_aligned)} candidates", flush=True)
    print("\nTOP 10:", flush=True)
    print(call_aligned.head(10)[cols].to_string(index=False), flush=True)

    # By archetype (top 3)
    print("\nBy archetype (top 3 each):", flush=True)
    for archetype in ["wide_vertical", "ratio", "wing", "tree"]:
        subset = call_aligned[call_aligned["structure_type"] == archetype].head(3)
        if subset.empty:
            print(f"\n  {archetype}: (no candidates)", flush=True)
            continue
        print(f"\n  {archetype}:", flush=True)
        print(subset[cols].to_string(index=False), flush=True)

    # By underlying (top 3)
    print("\nBy underlying (top 3 each):", flush=True)
    for u in sorted(call_aligned["underlying"].unique()):
        fwd_str = f"fwd={fwds[u]:.4f}" if u in fwds else ""
        subset = call_aligned[call_aligned["underlying"] == u].head(3)
        print(f"\n  {u} ({fwd_str}):", flush=True)
        print(subset[cols].to_string(index=False), flush=True)

    # --- Bucket 2: range-bound (condors centered on spot) -------------------
    range_aligned = df[real & debit_only & df["range_aligned"]].copy()
    range_aligned = range_aligned.sort_values("asymmetry_ratio", ascending=False)
    if not range_aligned.empty:
        print("\n" + "=" * 100, flush=True)
        print(
            f"BUCKET 2 — RANGE-BOUND STRUCTURES (centered within ±30bp of spot {SPOT_PRICE:.4f})",
            flush=True,
        )
        print("  → Bet on rates staying flat; condors / flies bracket the spot.", flush=True)
        print("=" * 100, flush=True)
        print(f"Total: {len(range_aligned)} candidates", flush=True)
        print("\nTOP 10:", flush=True)
        print(range_aligned.head(10)[cols].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
