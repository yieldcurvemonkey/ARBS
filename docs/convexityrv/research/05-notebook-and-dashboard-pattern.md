I have everything. Writing the map.

---

# 1. Which generator produces `usd_fomc_configurable_backtest.ipynb`

**`_make_config_notebook.py`** — not `_make_usd_notebook.py`.

| generator | `OUT =` | lines |
|---|---|---|
| `C:/Users/chris/clee/ARBS/notebooks/backtests/intraday_fed_hawk_dove/_make_config_notebook.py` | `HERE / "usd_fomc_configurable_backtest.ipynb"` | 725 |
| `C:/Users/chris/clee/ARBS/notebooks/backtests/intraday_fed_hawk_dove/_make_usd_notebook.py` | `HERE / "usd_fomc_speaker_hawk_dove_backtest.ipynb"` | 836 |
| `C:/Users/chris/clee/ARBS/notebooks/backtests/intraday_fed_hawk_dove/_make_nonvoter_fade_notebook.py` | `usd_fomc_nonvoter_fade.ipynb` | 1068 |

Grep evidence (`grep -n usd_fomc_configurable_backtest` over non-`.ipynb`):
```
_make_config_notebook.py:1:"""Generate usd_fomc_configurable_backtest.ipynb — one dict describes one backtest."""
_make_config_notebook.py:9:OUT = HERE / "usd_fomc_configurable_backtest.ipynb"
```

**Critical structural fact:** these three generators do **NOT** use `_py2nb.py`. They are *direct JSON emitters* — they build a `cells` list with `md()`/`code()` helpers and `json.dumps` it. `_py2nb.py` is the *other* notebook family (`sfr_rv_lab_*`, `run_*.py` drivers). Two distinct patterns coexist in this repo; pick one deliberately.

---

# 2. The configurable-notebook pattern, exactly

## 2a. The generator scaffold (verbatim, `_make_config_notebook.py` lines 1–15 and 720–725)

```python
"""Generate usd_fomc_configurable_backtest.ipynb — one dict describes one backtest."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "usd_fomc_configurable_backtest.ipynb"
cells: list = []


def _lines(src): return src.strip("\n").splitlines(keepends=True)
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells):02d}", "metadata": {}, "source": _lines(src)})
def code(src): cells.append({"cell_type": "code", "id": f"cd{len(cells):02d}", "execution_count": None, "metadata": {}, "outputs": [], "source": _lines(src)})
```

Footer:
```python
nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "stir", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.12"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({len(cells)} cells)")
```

Note `_make_usd_notebook.py` uses the identical scaffold with multi-line `def md/def code` bodies and the same kernelspec `stir` / `python 3.12` / `nbformat 4.5`.

## 2b. Cell order (exact)

| # | type | content |
|---|---|---|
| 0 | md | Title `# FOMC Speaker Hawk/Dove — Configurable Backtest, 2019 – 2026`, motivation, a fenced ```python CONFIG = {...}``` *preview*, "Order of operations" ASCII pipeline, "Three things a config deliberately cannot do", `---`, a blockquote `> ## ⚠ The default labels are not point-in-time` |
| 1 | code | **Setup cell**: `%load_ext autoreload` / `%autoreload 2`, absolute `REPO` string, `sys.path.insert`, imports, matplotlib style, MDP construction, bar-cache load, raw-event unpickle, then `print()` of a provenance banner |
| 2 | md | `## 1. The config` — "Edit this cell and re-run the notebook. Everything below reads `CONFIG`." |
| 3 | code | **The CONFIG dict + the single run** |
| 4 | md | `### 1.1 Recipes` — fenced ready-made configs |
| 5 | md | `## 2. Does the machine give the right answer to a question we already know?` |
| 6 | code | known-answer reproduction, `checks` list of `(name, bool, value)`, `display(...)`, `assert all(...)`, then explicit accounting of the residual |
| 7 | md | `## 3. What this config actually trades` |
| 8 | code | funnel table |
| 9 | md | `## 4. How this config performed` |
| 10 | code | `perf()` rows + 2-panel matplotlib (cum curve over per-trade bars) |
| 11 | md | `## 5. The instrument knob` |
| 12 | code | coverage probe → `WARM` ranks → `HC.compare(inst_cfgs, …)` → `inst_tbl`, 2 panels |
| 13 | md | `## 6. The timing knob` |
| 14 | code | entry×exit grid → 2 seaborn heatmaps (Sharpe, trades) |
| 15 | md | `## 7. The filter knob` |
| 16 | code | `FILTER_CFGS` list → `HC.compare` → `flt_tbl`, barh + cum curves |
| 17 | md | `### 7.1 The rotation as a natural experiment` |
| 18 | code | permutation test |
| 19 | md | `## 8. Costs` |
| 20 | code | cost sensitivity table + plot |
| 21 | md | `## 9. What the search cost` |
| 22 | code | Deflated Sharpe over every config the notebook ran |
| 23 | md | `## 10. Robustness of the active config` |
| 24 | code | sign-flip permutation, split-half, by-year, by-bucket (3 panels) |
| 25 | md | `## 11. Trade log` |
| 26 | code | styled log + CSV writeout with config attached |
| 27 | md | `## 12. Reading this notebook` — how to read, in bold-lead paragraphs |

Section numbering is `## N. <lowercase-ish sentence>`, subsections `### N.1 <…>`. Markdown prose is long-form argumentative English, **bold lead-ins**, tables where a comparison is being made, and it names failure modes rather than gesturing at them.

## 2c. How config knobs are declared and documented (verbatim, cell 3)

