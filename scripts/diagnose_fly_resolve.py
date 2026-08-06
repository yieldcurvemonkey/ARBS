"""Diagnose FLY resolve_pricable divergence between RL and QL backends."""

import datetime
import numpy as np

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapStructure import (
    IRSwapStructure,
    IRSwapStructureFunctionMap,
)
import rateslib as rl

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

# =====================================================================
# TEST 1: Does rateslib NPV depend on notional SIGN?
# =====================================================================
print("=" * 70)
print("TEST 1: rateslib NPV vs notional sign")
print("=" * 70)

s_pos = c_rl_1.build_irswap(fwd="0D", tenor="2Y", notional=1_000_000)
s_neg = c_rl_1.build_irswap(fwd="0D", tenor="2Y", notional=-1_000_000)

print(f"  Stored fixed_rate (pos): {s_pos.fixed_rate}")
print(f"  Stored fixed_rate (neg): {s_neg.fixed_rate}")
print(f"  Notional (pos): {c_rl_1.notional(s_pos):>15,.0f}")
print(f"  Notional (neg): {c_rl_1.notional(s_neg):>15,.0f}")

npv_pos_t1 = c_rl_1.npv(s_pos)
npv_neg_t1 = c_rl_1.npv(s_neg)
npv_pos_t2 = c_rl_2.npv(s_pos)
npv_neg_t2 = c_rl_2.npv(s_neg)
print(f"\n  NPV on T1 curve: pos={npv_pos_t1:>12,.2f}  neg={npv_neg_t1:>12,.2f}")
print(f"  NPV on T2 curve: pos={npv_pos_t2:>12,.2f}  neg={npv_neg_t2:>12,.2f}")
if npv_pos_t2 != 0:
    print(f"  Ratio T2 (neg/pos): {npv_neg_t2/npv_pos_t2:.6f}")

# Also test raw rateslib IRS directly
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS
curve_def_id = c_rl_1._curve_definition_id()
curve_def = RATESLIB_CURVE_DEFINITIONS[curve_def_id]
fair_rate_dec = c_rl_1.fair_rate(s_pos)
print(f"\n  Fair rate (decimal): {fair_rate_dec:.8f}")
print(f"  Fair rate * 100 (%): {fair_rate_dec*100:.6f}")

raw_pos = rl.IRS(
    effective=c_rl_1.effective_date(s_pos),
    termination=c_rl_1.maturity_date(s_pos),
    fixed_rate=fair_rate_dec * 100,
    spec=curve_def["ReferenceRate"],
    curves=c_rl_2._rl_curve_handle,
    notional=1_000_000,
    leg2_rate_fixings=c_rl_2._fixings,
)
raw_neg = rl.IRS(
    effective=c_rl_1.effective_date(s_pos),
    termination=c_rl_1.maturity_date(s_pos),
    fixed_rate=fair_rate_dec * 100,
    spec=curve_def["ReferenceRate"],
    curves=c_rl_2._rl_curve_handle,
    notional=-1_000_000,
    leg2_rate_fixings=c_rl_2._fixings,
)
raw_npv_pos = raw_pos.npv(curves=c_rl_2._rl_curve_handle).real
raw_npv_neg = raw_neg.npv(curves=c_rl_2._rl_curve_handle).real
print(f"\n  Raw rl.IRS NPV on T2 (fixed_rate={fair_rate_dec*100:.4f}%):")
print(f"    notional=+1M: {raw_npv_pos:>12,.2f}")
print(f"    notional=-1M: {raw_npv_neg:>12,.2f}")
if raw_npv_pos != 0:
    print(f"    Ratio (neg/pos): {raw_npv_neg/raw_npv_pos:.6f}")

# =====================================================================
# TEST 2: Outright resolve_pricable direction
# =====================================================================
print("\n" + "=" * 70)
print("TEST 2: Outright resolve_pricable")
print("=" * 70)

s_rl = c_rl_1.build_irswap(fwd="0D", tenor="2Y", notional=1_000_000)
s_ql = c_ql_1.build_irswap(fwd="0D", tenor="2Y", notional=1_000_000)

res_rl = c_rl_1.resolve_pricable(s_rl, risk_weight=1.0)
res_ql = c_ql_1.resolve_pricable(s_ql, risk_weight=1.0)
print(f"  Original: RL not={c_rl_1.notional(s_rl):>12,.0f}  QL not={c_ql_1.notional(s_ql):>12,.0f}")
print(f"  Resolved: RL not={c_rl_1.notional(res_rl):>12,.0f}  QL not={c_ql_1.notional(res_ql):>12,.0f}")

