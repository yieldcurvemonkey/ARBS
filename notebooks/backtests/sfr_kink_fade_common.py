"""Shared plumbing for the SFR kink-fade lab.

Deliberately thin. Every reporting block -- the header, the three-panel equity,
the grid distribution, the neighbourhood, the sign test, the regime split, the
linear-shadow decomposition, the median-config control and the league row -- is
imported unchanged from ``sfr_fly_meanrev_common``, so the two labs are graded by
**identical code** and their league tables are comparable line for line. Only
three things differ, and each is a measurement rather than a preference:

* the results go to ``notebooks/data/sfr_kink_fade/`` instead of overwriting the
  butterfly lab's CSVs;
* "taker" means the correct per-**contract** round trip on a ``1/-2/1``
  butterfly, **2.0bp** (4 contracts x 2 sides x 0.25bp), where the prior lab
  graded at 2.5bp -- so the two league tables share every column and every
  formula but are **not** directly comparable on ``net_bp_taker``, which is why
  that column now carries a ``taker_bp`` alongside it. The same correction
  applies to the shadow test, which the prior lab charged per *leg*; and
* the panel carries the FOMC meeting calendar, because the whole question is
  whether a butterfly's curvature is a dislocation or an artefact of when the
  Fed happens to meet inside each contract's IMM quarter.

.. warning::

   Importing this module **mutates** ``sfr_fly_meanrev_common``'s output
   directory, taker cost and shadow cost mode for the rest of the process. That
   is deliberate -- it is how the reporting blocks are reused without being
   forked -- but it means a single process must not run both labs. Each
   notebook runs in its own kernel, so this is safe in practice; use
   :func:`restore_fly_meanrev_defaults` if you need to undo it interactively.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import sfr_fly_meanrev_common as _fm  # noqa: E402

from RVUtils.MeanRev.diagnostics import (  # noqa: E402
    oracle_table, selectivity_table, signal_entry_mask, variance_decomposition,
)
from RVUtils.MeanRev.meetings import (  # noqa: E402
    calendar_fly_panel, calendar_tilted_fly, fomc_decisions, fomc_schedule,
    meeting_residual_panel,
)
from RVUtils.MeanRev.panel import add_strip_slots  # noqa: E402

DATA_DIR = REPO / "notebooks" / "data" / "sfr_kink_fade"
PANEL_DIR = _fm.PANEL_DIR

#: Per-CONTRACT round trip on a 1/-2/1 butterfly: 4 contracts, two sides, half a
#: tick each. The prior lab's 1.5bp is a per-LEG charge and is ~25% optimistic.
TAKER_BP = 2.0

#: What the notebook prints as its cost curve. 2.0 is the honest taker figure;
#: 2.5 is kept as a stress case and for comparability with the butterfly lab.
COST_CURVE_BP = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 4.0)

#: The shadow test charges each instrument its own cost. Per LEG that is 1.5bp
#: for a fly and 0.5bp for the outright belly; per CONTRACT it is 2.0bp and
#: 0.5bp, because the belly of a 1/-2/1 package is two contracts. Every shadow
#: except the butterfly costs the same either way, so per-leg costing hands the
#: fly a 0.5bp/trade head start in precisely the comparison the shadow test
#: exists to make. This lab charges per contract.
SHADOW_COST_MODE = "per_contract"

#: what ``sfr_fly_meanrev_common`` looked like before this module touched it
_FLY_DEFAULTS = {"path": _fm.DATA_DIR, "taker_bp": _fm.TAKER_BP,
                 "cost_curve_bp": _fm.COST_CURVE_BP,
                 "shadow_cost_mode": _fm.SHADOW_COST_MODE}

_fm.set_output_dir(DATA_DIR, taker_bp=TAKER_BP, cost_curve_bp=COST_CURVE_BP,
                   shadow_cost_mode=SHADOW_COST_MODE)


def restore_fly_meanrev_defaults() -> None:
    """Undo this module's import-time repointing of ``sfr_fly_meanrev_common``."""
    _fm.set_output_dir(**_FLY_DEFAULTS)

