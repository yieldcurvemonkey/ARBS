r"""Does TB/IRSwapsTB.sfr_cvx_adj's matched swap use ANNUAL or QUARTERLY fixed?

DESIGN.md section 5 says the matched swap MUST be quarterly/quarterly and that the
spec default (annual fixed) biases the convexity adjustment by ~4bp. `sfr_cvx_adj`
builds an IRSwapQuery(OUTRIGHT, effective_date, maturity_date) and reads
`curve.fair_rate(swap)`. It passes no frequency. If the spec default is annual,
every CVX_ADJ number the production timeseries path has ever produced carries the
~4bp bias.

Read-only. One cached CitiVelo curve build. No SR3 fetch.
"""
from __future__ import annotations

import os
import datetime as dt

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import rateslib as rl  # noqa: E402

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from Query.IRSwaps.IRSwapQuery import IRSwapQuery  # noqa: E402
from Query.IRSwaps.IRSwapStructure import IRSwapStructure  # noqa: E402
from Query.IRSwaps.IRSwapValue import IRSwapValue  # noqa: E402
from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate  # noqa: E402

CURVE = "USD-SOFR-1D"
DATES = [dt.date(2023, 6, 9), dt.date(2024, 6, 10), dt.date(2025, 6, 10)]

mdp = IRSwapsMDP(source="CITIVELO_EXCEL")


def one(d: dt.date) -> None:
    ch = mdp._get_curve(curve_name=CURVE, timestamp=d)
    print(f"\n=== {d} curve id={ch.id()} ===")

    cd = ch._curve_definition()
    print("  ReferenceRate spec:", cd.get("ReferenceRate"))
    try:
        spec = rl.defaults.spec[cd["ReferenceRate"]]
        print("  spec frequency:", spec.get("frequency"),
              " leg2_frequency:", spec.get("leg2_frequency"))
    except Exception as e:  # noqa: BLE001
        print("  spec lookup failed:", e)

    # A Greens-like pack window: rank 9..12 -> IMM(9) .. IMM(13)
    imm = rl.get_imm(code="H24") if d.year <= 2023 else rl.get_imm(code="H26")
    eff = imm
    mat = imm
    for _ in range(4):
        mat = rl.next_imm(mat)

    q_rate = matched_forward_swap_rate(ch, eff.date(), mat.date(), frequency="Q",
                                       leg2_frequency="Q")
    a_rate = matched_forward_swap_rate(ch, eff.date(), mat.date(), frequency=None,
                                       leg2_frequency=None)

    # exactly what sfr_cvx_adj does
    q = IRSwapQuery(
        curve=CURVE,
        effective_date=eff.date(),
        maturity_date=mat.date(),
        structure=IRSwapStructure.OUTRIGHT,
        structure_kwargs={"bpv": 1},
        value=IRSwapValue.CVX_ADJ,
    )
    pkg, rws = q.resolve_package(pricer_or_curve=ch, is_for_timeseries=True)
    tb_rate = float(ch.fair_rate(pkg[0]))
    if abs(tb_rate) < 1.0:
        tb_rate *= 100.0

    print(f"  window {eff.date()} -> {mat.date()}")
    print(f"  matched Q/Q          : {q_rate:.6f} %")
    print(f"  matched spec-default : {a_rate:.6f} %")
    print(f"  TB query fair_rate   : {tb_rate:.6f} %")
    print(f"  TB - Q/Q             : {(tb_rate - q_rate) * 100.0:+.4f} bp"
          "   <-- the bias carried by every published CVX_ADJ if non-zero")
    print(f"  spec-default - Q/Q   : {(a_rate - q_rate) * 100.0:+.4f} bp")

    # what frequency did the query actually build?
    obj = pkg[0]
    for attr in ("leg1", "leg2"):
        leg = getattr(obj, attr, None)
        if leg is not None:
            print(f"  {attr} schedule frequency:",
                  getattr(getattr(leg, "schedule", None), "frequency", "?"))


for d in DATES:
    try:
        one(d)
    except Exception as e:  # noqa: BLE001
        print(f"{d}: FAILED {type(e).__name__}: {e}")