npv_rl_e = c_rl_1.npv(res_rl)
npv_ql_e = c_ql_1.npv(res_ql)
res_rl_2 = c_rl_2.resolve_pricable(s_rl, risk_weight=1.0)
res_ql_2 = c_ql_2.resolve_pricable(s_ql, risk_weight=1.0)
npv_rl_m = c_rl_2.npv(res_rl_2)
npv_ql_m = c_ql_2.npv(res_ql_2)
pnl_rl = npv_rl_m - npv_rl_e
pnl_ql = npv_ql_m - npv_ql_e
print(f"  Entry NPV: RL={npv_rl_e:>12,.2f}  QL={npv_ql_e:>12,.2f}")
print(f"  MTM NPV:   RL={npv_rl_m:>12,.2f}  QL={npv_ql_m:>12,.2f}")
print(f"  P&L:       RL={pnl_rl:>12,.2f}  QL={pnl_ql:>12,.2f}")
if pnl_ql != 0:
    print(f"  Ratio:     {pnl_rl/pnl_ql:.6f}")

# =====================================================================
# TEST 3: Build FLY package
# =====================================================================
print("\n" + "=" * 70)
print("TEST 3: FLY package construction (2s5s10s, bpv=+100000)")
print("=" * 70)

struct_rl = IRSwapStructureFunctionMap(curve=c_rl_1)
struct_ql = IRSwapStructureFunctionMap(curve=c_ql_1)

pkg_rl, rw_rl = struct_rl.apply(
    IRSwapStructure.FLY,
    front_tenor="2Y", belly_tenor="5Y", back_tenor="10Y",
    bpv=100_000,
)
pkg_ql, rw_ql = struct_ql.apply(
    IRSwapStructure.FLY,
    front_tenor="2Y", belly_tenor="5Y", back_tenor="10Y",
    bpv=100_000,
)

print(f"  Risk weights RL: {rw_rl}")
print(f"  Risk weights QL: {rw_ql}")

legs = ["Front(2Y)", "Belly(5Y)", "Back(10Y)"]
print(f"\n  Leg notionals:")
for i, name in enumerate(legs):
    print(f"    {name}: RL={c_rl_1.notional(pkg_rl[i]):>15,.0f}  QL={c_ql_1.notional(pkg_ql[i]):>15,.0f}")

print(f"\n  Leg PV01:")
for i, name in enumerate(legs):
    print(f"    {name}: RL={c_rl_1.pv01(pkg_rl[i]):>12,.2f}  QL={c_ql_1.pv01(pkg_ql[i]):>12,.2f}")

# =====================================================================
# TEST 4: resolve_pricable per FLY leg
# =====================================================================
print("\n" + "=" * 70)
print("TEST 4: resolve_pricable per FLY leg")
print("=" * 70)

print("  RL (always negates notional, ignores risk_weight):")
for i, name in enumerate(legs):
    orig = c_rl_1.notional(pkg_rl[i])
    res = c_rl_1.resolve_pricable(pkg_rl[i], risk_weight=rw_rl[i])
    res_n = c_rl_1.notional(res)
    print(f"    {name}: orig={orig:>15,.0f} rw={rw_rl[i]:+.1f} resolved={res_n:>15,.0f}")

print("\n  QL (uses risk_weight for direction):")
for i, name in enumerate(legs):
    orig = c_ql_1.notional(pkg_ql[i])
    res = c_ql_1.resolve_pricable(pkg_ql[i], risk_weight=rw_ql[i])
    res_n = c_ql_1.notional(res)
    print(f"    {name}: orig={orig:>15,.0f} rw={rw_ql[i]:+.1f} resolved={res_n:>15,.0f}")

# =====================================================================
# TEST 5: FLY NPV and P&L
# =====================================================================
print("\n" + "=" * 70)
print("TEST 5: FLY NPV and P&L")
print("=" * 70)

res_rl_e = [c_rl_1.resolve_pricable(p, rw) for p, rw in zip(pkg_rl, rw_rl)]
res_ql_e = [c_ql_1.resolve_pricable(p, rw) for p, rw in zip(pkg_ql, rw_ql)]
res_rl_m = [c_rl_2.resolve_pricable(p, rw) for p, rw in zip(pkg_rl, rw_rl)]
res_ql_m = [c_ql_2.resolve_pricable(p, rw) for p, rw in zip(pkg_ql, rw_ql)]

