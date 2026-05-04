import datetime
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from RVUtils.ImpliedDistribution import SFRImpliedDistribution


OUT = Path("analysis_outputs/implied_distribution/jpm_appendix_recreation")
FETCH_MODE = "bounded_listed_otm_oi100"
RAW_MODE = "raw_jpm_bl"
SABR_MODE = "sabr_smoothed_bl"

CONTRACTS = [
    ("U6", "SFRU26"),
    ("Z6", "SFRZ26"),
    ("H7", "SFRH27"),
    ("M7", "SFRM27"),
]

DATES = [
    ("1BD ago", datetime.date(2026, 4, 29), "#ff3b3b"),
    ("5BD ago", datetime.date(2026, 4, 23), "#3b4cff"),
    ("21BD ago", datetime.date(2026, 4, 1), "#30d530"),
]

EXPECTED = {
    ("U6", datetime.date(2026, 4, 29)): dict(mean=3.72, median=3.67, mode=3.66, p5=3.14, p10=3.34, p25=3.58, p75=3.79, p90=4.18, p95=4.58, no_strikes=57, min_rate=0.50, max_rate=6.25),
    ("U6", datetime.date(2026, 4, 23)): dict(mean=3.68, median=3.67, mode=3.69, p5=3.10, p10=3.28, p25=3.54, p75=3.76, p90=3.95, p95=4.47, no_strikes=57, min_rate=0.50, max_rate=6.25),
    ("U6", datetime.date(2026, 4, 1)): dict(mean=3.73, median=3.68, mode=3.68, p5=2.93, p10=3.18, p25=3.54, p75=3.78, p90=4.43, p95=4.83, no_strikes=57, min_rate=0.50, max_rate=6.25),
    ("Z6", datetime.date(2026, 4, 29)): dict(mean=3.74, median=3.68, mode=3.66, p5=2.87, p10=3.14, p25=3.45, p75=4.01, p90=4.56, p95=4.96, no_strikes=60, min_rate=0.50, max_rate=6.50),
    ("Z6", datetime.date(2026, 4, 23)): dict(mean=3.64, median=3.66, mode=3.71, p5=2.78, p10=3.03, p25=3.37, p75=3.86, p90=4.34, p95=4.76, no_strikes=60, min_rate=0.50, max_rate=6.50),
    ("Z6", datetime.date(2026, 4, 1)): dict(mean=3.67, median=3.64, mode=3.69, p5=2.59, p10=2.89, p25=3.29, p75=3.97, p90=4.63, p95=5.04, no_strikes=60, min_rate=0.50, max_rate=6.50),
    ("H7", datetime.date(2026, 4, 29)): dict(mean=3.80, median=3.71, mode=3.63, p5=2.67, p10=2.99, p25=3.39, p75=4.14, p90=4.80, p95=5.27, no_strikes=51, min_rate=0.50, max_rate=6.75),
    ("H7", datetime.date(2026, 4, 23)): dict(mean=3.66, median=3.64, mode=3.72, p5=2.48, p10=2.83, p25=3.26, p75=3.99, p90=4.54, p95=5.18, no_strikes=51, min_rate=0.50, max_rate=6.75),
    ("H7", datetime.date(2026, 4, 1)): dict(mean=3.64, median=3.61, mode=3.64, p5=2.18, p10=2.57, p25=3.12, p75=4.07, p90=4.86, p95=5.37, no_strikes=51, min_rate=0.50, max_rate=6.75),
    ("M7", datetime.date(2026, 4, 29)): dict(mean=3.68, median=3.68, mode=3.64, p5=2.36, p10=2.73, p25=3.23, p75=4.13, p90=4.73, p95=5.20, no_strikes=35, min_rate=0.50, max_rate=6.00),
    ("M7", datetime.date(2026, 4, 23)): dict(mean=3.55, median=3.58, mode=3.62, p5=2.14, p10=2.57, p25=3.12, p75=3.99, p90=4.47, p95=5.19, no_strikes=35, min_rate=0.50, max_rate=6.00),
    ("M7", datetime.date(2026, 4, 1)): dict(mean=3.52, median=3.53, mode=3.63, p5=1.98, p10=2.36, p25=2.96, p75=4.03, p90=4.73, p95=5.35, no_strikes=35, min_rate=0.50, max_rate=6.00),
}

