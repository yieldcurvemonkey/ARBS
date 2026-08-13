"""The trade dashboard, now living in ``BT.trade_dashboard``.

This module was the first home of the five-panel interactive book view, written
for the econ-release fade. It generalised -- any study that produces a trade log
wants the same figure, and a QueryDrivenBacktest wants it too -- so the code
moved to ``BT/trade_dashboard.py`` and this file is the import path the
notebooks in this folder already use.

Nothing here changes what those notebooks draw: ``trade_dashboard`` and
``compare_curves`` are the same functions, and on a frame carrying this study's
columns (``release_ts``/``pnl_bp``/``hold_min``/``exit_reason``/``z``) they
produce an identical figure. What moved is the assumption set -- the unit is no
longer hard-coded to basis points, the colour axis is no longer required to be
an exit reason, and a backtest object can be passed where a frame used to be.

The renderer pin stays HERE rather than in the library. nbclient has no browser
to negotiate with, so it has to be pinned somewhere; doing it at import time in
``BT`` would mutate global plotly state for every process that imports the
package, which is not a library's business.
"""

from __future__ import annotations

import sys
from pathlib import Path

import plotly.io as pio

# The notebooks in this folder bake an absolute REPO into their first cell, and
# it is not necessarily the checkout this file is sitting in. Resolve the repo
# root from __file__ instead, so the shim finds BT wherever it was imported from
# rather than depending on what the caller happened to put on sys.path.
_ROOT = str(Path(__file__).resolve().parents[3])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from BT.trade_dashboard import (  # noqa: E402,F401  (re-exported for the notebooks)
    BG,
    CATEGORICAL,
    FG,
    GRID,
    MUTED,
    PANEL,
    REASON_COLOUR,
    compare_curves,
    summary_stats,
    to_book,
    trade_dashboard,
)

#: The mimetype bundle is what a saved .ipynb replays in Jupyter/VSCode; the
#: connected notebook renderer keeps plotly.js on a CDN rather than embedding
#: ~3MB of javascript into every notebook, every execution.
pio.renderers.default = "plotly_mimetype+notebook_connected"

__all__ = [
    "BG", "CATEGORICAL", "FG", "GRID", "MUTED", "PANEL", "REASON_COLOUR",
    "compare_curves", "summary_stats", "to_book", "trade_dashboard",
]