print("  Per-leg entry NPV:")
for i, name in enumerate(legs):
    rl_npv = c_rl_1.npv(res_rl_e[i])
    ql_npv = c_ql_1.npv(res_ql_e[i])
    print(f"    {name}: RL={rl_npv:>15,.2f}  QL={ql_npv:>15,.2f}")

fly_e_rl = sum(c_rl_1.npv(s) for s in res_rl_e)
fly_e_ql = sum(c_ql_1.npv(s) for s in res_ql_e)
fly_m_rl = sum(c_rl_2.npv(s) for s in res_rl_m)
fly_m_ql = sum(c_ql_2.npv(s) for s in res_ql_m)
fly_pnl_rl = fly_m_rl - fly_e_rl
fly_pnl_ql = fly_m_ql - fly_e_ql

print(f"\n  FLY entry NPV: RL={fly_e_rl:>15,.2f}  QL={fly_e_ql:>15,.2f}")
print(f"  FLY MTM NPV:   RL={fly_m_rl:>15,.2f}  QL={fly_m_ql:>15,.2f}")
print(f"  FLY P&L:        RL={fly_pnl_rl:>15,.2f}  QL={fly_pnl_ql:>15,.2f}")
if fly_pnl_ql != 0:
    print(f"  Ratio (RL/QL): {fly_pnl_rl/fly_pnl_ql:.6f}")

# =====================================================================
# TEST 6: Fix RL resolve_pricable to use risk_weight
# =====================================================================
print("\n" + "=" * 70)
print("TEST 6: RL with risk_weight-aware resolve_pricable")
print("=" * 70)

def rl_resolve_fixed(curve, irswap, risk_weight=None):
    """RL resolve_pricable using risk_weight for direction (like QL)."""
    notional = abs(curve.notional(irswap))
    if risk_weight is not None:
        direction = risk_weight
    else:
        direction = curve.pv01(irswap)
    if direction < 0:
        notional = notional * -1
    return curve.build_irswap(
        effective_date=curve.effective_date(irswap),
        maturity_date=curve.maturity_date(irswap),
        fixed_rate=curve.fixed_rate(irswap),
        notional=notional,
    )

# FLY with fixed resolve
fix_e = [rl_resolve_fixed(c_rl_1, p, rw) for p, rw in zip(pkg_rl, rw_rl)]
fix_m = [rl_resolve_fixed(c_rl_2, p, rw) for p, rw in zip(pkg_rl, rw_rl)]
fly_e_fix = sum(c_rl_1.npv(s) for s in fix_e)
fly_m_fix = sum(c_rl_2.npv(s) for s in fix_m)
fly_pnl_fix = fly_m_fix - fly_e_fix

print(f"  FLY P&L comparison:")
print(f"    RL (current, always negate): {fly_pnl_rl:>15,.2f}")
print(f"    RL (fixed, uses rw):         {fly_pnl_fix:>15,.2f}")
print(f"    QL (current):                {fly_pnl_ql:>15,.2f}")
if fly_pnl_ql != 0:
    print(f"\n  Ratios to QL:")
    print(f"    Current RL / QL: {fly_pnl_rl/fly_pnl_ql:.6f}")
    print(f"    Fixed RL / QL:   {fly_pnl_fix/fly_pnl_ql:.6f}")

# Outright with fixed resolve
s_out = c_rl_1.build_irswap(fwd="0D", tenor="2Y", notional=1_000_000)
cur_e = c_rl_1.resolve_pricable(s_out, risk_weight=1.0)
cur_m = c_rl_2.resolve_pricable(s_out, risk_weight=1.0)
fix_e_out = rl_resolve_fixed(c_rl_1, s_out, risk_weight=1.0)
fix_m_out = rl_resolve_fixed(c_rl_2, s_out, risk_weight=1.0)
pnl_cur = c_rl_2.npv(cur_m) - c_rl_1.npv(cur_e)
pnl_fix = c_rl_2.npv(fix_m_out) - c_rl_1.npv(fix_e_out)
print(f"\n  Outright P&L comparison (2Y, notional=+1M, rw=+1.0):")
print(f"    Current RL: {pnl_cur:>15,.2f}  (resolved not={c_rl_1.notional(cur_e):>12,.0f})")
print(f"    Fixed RL:   {pnl_fix:>15,.2f}  (resolved not={c_rl_1.notional(fix_e_out):>12,.0f})")
if pnl_fix != 0:
    print(f"    Ratio (current/fixed): {pnl_cur/pnl_fix:.6f}")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