DISPLAY_EDGES = np.array(
    [-np.inf, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0, 4.25, 4.5, np.inf],
    dtype=float,
)
DISPLAY_LABELS = [
    "<2",
    "2-2.25",
    "2.25-2.5",
    "2.5-2.75",
    "2.75-3",
    "3-3.25",
    "3.25-3.5",
    "3.5-3.75",
    "3.75-4",
    "4-4.25",
    "4.25-4.5",
    ">4.5",
]


def integrate_between(bl, lo, hi):
    rate = bl.strike_grid_rate
    dens = bl.rnd_density
    lo_eff = max(float(rate[0]), lo if math.isfinite(lo) else float(rate[0]))
    hi_eff = min(float(rate[-1]), hi if math.isfinite(hi) else float(rate[-1]))
    if hi_eff <= lo_eff:
        return 0.0
    mask = (rate > lo_eff) & (rate < hi_eff)
    xs = np.concatenate([[lo_eff], rate[mask], [hi_eff]])
    ys = np.interp(xs, rate, dens)
    return float(np.trapezoid(ys, xs))


def mode_rate(bl):
    return float(bl.strike_grid_rate[int(np.argmax(bl.rnd_density))])


def build_raw_extractor():
    # The library default is now the raw JPM-style BL workflow:
    # observed OTM premiums, OI >= 100, put-call parity, 25bp bins.
    return SFRImpliedDistribution()


def build_sabr_extractor():
    return SFRImpliedDistribution(
        use_sabr_vols=True,
        sabr_extrapolation=True,
        smoothing_param=1e-4,
        scale_smoothing_by_n=False,
        spline_order=4,
        n_ghost_points=10,
        ghost_extension_bps=5.0,
        bin_width_bps=25.0,
        sabr_rate_floor=0.0,
        sabr_rate_ceiling_nstdev=6.0,
        sabr_n_strikes=240,
    )


def append_summary_row(rows, *, short, symbol, day, legend, mode, bl, stat_keys):
    local = {
        "mean": bl.mean_rate,
        "median": bl.percentile(50),
        "mode": mode_rate(bl),
        "p5": bl.percentile(5),
        "p10": bl.percentile(10),
        "p25": bl.percentile(25),
        "p75": bl.percentile(75),
        "p90": bl.percentile(90),
        "p95": bl.percentile(95),
        "input_strikes": len(bl.input.strikes_price),
        "input_min_rate": float(100.0 - np.max(bl.input.strikes_price)),
        "input_max_rate": float(100.0 - np.min(bl.input.strikes_price)),
        "forward_rate": bl.input.forward_rate,
        "warnings": "; ".join(bl.warnings),
    }
    exp = EXPECTED[(short, day)]
    row = {
        "contract": short,
        "symbol": symbol,
        "date": day.isoformat(),
        "legend": legend,
        "fetch_mode": FETCH_MODE,
        "distribution_mode": mode,
    }
    row.update(local)
    for key in stat_keys:
        row[f"{key}_jpm"] = exp[key]
        row[f"{key}_diff"] = local[key] - exp[key]
    row["rmse_stats"] = float(np.sqrt(np.mean([(local[k] - exp[k]) ** 2 for k in stat_keys])))
    row["jpm_no_strikes"] = exp["no_strikes"]
    row["jpm_min_rate"] = exp["min_rate"]
    row["jpm_max_rate"] = exp["max_rate"]
    rows.append(row)


def append_coarse_bins(rows, *, short, symbol, day, legend, mode, bl):
    for idx, label in enumerate(DISPLAY_LABELS):
        rows.append(
            {
                "contract": short,
                "symbol": symbol,
                "date": day.isoformat(),
                "legend": legend,
                "distribution_mode": mode,
                "bin": label,
                "prob_pct": integrate_between(bl, DISPLAY_EDGES[idx], DISPLAY_EDGES[idx + 1]) * 100.0,
            }
        )


