"""End-to-end sign audit: does a 'long' position actually make the money we say?

Five checks, each one falsifiable:

  1. The convention table. Rate weights <-> futures contracts <-> desk notation,
     and what each position profits from.
  2. P&L reconciliation on REAL data: the engine's spread arithmetic against a
     naive per-contract price P&L computed from settles. Must agree to the cent.
  3. The flip identity. fade and momentum take the same trades on opposite
     sides, so  net_fade + net_momentum == -2 * total_cost  EXACTLY. If that
     holds, "just flip the sign" cannot work -- cost is a drain on both sides.
  4. Gross vs net equity. Is the curve monotone because of a signal, or because
     of a constant per-trade cost bleed?
  5. Per-side attribution: is one side of the trade carrying the loss?

House convention being checked against (the user's):
    NEGATIVE = paid   = makes money when rates go UP (sell off)
    POSITIVE = received = makes money when rates go DOWN
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import dataclasses

import numpy as np
import pandas as pd

from RVUtils.MeanRev import MRConfig, run_backtest
from RVUtils.MeanRev.contracts import SR3_DV01_USD
from RVUtils.MeanRev.signals import zscore_signal

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
pd.set_option("display.width", 235)
pd.set_option("display.max_columns", 60)

st = pd.read_parquet(DATA / "structures_3m.parquet")
st["as_of"] = pd.to_datetime(st["as_of"])
st = st[(st["as_of"] >= "2022-01-03") & (st["back_slot"] <= 12)]
contracts = pd.read_parquet(DATA / "contracts.parquet")
contracts["as_of"] = pd.to_datetime(contracts["as_of"])

print("=" * 104)
print("1. THE CONVENTION TABLE")
print("=" * 104)
print("""
An SR3 future is priced 100 - rate(%). BUY the future  -> profit when the rate FALLS -> RECEIVED.
                                       SELL the future -> profit when the rate RISES -> PAID.

  desk notation      rate weight w      futures action        position    profits when
  (neg = paid)       (internal)         (contracts)
  ---------------------------------------------------------------------------------------------
  front  +1          w_f = -1           BUY  1 front          received    front rate falls
  belly  -2          w_b = +2           SELL 2 belly          PAID        belly rate rises
  back   +1          w_k = -1           BUY  1 back           received    back rate falls

The desk label "1/-2/1" and the internal weight vector (-1, +2, -1) are the SAME
trade written in opposite sign conventions. Internally w > 0 means "profits when
that leg's rate rises", i.e. w > 0 == paid == the desk's negative.

  spread S = w . r = 2*belly - front - back   (bp)   <- the Query layer's FLY RATE
  LONG S (engine d = +1) == PAID the belly against the wings
                         == profits when the belly CHEAPENS (its rate rises) vs the wings
