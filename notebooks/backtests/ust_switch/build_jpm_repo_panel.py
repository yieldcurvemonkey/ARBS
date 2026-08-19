"""Build a per-issue UST repo / specialness panel from the JPM US Cash Analytics package.

The switch trade (long a seasoned issue, short the on-the-run) is financed on both
legs, and the *only* reason the on-the-run premium persists is that the short leg
finances below GC.  ARBS' own carry model
(``Query/FixedRateBonds/carry_roll.py::load_us_treasury_gc_fixing_pct``) applies **one
flat rate -- the last overnight SOFR fixing -- to every bond**, so a switch priced
through it nets its two financing legs to ~0 and the trade looks free.  It is not.

Source
------
``project-oasis/private/jpm_research/data/issue_specific_sofr_swap_spread_detailed_report_ds``
-- 2,217 daily parquets, 2016-08-10 .. 2025-08-26, one row per outstanding coupon
issue, carrying ``1m Repo`` and ``3m Repo`` as *levels in percent* for that specific
CUSIP.  GC is not a column: it is the modal repo level across the day's ~320 issues,
because the overwhelming majority of seasoned issues finance exactly at GC (302 of
321 rows on 2025-08-26 printed the identical 4.41).

Tie-out
-------
``treasury_carry_roll_and_relative_value_report_ds`` (192 days, 2024-08-22 ..
2025-08-26) publishes JPM's OWN ``3m Repo Special`` in bp per CUSIP.  That column is
the control: ``(GC_modal_3m - issue_3m_repo) * 100`` must reproduce it.  Verified by
hand on 2025-08-26 -- 10y OTR 4.31 GC vs 4.18 issue = 13.0bp, JPM prints 13.0.
``tie_out()`` runs it over all 192 days rather than the one.

Reopenings share (cpn, maturity) with their original, which is correct here: they are
the same security and finance as one.
"""

from __future__ import annotations

import datetime
import glob
import os
import pathlib
import sys

import numpy as np
import pandas as pd

JPM_ROOT = pathlib.Path(
    os.getenv("JPM_RESEARCH_DIR", r"C:/Users/chris/clee/project-oasis/private/jpm_research")
)
ISSUE_DS = JPM_ROOT / "data" / "issue_specific_sofr_swap_spread_detailed_report_ds"
CARRY_DS = JPM_ROOT / "data" / "treasury_carry_roll_and_relative_value_report_ds"

OUT_DIR = pathlib.Path(__file__).resolve().parent / "_data"
PANEL_PATH = OUT_DIR / "jpm_issue_repo_panel.parquet"
TIEOUT_PATH = OUT_DIR / "jpm_repo_tieout.parquet"


# --------------------------------------------------------------------------- helpers


def _parse_mat(s: pd.Series) -> pd.Series:
    """JPM writes 'Feb 28 2026' in the issue report and 'Feb 28, 2026' in the carry report."""
    txt = s.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_datetime(txt, format="%b %d %Y", errors="coerce")


#: Both sides of the tie-out carry tabula noise, in opposite directions:
#:   * issue report -- ``3m Repo`` read as ``0.0`` (a missed cell) makes the derived
#:     specialness equal the whole GC level (486bp on 2024-09-23);
#:   * carry report -- ``3m Repo Special`` reads ``526.0`` on 2024-08-22, which is the
#:     repo LEVEL 5.26% landing in the specialness column.
#: 0.94% of matched rows (525 / 55,793). Gating is not cosmetic: an ungated 486bp
#: "specialness" is a 486bp/yr financing subsidy handed to whichever leg carries it.
#:
#: The gate is on the repo **LEVEL**, not on the specialness spread, and this matters a
#: lot. A fixed spread bound like "special <= 300bp" silently encodes 2024 rate levels:
#: it is 0.94% of rows in the 2024-25 tie-out window and would be catastrophic in 2020-21,
#: where GC printed 0.00-0.05 and genuinely special issues printed NEGATIVE -- a
#: ``repo <= 0 -> NaN`` rule deletes real ZIRP data, and a 300bp clip truncates the
#: March-2020 fails episode. Both errors NaN out specialness in the most volatile era,
#: which hands the short leg free financing exactly when the trade is most exposed --
#: i.e. they flatter the strategy. The tie-out window never touches ZIRP or stress, so
#: it CANNOT certify these bounds; they have to be argued from market structure instead.
#:
#: Floor: -3.05%. A repo rate cannot go below the negative of the TMPG fails charge
#: (3% over the target floor) because a borrower would simply fail rather than pay more.
#: Ceiling: GC + 0.50%. An issue financing meaningfully ABOVE GC is not a market state;
#: it is a misread cell.
#: Plausible specialness is then whatever those levels imply, which is era-dependent by
#: construction -- in 2020 that is a few bp, in a squeeze it is the full distance to the
#: fails floor.
REPO_LEVEL_FLOOR_PCT = -3.05
REPO_LEVEL_CEIL_OVER_GC_PCT = 0.50

