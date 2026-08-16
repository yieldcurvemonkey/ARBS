"""Re-stamp the real-contract panel's expiries from the CURRENT expiry rules.

The harvest runs for the better part of an hour and is resumable across days, so
rows can be written under an expiry rule that is later corrected -- which is what
happened when the UST holiday defect surfaced mid-run (see
``harvest_listed_contract_vol.ust_expiry``). A long-running process also holds
the OLD code in memory, so its own end-of-run repair does not help a run that was
already in flight.

This applies the repair to whatever is on disk, and to the coverage JSON as well,
so the two named deliverables cannot disagree with each other. The expiry rule is
a pure function of the contract code, so re-running this is idempotent and costs
no network.

Usage::

    conda run -n stir python scripts/repair_listed_contract_expiries.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_harvest_listed_contract_vol", HERE / "harvest_listed_contract_vol.py")
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)


def main() -> int:
    panel = pd.read_parquet(h.PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["expiry_date"] = pd.to_datetime(panel["expiry_date"])
    fixed, changes = h.repair_expiries(panel)

    if not changes:
        print("no expiry changes; panel already matches the current rules")
    else:
        print(f"{len(changes)} contracts re-stamped:")
        for c in changes:
            print(f"  {c['contract_code']:<8} {c['was']} -> {c['now']} ({c['shift_days']:+d}d)")
    h._atomic_write(fixed, h.PANEL)
    print(f"wrote {h.PANEL}  rows={len(fixed):,}")

    # keep the coverage JSON consistent with the parquet
    if h.COVERAGE.exists():
        cov = json.loads(h.COVERAGE.read_text(encoding="utf-8"))
        moved = {c["contract_code"]: c["now"] for c in changes}
        n = 0
        exp_by_code = (fixed.groupby("contract_code")["expiry_date"].first()
                       .dt.date.astype(str).to_dict())
        last_by_code = fixed[fixed["value_type"] == "ABPV"].groupby("contract_code")["date"].max()
        for key, v in cov.items():
            code = key.split("|")[0]
            if code in moved:
                v["expiry"] = moved[code]
                if code in last_by_code.index and "last_vs_expiry_bd" in v:
                    v["last_vs_expiry_bd"] = int(len(pd.bdate_range(
                        last_by_code[code], pd.Timestamp(moved[code]))) - 1)
                n += 1
            elif code in exp_by_code and v.get("expiry") != exp_by_code[code]:
                v["expiry"] = exp_by_code[code]
                n += 1
        h._atomic_write_text(json.dumps(cov, indent=1), h.COVERAGE)
        print(f"updated {n} coverage entries in {h.COVERAGE}")

    # tie-out: with the corrected rule every DEAD contract's last quote must sit
    # within a few business days of its expiry, with no exceptions
    a = fixed[fixed["value_type"] == "ABPV"]
    end = a["date"].max()
    g = a.groupby("contract_code").agg(last=("date", "max"), exp=("expiry_date", "first"))
    dead = g[g["exp"] < end]
    gap = dead.apply(lambda r: len(pd.bdate_range(r["last"], r["exp"])) - 1, axis=1)
    bad = gap[(gap < 0) | (gap > 3)]
    print(f"\ntie-out: {len(dead)} expired contracts, last-quote-to-expiry gap "
          f"median {gap.median():.0f} bd, max {gap.max()} bd, "
          f"{len(bad)} outside [0, 3] bd")
    if len(bad):
        print(bad.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