```python
CONFIG = {
    "name": "baseline",
    "bank": "FED",

    # WHAT IS TRADED ------------------------------------------------------
    #   {"kind": "outright", "rank": 3}            the nth quarterly IMM contract
    #   {"structure": "FLY_2_3_4"}                 a named package (printed above)
    #   {"legs": [[2, -1.0], [4, 1.0]]}            explicit RATE-space weights
    "instrument": {"kind": "outright", "rank": 3},

    # WHEN ----------------------------------------------------------------
    "timing": {
        "entry_offset_min": -45,      # minutes relative to the speech, market-local
        "exit_offset_min": 180,
        "max_staleness_min": 45,      # how old the causal bar may be
        "retime_synthetic": False,    # day-only events trade the session, not a fake minute
    },

    # WHO / WHICH TRADES --------------------------------------------------
    "filters": {
        "start": None,                # "2022-01-01"
        "end": None,
        "voters": "all",              # all | voters | nonvoters
        "roles": None,                # ["Chair","Governor","President","President (NY)"]
        "speakers_include": None,
        "speakers_exclude": None,
        "timestamp_source": "all",    # all | forexfactory | synthetic
        "min_abs_bucket": 1,          # 2 -> conviction trades only
        "direction": "both",          # both | hawk | dove
        "era": "all",                 # all | GE | SR3
        "days_to_fomc_max": None,     # 10 -> only the run-up to a meeting
        "days_to_fomc_min": None,
        "weekdays": None,             # [0,1,2,3,4], Monday = 0
    },

    # HOW MUCH ------------------------------------------------------------
    "sizing": "equal",                # equal | conviction (x |bucket|)
    "cost_bp": 0.0,                   # round trip, per unit of gross risk
}

RES = HC.run_config(CONFIG, RAW, MDP)
CLOSED = RES.closed
print(f"{RES.structure.name}  ->  {len(CLOSED)} trades")
```

**Declaration conventions, distilled:** a plain nested `dict` (not a dataclass); ALL-CAPS banner comments (`# WHAT IS TRADED ---…`) group knobs into semantic blocks; every knob carries an inline `#` comment giving its legal values as `a | b | c` or a concrete example; `None` means "off"; the dict is *partial* — `HC.merge()` fills defaults.

Recipes cell (verbatim, markdown so it does not execute):
```python
VOTERS_ONLY    = {"name": "voters",      "filters": {"voters": "voters"}}
GOVERNORS      = {"name": "governors",   "filters": {"roles": ["Chair", "Governor"]}}
PRESIDENTS     = {"name": "presidents",  "filters": {"roles": ["President", "President (NY)"]}}
CONVICTION     = {"name": "|bucket|=2",  "filters": {"min_abs_bucket": 2}}
SOFR_ERA       = {"name": "SOFR only",   "filters": {"era": "SR3"}}
REAL_TIMES     = {"name": "timed only",  "filters": {"timestamp_source": "forexfactory"}}
PRE_MEETING    = {"name": "<=10d to FOMC", "filters": {"days_to_fomc_max": 10}}
FAST           = {"name": "T-15/T+60",   "timing": {"entry_offset_min": -15, "exit_offset_min": 60}}
FRONT_CONTRACT = {"name": "rank 1",      "instrument": {"kind": "outright", "rank": 1}}
CURVE_FLY      = {"name": "2s3s4s fly",  "instrument": {"structure": "FLY_2_3_4"}}
NET_OF_COST    = {"name": "0.25bp cost", "cost_bp": 0.25}
```

## 2d. The CONFIG contract lives in `hawk_dove_config.py` (imported as `HC`)

`C:/Users/chris/clee/ARBS/notebooks/backtests/intraday_fed_hawk_dove/hawk_dove_config.py` (484 lines). Public API:

```python
DEFAULT_CONFIG: Dict[str, Any]                    # line 58 — the same dict, plus "flip": "none"
FLIP_RULES = ("none", "nonvoters", "voters", "all")
def flip_sign(attrs, rule) -> float               # +1 as read, -1 to fade
def merge(*overrides) -> Dict[str, Any]           # DEFAULT_CONFIG + nested overrides, left to right
def catalogue(max_rank=6) -> Dict[str, GRID.Structure]
def resolve_instrument(spec, max_rank=8) -> GRID.Structure   # "legs" | "structure" | {"kind":"outright","rank":n}
def apply_filters(events, f) -> tuple             # (filtered, drops)
def retime(events, cfg, entry_min, exit_min, retime_synthetic) -> tuple
def check_coverage(events, cfg, ranks) -> dict    # {"ok","wanted","missing","hint"}

@dataclass
class Result:
    config: Dict[str, Any]
    structure: GRID.Structure
    closed: pd.DataFrame
    funnel: Dict[str, Any]
    @property
    def summary(self) -> Dict[str, Any]

def run_config(config, raw_events, mdp, *, show_progress=False, strict=True) -> Result
def compare(configs, raw_events, mdp, *, raise_on_cold=False) -> tuple   # (table_df, {name: Result})
def sweep_knob(base, path, values, raw_events, mdp, *, label=None) -> tuple
```

`run_config` docstring is the pipeline in one line: `"""Filter -> re-time -> resolve overlaps -> gate -> price. In that order."""`

`RES.closed` columns (from `run_config` rows, lines 404–431):
`tag, bank, ccy, speaker, role, is_voter, era, days_to_fomc, timestamp_source, symbol, structure, bucket, abs_bucket, flip, opened_at, closed_at, d_rate_bp, pnl_bp, pnl_bp_gross, year, direction, profitable`

`RES.funnel` keys: `raw, after_filters, filter_drops, after_retime_overlap, retime_drops, gate_reasons, coverage, n_missing_bars, panel_incomplete_dropped`

## 2e. How `QueryDrivenBacktest` is wired — **it is not, in this notebook**

Important correction to your brief: `usd_fomc_configurable_backtest.ipynb` uses a **closed-form vectorised pipeline** (`HC.run_config`), *not* `QueryDrivenBacktest`. §2 of the notebook exists precisely to *tie it out against* the engine's saved P&L:

```python
base = HC.run_config({"name": "published baseline"}, RAW, MDP)
with open(CACHE / "closed_manual.pkl", "rb") as f:
    eng = pickle.load(f)["FED"].copy()
eng["tag"] = [next(iter(q.tags), None) for q in eng["source_query"]]
j = base.closed.merge(eng[["tag","pnl_bp","opened_at","closed_at"]].rename(...), on="tag", how="inner")
...
assert all(ok for _, ok, _ in checks), "the config engine does NOT reproduce the published run"
```

The `QueryDrivenBacktest` wiring the family *describes* is stated in `_make_usd_notebook.py` markdown:

> `rateslib.STIRFuture` outrights on **SR3 (3M SOFR, CME)** through `Query.STIRFutures.STIRFutureQuery`, priced from Barchart minute bars, run on the same `QueryDrivenBacktest` / `TimeGrid` / `Trigger` / `AddQueryAction` / `UnwindPositionsAction` pattern as the original notebook. Hawk → rates higher → **pay fixed = SELL the future**.

Canonical wiring in code (`C:/Users/chris/clee/ARBS/BT/gss_fly/backtest.py:239`, same shape at `BT/xccy_rv/backtest.py:145`, `BT/serff/engine_backtest.py:248`):

```python
strategy = QueryStrategy(name=cfg.name, triggers=[trigger])
bt = QueryDrivenBacktest(
    time_grid=TimeGrid(grid_dates),
    strategy=strategy,
    mdp=mdp,
    show_progress=show_progress,
    progress_desc="GSS FLY BACKTEST",
)
bt.run()
equity = pd.Series(bt.mtm_history).sort_index()
```

## 2f. How results are rendered

- Tables → `display(pd.DataFrame(rows).set_index("book").round(4))` or `display(pd.Series(row).to_frame(CONFIG.get("name","config")))`.
- Matplotlib, `plt.style.use("ggplot")`, `figsize=(14,6)` default; multi-panel via `plt.subplots(..., gridspec_kw={"height_ratios": [2, 1]})`; always `plt.tight_layout(); plt.show()`.
- Green/red convention: `["seagreen" if x > 0 else "indianred" for x in …]`.
- Heatmaps via `sns.heatmap(..., annot=True, fmt=".2f", cmap="RdYlGn", center=0)`.
- **The bar-width trap, commented in both generators verbatim:**
```python
# Width needs a real duration: a bare int is read as NANOSECONDS against a
# datetime64 x, collapsing every bar to zero width. Cap keeps dense books visible.
_span = CLOSED.opened_at.max() - CLOSED.opened_at.min()
_w = _span / min(len(CLOSED), 400) if _span and len(CLOSED) else pd.Timedelta(days=1)
ax.bar(CLOSED.opened_at.values, CLOSED.pnl_bp.values, width=_w, ...)
```
- Trade log → pandas Styler with bars, then CSV with the config serialised alongside:
```python
display(log.style.format({"pnl_bp": "{:+.3f}", "cum_bp": "{:+.2f}", "d_rate_bp": "{:+.3f}"})
        .bar(subset=["pnl_bp"], color=["#d65f5f", "#5fba7d"], align="zero"))
out = CACHE / f"usd_fomc_config_{CONFIG.get('name','config').replace(' ', '_')}.csv"
log.to_csv(out, index=False)
summary = {"config": json.dumps(CONFIG, default=str), **{...G.summarize(CLOSED)...}}
```
- Plotly dashboards (the `_make_nonvoter_fade_notebook.py` evolution) — see §4e.

---

# 3. `.py` → `.ipynb` → executed → verified

## 3a. `_py2nb.py` — `C:/Users/chris/clee/ARBS/notebooks/backtests/_py2nb.py` (72 lines)

Percent-format splitter, jupytext convention. Rules:
- A line starting with `# %%` **ends** the current cell and starts a new one; the marker line itself is discarded.
- `# %% [markdown]` makes the next cell markdown; its body is a comment block, un-prefixed by `l[2:] if l.startswith("# ") else ("" if l.strip() == "#" else l)`.
- Empty/whitespace-only cells are dropped. Cell ids are `c000`, `c001`, …
- Output metadata: kernelspec `Python 3`/`python3`, `language_info` version `3.11`, `nbformat 4.5`, `json.dumps(nb, indent=1)`.

```python
def convert(py_path: Path, nb_path: Path | None = None) -> Path:
    nb_path = nb_path or py_path.with_suffix(".ipynb")
    ...
if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        print(convert(p))
```
Usage from its own docstring: `python notebooks/backtests/_py2nb.py sfr_rv_lab_skew_basis.py`

## 3b. `_verify_nb.py` — `C:/Users/chris/clee/ARBS/notebooks/backtests/_verify_nb.py` (57 lines)

Reads the `.ipynb` JSON rather than trusting the exit code. Per code cell: counts `execution_count is None` as `unrun`, counts every output, flags `output_type == "error"`, counts `image/png` outputs as figures.

```python
ok = not errors and unrun == 0
msg = (f"{path.name}: {len(code)} code cells, {n_out} outputs, {n_img} figures, "
       f"{unrun} unrun, {len(errors)} errors")
```
Prints `OK   `/`FAIL ` per file, `\n{bad} notebook(s) failed verification`, returns exit 1 if any failed. Accepts globs, resolved relative to CWD (`Path().glob(a)`), so **run it with `cwd` set to the notebook directory**.

## 3c. Exact command lines used in the repo

The canonical three-step driver, verbatim from `C:/Users/chris/clee/ARBS/notebooks/backtests/run_sfr_rv_lab.py:85-104` (identical in `run_zq_kink_fade.py`, `run_sfr_kink_fade.py`, `run_sfr_fly_meanrev.py`, `run_outcome_map.py`, `run_meeting_prob.py`):

```python
rc, log = sh([sys.executable, str(HERE / "_py2nb.py"), py.name], cwd=HERE)
...
rc, log = sh(["jupyter", "nbconvert", "--to", "notebook", "--execute",
              "--inplace", "--ExecutePreprocessor.timeout=5400",
              nb.name], cwd=HERE)
...
rc, log = sh([sys.executable, str(HERE / "_verify_nb.py")]
             + [f"{n}.ipynb" for n in names if (HERE / f"{n}.ipynb").exists()],
             cwd=HERE)
```
where `def sh(cmd, cwd, timeout=7200): p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)`.

