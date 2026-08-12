"""Re-run the whole imputation calibration with the module's own fitter.

Two jobs:
  1. VALIDATE THE TOOL. At LN_MU_SLACK = 30 it must reproduce every shipped
     constant -- 18 multipliers, IMPUTED_DV01_SHARE / IMPUTED_NOTIONAL_SHARE,
     both per-bucket dicts and both sensitivity endpoints. A sweep that cannot
     hit the known answer cannot be believed at the new one.
  2. Re-measure at a slack where the mu box does not bind, and emit the CAP_BANDS
     literal.

Usage:  python scratch/imp_fix01_sweep.py [slack ...]
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from SDRUtils.dealer_direction import imputation as imp  # noqa: E402

GRID = [("div", 2.0), ("div", 4.0), ("div", 10.0), ("div", 20.0),
        ("q", 0.90), ("q", 0.95)]
SHIPPED_TH = ("div", 4.0)

BUCKET = {  # (vintage, lo) -> coarse bucket, from partB_final_imputation_Cdiv4.csv
    ("V1", 0.0): "<=2y", ("V1", 0.12): "<=2y", ("V1", 0.3): "<=2y",
    ("V1", 0.54): "<=2y", ("V1", 1.04): "<=2y",
    ("V1", 2.25): "2-10y", ("V1", 5.25): "2-10y",
    ("V1", 10.75): "10-30y", ("V1", 31.0): ">30y",
    ("V2", 0.0): "<=2y", ("V2", 0.12): "<=2y", ("V2", 0.3): "<=2y",
    ("V2", 0.54): "<=2y", ("V2", 1.04): "<=2y",
    ("V2", 2.25): "2-10y", ("V2", 5.25): "2-10y",
    ("V2", 11.0): "10-30y", ("V2", 31.0): ">30y",
}
BUCKETS = ("<=2y", "2-10y", "10-30y", ">30y")


def load() -> pd.DataFrame:
    f = pd.read_csv(os.path.join(HERE, "partB_freq_cache.csv"))
    f = f.dropna(subset=["cell"]).copy()
    m = f["cell"].str.split("|", expand=True)
    f["vintage"] = m[0]
    for c, src in (("lo", m[1]), ("hi", m[2]), ("cap", m[3])):
        f[c] = src.astype(float)
    for c in ("notional", "n", "sum_t", "sum_dv01"):
        f[c] = f[c].astype(float)
    return f


def run(freq: pd.DataFrame, thresh) -> pd.DataFrame:
    """One threshold, every cell. Mirrors scratch/partB_sensitivity.run."""
    rows = []
    for cell, g in freq.groupby("cell", sort=True):
        C = float(g["cap"].iloc[0])
        cap_rows, sub_rows = g[g["is_capped"]], g[~g["is_capped"]]
        n_cap = float(cap_rows.loc[cap_rows["notional"] == C, "n"].sum())
        if thresh[0] == "div":
            u = C / thresh[1]
        else:
            v = g.sort_values("notional")
            cw = v["n"].cumsum() / v["n"].sum()
            u = float(v.loc[cw >= thresh[1], "notional"].iloc[0])
            u = min(max(u, C / 50), C / 1.8)
        t = sub_rows[(sub_rows["notional"] >= u) & (sub_rows["notional"] < C)]
        fit = (imp.fit_cell(t["notional"].to_numpy(float), t["n"].to_numpy(float),
                            u, C, n_cap) if len(t) else None)
        rec = {"vintage": g["vintage"].iloc[0], "lo": float(g["lo"].iloc[0]),
               "cap": C, "u": u, "n_cap": n_cap,
               "tot_notional": float((g["notional"] * g["n"]).sum()),
               "tot_dv01": float(g["sum_dv01"].sum()),
               "cap_mean_t": float(cap_rows["sum_t"].sum() / cap_rows["n"].sum()),
               "E_above_ln": np.nan, "n_sub": np.nan, "alpha": np.nan,
               "ln_mu": np.nan, "ln_sigma": np.nan, "ks_ln": np.nan,
               "ks_par": np.nan, "degenerate": None, "ncap_err": np.nan}
        if fit is not None:
            rec.update(E_above_ln=fit.mean_above_lognormal, n_sub=fit.n_sub,
                       alpha=fit.pareto_alpha_censored, ln_mu=fit.ln_mu_censored,
                       ln_sigma=fit.ln_sigma_censored, ks_ln=fit.ks_lognormal,
                       ks_par=fit.ks_pareto, degenerate=fit.ln_degenerate,
                       ncap_err=fit.capped_count_error)
        rows.append(rec)
    d = pd.DataFrame(rows)
    d["bucket"] = [BUCKET[(v, lo)] for v, lo in zip(d["vintage"], d["lo"])]
    d["mult"] = d["E_above_ln"] / d["cap"]
    d["exc_notional"] = d["n_cap"] * np.maximum(d["E_above_ln"] - d["cap"], 0)
    d["exc_dv01"] = d["exc_notional"] * d["cap_mean_t"] * 1e-4
    return d.sort_values(["vintage", "lo"]).reset_index(drop=True)


def shares(d: pd.DataFrame) -> tuple[float, float]:
    tn, te = d["tot_notional"].sum(), d["exc_notional"].sum()
    td, ted = d["tot_dv01"].sum(), d["exc_dv01"].sum()
    return te / (tn + te), ted / (td + ted)


def bucket_shares(d: pd.DataFrame) -> dict[str, tuple[float, float]]:
    out = {}
    for b in BUCKETS:
        out[b] = shares(d[d["bucket"] == b])
    return out


def sweep(freq, slack: float):
    imp.LN_MU_SLACK = slack
    return {th: run(freq, th) for th in GRID}


def report(freq, slack: float, *, emit: bool = False):
    per = sweep(freq, slack)
    d4 = per[SHIPPED_TH]
    print(f"\n{'=' * 100}\nLN_MU_SLACK = {slack}\n{'=' * 100}")
    print(d4[["vintage", "lo", "cap", "n_cap", "n_sub", "ln_mu", "ln_sigma",
              "mult", "alpha", "ncap_err", "ks_ln", "ks_par", "degenerate"]]
          .to_string(index=False))
    sn, sd = shares(d4)
    print(f"\n  headline at u=C/4:  notional share {sn:.4f}   DV01 share {sd:.4f}")
    wall = np.array([censored_on_box_wall(m, s, uu, cc) for m, s, uu, cc
                     in zip(d4["ln_mu"], d4["ln_sigma"], d4["u"], d4["cap"])])
    cap_at_cap = float((d4["n_cap"] * d4["cap"] * d4["cap_mean_t"] * 1e-4).sum())
    print(f"  censored fits on a box wall: {int(wall.sum())}/18  "
          f"= {d4['exc_dv01'][wall].sum() / d4['exc_dv01'].sum():.4f} of the excess DV01")
    print(f"  capped-at-cap DV01 share {cap_at_cap / d4['tot_dv01'].sum():.4f}   "
          f"effective k {1.0 + d4['exc_dv01'].sum() / cap_at_cap:.4f}")
    bs = bucket_shares(d4)
    for b in BUCKETS:
        print(f"    {b:8s} notional {bs[b][0]:.4f}  dv01 {bs[b][1]:.4f}")

    # the six-threshold band
    all_sn, all_sd = [], []
    per_bucket = {b: [] for b in BUCKETS}
    print("\n  threshold sweep:")
    for th in GRID:
        d = per[th]
        s = shares(d)
        all_sn.append(s[0])
        all_sd.append(s[1])
        lab = f"u=C/{th[1]:g}" if th[0] == "div" else f"u=q{th[1]:.2f}"
        nfit = int(d["E_above_ln"].notna().sum())
        ndeg = int(pd.Series(d["degenerate"]).fillna(False).astype(bool).sum())
        print(f"    {lab:9s} cells fitted {nfit:2d}  degenerate {ndeg:2d}  "
              f"notional {s[0]:.4f}  dv01 {s[1]:.4f}")
        bb = bucket_shares(d)
        for b in BUCKETS:
            # a bucket whose only cells are unfittable at this threshold
            # contributes no measurement -- that is how the shipped band was
            # built (">30y" is unfittable at two of the six).
            if d[(d["bucket"] == b)]["E_above_ln"].notna().any():
                per_bucket[b].append(bb[b][1])
    print(f"\n  SENSITIVITY_DV01_SHARE     = ({min(all_sd):.4f}, {max(all_sd):.4f})")
    print(f"  SENSITIVITY_NOTIONAL_SHARE = ({min(all_sn):.4f}, {max(all_sn):.4f})")
    for b in BUCKETS:
        print(f"  bucket {b:8s} dv01 range ({min(per_bucket[b]):.4f}, "
              f"{max(per_bucket[b]):.4f})")

    if emit:
        emit_literal(d4)
    return per


def censored_on_box_wall(mu: float, sigma: float, u: float, C: float) -> bool:
    """Did the CENSORED fit -- the shipped estimator -- land on a box wall?

    Censored only: the truncated comparator pins in cells where the shipped
    multiplier is perfectly interior (V2 46d-3m), and a flag that fired there
    would overstate how much of the table is bound-determined.
    """
    return bool(sigma > 0.98 * imp.LN_SIGMA_MAX
                or sigma < np.exp(-3.0) * 1.02
                or mu < np.log(u) - imp.LN_MU_SLACK + 1e-3
                or mu > np.log(C) + 10.0 - 1e-3)


def emit_literal(d4: pd.DataFrame):
    """The CAP_BANDS tuple, generated -- 18 x 9 numbers are not hand-copied."""
    shipped = {(b.vintage, b.lo): b for b in imp.CAP_BANDS}
    lines = ["CAP_BANDS: tuple[CapBand, ...] = ("]
    for _, r in d4.iterrows():
        b = shipped[(r["vintage"], r["lo"])]
        r = dict(r)
        r["degenerate"] = censored_on_box_wall(r["ln_mu"], r["ln_sigma"],
                                               r["u"], r["cap"])
        lines.append(
            f'    CapBand("{b.vintage}", {b.lo!r}, {b.hi!r}, {b.cap!r}, "{b.label}",\n'
            f'            ln_mu={r["ln_mu"]!r}, ln_sigma={r["ln_sigma"]!r},\n'
            f'            multiplier={r["mult"]!r}, tail_index={r["alpha"]!r},\n'
            f'            capped_count_error={r["ncap_err"]!r},\n'
            f'            ks_lognormal={r["ks_ln"]!r}, ks_pareto={r["ks_par"]!r},\n'
            f'            ln_degenerate={bool(r["degenerate"])!r}, '
            f'n_capped={int(r["n_cap"])}),')
    lines.append(")")
    path = os.path.join(HERE, "imp_fix01_cap_bands.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\n  wrote {path}")


def validate(freq, slack=None):
    """Reproduce the shipped constants at ``slack``, or stop.

    Run at 30 it validates the tool against the calibration this module shipped
    with; run at the module's own LN_MU_SLACK it validates the calibration
    against the code that is supposed to produce it.
    """
    slack = imp.LN_MU_SLACK if slack is None else slack
    print("=" * 100)
    print(f"VALIDATION: slack {slack} must reproduce the shipped calibration")
    print("=" * 100)
    imp.LN_MU_SLACK = slack
    d4 = run(freq, SHIPPED_TH)
    shipped = {(b.vintage, b.lo): b for b in imp.CAP_BANDS}
    bad = 0
    for _, r in d4.iterrows():
        b = shipped[(r["vintage"], r["lo"])]
        for name, got, want in (("mult", r["mult"], b.multiplier),
                                ("ln_mu", r["ln_mu"], b.ln_mu),
                                ("ln_sigma", r["ln_sigma"], b.ln_sigma),
                                ("alpha", r["alpha"], b.tail_index),
                                ("ks_ln", r["ks_ln"], b.ks_lognormal),
                                ("ks_par", r["ks_par"], b.ks_pareto),
                                ("ncap_err", r["ncap_err"], b.capped_count_error),
                                ("n_cap", r["n_cap"], b.n_capped)):
            if abs(got - want) > 2e-3 * max(1.0, abs(want)):
                print(f"  MISMATCH {b.vintage} {b.label} {name}: {got!r} vs {want!r}")
                bad += 1
    for _, r in d4.iterrows():
        b = shipped[(r["vintage"], r["lo"])]
        got = censored_on_box_wall(r["ln_mu"], r["ln_sigma"], r["u"], r["cap"])
        if got != b.ln_degenerate:
            print(f"  MISMATCH {b.vintage} {b.label} ln_degenerate {got} vs "
                  f"{b.ln_degenerate}")
            bad += 1
    sn, sd = shares(d4)
    checks = [("IMPUTED_DV01_SHARE", sd, imp.IMPUTED_DV01_SHARE, 5e-4),
              ("IMPUTED_NOTIONAL_SHARE", sn, imp.IMPUTED_NOTIONAL_SHARE, 5e-4)]
    bs = bucket_shares(d4)
    for b in BUCKETS:
        want_n, want_d = imp.IMPUTED_SHARE_BY_BUCKET[b]
        checks.append((f"bucket {b} notional", bs[b][0], want_n, 5e-4))
        checks.append((f"bucket {b} dv01", bs[b][1], want_d, 5e-4))
    for name, got, want, tol in checks:
        ok = abs(got - want) <= tol
        bad += not ok
        print(f"  {'ok  ' if ok else 'BAD '} {name:26s} {got:.4f} vs shipped {want:.4f}")
    print(f"\n  mismatches: {bad}")
    return bad


def main() -> int:
    freq = load()
    args = [a for a in sys.argv[1:] if a != "--no-validate"]
    if "--no-validate" not in sys.argv[1:]:
        bad = validate(freq)
        if bad:
            print("TOOL IS NOT VALIDATED -- stop.")
            return 1
    slacks = [float(a) for a in args] or [30.0]
    for slack in slacks:
        report(freq, slack, emit=(slack == slacks[-1]))
    imp.LN_MU_SLACK = 30.0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