def append_native_bins(rows, *, short, symbol, day, legend, mode, bl):
    edges = np.asarray(bl.bin_edges_rate, dtype=float)
    probs = np.asarray(bl.bin_probabilities, dtype=float)
    for idx, prob in enumerate(probs):
        rows.append(
            {
                "contract": short,
                "symbol": symbol,
                "date": day.isoformat(),
                "legend": legend,
                "distribution_mode": mode,
                "bin_left": float(edges[idx]),
                "bin_right": float(edges[idx + 1]),
                "bin_mid": float(0.5 * (edges[idx] + edges[idx + 1])),
                "prob_pct": float(prob * 100.0),
            }
        )


def plot_native_panels(snapshots, *, mode, filename, title):
    fig, axes = plt.subplots(1, 4, figsize=(18, 4.8), sharey=False)
    for ax, (short, _) in zip(axes, CONTRACTS):
        for legend, day, color in DATES:
            snap = snapshots.get((mode, short, day))
            if snap is None or snap.bl_result is None:
                continue
            bl = snap.bl_result
            edges = np.asarray(bl.bin_edges_rate, dtype=float)
            probs = np.asarray(bl.bin_probabilities, dtype=float) * 100.0
            if len(edges) != len(probs) + 1 or len(probs) == 0:
                continue
            ax.step(edges, np.r_[probs, probs[-1]], where="post", color=color, linewidth=1.6, label=legend)
        ax.set_title(short, loc="left", fontweight="bold", fontsize=16)
        ax.set_xlabel("rate (%)")
        ax.set_ylabel("probability (%)")
        ax.grid(True, linestyle=(0, (4, 4)), color="#bfbfbf", alpha=0.8)
        ax.set_xlim(1.75 if short in {"H7", "M7"} else 2.5, 6.0 if short in {"H7", "M7"} else 5.2)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.34), ncol=3, frameon=False, fontsize=9)
    fig.suptitle(title, fontsize=18, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_jpm_style_screenshot(summary, snapshots):
    raw_summary = summary[summary["distribution_mode"] == RAW_MODE].copy()
    if raw_summary.empty:
        return

    fig = plt.figure(figsize=(18, 8.7))
    fig.suptitle(
        "Implied Distributions* from SOFR Futures Options",
        x=0.01,
        y=0.985,
        ha="left",
        fontsize=24,
        fontweight="bold",
        fontfamily="serif",
    )
    fig.add_artist(
        plt.Line2D([0.01, 0.99], [0.995, 0.995], transform=fig.transFigure, color="#1685a9", linewidth=4)
    )

    table_ax = fig.add_axes([0.16, 0.63, 0.68, 0.28])
    table_ax.axis("off")
    columns = ["contract", "date", "mean", "median", "mode", "5th", "10th", "25th", "75th", "90th", "95th", "no. strikes", "min rate", "max rate"]
    rows = []
    for _, row in raw_summary.iterrows():
        rows.append(
            [
                row["contract"],
                row["date"],
                f"{row['mean']:.2f}",
                f"{row['median']:.2f}",
                f"{row['mode']:.2f}",
                f"{row['p5']:.2f}",
                f"{row['p10']:.2f}",
                f"{row['p25']:.2f}",
                f"{row['p75']:.2f}",
                f"{row['p90']:.2f}",
                f"{row['p95']:.2f}",
                f"{int(row['input_strikes'])}",
                f"{row['input_min_rate']:.2f}",
                f"{row['input_max_rate']:.2f}",
            ]
        )
    table = table_ax.table(cellText=rows, colLabels=columns, loc="center", cellLoc="right", colLoc="right")
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.25)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#3a3a3a")
        cell.set_linewidth(0.35)
        if r == 0:
            cell.set_text_props(fontweight="normal", fontfamily="serif")
            cell.set_linewidth(0.8)
        else:
            cell.set_text_props(fontfamily="serif")
        if c == 0:
            cell.set_text_props(ha="right", fontfamily="serif")

    panel_lefts = [0.06, 0.30, 0.54, 0.78]
    for left, (short, _) in zip(panel_lefts, CONTRACTS):
        ax = fig.add_axes([left, 0.20, 0.18, 0.36])
        for legend, day, color in DATES:
            snap = snapshots.get((RAW_MODE, short, day))
            if snap is None or snap.bl_result is None:
                continue
            bl = snap.bl_result
            edges = np.asarray(bl.bin_edges_rate, dtype=float)
            probs = np.asarray(bl.bin_probabilities, dtype=float) * 100.0
            if len(edges) != len(probs) + 1 or len(probs) == 0:
                continue
            ax.step(edges, np.r_[probs, probs[-1]], where="post", color=color, linewidth=1.4, label=legend)
        ax.text(0.02, 0.98, short, transform=ax.transAxes, ha="left", va="top", fontsize=18, fontweight="bold", fontfamily="serif")
        ax.set_xlabel("rate (%)", fontsize=10, fontfamily="serif")
        ax.set_ylabel("probability (%)", fontsize=10, fontfamily="serif")
        ax.grid(True, linestyle=(0, (4, 4)), color="#bfbfbf", alpha=0.8)
        ax.set_xlim(1.75 if short in {"H7", "M7"} else 2.5, 6.0 if short in {"H7", "M7"} else 5.2)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, frameon=False, fontsize=9)

    fig.savefig(OUT / "local_jpm_screenshot_sfr_implied_distribution_default.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    raw_dist = build_raw_extractor()
    sabr_dist = build_sabr_extractor()

    snapshots = {}
    summary_rows = []
    coarse_bin_rows = []
    native_bin_rows = []
    failures = []
    stat_keys = ["mean", "median", "mode", "p5", "p10", "p25", "p75", "p90", "p95"]

    for short, symbol in CONTRACTS:
        for legend, day, _ in DATES:
            print(f"FETCH {symbol} {day.isoformat()}", flush=True)
            try:
                # Use the listed-strike request bounded by the repo's SABR
                # smile offset cap, then apply the JPM extraction filters
                # locally. Full JPM generated-wing fetches can stall on
                # historical far-wing Barchart symbols that never listed.
                smile = mdp.fetch_sabr_smile(
                    {
                        "symbol": symbol,
                        "as_of": day,
                        "strike_offsets_bps": "listed",
                        "show_tqdm": False,
                    }
                )
                for mode, dist in ((RAW_MODE, raw_dist), (SABR_MODE, sabr_dist)):
                    snap = dist.extract(smile, run_gm=False)
                    bl = snap.bl_result
                    snapshots[(mode, short, day)] = snap
                    append_summary_row(
                        summary_rows,
                        short=short,
                        symbol=symbol,
                        day=day,
                        legend=legend,
                        mode=mode,
                        bl=bl,
                        stat_keys=stat_keys,
                    )
                    append_coarse_bins(
                        coarse_bin_rows,
                        short=short,
                        symbol=symbol,
                        day=day,
                        legend=legend,
                        mode=mode,
                        bl=bl,
                    )
                    append_native_bins(
                        native_bin_rows,
                        short=short,
                        symbol=symbol,
                        day=day,
                        legend=legend,
                        mode=mode,
                        bl=bl,
                    )
            except Exception as exc:
                failures.append({"contract": short, "symbol": symbol, "date": day.isoformat(), "error": repr(exc)})
                print(f"FAILED {symbol} {day.isoformat()}: {exc!r}", flush=True)

    summary = pd.DataFrame(summary_rows)
    coarse_bins = pd.DataFrame(coarse_bin_rows)
    native_bins = pd.DataFrame(native_bin_rows)
    pd.DataFrame(failures).to_csv(OUT / "failures.csv", index=False)
    summary.to_csv(OUT / "summary_vs_jpm_appendix_modes.csv", index=False)
    coarse_bins.to_csv(OUT / "coarse_bin_probabilities_modes.csv", index=False)
    native_bins.to_csv(OUT / "native_25bp_bin_probabilities_modes.csv", index=False)

    fig, axes = plt.subplots(1, 4, figsize=(18, 4.8), sharey=False)
    x_edges = np.array([1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0, 4.25, 4.5, 4.75])
    for ax, (short, _) in zip(axes, CONTRACTS):
        for legend, day, color in DATES:
            snap = snapshots.get((RAW_MODE, short, day))
            if snap is None or snap.bl_result is None:
                continue
            probs = [
                integrate_between(snap.bl_result, DISPLAY_EDGES[idx], DISPLAY_EDGES[idx + 1]) * 100.0
                for idx in range(len(DISPLAY_LABELS))
            ]
            ax.step(x_edges, probs + [probs[-1]], where="post", color=color, linewidth=1.6, label=legend)
        ax.set_title(short, loc="left", fontweight="bold", fontsize=16)
        ax.set_xlabel("rate (%)")
        ax.set_ylabel("probability (%)")
        ax.grid(True, linestyle=(0, (4, 4)), color="#bfbfbf", alpha=0.8)
        ax.set_xlim(1.75 if short in {"H7", "M7"} else 2.5, 6.0 if short in {"H7", "M7"} else 5.2)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.34), ncol=3, frameon=False, fontsize=9)
    fig.suptitle("Local JPM-Method Implied Distributions from SOFR Futures Options", fontsize=18, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "local_jpm_appendix_recreation_panels_bounded.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    plot_native_panels(
        snapshots,
        mode=RAW_MODE,
        filename="local_jpm_appendix_native_25bp_bins.png",
        title="Local Raw-Premium BL Distributions, Native 25bp Bins",
    )
    plot_jpm_style_screenshot(summary, snapshots)
    plot_native_panels(
        snapshots,
        mode=SABR_MODE,
        filename="local_sabr_smoothed_native_25bp_bins.png",
        title="Local SABR-Smoothed BL Distributions, Native 25bp Bins",
    )

    if not summary.empty:
        cols = [f"{key}_diff" for key in stat_keys]
        plot_df = summary[summary["distribution_mode"] == RAW_MODE].copy()
        plot_df["row"] = plot_df["contract"] + " " + plot_df["date"]
        mat = plot_df.set_index("row")[cols]
        fig, ax = plt.subplots(figsize=(11, max(4, 0.35 * len(mat))))
        im = ax.imshow(mat.values, cmap="RdBu_r", vmin=-0.35, vmax=0.35, aspect="auto")
        ax.set_yticks(range(len(mat.index)))
        ax.set_yticklabels(mat.index, fontsize=8)
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([c.replace("_diff", "") for c in cols], rotation=45, ha="right")
        for row_idx in range(mat.shape[0]):
            for col_idx in range(mat.shape[1]):
                ax.text(col_idx, row_idx, f"{mat.values[row_idx, col_idx]:+.2f}", ha="center", va="center", fontsize=7)
        ax.set_title("Local minus JPM appendix table (rate pct-points)")
        fig.colorbar(im, ax=ax, label="pct-points")
        fig.tight_layout()
        fig.savefig(OUT / "local_minus_jpm_stats_heatmap_bounded.png", dpi=180, bbox_inches="tight")
        plt.close(fig)

        plot_df = summary[summary["distribution_mode"] == SABR_MODE].copy()
        plot_df["row"] = plot_df["contract"] + " " + plot_df["date"]
        mat = plot_df.set_index("row")[cols]
        fig, ax = plt.subplots(figsize=(11, max(4, 0.35 * len(mat))))
        im = ax.imshow(mat.values, cmap="RdBu_r", vmin=-0.35, vmax=0.35, aspect="auto")
        ax.set_yticks(range(len(mat.index)))
        ax.set_yticklabels(mat.index, fontsize=8)
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([c.replace("_diff", "") for c in cols], rotation=45, ha="right")
        for row_idx in range(mat.shape[0]):
            for col_idx in range(mat.shape[1]):
                ax.text(col_idx, row_idx, f"{mat.values[row_idx, col_idx]:+.2f}", ha="center", va="center", fontsize=7)
        ax.set_title("SABR-smoothed local minus JPM appendix table (rate pct-points)")
        fig.colorbar(im, ax=ax, label="pct-points")
        fig.tight_layout()
        fig.savefig(OUT / "local_sabr_minus_jpm_stats_heatmap.png", dpi=180, bbox_inches="tight")
        plt.close(fig)

    print(f"WROTE {OUT.resolve()}", flush=True)
    if not summary.empty:
        cols = [
            "contract",
            "date",
            "input_strikes",
            "jpm_no_strikes",
            "mean",
            "mean_jpm",
            "median",
            "median_jpm",
            "mode",
            "mode_jpm",
            "p5",
            "p5_jpm",
            "p95",
            "p95_jpm",
            "rmse_stats",
        ]
        print(summary[cols].to_string(index=False), flush=True)
    if failures:
        print(f"FAILURES {failures}", flush=True)


if __name__ == "__main__":
    main()