# re-export the shared blocks so a notebook imports from one place
attach_cm = _fm.attach_cm
config_from_row = _fm.config_from_row
cost_block = _fm.cost_block
coverage_report = _fm.coverage_report
exit_comparison = _fm.exit_comparison
grid_block = _fm.grid_block
header_block = _fm.header_block
league_row = _fm.league_row
load_lab = _fm.load_lab
median_row = _fm.median_row
per_slot_table = _fm.per_slot_table
regime_block = _fm.regime_block
run_family = _fm.run_family
shadow_block = _fm.shadow_block
sign_test = _fm.sign_test
signal_params_from_row = _fm.signal_params_from_row
stability_block = _fm.stability_block
three_panel_equity = _fm.three_panel_equity
BAD_DATES = _fm.BAD_DATES
REGIME_ORDER = _fm.REGIME_ORDER
WINDOWS = _fm.WINDOWS

__all__ = [
    "DATA_DIR", "PANEL_DIR", "TAKER_BP", "COST_CURVE_BP", "SHADOW_COST_MODE",
    "BAD_DATES", "REGIME_ORDER", "WINDOWS",
    "attach_cm", "config_from_row", "cost_block", "coverage_report",
    "exit_comparison", "grid_block", "header_block", "league_row", "load_lab",
    "median_row", "per_slot_table", "regime_block", "run_family",
    "shadow_block", "sign_test", "signal_params_from_row", "stability_block",
    "three_panel_equity",
    "load_contracts", "load_kink_lab", "meeting_audit", "pond_block",
    "calendar_summary", "cm_variance_decomposition",
    "imm_roll_fomc_collisions", "restore_fly_meanrev_defaults",
    "oracle_table", "selectivity_table", "signal_entry_mask",
    "variance_decomposition",
]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_contracts(*, drop_dates: Sequence[str] = _fm.BAD_DATES) -> pd.DataFrame:
    """The raw per-(date, contract) panel, with the corrupt sessions removed."""
    c = pd.read_parquet(PANEL_DIR / "contracts.parquet")
    c["as_of"] = pd.to_datetime(c["as_of"])
    if drop_dates:
        c = c[~c["as_of"].isin(pd.DatetimeIndex(pd.to_datetime(list(drop_dates))))]
    return c.reset_index(drop=True)


def load_kink_lab(structure: str = "3m", window: str = "liquid16", *,
                  lam: float = 10.0, max_slot: int = 16,
                  contracts: Optional[pd.DataFrame] = None) -> Dict[str, object]:
    """``load_lab`` plus everything the meeting calendar contributes.

    Adds to the standard lab dict:

    ``contracts``    the raw contract panel restricted to the lab's dates
    ``calendar``     per (date, key) ``phi_sum`` / meeting counts / ``asym``
    ``phi``          wide ``date x key`` calendar curvature (bp per 1bp/meeting)
    ``asym``         wide ``date x key`` integer meeting-count asymmetry
    ``resid_slots``  ``date x slot`` residual from the smooth policy-path fit, bp
    ``resid_extras`` ``fitted`` / ``n_meetings`` / ``proj_share`` / ``path_bp``
    ``tilted``       the calendar-tilted fly level panel and its wing shares
    """
    lab = _fm.load_lab(structure, window)
    levels = lab["levels"]
    full = load_contracts() if contracts is None else contracts

    # The smooth-path fit is CROSS-SECTIONAL PER DATE, so restricting the
    # contract panel to the window first would not change a single residual --
    # but it would produce a second, subtly different panel for callers to pick
    # the wrong one from. One residual panel, built on everything, sliced on the
    # way out.
    resid, extras = meeting_residual_panel(full, lam=lam, max_slot=max_slot,
                                           return_extras=True)
    resid = resid.reindex(index=levels.index)
    extras = {k: (v.reindex(levels.index) if isinstance(v, (pd.Series, pd.DataFrame))
                  else v) for k, v in extras.items()}

    c = full[(full["as_of"] >= levels.index.min())
             & (full["as_of"] <= levels.index.max())]
    cal = calendar_fly_panel(lab["struct"], c)
    phi = cal.pivot_table(index="as_of", columns="key", values="phi_sum",
                          aggfunc="first").reindex(index=levels.index,
                                                   columns=levels.columns)
    asym = cal.pivot_table(index="as_of", columns="key", values="asym",
                           aggfunc="first").reindex(index=levels.index,
                                                    columns=levels.columns)
    tilted = calendar_tilted_fly(lab["struct"], cal)

    lab.update({"contracts": c, "contracts_full": full, "calendar": cal,
                "phi": phi, "asym": asym, "resid_slots": resid,
                "resid_extras": extras, "tilted": tilted, "lam": lam})
    return lab


