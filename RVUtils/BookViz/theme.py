"""One dark palette and one renderer decision, shared by every figure in the package.

Kept separate from the figures so a notebook can restyle the whole package by rebinding a name,
and so the renderer choice is stated once with its reason rather than repeated at the top of every
module that happens to import plotly.
"""

from __future__ import annotations

from typing import Dict, Sequence

import plotly.io as pio

__all__ = [
    "BG", "PANEL", "GRID", "FG", "MUTED", "ACCENT", "POS", "NEG", "WARN",
    "SERIES_PALETTE", "CATEGORY_COLOURS", "category_colour", "use_notebook_renderer",
]

BG = "#0e1117"
PANEL = "#161a23"
GRID = "#2a3040"
FG = "#d8dee9"
MUTED = "#7b8394"

ACCENT = "#4dabf7"
POS = "#3ddc84"
NEG = "#ff5c5c"
WARN = "#ff9f43"

#: Distinct hues for N unrelated series (book comparison, component decomposition).
SERIES_PALETTE: Sequence[str] = ("#4dabf7", "#3ddc84", "#ff9f43", "#ff5c5c", "#9b8cff", "#f6c744",
                                 "#4dd0e1", "#f06292")

#: Conventional colours for exit reasons seen across ARBS books. Anything unlisted falls back to
#: MUTED, which is deliberate: an unrecognised category should look unremarkable rather than borrow
#: the visual weight of "stop" or "target".
CATEGORY_COLOURS: Dict[str, str] = {
    # econ-release-fade vocabulary
    "target": POS, "stop": NEG, "trail": WARN, "time_stop": "#f6c744",
    "eod": "#9b8cff", "no_path": MUTED,
    # GSS / QDB vocabulary
    "zsig_below_repo": POS, "z_rollover": "#9b8cff", "gss_exit": ACCENT,
    # generic
    "win": POS, "loss": NEG, "flat": MUTED, "-": MUTED,
}


def category_colour(name: object) -> str:
    return CATEGORY_COLOURS.get(str(name), MUTED)


def use_notebook_renderer() -> None:
    """Pin the plotly renderer for headless notebook execution.

    nbclient has no browser to negotiate with, so the renderer must be explicit or figures render
    to nothing on execution. ``notebook_connected`` keeps plotly.js on a CDN rather than embedding
    ~3MB of javascript into every notebook on every execution.

    Not called at import: a module that mutates global renderer state simply by being imported is
    hostile to any caller with its own opinion. The notebook builders call it.
    """
    pio.renderers.default = "plotly_mimetype+notebook_connected"
