"""Diagnose RL vs QL pricing divergence — focused on the bpv=-bpv sign flip."""

import datetime
import numpy as np
import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

T1 = datetime.date(2024, 6, 3)
T2 = datetime.date(2024, 6, 4)
CURVE = "USD-SOFR-1D"

print("Loading curves...")
mdp_rl = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
mdp_ql = IRSwapsMDP(source="ERIS_EOD_LIVE-QL_BASIC")

c_rl_1 = mdp_rl.get_data({"curve_name": CURVE, "timestamp": T1})
c_rl_2 = mdp_rl.get_data({"curve_name": CURVE, "timestamp": T2})
c_ql_1 = mdp_ql.get_data({"curve_name": CURVE, "timestamp": T1})
c_ql_2 = mdp_ql.get_data({"curve_name": CURVE, "timestamp": T2})
print("Done.\n")

# ═══════════════════════════════════════════════════════════════════════
# TEST A: build_irswap with bpv=+100000 (outright 2Y)
# ═══════════════════════════════════════════════════════════════════════
print("=" * 70)
print("TEST A: build_irswap(fwd='0D', tenor='2Y', bpv=+100000)")
print("=" * 70)

s_rl = c_rl_1.build_irswap(fwd="0D", tenor="2Y", bpv=100_000)
s_ql = c_ql_1.build_irswap(fwd="0D", tenor="2Y", bpv=100_000)

# Notional and direction
not_rl = c_rl_1.notional(s_rl)
not_ql = c_ql_1.notional(s_ql)
print(f"  RL notional: {not_rl:>15,.0f}  (positive = receiver)")
print(f"  QL notional: {not_ql:>15,.0f}  (QL: bpv=-bpv at line 27 inverts)")

# PV01 / BPS
pv01_rl = c_rl_1.pv01(s_rl)
pv01_ql = c_ql_1.pv01(s_ql)
print(f"\n  RL pv01 (analytic_delta): {pv01_rl:>12,.2f}  (positive = recv convention)")
print(f"  QL pv01 (fixedLegBPS):   {pv01_ql:>12,.2f}  (negative = recv, positive = pay)")

# Entry NPV via resolve_pricable (how the backtest does it)
res_rl = c_rl_1.resolve_pricable(s_rl, risk_weight=1.0)
res_ql = c_ql_1.resolve_pricable(s_ql, risk_weight=1.0)
print(f"\n  After resolve_pricable(rw=1.0):")
print(f"    RL resolved notional: {c_rl_1.notional(res_rl):>15,.0f}  (always negated)")
print(f"    QL resolved notional: {c_ql_1.notional(res_ql):>15,.0f}  (direction from rw)")

entry_npv_rl = c_rl_1.npv(res_rl)
entry_npv_ql = c_ql_1.npv(res_ql)
print(f"\n  Entry NPV (resolved):")
print(f"    RL: {entry_npv_rl:>15,.2f}")
print(f"    QL: {entry_npv_ql:>15,.2f}")

# T+1 mark
res_rl_2 = c_rl_2.resolve_pricable(s_rl, risk_weight=1.0)
res_ql_2 = c_ql_2.resolve_pricable(s_ql, risk_weight=1.0)
mark_npv_rl = c_rl_2.npv(res_rl_2)
mark_npv_ql = c_ql_2.npv(res_ql_2)
print(f"\n  T+1 NPV (resolved):")
print(f"    RL: {mark_npv_rl:>15,.2f}")
print(f"    QL: {mark_npv_ql:>15,.2f}")

pnl_rl = mark_npv_rl - entry_npv_rl
pnl_ql = mark_npv_ql - entry_npv_ql
print(f"\n  1-day P&L = T+1 - entry:")
print(f"    RL: {pnl_rl:>15,.2f}")
print(f"    QL: {pnl_ql:>15,.2f}")
print(f"    Ratio (RL/QL): {pnl_rl/pnl_ql:.4f}" if pnl_ql != 0 else "    QL P&L is zero")

# ═══════════════════════════════════════════════════════════════════════
# TEST B: Same but with bpv=-100000 (should give opposite direction)
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST B: build_irswap(fwd='0D', tenor='2Y', bpv=-100000)")
print("=" * 70)

sn_rl = c_rl_1.build_irswap(fwd="0D", tenor="2Y", bpv=-100_000)
sn_ql = c_ql_1.build_irswap(fwd="0D", tenor="2Y", bpv=-100_000)
print(f"  RL notional: {c_rl_1.notional(sn_rl):>15,.0f}")
print(f"  QL notional: {c_ql_1.notional(sn_ql):>15,.0f}")

resn_rl = c_rl_1.resolve_pricable(sn_rl, risk_weight=-1.0)
resn_ql = c_ql_1.resolve_pricable(sn_ql, risk_weight=-1.0)
print(f"\n  After resolve_pricable(rw=-1.0):")
print(f"    RL resolved notional: {c_rl_1.notional(resn_rl):>15,.0f}  (always negated)")
print(f"    QL resolved notional: {c_ql_1.notional(resn_ql):>15,.0f}  (direction from rw)")