#: The one systematic misparse the level gate cannot see: tabula renders a dropped cell
#: as exactly ``0.00``, which is INSIDE the plausible level band whenever GC is high.
#: Split by era rather than by magnitude, because both readings are real somewhere:
#:   * GC ~0.00-0.14 (2016, 2020-21): a 0.00 repo print is the actual market. 1,870 rows,
#:     implied specialness 0-14bp. Keep.
#:   * GC 4.41-5.47 (2023-25): a 0.00 print implies 441-547bp of specialness. 563 rows.
#:     Drop.
#: The cut is placed at GC > 1% and validated against the sample's genuine specials, which
#: is the part that had to be measured rather than assumed. Excluding zero prints, the
#: largest specials in nine years are 272bp (2023), 229bp (2022), 134bp (2016-11 5Y at
#: -0.55% repo) and the Feb-2018 10Y squeeze at 115-124bp -- all real, all non-round, and
#: all of which a naive "special > 100bp is garbage" clip would have deleted. Genuine
#: sub-GC prints in a high-GC world are non-round (0.43, 0.50, 0.92, 1.35, 2.10); the
#: sentinel is round to the cent and implies a special larger than any of them.
ZERO_SENTINEL_GC_PCT = 1.0


def _modal_gc(x: pd.Series) -> float:
    """GC = the modal financing level of the day.

    Mode, not median: on a day where more than half the universe is special the median
    drifts with it, whereas the mode sits on the GC print as long as GC is the single
    most common level -- which it is by a wide margin (302/321 on the checked day).
    Ties break to the HIGHEST level, because specialness is one-sided: an issue can
    only finance *below* GC, so of two equally-common levels GC is the upper one.
    """
    v = pd.to_numeric(x, errors="coerce").dropna()
    if v.empty:
        return np.nan
    counts = v.round(4).value_counts()
    top = counts.max()
    return float(max(counts[counts == top].index))


# --------------------------------------------------------------------------- build


def build_panel(limit: int | None = None) -> pd.DataFrame:
    files = sorted(glob.glob(str(ISSUE_DS / "*.parquet")))
    if limit:
        files = files[-limit:]
    if not files:
        raise FileNotFoundError(f"no JPM issue parquets under {ISSUE_DS}")

    frames = []
    for f in files:
        date = pd.Timestamp(pathlib.Path(f).stem)
        try:
            d = pd.read_parquet(f)
        except Exception as exc:  # a corrupt day is a fact, not a reason to stop
            print(f"  !! {date.date()} unreadable: {exc}", file=sys.stderr)
            continue
        need = {"Cpn", "Mat", "OI", "1m Repo", "3m Repo"}
        if not need.issubset(d.columns):
            print(f"  !! {date.date()} missing {need - set(d.columns)}", file=sys.stderr)
            continue

        out = pd.DataFrame(
            {
                "date": date,
                "cpn": pd.to_numeric(d["Cpn"], errors="coerce"),
                "maturity": _parse_mat(d["Mat"]),
                "oi": pd.to_numeric(d["OI"], errors="coerce"),
                "ytm": pd.to_numeric(d.get("Spot YTM"), errors="coerce"),
                "repo_1m": pd.to_numeric(d["1m Repo"], errors="coerce"),
                "repo_3m": pd.to_numeric(d["3m Repo"], errors="coerce"),
                "issue_size": pd.to_numeric(d.get("Issue Size"), errors="coerce"),
                "soma_pct": pd.to_numeric(d.get("Soma pct"), errors="coerce"),
            }
        )
        out = out.dropna(subset=["cpn", "maturity"])
        if out.empty:
            continue
        out["gc_1m"] = _modal_gc(out["repo_1m"])
        out["gc_3m"] = _modal_gc(out["repo_3m"])
        frames.append(out)

    panel = pd.concat(frames, ignore_index=True)
    # Positive = special = finances BELOW GC.
    panel["special_1m_bp"] = (panel["gc_1m"] - panel["repo_1m"]) * 100.0
    panel["special_3m_bp"] = (panel["gc_3m"] - panel["repo_3m"]) * 100.0
    panel["ttm_yrs"] = (panel["maturity"] - panel["date"]).dt.days / 365.25

    # Gate on the LEVEL (see REPO_LEVEL_FLOOR_PCT). NaN, not 0: a bond whose repo cell
    # did not extract has *unknown* financing, and calling that "finances at GC" would
    # silently hand the trade free carry on exactly the days the PDF was worst.
    for horizon in ("1m", "3m"):
        lvl, gc, sp = f"repo_{horizon}", f"gc_{horizon}", f"special_{horizon}_bp"
        bad = (
            panel[lvl].isna()
            | (panel[lvl] < REPO_LEVEL_FLOOR_PCT)
            | (panel[lvl] > panel[gc] + REPO_LEVEL_CEIL_OVER_GC_PCT)
            | (panel[lvl].eq(0.0) & panel[gc].gt(ZERO_SENTINEL_GC_PCT))
        )
        panel.loc[bad, [lvl, sp]] = np.nan
        # A GC that is itself unreadable makes every specialness on that day meaningless.
        panel.loc[panel[gc].isna(), sp] = np.nan

    # 34 duplicate (date, cpn, maturity) keys across 656k rows -- a bond printed twice by
    # tabula. Median so a duplicated-but-differing pair does not pick arbitrarily.
    panel = (
        panel.groupby(["date", "cpn", "maturity"], as_index=False)
        .agg(
            oi=("oi", "first"),
            ytm=("ytm", "median"),
            repo_1m=("repo_1m", "median"),
            repo_3m=("repo_3m", "median"),
            gc_1m=("gc_1m", "first"),
            gc_3m=("gc_3m", "first"),
            special_1m_bp=("special_1m_bp", "median"),
            special_3m_bp=("special_3m_bp", "median"),
            issue_size=("issue_size", "median"),
            soma_pct=("soma_pct", "median"),
            ttm_yrs=("ttm_yrs", "first"),
        )
    )
    return panel