Shell equivalents actually used in the repo:

```bash
# driver (docstring of run_sfr_rv_lab.py)
conda run -n stir python notebooks/backtests/run_sfr_rv_lab.py
conda run -n stir python notebooks/backtests/run_sfr_rv_lab.py --only skew_basis
conda run -n stir python notebooks/backtests/run_sfr_rv_lab.py --no-merge

# one-off execute, docs/plans/2026-04-13-trade-tape.md:1264
cd C:/Users/chris/clee/ARBS && conda run -n stir jupyter nbconvert --to notebook --execute notebooks/sdr/13_trade_tape.ipynb --output 13_trade_tape.ipynb --ExecutePreprocessor.timeout=300

# in-place, docs/superpowers/plans/2026-06-23-rv-toolkit.md:151
conda run -n stir jupyter nbconvert --to notebook --execute --inplace notebooks/rv/<nb>.ipynb

# notebooks/dealer_direction/README.md:19 — the direct-interpreter form
ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe -m nbconvert \
    --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 \
    notebooks/dealer_direction/dealer_direction_showcase.ipynb
```

For the **configurable-notebook family specifically** the first step is different — there is no `.py` percent source:

```bash
C:/Users/chris/anaconda3/envs/stir/python.exe notebooks/backtests/intraday_fed_hawk_dove/_make_config_notebook.py
C:/Users/chris/anaconda3/envs/stir/python.exe -m nbconvert --to notebook --execute --inplace \
    --ExecutePreprocessor.timeout=5400 notebooks/backtests/intraday_fed_hawk_dove/usd_fomc_configurable_backtest.ipynb
cd notebooks/backtests/intraday_fed_hawk_dove && C:/Users/chris/anaconda3/envs/stir/python.exe ../_verify_nb.py usd_fomc_configurable_backtest.ipynb
```

Design specs state the gate as a contract (`docs/superpowers/specs/2026-08-04-outcome-map-rv-handover.md:208`):
> Notebook flow: `# %%` .py source → `_py2nb.py` → `jupyter nbconvert --execute --inplace` → `_verify_nb.py` (0 errors / 0 unrun) — commit

---

# 4. `BT/trade_dashboard.py` — public API

