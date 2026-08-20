r"""One table with every headline number, assembled from the files that produced them.

Written so the next reader does not have to re-derive a figure from a log, and so
that a figure quoted anywhere can be traced to the CSV it came from. Nothing here
recomputes anything: every value is read back out of the artefact that measured
it, which is also a check that the artefacts say what the summary claims.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"


def rows() -> list[dict]:
    out: list[dict] = []

    def add(section, metric, value, unit="", source=""):
        out.append({"section": section, "metric": metric, "value": value,
                    "unit": unit, "source": source})

    uni = pd.read_csv(DATA / "intraday_universe.csv")
    add("universe", "bonds", len(uni), "count", "intraday_universe.csv")
    add("universe", "held by TLT 2021-2026", int(uni["held_by_tlt"].sum()), "count",
        "intraday_universe.csv")
    add("universe", "in reference band, never held", int(((~uni["held_by_tlt"])
        & uni["in_reference_band"]).sum()), "count", "intraday_universe.csv")

    lay = pd.read_csv(DATA / "intraday_layer_summary.csv")
    for _, r in lay.iterrows():
        add(f"layer {r['layer']}", "tags served / expected",
            f"{int(r['tags_served'])}/{int(r['tags_expected'])}", "", "intraday_layer_summary.csv")
        add(f"layer {r['layer']}", "cells", int(r["rows"]), "count",
            "intraday_layer_summary.csv")
        add(f"layer {r['layer']}", "date floor", str(r["floor"]), "", "intraday_layer_summary.csv")
        add(f"layer {r['layer']}", "median MIN spacing", float(r["min_gap_s_median"]), "s",
            "intraday_layer_summary.csv")
        add(f"layer {r['layer']}", "median MEDIAN spacing", float(r["med_gap_s_median"]), "s",
            "intraday_layer_summary.csv")

    man = [json.loads(l) for l in (DATA / "intraday_backfill_manifest.jsonl")
           .read_text(encoding="utf-8").splitlines() if l.strip()]
    m = pd.DataFrame(man)
    for layer, g in m.groupby("layer"):
        add(f"layer {layer}", "requests issued", len(g), "count", "manifest")
        for st in ("ok", "empty", "error"):
            add(f"layer {layer}", f"requests {st}", int((g["status"] == st).sum()), "count",
                "manifest")
        if "min_gap_s" in g.columns:
            ok = g[g["status"] == "ok"]
            # The downsample signature is frequency-specific and applying one
            # threshold to every layer is how a correct HOURLY window gets
            # reported as downsampled: 3,600 s IS the right spacing there. The
            # add-in's next step down from MI01 is 10 minutes and from HOURLY is
            # a day, so those are the thresholds that mean something.
            freq = str(g["freq"].iloc[0])
            thresh = {"MI01": 600.0, "MI10": 3600.0, "HOURLY": 86400.0}.get(freq, 1e18)
            add(f"layer {layer}", f"requests downsampled ({freq}: union min gap "
                f">= {thresh:.0f}s)",
                int((ok["min_gap_s"].fillna(0) >= thresh).sum()), "count", "manifest")
            add(f"layer {layer}", f"union min gap values seen ({freq})",
                ",".join(f"{v:.0f}" for v in sorted(ok["min_gap_s"].dropna().unique())[:8]),
                "s", "manifest")
    add("excel", "peak working set in the manifest", float(m["excel_mb"].max()), "MB", "manifest")

    try:
        st = pd.read_csv(DATA / "intraday_stamp_convention_minutes_exact.csv", index_col=0)
        add("stamp convention", "exact match of HOURLY stamp H to MI01 at H+59m",
            float(st.loc["H+59m"].mean()), "fraction",
            "intraday_stamp_convention_minutes_exact.csv")
    except Exception:  # noqa: BLE001
        pass

    try:
        tz = pd.read_csv(DATA / "intraday_timezone_evidence.csv")
        for _, r in tz.iterrows():
            add("timezone", r["test"], f"peak at stamp hour {r['observed_peak_hour']} "
                f"(ET expects {r['expected_hour_if_ET']}, UTC expects "
                f"{r['expected_hour_if_UTC']})", "", "intraday_timezone_evidence.csv")
    except Exception:  # noqa: BLE001
        pass

    try:
        q = pd.read_csv(DATA / "intraday_mark_quality.csv")
        for _, r in q.iterrows():
            add("mark quality", r["metric"], float(r["value"]), "", "intraday_mark_quality.csv")
    except Exception:  # noqa: BLE001
        pass

    try:
        imp = pd.read_csv(DATA / "intraday_impossible_cells_tight.csv")
        add("data defects", "impossible hourly YIELD cells", len(imp), "count",
            "intraday_impossible_cells_tight.csv")
        add("data defects", "of those inside the New York session (stamps 08-16)",
            int(((imp["hour"] >= 8) & (imp["hour"] <= 16)).sum()), "count",
            "intraday_impossible_cells_tight.csv")
        add("data defects", "of those at stamp 14 or 15 (the 15:00 / 16:00 marks)",
            int(imp["hour"].isin([14, 15]).sum()), "count",
            "intraday_impossible_cells_tight.csv")
    except Exception:  # noqa: BLE001
        pass

    try:
        h = pd.read_csv(DATA / "intraday_horizon_sweep.csv")
        for _, r in h.iterrows():
            add("perfect-foresight ceiling per butterfly", r["horizon"],
                round(float(r["perfect_foresight_gross_bp"]), 4), "bp gross",
                "intraday_horizon_sweep.csv")
            add("perfect-foresight ceiling per butterfly", f"{r['horizon']} / cost",
                round(float(r["gross_over_cost"]), 4), "x of 0.535bp",
                "intraday_horizon_sweep.csv")
    except Exception:  # noqa: BLE001
        pass

    try:
        w = pd.read_csv(DATA / "intraday_fly_width_sweep.csv")
        add("fly width robustness", "widest gross/cost over wing steps 1,2,3,4,6",
            round(float(w["gross_over_cost"].max()), 4), "x of 0.535bp",
            "intraday_fly_width_sweep.csv")
    except Exception:  # noqa: BLE001
        pass

    return out


def main() -> int:
    df = pd.DataFrame(rows())
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", 300)
    print(df.to_string(index=False))
    df.to_csv(DATA / "intraday_SUMMARY.csv", index=False)
    print("\nwrote intraday_SUMMARY.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