# --------------------------------------------------------------------------- tie-out


def tie_out(panel: pd.DataFrame) -> pd.DataFrame:
    """Reproduce JPM's published ``3m Repo Special`` from the issue-level repo levels."""
    files = sorted(glob.glob(str(CARRY_DS / "*.parquet")))
    if not files:
        raise FileNotFoundError(f"no JPM carry parquets under {CARRY_DS}")

    frames = []
    for f in files:
        date = pd.Timestamp(pathlib.Path(f).stem)
        d = pd.read_parquet(f)
        if "3m Repo Special" not in d.columns:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "date": date,
                    "cusip": d.get("CUSIP"),
                    "cpn": pd.to_numeric(d["Cpn"], errors="coerce"),
                    "maturity": _parse_mat(d["Maturity"]),
                    "jpm_special_3m_bp": pd.to_numeric(d["3m Repo Special"], errors="coerce"),
                    "jpm_carry_3m": pd.to_numeric(d.get("3m Carry"), errors="coerce"),
                    "jpm_roll_3m": pd.to_numeric(d.get("3m Roll"), errors="coerce"),
                }
            )
        )
    pub = pd.concat(frames, ignore_index=True).dropna(subset=["cpn", "maturity"])

    # A whole-universe specialness is a contradiction in terms: specialness is defined
    # against GC, so the modal issue must print ~0 by construction. On 2024-11-08 the
    # published column prints 25.0 for 319 of ~320 issues (the day after the Nov-7 FOMC
    # cut), which is a shifted cell, not a market event -- and it is 319 of the 340
    # disagreements on its own. Flagged per-day rather than per-row so the test is the
    # structural one, not "drop what disagrees with me".
    day_median = pub.groupby("date")["jpm_special_3m_bp"].transform("median")
    pub["published_day_ok"] = day_median <= 1.0

    m = pub.merge(
        panel[["date", "cpn", "maturity", "special_3m_bp", "special_1m_bp", "oi", "gc_3m", "repo_3m"]],
        on=["date", "cpn", "maturity"],
        how="inner",
    )

    # Structural gate on the published side, argued rather than thresholded: a printed
    # "specialness" that equals the day's GC LEVEL in bp is the repo level that landed in
    # the wrong column (526.0 against GC 5.26% on 2024-08-22), not a 5.26%/yr special.
    looks_like_level = (
        (m["jpm_special_3m_bp"] - m["gc_3m"] * 100.0).abs() < 1.0
    ) & (m["jpm_special_3m_bp"] > 50.0)
    m.loc[looks_like_level, "jpm_special_3m_bp"] = np.nan
    m["published_row_ok"] = ~looks_like_level
    m = m.dropna(subset=["jpm_special_3m_bp"])

    m["err_bp"] = m["special_3m_bp"] - m["jpm_special_3m_bp"]
    return m


