r"""Do the CA label and the ``IMM_k`` swap leg roll on the SAME date?

The whole point of pairing a constant-rank CA structure with an ``IMM_k`` swap
leg is that both switch underlying on the same day, so a blackout that flattens
the book removes both jumps at once.  A one-day mismatch would leave one leg
jumping unhedged -- precisely the artifact class this block exists to remove.

Two independent clocks are compared, both pure computation (no network):

* ``IRSwapsTB._cvx_front_imm_code(d)`` -- the SR3 rank-to-contract map, which
  the module docstring says rolls on the IMM date itself;
* ``Query.Base.imm_resolution.resolve_imm_token("IMM_1", d)`` -- what an
  ``IMM_1x2y`` swap leg resolves its effective date to.

and graded against a third, model-free witness: the dates on which the CA panel
itself shows a level jump.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from Query.Base.imm_resolution import resolve_imm_token  # noqa: E402
from TB.IRSwapsTB import _cvx_front_imm_code, _cvx_imm_code_from_date_rank  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
ca = pd.read_parquet(DATA / "cavf_ca_panel.parquet")
dates = [d.date() for d in pd.to_datetime(ca.index)]
print(f"{len(dates)} panel dates {dates[0]}..{dates[-1]}")

rows = []
for d in dates:
    rows.append({
        "date": d,
        "ca_front": _cvx_front_imm_code(d),
        "ca_rank13": _cvx_imm_code_from_date_rank(d, 13),
        "imm1": resolve_imm_token("IMM_1", d),
        "imm13": resolve_imm_token("IMM_13", d),
    })
m = pd.DataFrame(rows).set_index("date")

ca_roll = m.index[m["ca_front"].ne(m["ca_front"].shift())][1:]
leg_roll = m.index[m["imm1"].ne(m["imm1"].shift())][1:]
ca_roll13 = m.index[m["ca_rank13"].ne(m["ca_rank13"].shift())][1:]
leg_roll13 = m.index[m["imm13"].ne(m["imm13"].shift())][1:]

print(f"\nCA front-code roll dates : {len(ca_roll)}")
print(f"IMM_1 leg roll dates     : {len(leg_roll)}")
print(f"CA rank-13 roll dates    : {len(ca_roll13)}")
print(f"IMM_13 leg roll dates    : {len(leg_roll13)}")
print(f"front  identical: {list(ca_roll) == list(leg_roll)}")
print(f"rank13 identical: {list(ca_roll13) == list(leg_roll13)}")

if list(ca_roll) != list(leg_roll):
    a, b = set(ca_roll), set(leg_roll)
    print(f"  CA-only  {sorted(a - b)[:8]}")
    print(f"  leg-only {sorted(b - a)[:8]}")

print("\nfirst 8 roll dates and the codes either side:")
for d in list(ca_roll)[:8]:
    i = m.index.get_loc(d)
    prev = m.index[i - 1]
    print(f"  {d} (prev {prev})  CA {m.loc[prev,'ca_front']}->{m.loc[d,'ca_front']}"
          f"   IMM_1 {m.loc[prev,'imm1']}->{m.loc[d,'imm1']}")

# ---- model-free witness: where does the CA panel actually jump? -------------
print("\n=== does the CA level jump on those dates? ===")
print(f"{'label':10s} {'sd(dCA) off-roll':>17s} {'mean|dCA| off':>14s} "
      f"{'mean|dCA| ON roll':>18s} {'ratio':>7s}")
roll_set = set(ca_roll)
for lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
    s = ca[f"USD-SOFR-1D {lab} PACKS CVX_ADJ"].dropna()
    dd = s.diff().dropna()
    on = dd[[d.date() in roll_set for d in dd.index]]
    off = dd[[d.date() not in roll_set for d in dd.index]]
    print(f"{lab:10s} {off.std():17.3f} {off.abs().mean():14.3f} "
          f"{on.abs().mean():18.3f} {on.abs().mean()/off.abs().mean():7.2f}")
print(f"n roll days in panel: {sum(1 for d in ca.index if d.date() in roll_set)}")

# a stricter witness: is the roll-day change SIGNED (block 3's claim that
# 22/33 SR3 rolls are FOMC dates, so the jump has a systematic sign)?
print("\nsigned roll-day change, by label:")
for lab in ("GREENS", "BLUES", "GOLDS"):
    s = ca[f"USD-SOFR-1D {lab} PACKS CVX_ADJ"].dropna()
    dd = s.diff().dropna()
    on = dd[[d.date() in roll_set for d in dd.index]]
    t = float(on.mean() / (on.std() / np.sqrt(len(on)))) if len(on) > 2 else float("nan")
    print(f"  {lab:8s} n={len(on):3d} mean={on.mean():+7.3f} sd={on.std():6.3f} t={t:+5.2f}")

m.to_parquet(DATA / "p2_roll_map.parquet")
print(f"\nwrote {DATA / 'p2_roll_map.parquet'}")
