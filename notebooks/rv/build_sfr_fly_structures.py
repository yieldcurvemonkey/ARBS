"""Turn the SR3 contract panel into the butterfly panels the lab backtests.

Reads ``contracts.parquet`` (from ``build_sfr_fly_panel.py``) and writes:

* ``slot_panel.parquet``      -- date x strip-slot rates in percent (the curve
                                object the PCA / curve-fit residual signals fit)
* ``structures_3m.parquet``   -- every 3m fly, slots (i, i+1, i+2), i = 1..14
* ``structures_6m.parquet``   -- every 6m fly, slots (i, i+2, i+4), i = 1..12
* ``structures_6m_asym.parquet`` -- the asymmetric (i, i+2, i+3) variant, kept
                                only as a reported ablation
* ``panel_audit.txt``         -- coverage, level distributions, liquidity

Every structure is keyed on its **absolute** contract triple, so no roll enters
a series. Constant-maturity slot, pack colour and policy regime are attached as
reporting tags evaluated as of each date.

Usage::

    conda run -n stir python notebooks/rv/build_sfr_fly_structures.py
    conda run -n stir python notebooks/rv/build_sfr_fly_structures.py --verify-sign
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

from RVUtils.MeanRev.panel import (
    add_strip_slots,
    enumerate_structures,
    regime_tag,
    structure_liquidity,
)

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
MAX_SLOT = 16


def build(contracts: pd.DataFrame, spacing: int, weights, label: str,
          *, max_slot: int = MAX_SLOT) -> pd.DataFrame:
    slots = add_strip_slots(contracts)
    st = enumerate_structures(slots, spacing=spacing, max_slot=max_slot,
                              weights=weights)
    if st.empty:
        return st
    st = structure_liquidity(st, contracts, n_legs=len(weights))
    st["belly"] = st["leg1_id"]
    st["structure"] = label

    # days from today to the FRONT leg's reference-quarter start. The fly dies
    # when that hits zero (the front leg starts accruing and leaves the strip),
    # so this is the tradeable-life clock.
    starts = contracts[["code", "imm_start"]].drop_duplicates().rename(
        columns={"code": "leg0_id", "imm_start": "_front_start"})
    st = st.merge(starts, on="leg0_id", how="left")
    st["days_to_front_start"] = (pd.to_datetime(st["_front_start"])
                                 - pd.to_datetime(st["as_of"])).dt.days
    st = st.drop(columns=["_front_start"])

    reg = regime_tag(st["as_of"])
    st["regime"] = reg.to_numpy()
    return st


def audit(name: str, st: pd.DataFrame, out) -> None:
    p = lambda *a: print(*a, file=out, flush=True)          # noqa: E731
    p("\n" + "=" * 78)
    p(f"{name}: {len(st):,} rows | {st['key'].nunique()} absolute flies | "
      f"{st['as_of'].nunique():,} sessions")
    p(f"window {st['as_of'].min().date()} -> {st['as_of'].max().date()}")
    p("=" * 78)

    p("\n-- level (bp) by CM slot, full sample --")
    g = st.groupby("cm_label_short")["value"]
    tbl = pd.DataFrame({
        "n": g.count(), "mean": g.mean(), "median": g.median(),
        "q25": g.quantile(0.25), "q75": g.quantile(0.75),
        "q05": g.quantile(0.05), "q95": g.quantile(0.95), "sd": g.std(),
    })
    tbl["slot"] = st.groupby("cm_label_short")["cm_slot"].first()
    p(tbl.sort_values("slot").round(2).to_string())

    p("\n-- median level (bp) by CM slot x regime --")
    piv = st.pivot_table(index="cm_label_short", columns="regime", values="value",
                         aggfunc="median")
    order = st.groupby("cm_label_short")["cm_slot"].first().sort_values().index
    p(piv.reindex(order).round(2).to_string())

    p("\n-- daily change sd (bp) by CM slot x regime --")
    st2 = st.sort_values(["key", "as_of"]).copy()
    st2["dv"] = st2.groupby("key")["value"].diff()
    piv2 = st2.pivot_table(index="cm_label_short", columns="regime", values="dv",
                           aggfunc=lambda s: s.std())
    p(piv2.reindex(order).round(2).to_string())

    p("\n-- min-leg open interest by CM slot x year (median) --")
    st["year"] = st["as_of"].dt.year
    piv3 = st.pivot_table(index="cm_label_short", columns="year",
                          values="min_open_interest", aggfunc="median")
    p(piv3.reindex(order).round(0).to_string())

    p("\n-- flies per session, by year --")
    per = st.groupby(["year", "as_of"])["key"].nunique()
    p(per.groupby(level=0).agg(["mean", "min", "max"]).round(1).to_string())

    p("\n-- tradeable life: days from as_of to the FRONT leg's accrual start --")
    p(st["days_to_front_start"].describe().round(1).to_string())


def verify_sign(contracts: pd.DataFrame, st: pd.DataFrame, out) -> None:
    """Cross-check the settle-derived fly against the Query layer's FLY RATE.

    They are different objects -- ours is 2*belly - front - back on raw settles,
    the Query layer's is the same combination on a *calibrated curve* -- so they
    will not agree to the tick. What must agree is the sign and the rough
    magnitude; a sign flip here would invalidate every result downstream.
    """
    import pytz

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    p = lambda *a: print(*a, file=out, flush=True)          # noqa: E731
    NYC = pytz.timezone("America/New_York")
    CURVE = "USD-SOFR-1D-Q16STIRT"
    MON = {"H": 3, "M": 6, "U": 9, "Z": 12}

    def imm_tok(code):
        return f"IMM_{code[0]}{code[1:]}"

    def next_code(code):
        order = ["H", "M", "U", "Z"]
        i = order.index(code[0])
        y = int(code[1:])
        i += 1
        if i == 4:
            i, y = 0, y + 1
        return f"{order[i]}{y:02d}"

    p("\n" + "=" * 78)
    p("SIGN VERIFICATION: settle-derived fly vs Query-layer FLY RATE")
    p("=" * 78)
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    rows = []
    sample = (st[st["as_of"] >= "2025-01-01"]
              .groupby("as_of").head(2).groupby("as_of").tail(1).tail(6))
    for _, r in sample.iterrows():
        d = pd.Timestamp(r["as_of"]).date()
        ts = NYC.localize(datetime.datetime.combine(d, datetime.time(17, 0)))
        legs = [r["leg0_id"], r["leg1_id"], r["leg2_id"]]
        tenor = "/".join(f"{imm_tok(c)}x{imm_tok(next_code(c))}" for c in legs)
        try:
            ch = mdp.get_pricer(request=dict(curve_name=CURVE, timestamp=ts))
            q = IRSwapQuery(curve=CURVE, tenor=tenor).resolve_query(ts, pricer_or_curve=ch)
            pkg, rw = q.resolve_package(pricer_or_curve=ch)
            rates = [lg.__dict__["kwargs"]["fixed_rate"] for lg in pkg]
            curve_fly = (2 * rates[1] - rates[0] - rates[2]) * 100.0
        except Exception as exc:
            p(f"  {d} {r['key']}: curve fetch failed ({type(exc).__name__}: "
              f"{str(exc)[:70]})")
            continue
        rows.append({"as_of": d, "key": r["key"], "settle_fly_bp": r["value"],
                     "curve_fly_bp": curve_fly,
                     "diff_bp": r["value"] - curve_fly})
    if rows:
        cmp = pd.DataFrame(rows)
        p(cmp.round(3).to_string(index=False))
        same = (np.sign(cmp["settle_fly_bp"]) == np.sign(cmp["curve_fly_bp"]))
        p(f"\nsame sign on {int(same.sum())}/{len(cmp)} checks; "
          f"median |diff| {cmp['diff_bp'].abs().median():.3f}bp")
        if not bool(same.all()):
            p("  *** SIGN MISMATCH -- do not proceed ***")
    else:
        p("  no comparable rows fetched")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--max-slot", type=int, default=MAX_SLOT)
    ap.add_argument("--verify-sign", action="store_true")
    a = ap.parse_args(argv)

    contracts = pd.read_parquet(a.data_dir / "contracts.parquet")
    contracts["as_of"] = pd.to_datetime(contracts["as_of"])
    contracts["imm_start"] = pd.to_datetime(contracts["imm_start"])

    slots = add_strip_slots(contracts)
    slot_panel = slots[slots["slot"] <= a.max_slot].pivot_table(
        index="as_of", columns="slot", values="rate_pct", aggfunc="first")
    slot_panel.to_parquet(a.data_dir / "slot_panel.parquet")

    specs = [
        ("structures_3m", 1, (-1.0, 2.0, -1.0), "3m"),
        ("structures_6m", 2, (-1.0, 2.0, -1.0), "6m"),
    ]
    built = {}
    with open(a.data_dir / "panel_audit.txt", "w", encoding="utf-8") as fh:
        class Tee:
            def write(self, s):
                fh.write(s)
                sys.stdout.write(s)

            def flush(self):
                fh.flush()
                sys.stdout.flush()

        out = Tee()
        print(f"contracts {contracts.shape} | slot_panel {slot_panel.shape}",
              file=out, flush=True)
        for name, spacing, w, label in specs:
            st = build(contracts, spacing, w, label, max_slot=a.max_slot)
            st.to_parquet(a.data_dir / f"{name}.parquet", index=False)
            built[name] = st
            audit(name, st, out)

        # asymmetric ablation: legs at slots (i, i+2, i+3) -- 2 quarters on the
        # front wing, 1 on the back. Not a 1/-2/1 package; reported, not traded.
        slots_df = add_strip_slots(contracts)
        wide_v = slots_df.pivot_table(index="as_of", columns="slot",
                                      values="rate_pct", aggfunc="first")
        wide_id = slots_df.pivot_table(index="as_of", columns="slot",
                                       values="code", aggfunc="first")
        frames = []
        for i in range(1, a.max_slot - 2):
            legs = [i, i + 2, i + 3]
            if legs[-1] > a.max_slot or any(l not in wide_v.columns for l in legs):
                continue
            val = (2 * wide_v[legs[1]] - wide_v[legs[0]] - wide_v[legs[2]]) * 100
            key = (wide_id[legs[0]].astype(str) + "-" + wide_id[legs[1]].astype(str)
                   + "-" + wide_id[legs[2]].astype(str))
            frames.append(pd.DataFrame({
                "as_of": wide_v.index, "key": key.to_numpy(), "value": val.to_numpy(),
                "cm_slot": legs[1], "cm_label_short": f"SFR{legs[0]}{legs[1]}{legs[2]}",
            }))
        asym = pd.concat(frames, ignore_index=True).dropna(subset=["value"])
        asym = asym[~asym["key"].str.contains("nan")]
        asym.to_parquet(a.data_dir / "structures_6m_asym.parquet", index=False)
        print(f"\nasymmetric ablation: {len(asym):,} rows, "
              f"{asym['key'].nunique()} keys", file=out, flush=True)

        if a.verify_sign:
            verify_sign(contracts, built["structures_3m"], out)

    print(f"\nwrote {a.data_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