def report_tieout(m_all: pd.DataFrame) -> None:
    n_flag = int((~m_all["published_day_ok"]).sum())
    if n_flag:
        days = sorted(m_all.loc[~m_all["published_day_ok"], "date"].dt.date.unique())
        print(f"\n[gate] dropping {n_flag:,} rows on {len(days)} day(s) whose PUBLISHED "
              f"column has a non-zero universe median: {days}")
    m = m_all[m_all["published_day_ok"]]

    print("\n=== TIE-OUT: derived (GC_modal - issue repo) vs JPM published '3m Repo Special' ===")
    print(f"matched rows          : {len(m):,}  over {m['date'].nunique()} days")
    print(f"days                  : {m['date'].min().date()} .. {m['date'].max().date()}")
    err = m["err_bp"].dropna()
    print(f"mean abs error        : {err.abs().mean():.3f} bp")
    print(f"median abs error      : {err.abs().median():.3f} bp")
    print(f"p95 abs error         : {err.abs().quantile(0.95):.3f} bp")
    print(f"max abs error         : {err.abs().max():.3f} bp")
    print(f"within 0.5bp          : {(err.abs() <= 0.5).mean():.2%}")
    print(f"within 1.0bp          : {(err.abs() <= 1.0).mean():.2%}")
    print(f"corr                  : {m['special_3m_bp'].corr(m['jpm_special_3m_bp']):.4f}")

    # The rows that matter are the special ones -- agreement on the 0-bp mass is trivial.
    sp = m[m["jpm_special_3m_bp"] > 0.5]
    print(f"\n-- rows JPM flags special (>0.5bp): {len(sp):,}")
    if len(sp):
        e = sp["err_bp"]
        print(f"   mean err {e.mean():+.3f}  mean abs {e.abs().mean():.3f}  "
              f"p95 abs {e.abs().quantile(0.95):.3f}  max abs {e.abs().max():.3f}")
        print(f"   within 1bp: {(e.abs() <= 1.0).mean():.2%}   corr: "
              f"{sp['special_3m_bp'].corr(sp['jpm_special_3m_bp']):.4f}")
        print("\n   by original-issue tenor:")
        g = sp.groupby("oi").apply(
            lambda d: pd.Series(
                {
                    "n": len(d),
                    "jpm_mean": d["jpm_special_3m_bp"].mean(),
                    "derived_mean": d["special_3m_bp"].mean(),
                    "mean_err": d["err_bp"].mean(),
                    "max_abs_err": d["err_bp"].abs().max(),
                    "corr": d["special_3m_bp"].corr(d["jpm_special_3m_bp"]),
                }
            ),
            include_groups=False,
        )
        print(g.round(3).to_string())


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("building JPM issue repo panel ...")
    panel = build_panel()
    panel.to_parquet(PANEL_PATH, index=False)
    print(f"panel: {panel.shape} -> {PANEL_PATH}")
    print(f"  dates {panel['date'].min().date()} .. {panel['date'].max().date()} "
          f"({panel['date'].nunique()} days)")
    print(f"  GC 3m range {panel['gc_3m'].min():.3f} .. {panel['gc_3m'].max():.3f}")
    print("\nspecialness by original-issue tenor (3m, bp) -- mean over all issues:")
    print(panel.groupby("oi")["special_3m_bp"].describe()[["count", "mean", "50%", "max"]].to_string())

    # --- the era the tie-out window cannot certify -------------------------------
    # The tie-out runs 2024-08..2025-08: GC ~4-5%, no ZIRP, no stress. Everything the
    # gates do at the ZIRP floor and through the March-2020 fails episode is therefore
    # UNTESTED by it, and that is exactly where a spread-based gate would have silently
    # deleted data. Print those eras so the gate is inspected, not assumed.
    print("\n=== eras the tie-out window cannot certify ===")
    for label, lo, hi in [
        ("ZIRP 2020-06..2021-12", "2020-06-01", "2021-12-31"),
        ("COVID stress 2020-03", "2020-03-01", "2020-04-15"),
        ("2019 repo spike", "2019-09-01", "2019-10-15"),
    ]:
        e = panel[(panel["date"] >= lo) & (panel["date"] <= hi)]
        if e.empty:
            print(f"{label:26s}: NO DATA")
            continue
        gc = e.groupby("date")["gc_3m"].first()
        print(
            f"{label:26s}: {e['date'].nunique():4d} days  "
            f"GC3m {gc.min():.3f}..{gc.max():.3f}  "
            f"repo3m min {e['repo_3m'].min():.3f}  "
            f"special3m max {e['special_3m_bp'].max():.1f}bp  "
            f"NaN special {e['special_3m_bp'].isna().mean():.1%}"
        )
    covid = panel[(panel["date"] >= "2020-03-01") & (panel["date"] <= "2020-04-15")]
    if not covid.empty:
        top = covid.nlargest(6, "special_3m_bp")[
            ["date", "cpn", "maturity", "oi", "gc_3m", "repo_3m", "special_3m_bp"]
        ]
        print("\n  most-special issues in the COVID window (fails episode should show here):")
        print(top.to_string(index=False))

    m = tie_out(panel)
    m.to_parquet(TIEOUT_PATH, index=False)
    report_tieout(m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
