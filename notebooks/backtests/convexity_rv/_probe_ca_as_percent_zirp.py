r"""IRSwapValue._convexity_adjustment's `_as_percent` heuristic on a ZIRP price.

    def _as_percent(x): return x * 100.0 if abs(x) < 1.0 else x

The futures leg feeds it `rl.STIRFuture.fixed_rate`. If rateslib carries that in
PERCENT, then a 2021 SR3 at 99.80 has fixed_rate == 0.20, `abs(0.20) < 1.0` is
True, and the heuristic multiplies it to 20.00 %. Every White/Red pack in the
ZIRP window (2020-03 .. 2022-06, when SR3 rates sat below 1 %) would then carry a
CA in the thousands of basis points.

No network, no curve build: rl.STIRFuture's `fixed_rate` is a pure function of
`price`.
"""
from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import rateslib as rl  # noqa: E402


def as_percent(x: float) -> float:
    x = float(x)
    return x * 100.0 if abs(x) < 1.0 else x


def stirf(code: str, price: float):
    return rl.STIRFuture(
        effective=rl.scheduling.get_imm(code=code),
        termination=rl.scheduling.next_imm(rl.scheduling.get_imm(code=code)),
        spec="usd_stir",
        curves="dummy",
        price=price,
    )


CASES = [
    ("H21", 99.9500, "ZIRP front  (0.05 %)"),
    ("M21", 99.8000, "ZIRP        (0.20 %)"),
    ("Z21", 99.5000, "ZIRP        (0.50 %)"),
    ("H22", 99.0500, "just under 1 % (0.95 %)"),
    ("M22", 98.9500, "just over 1 %  (1.05 %)"),
    ("H24", 95.0000, "normal      (5.00 %)"),
]

print(f"{'code':6} {'price':>9} {'fixed_rate':>12} {'as_percent':>12}  {'verdict':<10} note")
bad = 0
for code, px, note in CASES:
    f = stirf(code, px)
    fr = getattr(f, "fixed_rate", None)
    fr = float(getattr(fr, "real", fr))
    got = as_percent(fr)
    truth = 100.0 - px
    ok = abs(got - truth) < 1e-9
    bad += 0 if ok else 1
    print(f"{code:6} {px:9.4f} {fr:12.6f} {got:12.6f}  {'OK' if ok else 'CORRUPT':<10} {note}"
          f"{'' if ok else f'  -> truth {truth:.4f} %, error {(got-truth)*100:,.0f} bp'}")

print()
print(f"corrupted cases: {bad}/{len(CASES)}")
print("threshold: any SR3 price above 99.00 (rate below 1 %) trips the heuristic.")
