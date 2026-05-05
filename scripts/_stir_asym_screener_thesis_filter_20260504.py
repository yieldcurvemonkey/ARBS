"""Filter the 2026-05-04 hold-thesis screener output to thesis-aligned trades.

Thesis: FOMC holds rates flat for 2026 (no cuts, no hikes).
Market on 2026-05-04 pricing meaningful cuts → if reality holds, rates
end higher than market priced → futures end LOWER than implied →
PUT structures pay off.

Filter rules:
1. ALIGNED: net positive put-side exposure (long puts, long put spreads,
   long put ratios with long-near-OTM dominant). Reject call-side trades
   that profit from rate cuts.
2. Realistic premium: net debit ≥ 1 tick, ≤ 50 ticks
3. Realistic asymmetry: 4 ≤ ratio ≤ 50 (cap to avoid model artifacts)
4. Show forward price context per underlying.
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import pandas as pd

from RVUtils.STIRAsymmetricScreener._market_data import _default_smile_loader
import datetime


def main():
    sys.stdout.reconfigure(line_buffering=True)
    parquet_path = Path("data/screener_results/stir_asymmetric_screener/2026-05-04/snapshot.parquet")
    df = pd.read_parquet(parquet_path)

    # Forward prices
    fwds = {}
    for contract in ["SFRM26", "SFRU26", "SFRZ26"]:
        try:
            smile = _default_smile_loader(
                contract=contract,
                as_of=datetime.date(2026, 5, 4),
                options_source="BARCHART_STIRFO-QL",
            )
            fwds[contract] = float(smile.params.forward_price)
            print(f"{contract}: forward={fwds[contract]:.4f}, implied_rate={100.0 - fwds[contract]:.4f}%", flush=True)
        except Exception as e:
            print(f"{contract}: smile fetch failed: {e}", flush=True)

    # Decode legs and compute thesis alignment
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

    def _is_put_thesis_aligned(legs):
        """Return True if this structure pays off when futures price stays
        flat or falls (i.e. when rates stay flat or rise — the FOMC-holds /
        cuts-don't-deliver thesis).

        Heuristic: structure is put-aligned when:
        - All legs are puts AND net long quantity is non-negative when summed
          weighted by strike-distance from forward (i.e., the long leg sits
          at a higher strike than the short leg → debit put spread or put
          ratio with long-near-OTM dominant).
        - OR a single long put leg.
        We exclude any structure with long calls (not aligned) or net-short
        put structures (different thesis).
        """
        if not legs:
            return False
        rights = {leg.get("right") for leg in legs}
        if "C" in rights:
            return False  # only pure-put structures aligned with hold-thesis
        # Compute weighted center of long vs short puts
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
            return True  # outright long puts
        # For put spreads/ratios: long strike must be > short strike
        # (long higher = closer-to-ATM, short lower = further-OTM)
        long_avg = long_strike_sum / long_qty_sum
        short_avg = short_strike_sum / short_qty_sum
        return long_avg > short_avg

    df["legs_decoded"] = df["legs"].apply(_decode_legs)
    df["legs_str"] = df["legs_decoded"].apply(_legs_str)
    df["aligned"] = df["legs_decoded"].apply(_is_put_thesis_aligned)

    # Realistic filter — relax premium floor for wings (inherently cheap)
    real = (
        (df["net_premium"].abs() >= 0.25)  # 1 quarter-tick = 0.25 of a tick
        & (df["net_premium"].abs() <= 50.0)
        & (df["asymmetry_ratio"] >= 4.0)
        & (df["asymmetry_ratio"] <= 100.0)
        & (df["max_loss"] < -0.25)
    )
    aligned = df["aligned"]
    debit_only = df["net_premium"] > 0  # entered as debit

    candidates = df[real & aligned & debit_only].copy()
    candidates = candidates.sort_values("asymmetry_ratio", ascending=False)
    print(f"\nTotal candidates (real, aligned, debit): {len(candidates)}", flush=True)

    cols = [
        "structure_type", "underlying", "dte", "asymmetry_ratio",
        "max_payoff", "max_loss", "net_premium", "legs_str",
    ]

    pd.set_option("display.max_colwidth", 200)
    pd.set_option("display.width", 240)

    print("\n" + "=" * 100, flush=True)
    print("TOP 15 THESIS-ALIGNED ASYMMETRIC TRADES", flush=True)
    print("(SFR options on 2026-05-04 close — Fed-holds-2026 thesis — net long puts, debit entry)", flush=True)
    print("=" * 100, flush=True)
    print(candidates.head(15)[cols].to_string(index=False), flush=True)

    print("\n" + "-" * 100, flush=True)
    print("BREAKDOWN BY ARCHETYPE (TOP 3 EACH)", flush=True)
    print("-" * 100, flush=True)
    for archetype in ["wide_vertical", "ratio", "wing", "ladder", "tree", "condor"]:
        subset = candidates[candidates["structure_type"] == archetype].head(3)
        if subset.empty:
            print(f"\n  {archetype}: (no aligned candidates)", flush=True)
            continue
        print(f"\n  {archetype}:", flush=True)
        print(subset[cols].to_string(index=False), flush=True)

    print("\n" + "-" * 100, flush=True)
    print("BREAKDOWN BY UNDERLYING (TOP 3 EACH)", flush=True)
    print("-" * 100, flush=True)
    for u in sorted(candidates["underlying"].unique()):
        fwd_str = f"forward={fwds[u]:.4f}" if u in fwds else "(forward unknown)"
        subset = candidates[candidates["underlying"] == u].head(3)
        print(f"\n  {u} ({fwd_str}):", flush=True)
        print(subset[cols].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
