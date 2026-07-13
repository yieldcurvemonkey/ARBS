"""Clarus tick pairs + BoE dispersion metrics (spec section 6)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow import config


def tenor_bucket_for(row) -> str:
    stt = row.get("special_tenor_type") or "STANDARD"
    if stt == "FOMC":
        lbl = row.get("fomc_meeting_label")
        return f"FOMC_{lbl}" if lbl else "UNMAPPED"
    if stt == "IMM":
        t = row.get("tenor_label")
        return f"IMM_{t}" if t else "UNMAPPED"
    t = row.get("tenor_label")
    if not t:
        return "UNMAPPED"
    fsy = row.get("forward_start_years") or 0.0
    if abs(fsy) < 0.05:
        return str(t)
    fwd = row.get("forward_label")
    return f"{fwd}x{t}" if fwd else "UNMAPPED"


_KEY = ["tenor_bucket", "structure_type", "as_of_date", "execution_session"]


def build_tick_pairs(prints: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, grp in prints.groupby(_KEY, dropna=False):
        g = grp.sort_values("execution_timestamp")
        ts = pd.to_datetime(g["execution_timestamp"])
        gap_min = ts.diff().dt.total_seconds() / 60.0
        tick = (g["rate_pct"].diff().abs() * 100.0)
        ok = gap_min <= config.TICK_PAIR_MAX_GAP_MIN
        sel = g[ok & tick.notna()]
        if sel.empty:
            continue
        out.append(pd.DataFrame({
            "tenor_bucket": sel["tenor_bucket"].values,
            "structure_type": sel["structure_type"].values,
            "dv01_bucket": [config.assign_dv01_bucket(v) for v in sel["dv01"]],
            "as_of_date": sel["as_of_date"].values,
            "tick_bps": tick[sel.index].values,
        }))
    if not out:
        return pd.DataFrame(columns=["tenor_bucket", "structure_type", "dv01_bucket",
                                     "as_of_date", "tick_bps"])
    return pd.concat(out, ignore_index=True)


def compute_dispersion(prints: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, g in prints.groupby(["tenor_bucket", "structure_type", "as_of_date"], dropna=False):
        w = g["dv01"].abs().astype(float)
        if w.sum() <= 0:
            w = pd.Series(1.0, index=g.index)
        w = w / w.sum()
        vwap = float((w * g["rate_pct"]).sum())
        disp_vw = float(np.sqrt((w * ((g["rate_pct"] - vwap) * 100.0) ** 2).sum()))
        disp_jns = None
        if "s2m_bps" in g and g["s2m_bps"].notna().any():
            m = g["s2m_bps"].notna()
            wj = w[m] / w[m].sum()
            disp_jns = float(np.sqrt((wj * g.loc[m, "s2m_bps"] ** 2).sum()))
        suspect = False
        if disp_jns is not None:
            suspect = (disp_jns / max(disp_vw, config.MIN_DISP_VW_BPS)) > config.CURVE_SUSPECT_RATIO
        rows.append(dict(zip(["tenor_bucket", "structure_type", "as_of_date"], key))
                    | dict(disp_vw=disp_vw, disp_jns=disp_jns, curve_suspect=suspect,
                           vwap_rate_pct=vwap, total_dv01=float(g["dv01"].abs().sum()),
                           trade_count=len(g)))
    return pd.DataFrame(rows)


def compute_amihud(daily_vwap: pd.DataFrame) -> pd.DataFrame:
    df = daily_vwap.sort_values("as_of_date").copy()
    def _per_bucket(g):
        g = g.copy()
        dv = g["vwap_rate_pct"].diff().abs() * 100.0
        g["amihud"] = dv / g["total_dv01"]
        return g
    return df.groupby(["tenor_bucket", "structure_type"], group_keys=False).apply(_per_bucket)


def compute_bucket_stats(pairs: pd.DataFrame, prints: pd.DataFrame,
                         offmkt: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for with_all in (False, True):
        p = pairs.copy()
        o = offmkt.copy() if offmkt is not None and len(offmkt) else pd.DataFrame(
            columns=["tenor_bucket", "structure_type", "dv01_bucket", "as_of_date",
                     "dealer_charge_bps"])
        if with_all:
            p["dv01_bucket"] = "ALL"
            o["dv01_bucket"] = "ALL"
        key = ["tenor_bucket", "structure_type", "dv01_bucket", "as_of_date"]
        tick_stats = p.groupby(key)["tick_bps"].agg(
            mean_tick_bps="mean", median_tick_bps="median",
            p25_tick_bps=lambda s: s.quantile(0.25),
            p75_tick_bps=lambda s: s.quantile(0.75),
            tick_sample_count="count").reset_index()
        edge = o.groupby(key)["dealer_charge_bps"].agg(
            mean_dealer_charge_bps="mean", median_dealer_charge_bps="median",
            edge_sample_count="count").reset_index()
        frames.append(tick_stats.merge(edge, on=key, how="outer"))
    stats = pd.concat(frames, ignore_index=True)
    # futures tick floor: FED_FUNDS or FOMC_* buckets -> 0.5, else 0.25
    idx_map = {}
    if prints is not None and len(prints) and "rate_index_clean" in prints:
        idx_map = prints.groupby("tenor_bucket")["rate_index_clean"].first().to_dict()
    def _floor(b):
        ri = idx_map.get(b, "SOFR")
        stt = "FOMC" if str(b).startswith("FOMC_") else "STANDARD"
        return config.futures_tick_bps(ri, stt)
    stats["futures_min_tick_bps"] = stats["tenor_bucket"].map(_floor)
    return stats