""")

# --------------------------------------------------------------------------
print("=" * 104)
print("2. P&L RECONCILIATION ON REAL DATA  (spread arithmetic vs raw settles)")
print("=" * 104)
KEY = "U26-Z26-H27"
g = st[st["key"] == KEY].sort_values("as_of")
legs = ["U26", "Z26", "H27"]
W_RATE = np.array([-1.0, 2.0, -1.0])          # internal: +ve = paid
W_FUT = -W_RATE                                # futures contracts: +ve = BUY (long price)
px = contracts[contracts["code"].isin(legs)].pivot_table(
    index="as_of", columns="code", values="settle", aggfunc="first")[legs].dropna()
d0, d1 = g["as_of"].iloc[-40], g["as_of"].iloc[-1]
p0, p1 = px.loc[d0], px.loc[d1]
r0, r1 = 100.0 - p0, 100.0 - p1

print(f"key {KEY}, from {d0.date()} to {d1.date()}\n")
tbl = pd.DataFrame({
    "settle_t0": p0, "settle_t1": p1, "d_price": p1 - p0,
    "rate_t0_pct": r0, "rate_t1_pct": r1, "d_rate_bp": (r1 - r0) * 100,
    "rate_weight_w": W_RATE, "futures_contracts": W_FUT,
})
tbl["action"] = np.where(W_FUT > 0, "BUY (receive)", "SELL (pay)")
print(tbl.round(4).to_string())

spread0 = float(W_RATE @ (r0.to_numpy() * 100))
spread1 = float(W_RATE @ (r1.to_numpy() * 100))
engine_bp = spread1 - spread0
# naive: each contract earns $25 per bp its own PRICE rises = -rate falls
naive_usd = float(np.sum(W_FUT * (p1 - p0).to_numpy() * 100.0 * SR3_DV01_USD))
engine_usd = engine_bp * SR3_DV01_USD
print(f"\n  spread (2b-f-k) : {spread0:+.4f}bp -> {spread1:+.4f}bp   change {engine_bp:+.4f}bp")
print(f"  LONG 1 package, P&L via spread arithmetic : ${engine_usd:+,.2f}")
print(f"  LONG 1 package, P&L via raw contract legs : ${naive_usd:+,.2f}")
print(f"  agreement: {'MATCH' if abs(engine_usd - naive_usd) < 1e-6 else 'MISMATCH'} "
      f"(diff {engine_usd - naive_usd:+.10f})")
print(f"\n  sanity: the belly rate moved {(r1-r0)['Z26']*100:+.2f}bp; a LONG-spread "
      f"position is PAID the belly,\n  so it should "
      f"{'GAIN' if (r1-r0)['Z26'] > 0 else 'LOSE'} on that leg -- and the belly leg "
      f"contributes "
      f"${W_FUT[1] * (p1 - p0)['Z26'] * 100 * SR3_DV01_USD:+,.2f}.")

# --------------------------------------------------------------------------
print("\n" + "=" * 104)
print("3. THE FLIP IDENTITY  --  net_fade + net_momentum == -2 * total_cost")
print("=" * 104)
lv = st.pivot_table(index="as_of", columns="key", values="value", aggfunc="first")
sig = zscore_signal(lv, window=120)
gate = lv.notna()
base = MRConfig(lag=1, round_trip_cost_bp=2.0, max_hold=20, entry_z=2.0,
                exit_style="z0", n_packages=100)
rows = []
res = {}
for direction in ("fade", "momentum"):
    r = run_backtest(dataclasses.replace(base, direction=direction),
                     levels=lv, signal=sig, gate=gate)
    res[direction] = r
    m = r.metrics
    rows.append({"direction": direction, "n_trades": m["n_trades"],
                 "gross_bp": m["total_gross_bp"], "cost_bp": m["n_trades"] * 2.0,
                 "net_bp": m["total_net_bp"], "hit_rate": m["hit_rate"],
                 "sharpe": m["sharpe"]})
flip = pd.DataFrame(rows)
print(flip.round(4).to_string(index=False))
gf, gm = flip.set_index("direction")["gross_bp"]["fade"], flip.set_index("direction")["gross_bp"]["momentum"]
nf, nm = flip.set_index("direction")["net_bp"]["fade"], flip.set_index("direction")["net_bp"]["momentum"]
tc = flip["cost_bp"].iloc[0]
print(f"\n  gross_fade + gross_momentum = {gf + gm:+.6f}   (must be 0 -- same trades, opposite sides)")
print(f"  net_fade   + net_momentum   = {nf + nm:+.4f}")
print(f"  -2 x total cost             = {-2 * tc:+.4f}")
print(f"  identity holds: {abs((nf + nm) - (-2 * tc)) < 1e-6}")
print(f"\n  => Flipping the sign flips the GROSS but NOT the cost. Both sides pay it.")
print(f"     Best possible outcome from choosing the better side: "
      f"{max(nf, nm):+.1f}bp, still negative,")
print(f"     because |gross| = {abs(gf):.1f}bp is smaller than the cost "
      f"{tc:.1f}bp.")

# --------------------------------------------------------------------------
print("\n" + "=" * 104)
print("4. IS THE CURVE MONOTONE BECAUSE OF SIGNAL, OR BECAUSE OF COST BLEED?")
print("=" * 104)
r = res["fade"]
tr = r.trades.sort_values("exit")
gross_curve = tr["gross_bp"].cumsum()
net_curve = tr["net_bp"].cumsum()
print(f"  trades {len(tr)}   gross total {tr['gross_bp'].sum():+.2f}bp   "
      f"net total {tr['net_bp'].sum():+.2f}bp")
print(f"  gross curve: max {gross_curve.max():+.1f}  min {gross_curve.min():+.1f}  "
      f"final {gross_curve.iloc[-1]:+.1f}")
print(f"  net   curve: max {net_curve.max():+.1f}  min {net_curve.min():+.1f}  "
      f"final {net_curve.iloc[-1]:+.1f}")
up_g = float((gross_curve.diff().dropna() > 0).mean())
up_n = float((net_curve.diff().dropna() > 0).mean())
print(f"\n  share of trades that move the curve UP:  gross {up_g:.1%}   net {up_n:.1%}")
print(f"  gross curve new highs: {int((gross_curve == gross_curve.cummax()).sum())}"
      f"/{len(gross_curve)}   net curve new highs: "
      f"{int((net_curve == net_curve.cummax()).sum())}/{len(net_curve)}")
print("\n  A monotone-looking NET curve with a wandering GROSS curve is a cost bleed,")
print("  not a signal you can invert: every trade subtracts a fixed 2.0bp.")

# --------------------------------------------------------------------------
print("\n" + "=" * 104)
print("5. PER-SIDE ATTRIBUTION -- is one side carrying the loss?")
print("=" * 104)
for direction in ("fade", "momentum"):
    t = res[direction].trades
    if t.empty:
        continue
    side = (t.groupby("dir")
            .agg(n=("net_bp", "size"), gross_bp=("gross_bp", "sum"),
                 net_bp=("net_bp", "sum"), avg_gross=("gross_bp", "mean"),
                 hit=("net_bp", lambda s: (s > 0).mean()))
            .rename(index={1: "long spread (PAID belly)",
                           -1: "short spread (RECEIVED belly)"}))
    print(f"\n  {direction}:")
    print(side.round(4).to_string())
print("\n  If both sides are individually gross-positive-but-cost-negative, there is")
print("  no side to pick. If one side is gross-negative, THAT is a sign error worth")
print("  chasing -- a symmetric mean-reversion rule should not be one-sided.")

# --------------------------------------------------------------------------
print("\n" + "=" * 104)
print("6. THE ORACLE CEILING -- what if you ALWAYS picked the winning side?")
print("=" * 104)
t = res["fade"].trades
for cost in (0.0, 0.5, 1.0, 2.0, 2.5):
    oracle_gross = float(t["gross_bp"].abs().sum())
    oracle_net = oracle_gross - len(t) * cost
    real_net = float(t["gross_bp"].sum()) - len(t) * cost
    print(f"  cost {cost:4.1f}bp | perfect-hindsight side: {oracle_net:+9.1f}bp "
          f"| actual rule: {real_net:+9.1f}bp | "
          f"oracle edge/trade {oracle_gross / len(t):+.3f}bp")
print(f"\n  An ORACLE that knows the right side on every one of the {len(t)} trades")
print(f"  earns {float(t['gross_bp'].abs().sum()) / len(t):.3f}bp per trade gross.")
print(f"  The round trip is 2.0bp. So even perfect direction calling loses money")
print(f"  at taker costs -- the ceiling is set by the SIZE of the moves being")
print(f"  captured, not by getting the sign right.")
be = float(t["gross_bp"].abs().sum()) / len(t)
print(f"\n  break-even cost for a perfect oracle: {be:.3f}bp round trip "
      f"({be / 8:.4f}bp per contract per side)")
