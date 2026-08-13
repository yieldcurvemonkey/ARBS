"""Shared wiring for the dealer-direction repricing probes.

The one thing worth stating here rather than in each script: the MDP source that
reaches the Citi minute CurveStore is ``"CITIVELO_EXCEL"`` and it must be an
**RL** token. ``IRSwapsMDP._build_citivelo_excel_curve`` gates the store fast
path on ``backend == "rl"``, so ``CITIVELO_EXCEL-QL`` would skip the store
entirely and a strict policy would then miss on every single request -- looking
exactly like a cold store rather than like the wrong source string.

``SDRUtils/stir_flow/config.CURVE_SOURCE`` is still ``BARCHART_STIRF-RL`` and
its ``CURVE_FOR`` names are Barchart curve names; neither is used here.
"""
from __future__ import annotations

import datetime
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd

#: The source string that works. RL backend, reaches the CITIVELOEXCELMIN store.
CITI_MIN_SOURCE = "CITIVELO_EXCEL"

#: Tape ``rate_index_clean`` -> Citi curve name (NOT ``config.CURVE_FOR``).
CURVE_FOR = {"SOFR": "USD-SOFR-1D", "FED_FUNDS": "USD-FEDFUNDS-1D"}


def strict_policy(minutes: float = 1.0):
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy

    return SnapshotPolicy.strict(minutes=minutes)


def hole_policy(hours: float = 2.0):
    """Backward-only, bounded at ``hours``, loud - for the nightly hole ONLY.

    Applied globally this would admit a two-hour staleness at 10:00 on a
    Tuesday, which the fidelity report measures at 2.63 bp p90 against 0.87 bp
    for the same elapsed time across the 23:00-00:59 ET hole. The bound is not
    decoration either: it is what still refuses a night that follows a
    truncated session, whose last curve is four to six hours old.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy

    return SnapshotPolicy(
        method="asof",
        max_lag=datetime.timedelta(hours=float(hours)),
        allow_future=False,
        on_miss="raise",
    )


def make_pricer(policy):
    """A ``CurvePricer`` on the Citi minute source under ``policy``.

    ``curve_kwargs`` is fixed per instance by design (the handle cache is keyed
    on ``(curve_name, ts)`` only), so a policy branch means two pricers, not one
    pricer with two call sites.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from SDRUtils.stir_flow.pricing import CurvePricer

    mdp = IRSwapsMDP(source=CITI_MIN_SOURCE)
    return CurvePricer(mdp, curve_kwargs={"snapshot_policy": policy})


def snap_of(row) -> pd.Timestamp:
    from SDRUtils.stir_flow.pricing import snap_timestamp

    return pd.Timestamp(snap_timestamp(row["orig_exec_ts"], row["exec_ts"]))


def load_sample(path="C:/Users/chris/clee/ARBS-dd/scratch/out_sample20.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    for c in ("exec_ts", "orig_exec_ts"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def curve_meta(handle) -> dict:
    """The served-snapshot diagnostics off an ``RLIRSwapCurve``.

    The accessor is ``.meta()`` -- ``_meta_data`` is private and there is no
    ``meta_data`` attribute, so ``getattr(handle, "meta_data", None)`` silently
    returns ``None`` and every lag reads as missing while the prices look fine.
    """
    md = handle.meta() if hasattr(handle, "meta") else None
    if not isinstance(md, dict):
        md = getattr(handle, "_meta_data", None)
    md = md if isinstance(md, dict) else {}
    return {
        "served_utc": md.get("snapshot_served_utc"),
        "lag_signed_s": md.get("snapshot_lag_signed_seconds"),
        "from_future": md.get("snapshot_served_from_future"),
        "same_local_date": md.get("snapshot_same_local_date"),
        "policy": md.get("snapshot_policy"),
        "asset": md.get("asset"),
        "mode": md.get("mode"),
    }