entry_n_rl = c_rl_1.npv(resn_rl)
entry_n_ql = c_ql_1.npv(resn_ql)
resn_rl_2 = c_rl_2.resolve_pricable(sn_rl, risk_weight=-1.0)
resn_ql_2 = c_ql_2.resolve_pricable(sn_ql, risk_weight=-1.0)
mark_n_rl = c_rl_2.npv(resn_rl_2)
mark_n_ql = c_ql_2.npv(resn_ql_2)
pnl_n_rl = mark_n_rl - entry_n_rl
pnl_n_ql = mark_n_ql - entry_n_ql
print(f"\n  1-day P&L:")
print(f"    RL: {pnl_n_rl:>15,.2f}")
print(f"    QL: {pnl_n_ql:>15,.2f}")
print(f"    Ratio: {pnl_n_rl/pnl_n_ql:.4f}" if pnl_n_ql != 0 else "    QL P&L is zero")

# ═══════════════════════════════════════════════════════════════════════
# TEST C: Check what QL builds WITHOUT the bpv=-bpv negation
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST C: What if QL didn't have bpv=-bpv? (manual sizing)")
print("=" * 70)

# Build a unit swap and manually scale
unit_ql = c_ql_1.build_irswap(fwd="0D", tenor="2Y", notional=1)
bps_unit = c_ql_1.pv01(unit_ql)  # fixedLegBPS for unit receiver
print(f"  Unit QL swap BPS: {bps_unit:.8f}")
print(f"  (negative for receiver: rate up -> fixed leg loses)")

# Scale to get bpv=+100000 without the -bpv trick:
# We want fixedLegBPS * notional_scale = -100000 (negative because receiver)
# So notional_scale = -100000 / bps_unit
manual_scale = -100_000 / bps_unit
# But we need it as receiver, so copysign to match positive BPV → receiver
# Actually just compute: we want positive BPV (= receiver = gain when rates fall)
# fixedLegBPS is the NPV change per +1bp rate increase
# For receiver: BPS < 0, so BPV = -BPS should be positive
# Target: BPV = 100000, so -BPS*N = 100000, so N = -100000/BPS
target_notional = -100_000 / bps_unit
print(f"  Manual target notional (for bpv=+100000 receiver): {target_notional:,.0f}")

manual_swap = c_ql_1.build_irswap(fwd="0D", tenor="2Y", notional=target_notional)
print(f"  Manual swap notional: {c_ql_1.notional(manual_swap):>15,.0f}")
print(f"  Manual swap BPS: {c_ql_1.pv01(manual_swap):>12,.2f}")

# Compare with what bpv= produces
print(f"\n  vs bpv=100000 swap:")
print(f"  bpv swap notional: {c_ql_1.notional(s_ql):>15,.0f}")
print(f"  bpv swap BPS:      {c_ql_1.pv01(s_ql):>12,.2f}")

# ═══════════════════════════════════════════════════════════════════════
# TEST D: Fair rate comparison between RL and QL across tenors
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST D: Fair rate comparison across tenors")
print("=" * 70)

for tenor in ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]:
    try:
        s_rl_t = c_rl_1.build_irswap(fwd="0D", tenor=tenor)
        s_ql_t = c_ql_1.build_irswap(fwd="0D", tenor=tenor)
        fr_rl = c_rl_1.fair_rate(s_rl_t)  # Returns decimal
        fr_ql = c_ql_1.fair_rate(s_ql_t)  # Returns decimal
        diff = (fr_rl - fr_ql) * 10000
        print(f"  {tenor:>3s}:  RL={fr_rl:.6f}  QL={fr_ql:.6f}  diff={diff:+.2f}bp")
    except Exception as e:
        print(f"  {tenor:>3s}:  Error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# TEST E: Forward rates (the actual fly components)
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST E: Forward rate comparison (fly components)")
print("=" * 70)

for fwd_tenor in ["1Yx1Y", "2Yx1Y", "3Yx1Y"]:
    try:
        s_rl_f = c_rl_1.build_irswap(fwd=fwd_tenor.split("x")[0], tenor=fwd_tenor.split("x")[1])
        s_ql_f = c_ql_1.build_irswap(fwd=fwd_tenor.split("x")[0], tenor=fwd_tenor.split("x")[1])
        fr_rl = c_rl_1.fair_rate(s_rl_f)
        fr_ql = c_ql_1.fair_rate(s_ql_f)
        diff = (fr_rl - fr_ql) * 10000
        print(f"  {fwd_tenor:>6s}:  RL={fr_rl:.6f}  QL={fr_ql:.6f}  diff={diff:+.2f}bp")
    except Exception as e:
        print(f"  {fwd_tenor:>6s}:  Error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ROOT CAUSE ANALYSIS")
print("=" * 70)
print(f"""
1. QL build_ql_irswap() has 'bpv = -bpv' at line 27 (ql_pricer.py).
   For bpv=+100000: RL builds RECEIVER (notional=+{abs(not_rl):,.0f})
                     QL builds PAYER   (notional={not_ql:,.0f})

   The QL swap is the OPPOSITE direction from RL for the same BPV input.

2. RL resolve_pricable() ALWAYS negates notional (line 205).
   QL resolve_pricable() uses risk_weight to determine sign.

   After resolve_pricable(rw=1.0):
     RL: {c_rl_1.notional(res_rl):,.0f} (receiver → payer)
     QL: {c_ql_1.notional(res_ql):,.0f} (payer → still payer? or receiver?)

3. Combined effect on P&L:
   RL P&L = {pnl_rl:,.2f}
   QL P&L = {pnl_ql:,.2f}

   If ratio ≈ -1.0, the sign is flipped between backends.
   Actual ratio: {pnl_rl/pnl_ql:.4f}
""")