File: `C:/Users/chris/clee/ARBS/BT/trade_dashboard.py`, 579 lines. Exports (per the shim's `__all__`): `BG, CATEGORICAL, FG, GRID, MUTED, PANEL, REASON_COLOUR, compare_curves, summary_stats, to_book, trade_dashboard`.

Module-level constants:
```python
BG = "#0e1117"; PANEL = "#161a23"; GRID = "#2a3040"; FG = "#d8dee9"; MUTED = "#7b8394"
REASON_COLOUR = {"target": "#3ddc84", "stop": "#ff5c5c", "trail": "#ff9f43",
                 "time_stop": "#f6c744", "eod": "#9b8cff", "no_path": MUTED}
CATEGORICAL = ["#4dabf7", "#3ddc84", "#ff9f43", "#ff5c5c", "#9b8cff", "#f6c744",
               "#40c4aa", "#e879f9", "#94a3b8", "#fb923c"]
```

## 4a. `to_book()`

```python
def to_book(source: Any, *, time_col: Optional[str] = None,
            pnl_col: Optional[str] = None, unit: Optional[str] = None,
            signal_col: Optional[str] = None, colour_col: Optional[str] = None,
            label_col: Optional[str] = None, side_col: Optional[str] = None,
            size_metric: Optional[str] = None) -> pd.DataFrame:
```

**Accepted source types** (four):
1. **`pd.DataFrame` already normalised** — if `source.attrs.get("book")` is truthy it is returned **by identity** (`to_book(b) is b`).
2. **`pd.DataFrame` trade log** — auto-detected columns, `→ _book_from_frame`.
3. **`QueryDrivenBacktest` — yes, directly.** Duck-typed: `_is_backtest(obj) = hasattr(obj, "mtm_history") and hasattr(obj, "portfolio")`. No engine import at module scope.
4. **`QueryBacktestTearSheet` / `QueryBacktestAnalytics`** — unwrapped by walking `("analytics", "backtest")` attributes until `_is_backtest` passes.

Anything else raises:
```python
raise TypeError(
    f"cannot read a book out of {type(source).__name__}. Pass a trade-log "
    "DataFrame, a QueryDrivenBacktest, or a QueryBacktestTearSheet.")
```

**Auto-detection tuples (first match wins):**
```python
_TIME_COLS   = ("release_ts", "entry_ts", "opened_at", "closed_at", "timestamp")
_PNL_COLS    = ("pnl_bp", "pnl", "realized_pnl", "net_bp")
_GROSS_COLS  = ("pnl_bp_gross", "gross_realized_pnl", "gross_bp")
_COST_COLS   = ("cost_bp", "fee_allocated", "cost")
_LABEL_COLS  = ("release", "lead_title", "query_label", "product", "speaker", "structure", "symbol")
_SIDE_COLS   = ("side", "direction", "direction_label")
_SIGNAL_COLS = ("z", "move_bp", "surprise", "bucket", "signal")
_COLOUR_COLS = ("exit_reason",)
```

**Canonical columns added** (originals are kept):
```python
_T, _PNL, _GROSS, _COST = "_t", "_pnl", "_gross", "_cost"
_LABEL, _SIDE, _REASON, _HOLD, _SIGNAL = "_label", "_side", "_reason", "_hold", "_signal"
```
- `_t` = `pd.to_datetime(d[tcol], utc=True)`; the frame is **sorted by `_t` and reindexed**.
- `_pnl` numeric-coerced float; non-finite rows are **dropped**.
- `_gross`, `_cost` = numeric or `np.nan` if absent.
- `_label` = str or `"-"`. `_side` = `"LONG"/"SHORT"/"FLAT"` if numeric, else `str`, else `"-"`.
- `_reason` = the colour axis, str, or `"-"`.
- `_hold` = `hold_min` (unit `"min"`) → `holding_period_days` (unit `"d"`) → derived from `closed_at - opened_at` in minutes (unit `"min"`) → `NaN`.
- `_signal` = numeric-coerced.

**`.attrs` set** by `_book_from_frame`:
```python
d.attrs.update({
    "book": True,
    "unit": _unit_for(pcol, unit),   # "bp" if pnl col endswith "_bp" or in {"move_bp","net_bp"}; else ""
    "signal_name": sig,
    "colour_name": rcol,
    "label_name": lcol,
    "hold_unit": hold_unit,          # "min" | "d" | ""
    "time_name": tcol,
    "has_gross": gcol is not None,
    "has_cost": ccol is not None,
    "source": "frame",
})
```
Plus, on the backtest path: `attrs["source"] = "QueryDrivenBacktest"`, `attrs["mtm"] = pd.Series(dict(bt.mtm_history), dtype=float).sort_index()`, `attrs["name"] = bt.strategy.name`.

**Backtest-path defaults** (verbatim):
```python
from BT.query_tearsheet import closed_trade_frame          # lazy import
closed = closed_trade_frame(bt, size_metric=size_metric)
book = _book_from_frame(
    closed,
    time_col=time_col or "closed_at",
    pnl_col=pnl_col or "realized_pnl",
    unit=unit or "",                       # currency, not basis points
    signal_col=signal_col,
    colour_col=colour_col or "exit_reason",
    label_col=label_col or "query_label",
    side_col=side_col or "direction")
```

An unknown `colour_col`/`signal_col` **raises `KeyError`** rather than silently drawing nothing.

**What `closed_trade_frame` supplies** (`BT/query_tearsheet.py:374`, `_build_closed_trade_frame:606`, `_base_position_row:568`):
`timestamp, position_id, opened_at, product, query_label, query_signature, curve, tenor, tags, tag_text, gross_weight, net_weight, package_size, size_metric, size_value, size_abs, direction, handler_name, meta, source_query, closed_at, holding_period_steps, holding_period_days, realized_pnl, gross_realized_pnl, fee_allocated, exit_reason, is_winner, exit_meta, position_meta, entry_session, exit_session, direction_label, duration_bucket, pnl_per_day, gross_pnl_per_day, pnl_per_size_unit, gross_pnl_per_size_unit, fee_pct_of_gross_pnl`

Caveat stated in its docstring: `realized_pnl` is the **price leg net of allocated fees** — coupons/financing/open positions are absent, so it need not equal `mtm_history`.

## 4b. `trade_dashboard()`

```python
def trade_dashboard(source: Any, *, title: str = "book",
                    span_years: Optional[float] = None,
                    signal_col: Optional[str] = None,
                    colour_col: Optional[str] = None,
                    bar_width: Optional[Any] = None,
                    height: int = 1080, **kw: Any) -> go.Figure:
```
`**kw` is forwarded to `to_book` (`time_col`, `pnl_col`, `unit`, `label_col`, `side_col`, `size_metric`).

**Five stacked panels**, `make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.035, row_heights=[0.32, 0.19, 0.14, 0.17, 0.18], specs=[[{}],[{}],[{}],[{}],[{"type":"table"}]])`:

1. **Cumulative net** — `lines+markers`, `#4dabf7`, each marker coloured by `_reason`; a dotted grey **gross** line if `has_gross`; a dashed amber **`"total P&L (incl. carry & open)"`** line from `attrs["mtm"]` when present, with an annotation stating the terminal gap when `abs(gap) > 1%`.
2. **Per-trade bars** — one `go.Bar` trace *per distinct colour value* so the legend explains the colours; `bar_width` passed through as `width`.
3. **Drawdown from peak** — filled `#ff5c5c`.
4. **Signal vs outcome** — `go.Scatter` of `_signal` coloured by net on `RdYlGn` with `cmid=0`; **if no signal column**, falls back to a `go.Bar` of net P&L grouped by `_label`.
5. **Summary** — `go.Table` fed by `summary_stats(d, span_years=span_years)`.

X axes carry a crosshair: `showspikes=True, spikemode="across", spikesnap="cursor"`. All timestamps rendered `d[_T].dt.tz_convert("America/New_York")`. Layout `template="plotly_dark"`, `hovermode="closest"`, `bargap=0.55`. Empty book returns `go.Figure(layout=dict(template="plotly_dark", title=f"{title} -- no trades"))`.

**What it needs in the book:** a timestamp column and a P&L column (everything else degrades gracefully). The hover template additionally reads `symbol` if present and a "second" column picked from `("surprise", "d_rate_bp", "size_value")`.

`bar_width` docstring, verbatim:
> `bar_width` sets the per-trade bar width explicitly, in milliseconds on a date axis. Left alone, plotly sizes bars from the SMALLEST gap between two trades, so a book with two speeches in one afternoon draws all five hundred of its bars one pixel wide and the colour axis stops being legible. Sparse books do not need it; dense ones do, and the caller knows which it has — `(t.max() - t.min()) / min(len(book), 400)` is the usual choice.

## 4c. `compare_curves()`

```python
def compare_curves(books: Mapping[str, Any], *, title: str = "comparison",
                   height: int = 520, **kw: Any) -> go.Figure:
```
**Input shape:** a `Mapping[str, <anything to_book accepts>]` — `{label: DataFrame | QueryDrivenBacktest | TearSheet}`. `None` values and empty books are filtered out:
```python
norm = [(name, to_book(src, **kw)) for name, src in books.items() if src is not None]
norm = [(name, d) for name, d in norm if not d.empty]
unit = norm[0][1].attrs.get("unit", "") if norm else ""
```
Two rows, `row_heights=[0.66, 0.34]`, subplot titles `f"cumulative net{uu}"` and `f"drawdown ({unit})"`. One `lines+markers` trace per book from `palette = ["#4dabf7", "#3ddc84", "#ff9f43", "#ff5c5c", "#9b8cff", "#f6c744"]`, plus a dotted same-colour drawdown trace (`showlegend=False`). `hovermode="x unified"`.

Note: `**kw` applies to **every** book, so mixed-schema books need pre-normalising.

## 4d. `summary_stats()`

```python
def summary_stats(source: Any, *, span_years: Optional[float] = None,
                  **kw: Any) -> pd.DataFrame:
```
Returns a 2-column frame `["metric", "value"]`, all values **pre-formatted strings**. Rows, in order:

| metric | value format |
|---|---|
| `trades` | `f"{len(p):,}"` |
| `net bp / trade` (or `net / trade` when unit is `""`) | `f"{p.mean():+.4f}"` |
| `gross{unit} / trade` | `f"{d[_GROSS].mean():+.4f}"` or `"-"` |
| `cost{unit} / trade` | `f"{d[_COST].mean():.4f}"` or `"-"` |
| `total net{unit}` | `f"{p.sum():+.2f}"` |
| `hit rate` | `f"{(p > 0).mean() * 100:.1f}%"` |
| `avg win / avg loss` | `f"{wins.mean():+.3f} / {losses.mean():+.3f}"` or `"-"` |
| `payoff ratio` | `f"{wins.mean() / abs(losses.mean()):.3f}"` or `"-"` |
| `Sharpe / trade` | `f"{p.mean()/p.std(ddof=1):.4f}"` |
| `t-statistic` | `f"{p.mean() / (sd / np.sqrt(len(p))):.2f}"` or `"-"` |
| `best / worst trade` | `f"{p.max():+.3f} / {p.min():+.3f}"` |
| `max drawdown (bp)` | `f"{dd.min():.2f}"` — `dd = eq - np.maximum.accumulate(eq)` |
| `longest win / loss run` | `f"{_streak(p > 0)} / {_streak(p <= 0)}"` |
| `avg hold (min|d)` | `f"{d[_HOLD].mean():.1f}"` or `"-"` |
| `trades / year` | only if `span_years` |
| `annualised Sharpe` | only if `span_years`: `srt * np.sqrt(len(p)/span_years)` |
| `exit mix` / `{colour_name} mix` | `"target 42%  stop 33%  …"` |

Empty book → `pd.DataFrame(columns=["metric", "value"])`.

Docstring on `span_years`, verbatim:
> It is left to the caller because a book of 41 event-driven trades has no natural frequency, and inventing one is how a Sharpe of 0.3 per trade becomes a Sharpe of 3.

## 4e. Real call sites, verbatim with context

**(1) `C:/Users/chris/clee/ARBS/notebooks/backtests/intraday_fed_hawk_dove/_make_nonvoter_fade_notebook.py:344-380`** — the closest sibling to your target notebook, and the one that shows the full plotly setup block:

```python
code(r'''
import plotly.io as pio

# nbclient has no browser to negotiate with, so the renderer is pinned here. The
# mimetype bundle is what a saved .ipynb replays; the connected notebook renderer
# keeps plotly.js on a CDN rather than embedding ~3MB of javascript per execution.
pio.renderers.default = "plotly_mimetype+notebook_connected"

from BT.trade_dashboard import compare_curves, trade_dashboard

SPAN_YEARS = (D.opened_at.max() - D.opened_at.min()).days / 365.25

# Colour the combined book by which half a trade came from: that is the whole
# question this notebook asks, and it is invisible in a pooled equity curve.
DB = D.assign(leg=np.where(D.is_voter, "voter — as read", "non-voter — FADED"))

# 504 trades and two speeches in an afternoon: left to itself plotly sizes every
# bar off the SMALLEST gap between two of them and draws all 504 one pixel wide,
# which throws away the colour axis. Size them off the span instead.
BAR_MS = (D.opened_at.max() - D.opened_at.min()) / min(len(D), 400) / pd.Timedelta("1ms")

fig = trade_dashboard(
    DB, title="D — voters as read + non-voting presidents FADED",
    span_years=SPAN_YEARS, signal_col="bucket", colour_col="leg",
    bar_width=BAR_MS)
fig.show()
''')

code(r'''
fig = compare_curves(
    {"A voters only": A, "C non-voters FADED": Cc,
     "D combined": D, "E everyone as read": E},
    title="the four books that differ only in what they do with a non-voter")
fig.show()
''')
```
Here `A`, `B`, `Cc`, `D`, `E` are `HC.run_config(...).closed` frames.

**(2) `C:/Users/chris/clee/ARBS/notebooks/backtests/econ_release_fade/_make_surprise_notebook.py:350-355, 468-470, 495-497`** — imported as `import econ_fade_plotly as P` (a shim re-exporting `BT.trade_dashboard` and pinning the renderer):

```python
fig = P.trade_dashboard(engine, title=f"consensus surprise fade | {book.instrument.root} | "
                                      f"|z| >= {CONFIG['z']['min_abs_z']:g}",
                        span_years=SPAN_YEARS, signal_col="z")
fig.show()
```
```python
fig = P.compare_curves(frames, title="the fork: fade vs momentum vs fade-then-flip")
fig.show()
```
```python
fig = P.compare_curves({k: g for k, g in d.groupby("surprise_dir")},
                       title="cold surprises against hot ones")
fig.show()
```
The third is the idiomatic "split one book into curves" form: a `groupby` dict-comprehension straight into `compare_curves`.

**(3) `C:/Users/chris/clee/ARBS/notebooks/backtests/econ_release_fade/_make_exits_notebook.py:338-341, 366-367`**:
```python
SPAN_YEARS = (pd.Timestamp("2026-08-07") - pd.Timestamp("2019-01-03")).days / 365.25
fig = P.trade_dashboard(engine, title=f"CPI x {book.instrument.root} bracket | {RULE.name}",
                        span_years=SPAN_YEARS, signal_col="move_bp")
fig.show()
...
fig = P.compare_curves(alts, title="does the bracket beat simply holding to the clock?")
fig.show()
```

## 4f. Minimal working example — `QueryDrivenBacktest` → `compare_curves` / `trade_dashboard`

The only *object-level* usage in the repo is `tests/test_trade_dashboard.py:249-296` and `BT/query_tearsheet.py:110-122`. Composite, from those two verbatim:

```python
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

dates = list(simple_time_grid)
q1 = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                 tenor="5Y", curve="USD-SOFR-1D",
                 structure_kwargs={"bpv": 1_000_000}, tags=("macro-rv",))
q2 = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                 tenor="10Y", curve="USD-SOFR-1D",
                 structure_kwargs={"bpv": -500_000}, tags=("carry",))
triggers = [
    DateTrigger(DateTriggerRequirements(dates=[dates[0].date()]),
                actions=[AddQueryAction(query=q1)]),
    DateTrigger(DateTriggerRequirements(dates=[dates[1].date()]),
                actions=[AddQueryAction(query=q2)]),
    DateTrigger(DateTriggerRequirements(dates=[dates[3].date()]),
                actions=[UnwindPositionsAction(match_tag="macro-rv")]),
]
bt = QueryDrivenBacktest(time_grid=simple_time_grid,
                         strategy=QueryStrategy(name="dashboard test",
                                                triggers=triggers),
                         mdp=mock_mdp, show_progress=False)
bt.run()

# --- the object goes straight in, no frame extraction ---
fig = trade_dashboard(bt, title="qdb")          # 5 panels + the amber mtm_history overlay
fig.show()

fig = compare_curves({"engine": bt, "closed-form": my_pnl_frame})
fig.show()
```

Asserted behaviour from that test (this is the contract):
```python
b = to_book(bt)
assert b.attrs["source"] == "QueryDrivenBacktest"
assert b.attrs["unit"] == ""                      # currency, not basis points
assert b.attrs["colour_name"] == "exit_reason"
assert b.attrs["hold_unit"] == "d"
assert b.attrs["name"] == "dashboard test"
assert len(b) == len(bt.portfolio.closed_positions_log)
assert isinstance(b.attrs["mtm"], pd.Series) and len(b.attrs["mtm"])
fig = trade_dashboard(bt, title="qdb")
names = [t.name for t in fig.data]
assert "total P&L (incl. carry & open)" in names, names
```

Tearsheet route (`BT/query_tearsheet.py:110-122`), which auto-titles from the strategy name:
```python
sheet = QueryBacktestTearSheet.from_backtest(bt)
fig = sheet.plot(backend="dashboard")     # kwargs.setdefault("title", self.analytics.name)
```

**Notebook boilerplate you must include** for a plotly figure to survive `nbconvert --execute` (from `_make_nonvoter_fade_notebook.py`; the library deliberately does *not* pin this):
```python
import plotly.io as pio
pio.renderers.default = "plotly_mimetype+notebook_connected"
```

---

# 5. `BT/triggers.py` — every Trigger and its Requirements

File: `C:/Users/chris/clee/ARBS/BT/triggers.py`, 327 lines. Imports `from BT.event import TriggerInfo`, `from BT.actions import Action, AddTradeAction, AddScaledTradeAction, HedgeAction`, `from BT.order import Order`.

## Base

```python
class TriggerRequirements:
    calc_type: str = "point_in_time"
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo: raise NotImplementedError
    def get_trigger_times(self) -> List[dt.time]: return []

@dataclass
class Trigger:
    trigger_requirements: TriggerRequirements
    actions: Union[Action, Iterable[Action], None] = None
```
`Trigger.__post_init__` normalises `actions` to a list (`None` → `[]`, scalar → `[a]`). Properties: `.requirements` (alias of `trigger_requirements`), `.calc_type` (delegated), `.risks` (`[x.risk for x in actions if getattr(x,"risk",None) is not None]`). `Trigger.sub_classes()` returns every registered subclass.

**Construction is positional-friendly:** `SomeTrigger(SomeRequirements(...), actions=[...])`.

## Requirements dataclasses — every field

| dataclass | fields | `calc_type` | triggers when |
|---|---|---|---|
| `PeriodicTriggerRequirements` | `dates: Sequence[dt.date]` | `"calendar"` | `state.date() in set(dates)` |
| `IntradayTriggerRequirements` | `times: Sequence[dt.time]` | `"intraday"` | `state.time() in times`; also implements `get_trigger_times()` |
| `MktTriggerRequirements` | `fetch: Callable[[dt.datetime], Optional[float]]`, `op: Callable[[float,float],bool]`, `threshold: float` | `"market"` | `v is not None and op(float(v), float(threshold))` |
| `RiskTriggerRequirements` | `risk: str`, `op: Callable[[float,float],bool]`, `threshold: float` | `"risk"` | `op(backtest.get_strategy_risk(risk), threshold)` |
| `AggregateTriggerRequirements` | `triggers: List[Trigger]`, `mode: str = "any"` | `"aggregate"` | `all(...)` if `mode=="all"` else `any(...)`; merges child `info` maps |
| `NotTriggerRequirements` | `trigger: Trigger` | `"not"` | `not bool(child)`, keeps `child.info` |
| `DateTriggerRequirements` | `dates: Sequence[dt.date]`, `info: Dict[Any,Any] = field(default_factory=dict)` | `"date"` | `state.date() in set(dates)`; emits `dict(info)` on the triggered step |
| `FlowSignalTriggerRequirements` | `signal_fn: Callable[[dt.datetime, Any], Any]` | `"flow_signal"` | whatever `signal_fn(state, backtest)` returns — accepts `TriggerInfo`, `(bool, dict)`, `dict` with a `"triggered"` key, or a bare truthy |
| `PortfolioTriggerRequirements` | `predicate: Callable[[Any], bool]` | `"portfolio"` | `predicate(backtest)` |
| `MeanReversionTriggerRequirements` | `fetch: Callable[[dt.datetime], Optional[float]]`, `lookback: int`, `z_entry: float` | `"stat"` | `abs(z) >= z_entry`; emits `{AddScaledTradeAction: {"scaling": -z/z_entry}}` |
| `TradeCountTriggerRequirements` | `lookback: dt.timedelta`, `op: Callable[[int,int],bool]`, `count: int` | `"trade_count"` | `op(backtest.trade_count_since(state - lookback, state), count)` |
| `EventTriggerRequirements` | `events_on: Callable[[dt.datetime], List[str]]`, `event_name: str` | `"event"` | `event_name in set(events_on(state))` |
| `ConstantMaturityRollTriggerRequirements` | `timestamp: dt.datetime`, `previous: Dict[str,str]`, `new: Dict[str,str]` | `"roll_event"` | always `True` once injected; emits `{"roll": {"ts","previous","new"}}` |

## Concrete Trigger classes

All are `@dataclass class X(Trigger): pass` unless noted:

`PeriodicTrigger`, `IntradayPeriodicTrigger`, `MktTrigger`, `StrategyRiskTrigger` (overrides `.risks` → `super().risks + [self.trigger_requirements.risk]`), `AggregateTrigger`, `NotTrigger`, `DateTrigger`, `PortfolioTrigger`, `MeanReversionTrigger`, `TradeCountTrigger`, `EventTrigger`, `ConstantMaturityRollTrigger`.

Plus one with behaviour:
```python
@dataclass
class OrdersGeneratorTrigger(Trigger):
    """Base class for time-grid order generation."""
    def get_trigger_times(self) -> List[dt.time]: ...
    def generate_orders(self, state, backtest=None) -> List[Order]:
        raise RuntimeError("generate_orders must be implemented by subclass")
    def has_triggered(self, state, backtest=None) -> TriggerInfo:
        if state.time() not in self.get_trigger_times():
            return TriggerInfo(False)
        orders = self.generate_orders(state, backtest)
        info = {type(a): orders for a in (self.actions or [])} if orders else {}
        return TriggerInfo(bool(orders), info)
```

Note: `FlowSignalTriggerRequirements` has **no** matching `FlowSignalTrigger` class — use the base `Trigger(FlowSignalTriggerRequirements(...), actions=[...])`, which is exactly what `BT/signals/jpm_rv_backtest.py:677` does with a custom requirements class:
```python
trigger = Trigger(trigger_requirements=_AlwaysOnRequirements(), actions=[action])
strategy = QueryStrategy(name="jpm_rv_query_backtest", triggers=[trigger])
```

**How to build the three you asked about:**
- *daily* → `PeriodicTrigger(PeriodicTriggerRequirements(dates=[d.date() for d in grid]), actions=[...])`, or `DateTrigger(DateTriggerRequirements(dates=[...], info={...}))` when you need per-date payload.
- *periodic intraday* → `IntradayPeriodicTrigger(IntradayTriggerRequirements(times=[dt.time(9,30), dt.time(15,0)]), actions=[...])`.
- *signal* → `Trigger(FlowSignalTriggerRequirements(signal_fn=lambda state, bt: (bool, {ActionType: payload})), actions=[...])`, or `MktTrigger(MktTriggerRequirements(fetch=lambda t: series.get(t), op=operator.gt, threshold=2.0))`, or `MeanReversionTrigger(MeanReversionTriggerRequirements(fetch=..., lookback=60, z_entry=2.0), actions=[AddScaledTradeAction(...)])`.

---

# 6. Conda env and run command

**Env name: `stir`.** Confirmed present at `C:/Users/chris/anaconda3/envs/stir/python.exe`. (Other envs on the box: `code_tester_arbs`, `code_tester_arbs2`, `code_tester_arbs3`, `markitdown`, `ql_env` — none of them are the project env.) The notebooks' own kernelspec is `{"display_name": "stir", "name": "python3"}`.

`C:/Users/chris/clee/ARBS/CLAUDE.md` (all 8 lines) gives only the test commands:
```
- Fast gate (pre-commit): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
- Full suite (~1.5h; needs network + DATABASE_URL): `conda run -n stir python -m pytest tests`
```

**Two run forms are in use, and they conflict — the direct one is the safer default:**

```bash
# A. what most repo scripts and docs use
conda run -n stir python <script.py>

# B. what notebooks/dealer_direction/README.md:26-28 mandates instead
C:/Users/chris/anaconda3/envs/stir/python.exe <script.py>
```

That README states the reason verbatim:
> Invoke the interpreter **directly**. Never `conda run` — parallel invocations collide on a temp file and return empty output with exit code 0, a fake pass.

This matches your global note that `conda run` also rejects multiline `-c`. **Use form B** for anything you launch in parallel or in background, and for anything whose exit code you intend to trust. Concretely, for this pattern:

```bash
C:/Users/chris/anaconda3/envs/stir/python.exe C:/Users/chris/clee/ARBS/notebooks/backtests/intraday_fed_hawk_dove/_make_config_notebook.py
```

---

# 7. Two traps specific to reproducing this pattern

1. **The generated notebook hard-codes a repo path that is not this checkout.** Both `_make_config_notebook.py:81` and `_make_usd_notebook.py:77` emit `REPO = r"C:\Users\chris\clee\ARBS-gcb"` into the notebook's first cell — a *sibling worktree*, not `C:/Users/chris/clee/ARBS`. If you copy the pattern, either parametrise it or emit the generator's own resolved root. `econ_fade_plotly.py:29-35` documents the same problem and works around it with `Path(__file__).resolve().parents[3]`.

2. **`_verify_nb.py` globs relative to CWD** (`Path().glob(a)`), so it must be invoked with `cwd` set to the notebook's directory — which is why every `run_*.py` driver passes `cwd=HERE`.