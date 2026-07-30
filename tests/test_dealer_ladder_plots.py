"""Figure-layer tests, aimed at the two ways a figure can lie.

The first is stating the wrong thing: a gate that was NOT REACHED painted green as PASS.
That happened, and the cause is that ``pass=None`` comes back from ``read_csv`` as NaN
and **NaN is truthy**, so ``"PASS" if p else "FAIL"`` reported an ungated result as a
passing one — the single worst thing this figure could do.

The second is being unreadable: text overprinting text. Placement here is MEASURED from
the laid-out labels rather than guessed at in data coordinates, because the guessing
approach put "G4-primary(in-sample)" through its own FAIL and then, once the columns were
reordered, through its own headline.
"""
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from BT.dealer_ladder import plots  # noqa: E402


@pytest.fixture(autouse=True)
def _style_and_close():
    plots.use_style()
    yield
    plt.close("all")


# ------------------------------------------------------------------ the truthiness bug
@pytest.mark.parametrize("value", [None, float("nan"), np.nan, "", "none", "nan",
                                   "NaN", "unknown"])
def test_an_undecided_gate_is_never_reported_as_passing(value):
    assert plots._state(value) is None


@pytest.mark.parametrize("value", [True, 1, "True", "true", "PASS", "yes", "1"])
def test_pass_survives_a_csv_round_trip(value):
    assert plots._state(value) is True


@pytest.mark.parametrize("value", [False, 0, "False", "false", "FAIL", "no", "0"])
def test_fail_survives_a_csv_round_trip(value):
    assert plots._state(value) is False


def test_nan_is_truthy_which_is_why_state_exists():
    """The property the bug rested on, pinned so the shortcut is never reinstated."""
    assert bool(float("nan")) is True
    assert plots._state(float("nan")) is None


def test_verdict_strip_words_match_the_states():
    rows = [{"gate": "G0", "pass": True, "headline": "a"},
            {"gate": "G1", "pass": False, "headline": "b"},
            {"gate": "G2", "pass": np.nan, "headline": "not reached"}]
    ax = plots.verdict_strip(rows)
    words = [t.get_text() for t in ax.texts]
    assert "PASS" in words and "FAIL" in words and "N/A" in words
    # and the unreached gate is grey, not green
    na = [t for t in ax.texts if t.get_text() == "N/A"][0]
    assert na.get_color() == plots.MUTED


def test_a_real_csv_round_trip_keeps_an_unreached_gate_unreached(tmp_path):
    """End to end, because the bug lived in the seam and not in either half."""
    path = tmp_path / "verdicts.csv"
    pd.DataFrame([{"gate": "G3", "pass": None, "headline": "not reached"},
                  {"gate": "G4", "pass": False, "headline": "failed"}]).to_csv(path)
    back = pd.read_csv(path, index_col=0)
    ax = plots.verdict_strip(back.to_dict("records"))
    words = [t.get_text() for t in ax.texts]
    assert "N/A" in words
    assert "PASS" not in words


# ---------------------------------------------------------------------- the layout bug
def _extents(ax):
    fig = ax.figure
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    return {t.get_text(): t.get_window_extent(renderer=rend) for t in ax.texts}


def test_the_longest_gate_name_does_not_overprint_its_headline():
    rows = [{"gate": "G4-primary(LOCKOUT one-shot)", "pass": False,
             "headline": "HEADLINE-TEXT"},
            {"gate": "G0", "pass": True, "headline": "short"}]
    ax = plots.verdict_strip(rows)
    ext = _extents(ax)
    label = ext["G4-primary(LOCKOUT one-shot)"]
    head = ext["HEADLINE-TEXT"]
    assert head.x0 > label.x1, (head.x0, label.x1)


def test_the_state_word_never_overprints_the_gate_name():
    ax = plots.verdict_strip([{"gate": "G4-primary(in-sample)", "pass": False,
                               "headline": "h"}])
    ext = _extents(ax)
    assert ext["G4-primary(in-sample)"].x0 > ext["FAIL"].x1


def test_a_gate_name_is_never_truncated():
    """Truncating would drop the suffix that distinguishes the in-sample run from the
    one-shot LOCKOUT, which is the most important distinction on the figure."""
    name = "G4-primary(LOCKOUT one-shot)"
    ax = plots.verdict_strip([{"gate": name, "pass": False, "headline": "h"}])
    assert name in [t.get_text() for t in ax.texts]


def test_short_labels_keep_the_tight_layout():
    ax = plots.verdict_strip([{"gate": "G0", "pass": True, "headline": "HEAD"}])
    ext = _extents(ax)
    inv = ax.transAxes.inverted()
    x = inv.transform((ext["HEAD"].x0, 0.0))[0]
    assert x == pytest.approx(0.335, abs=0.01), "must not drift right without cause"


# --------------------------------------------------------------- the other figures run
def test_staleness_panels_render_and_keep_one_axis_each():
    tab = pd.DataFrame({"max_stale_min": ["none", 30, 5, 0],
                        "n_trades": [900, 880, 420, 120], "gross_bp": [.4, .42, .55, .3],
                        "net_bp": [-.09, -.08, .05, -.2],
                        "share_of_uncapped_trades": [1, .98, .47, .13]})
    axes = plots.staleness_panels(tab)
    assert len(axes) == 2
    for ax in axes:
        # a twin axis would show up as a second y-axis sharing the same subplot spec
        assert len([a for a in ax.figure.axes
                    if a.get_subplotspec() == ax.get_subplotspec()]) == 1


def test_attenuation_curve_puts_chance_accuracy_at_minus_cost():
    ax = plots.attenuation_curve(1.0, 0.5)
    line = ax.lines[0]
    xs, ys = line.get_xdata(), line.get_ydata()
    at_half = ys[list(xs).index(0.5)]
    assert at_half == pytest.approx(-0.5), "a=0.5 is trading noise and paying every tick"


def test_league_dotplot_takes_its_labels_from_the_index_when_needed():
    df = pd.DataFrame({"mean": [0.1, -0.2], "lo": [-0.1, -0.4], "hi": [0.3, 0.0]},
                      index=pd.Index(["variant-a", "variant-b"], name="variant"))
    ax = plots.league_dotplot(df)
    assert any("variant-" in str(t.get_text()) for t in ax.get_yticklabels())


def test_placebo_panel_takes_its_labels_from_the_index_when_needed():
    df = pd.DataFrame({"mean": [-0.09, 0.0]},
                      index=pd.Index(["none (reference)", "sign shuffle"],
                                     name="placebo"))
    ax = plots.placebo_panel(df)
    assert any("none" in str(t.get_text()) for t in ax.get_yticklabels())