# ---------------------------------------------------------------------------
# the blocks this lab adds
# ---------------------------------------------------------------------------

def imm_roll_fomc_collisions(contracts: pd.DataFrame) -> pd.DataFrame:
    """How often an IMM roll date IS an FOMC decision date.

    Both land on a Wednesday in the middle of March, June, September and
    December, so they collide constantly. That matters because it makes the
    obvious version of :func:`meeting_audit` -- pivot rates by constant-maturity
    **slot** and take a first difference -- measure the wrong thing: on a roll
    date slot 1 becomes a different contract, so the "daily change" is a splice
    worth tens of basis points, and it lands squarely on the days the audit is
    calling FOMC days.
    """
    c = contracts.copy()
    c["as_of"] = pd.to_datetime(c["as_of"])
    imm = sorted({pd.Timestamp(d).date() for d in c["imm_start"].unique()})
    lo, hi = c["as_of"].min().date(), c["as_of"].max().date()
    imm = [d for d in imm if lo <= d <= hi]
    mt = set(fomc_decisions(lo, hi))
    hits = [d for d in imm if d in mt]
    return pd.DataFrame([{"n_imm_rolls": len(imm), "n_also_fomc": len(hits),
                          "pct": (100.0 * len(hits) / len(imm)) if imm else np.nan}])


def meeting_audit(contracts: pd.DataFrame, *, front_slots: int = 4,
                  years: Sequence[int] = (2018, 2019, 2020, 2021, 2022)
                  ) -> pd.DataFrame:
    """Do front SR3 rates actually move more on FOMC decision days?

    The hardcoded calendar agrees with ``_CENTRAL_BANK_DATES`` exactly from
    2023-02 onward, and the lab's regime boundaries land on meetings -- but
    **no in-repo source covers 2018-2022**, which is most of the ``front8``
    window. This is the independent check for those years: if the dates are
    right, the mean absolute daily change of the front contracts is materially
    larger on decision days than on every other session.

    **The daily change is taken per CONTRACT, never per strip slot.** A slot
    series splices at every IMM roll, and 23 of the 35 IMM rolls in this sample
    are themselves FOMC decision dates (see :func:`imm_roll_fomc_collisions`),
    so a slot-pivoted difference would attribute the roll gap to the meeting and
    manufacture the very result the audit is supposed to test.

    Uses the **day after** the decision as well, because the target range takes
    effect then and the settle that reflects it is the next one.
    """
    c = contracts.copy()
    c["as_of"] = pd.to_datetime(c["as_of"])
    sl = add_strip_slots(c, order_col="imm_start", start_col="imm_start")
    # one column per CONTRACT: diff() can never cross a roll
    wide = sl.pivot_table(index="as_of", columns="code", values="rate_pct",
                          aggfunc="first").sort_index()
    slot = sl.pivot_table(index="as_of", columns="code", values="slot",
                          aggfunc="first").reindex(index=wide.index,
                                                   columns=wide.columns)
    dw = wide.diff().abs()
    # a contract only counts on days it is inside the front slots AND was also
    # inside them the day before, so a contract entering the strip does not
    # contribute a spurious first difference
    live = (slot <= int(front_slots)) & (slot.shift(1) <= int(front_slots))
    d = dw.where(live).mean(axis=1) * 100.0        # bp
    d = d.dropna()
    mt = pd.DatetimeIndex(pd.to_datetime(
        fomc_decisions(d.index.min().date(), d.index.max().date())))
    on = d.index.isin(mt) | d.index.isin(mt + pd.Timedelta(days=1))
    rows = []
    for y in list(years) + ["ALL"]:
        m = np.ones(len(d), dtype=bool) if y == "ALL" else (d.index.year == y)
        a, b = d[m & on], d[m & ~on]
        if len(a) < 3 or len(b) < 3:
            continue
        pooled = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        rows.append({"year": y, "n_fomc_days": len(a), "n_other": len(b),
                     "fomc_abs_move_bp": float(a.mean()),
                     "other_abs_move_bp": float(b.mean()),
                     "ratio": float(a.mean() / b.mean()) if b.mean() > 0 else np.nan,
                     "welch_t": float((a.mean() - b.mean()) / pooled)
                     if pooled > 0 else np.nan})
    return pd.DataFrame(rows)


