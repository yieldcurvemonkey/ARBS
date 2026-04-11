import datetime as dt

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import rateslib as rl

from MDP.IRSwaps.BARCHART_STIRF.rl import plot_overnight_forward_curves
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS


def _make_sofr_curve(*, ref_date: dt.date, tail_shift: float = 0.0) -> rl.Curve:
    cfg = RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]
    nodes = {
        rl.dt(ref_date.year, ref_date.month, ref_date.day): 1.0,
        rl.dt(ref_date.year + 1, ref_date.month, ref_date.day): 0.9600 - tail_shift,
        rl.dt(ref_date.year + 2, ref_date.month, ref_date.day): 0.9200 - tail_shift,
        rl.dt(ref_date.year + 3, ref_date.month, ref_date.day): 0.8800 - tail_shift,
        rl.dt(ref_date.year + 4, ref_date.month, ref_date.day): 0.8400 - tail_shift,
    }
    curve = rl.Curve(
        nodes=nodes,
        id="USD-SOFR-1D",
        convention=cfg["DayCounter"],
        calendar=cfg["Calendar"],
        modifier=cfg["BusinessConvention"],
    )
    curve.reference_key = "USD-SOFR-1D"
    curve.timestamp = pd.Timestamp(ref_date)
    return curve


def test_plot_overnight_forward_curves_can_plot_first_twelve_quarterly_imm_forwards():
    ref_date = dt.date(2026, 9, 21)
    base_curve = _make_sofr_curve(ref_date=ref_date)
    shifted_curve = _make_sofr_curve(ref_date=ref_date, tail_shift=0.0025)

    fig, ax, lines = plot_overnight_forward_curves(
        [base_curve, shifted_curve],
        labels=["base", "shifted"],
        quarterly_imm_forwards=True,
        title="IMM Forwards",
    )
    try:
        fig.canvas.draw()
        tick_labels = [tick.get_text() for tick in ax.get_xticklabels()]

        assert len(lines) == 2
        assert tick_labels[:4] == [
            "IMM_Z26xIMM_H27",
            "IMM_H27xIMM_M27",
            "IMM_M27xIMM_U27",
            "IMM_U27xIMM_Z27",
        ]
        assert ax.get_title() == "IMM Forwards"
    finally:
        plt.close(fig)


def test_plot_overnight_forward_curves_quarterly_imm_difference_uses_comparator_only():
    ref_date = dt.date(2026, 9, 21)
    base_curve = _make_sofr_curve(ref_date=ref_date)
    shifted_curve = _make_sofr_curve(ref_date=ref_date, tail_shift=0.0025)

    fig, ax, lines = plot_overnight_forward_curves(
        [base_curve, shifted_curve],
        labels=["base", "shifted"],
        quarterly_imm_forwards=True,
        difference=True,
    )
    try:
        fig.canvas.draw()
        ydata = list(lines[0].get_ydata())
        legend = ax.get_legend()

        assert len(lines) == 1
        assert len(ydata) == 12
        assert any((not pd.isna(value)) and float(value) > 0.0 for value in ydata)
        assert legend is not None
        assert [text.get_text() for text in legend.get_texts()] == ["shifted"]
    finally:
        plt.close(fig)