def calendar_summary(cal: pd.DataFrame, struct: pd.DataFrame) -> pd.DataFrame:
    """Per CM slot: how big is the calendar's own curvature, and how often?"""
    m = struct[["as_of", "key", "cm_slot", "cm_label_short", "value"]].merge(
        cal, on=["as_of", "key"], how="inner")
    g = m.groupby(["cm_slot", "cm_label_short"])
    out = pd.DataFrame({
        "n": g.size(),
        "phi_mean": g["phi_sum"].mean(),
        "phi_sd": g["phi_sum"].std(),
        "phi_p05": g["phi_sum"].quantile(0.05),
        "phi_p95": g["phi_sum"].quantile(0.95),
        "pct_asym0": g["asym"].apply(lambda s: float((s == 0).mean())),
        "fly_sd_bp": g["value"].std(),
        "corr_fly_phi": g.apply(lambda x: x["value"].corr(x["phi_sum"]),
                                include_groups=False),
        "pct_projected": g["proj_any"].mean(),
    }).reset_index().sort_values("cm_slot")
    return out


def pond_block(levels: pd.DataFrame, signals: Dict[str, pd.DataFrame], *,
               entry_z: float = 2.0, gate: Optional[pd.DataFrame] = None,
               horizons: Sequence[int] = (5, 10, 21),
               round_trip_bp: float = TAKER_BP, tag: str = "") -> pd.DataFrame:
    """The pond test, printed. Runs before any grid, because it can end one.

    A signal that fires on days the fly moves no further than average
    (``selectivity`` ~ 1.0) has to earn its entire edge from the sign call, and
    the prior lab measured that ceiling at ~2.4bp against a 2.0bp round trip.
    """
    t = selectivity_table(levels, signals, entry_z=entry_z, gate=gate,
                          horizons=horizons, round_trip_bp=round_trip_bp)
    print(f"\nPOND TEST (|forward move| on the days each signal fires, "
          f"entry |z| >= {entry_z}, round trip {round_trip_bp}bp)")
    print("  selectivity 1.00 = the signal picks days at random with respect to "
          "move size")
    print(t.round(3).to_string(index=False))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t.to_csv(DATA_DIR / f"pond_test{'_' + tag if tag else ''}.csv", index=False)
    return t


def cm_variance_decomposition(
    actual: pd.DataFrame, explained: pd.DataFrame, struct: pd.DataFrame, *,
    date_col: str = "as_of", label_col: str = "cm_label_short",
) -> pd.DataFrame:
    """Variance decomposition attributed by the CM slot a key occupied **that day**.

    A key's constant-maturity slot rolls -- a fly born at slot 15 arrives at
    slot 2 four years later -- so grouping columns by the label a key was *born*
    with tags every key with the wrong bucket. That was bug 11 of the prior lab
    and it is just as wrong here, so the attribution is done on the long frame,
    per ``(date, key)``.
    """
    a = actual.stack(future_stack=True).rename("actual").reset_index()
    a.columns = [date_col, "key", "actual"]
    e = explained.stack(future_stack=True).rename("model").reset_index()
    e.columns = [date_col, "key", "model"]
    lab = struct[[date_col, "key", label_col, "cm_slot"]].copy()
    lab[date_col] = pd.to_datetime(lab[date_col])
    m = a.merge(e, on=[date_col, "key"]).merge(lab, on=[date_col, "key"])
    m = m.dropna(subset=["actual", "model"])
    m["resid"] = m["actual"] - m["model"]
    g = m.groupby([label_col, "cm_slot"])
    out = pd.DataFrame({
        "n": g.size(),
        "sd_actual_bp": g["actual"].std(),
        "sd_model_bp": g["model"].std(),
        "sd_resid_bp": g["resid"].std(),
        "corr": g.apply(lambda x: x["actual"].corr(x["model"]),
                        include_groups=False),
    }).reset_index()
    out["resid_share"] = out["sd_resid_bp"] / out["sd_actual_bp"]
    out["r2"] = 1.0 - out["resid_share"] ** 2
    return out.sort_values("cm_slot")
