"""Verify every artefact staged for the dealer-direction notebook.

For each file: parse it, print shape + columns, and assert at least one headline
number against the corresponding documented claim.

Every asserted value was hand-verified against the write-ups BEFORE this script
was written (R0_RESULT.md / R0B_RESULT.md on branch r0-leadlag, S1_RESULT.md,
S2_RESULT.md, S_DEVIATIONS.md, scratch/ppfix_results.txt), so the checker is
checked against known answers rather than against itself.

Exit 0 only if every assertion passes.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
import traceback

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
DATA = ROOT / "notebooks" / "dealer_direction" / "data"

FAILS: list[str] = []
NCHECK = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global NCHECK
    NCHECK += 1
    if cond:
        print(f"    PASS  {label}   {detail}")
    else:
        print(f"    FAIL  {label}   {detail}")
        FAILS.append(f"{label}  {detail}")


def near(a: float, b: float, tol: float) -> bool:
    return abs(float(a) - float(b)) <= tol


def load(name: str) -> pd.DataFrame:
    p = DATA / name
    df = pd.read_csv(p)
    print(f"\n{name}   shape={df.shape}")
    print(f"    columns: {list(df.columns)}")
    return df


def banner(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# ---------------------------------------------------------------- R0 / R0b ---
def verify_r0() -> None:
    banner("1. R0 / R0b  (COPIED from r0-leadlag c97205bd; window R, 67 sessions)")

    for name, want in [("r0_verdict.txt", "FAIL"),
                       ("r0_d1_downgrade.txt", "UNINFORMATIVE"),
                       ("r0b_verdict.txt", "FAIL")]:
        txt = (DATA / name).read_text(encoding="utf-8").strip()
        print(f"\n{name}   {txt!r}")
        check(f"{name} == {want}", txt == want, f"got {txt!r}")

    # --- beta profiles ------------------------------------------------------
    for name in ("r0_betas.csv", "r0b_betas.csv"):
        b = load(name)
        check(f"{name} 732 rows", len(b) == 732, f"got {len(b)}")
        check(f"{name} columns",
              list(b.columns) == ["clock", "bucket", "k", "beta",
                                  "se_cluster", "se_nw"])
        check(f"{name} k spans -30..30", (b.k.min(), b.k.max()) == (-30, 30),
              f"{b.k.min()}..{b.k.max()}")
        check(f"{name} two clocks", sorted(b.clock.unique()) == ["diss", "exec"],
              str(sorted(b.clock.unique())))
        check(f"{name} 6 scopes", b.bucket.nunique() == 6,
              str(sorted(b.bucket.unique())))
        check(f"{name} no nulls", int(b.isna().sum().sum()) == 0)

    # the betas must sum to the table's reported sums -- an internal tie-out
    # that neither file imposes on the other
    rb = pd.read_csv(DATA / "r0_betas.csv")
    rt = pd.read_csv(DATA / "r0_table.csv")
    sel = rb[(rb.clock == "diss") & (rb.bucket == "POOLED")]
    row = rt[(rt.clock == "diss") & (rt.split == "all") & (rt.scope == "pooled")].iloc[0]
    s_neg = float(sel[sel.k <= -1].beta.sum())
    s_pos = float(sel[sel.k >= 1].beta.sum())
    print(f"\nR0 tie-out: betas sum kneg={s_neg:.6f} vs table {row.sum_beta_kneg:.6f}")
    check("r0 betas sum == r0_table sum_beta_kneg",
          near(s_neg, row.sum_beta_kneg, 1e-9), f"{s_neg:.9f}")
    check("r0 betas sum == r0_table sum_beta_kpos",
          near(s_pos, row.sum_beta_kpos, 1e-9), f"{s_pos:.9f}")

    # --- summary tables: the governing (diss, pooled) row -------------------
    print("\n--- the governing row: clock=diss, split=all, scope=pooled ---")
    r0 = rt[(rt.clock == "diss") & (rt.split == "all") & (rt.scope == "pooled")].iloc[0]
    r0b_t = load("r0b_table.csv")
    r0b = r0b_t[(r0b_t.clock == "diss") & (r0b_t.split == "all")
                & (r0b_t.scope == "pooled")].iloc[0]
    check("r0_table 60 rows", len(rt) == 60, f"got {len(rt)}")
    check("r0b_table 60 rows", len(r0b_t) == 60, f"got {len(r0b_t)}")

    print(f"  R0   sum_beta_kneg = {r0.sum_beta_kneg:+.5f}  t = {r0.t_cluster_kneg:+.2f}")
    print(f"  R0   sum_beta_kpos = {r0.sum_beta_kpos:+.5f}  t = {r0.t_cluster_kpos:+.2f}")
    print(f"  R0b  sum_beta_kneg = {r0b.sum_beta_kneg:+.5f}  t = {r0b.t_cluster_kneg:+.3f}")
    print(f"  R0b  sum_beta_kpos = {r0b.sum_beta_kpos:+.5f}  t = {r0b.t_cluster_kpos:+.2f}")
    print(f"  R0   n_obs={r0.n_obs}  n_days={r0.n_days}")

    check("R0 pre-print sum == -0.10746", near(r0.sum_beta_kneg, -0.10746, 5e-6))
    check("R0 pre-print t == -5.90", near(r0.t_cluster_kneg, -5.90, 5e-3))
    check("R0 post-print sum == +0.00761", near(r0.sum_beta_kpos, 0.00761, 5e-6))
    check("R0 post-print t == +0.59", near(r0.t_cluster_kpos, 0.59, 5e-3))
    check("R0 |Spos/Sneg| == 0.071", near(r0.abs_ratio_pos_over_neg, 0.071, 5e-4),
          f"{r0.abs_ratio_pos_over_neg:.4f}")
    check("R0 N_bins == 402946", int(r0.n_obs) == 402946, str(r0.n_obs))
    check("R0 N_days == 67", int(r0.n_days) == 67, str(r0.n_days))

    check("R0b pre-print sum == +0.01591", near(r0b.sum_beta_kneg, 0.01591, 5e-6))
    check("R0b pre-print t == +1.955 (BELOW 1.96)",
          near(r0b.t_cluster_kneg, 1.955, 5e-3) and r0b.t_cluster_kneg < 1.96,
          f"{r0b.t_cluster_kneg:.4f}")
    check("R0b post-print sum == -0.00114", near(r0b.sum_beta_kpos, -0.00114, 5e-6))
    check("R0b post-print t == -0.13", near(r0b.t_cluster_kpos, -0.13, 5e-3))
    check("R0b |Spos/Sneg| == 0.072", near(r0b.abs_ratio_pos_over_neg, 0.072, 5e-4),
          f"{r0b.abs_ratio_pos_over_neg:.4f}")
    check("R0b N_bins identical to R0's", int(r0b.n_obs) == int(r0.n_obs))
    # the artifact: the pre-print sums have OPPOSITE signs
    check("pre-print mass flips sign between the two mid rules",
          (r0.sum_beta_kneg < 0) and (r0b.sum_beta_kneg > 0),
          f"{r0.sum_beta_kneg:+.5f} -> {r0b.sum_beta_kneg:+.5f}")
    # 88% of R0b's |beta| profile is what noise would produce
    ratio = float(r0b.abs_beta_mass_null / r0b.abs_beta_mass)
    check("R0b |beta| mass ~88% of the null", near(ratio, 0.88, 0.02),
          f"null/actual = {ratio:.3f}")

    # --- the gate: R0b's exclusion interval ---------------------------------
    g = load("r0b_gate.csv")
    p = g[g.scope == "POOLED"].iloc[0]
    lo = float(p.sum_beta_kpos - p.mde)
    hi = float(p.sum_beta_kpos + p.mde)
    print(f"  pooled post-print 95% CI = ({lo:+.5f}, {hi:+.5f})")
    check("r0b_gate mde == 1.96*se", near(p.mde, 1.96 * p.se_cluster_kpos, 1e-9))
    check("R0b post-print CI low  == -0.0188", near(lo, -0.0188, 5e-5), f"{lo:.6f}")
    check("R0b post-print CI high == +0.0165", near(hi, 0.0165, 5e-5), f"{hi:.6f}")
    check("informative == False in all 6 scopes", (~g.informative).all(),
          str(g.informative.tolist()))

    # --- attenuation / rho --------------------------------------------------
    a = load("attenuation.csv")
    check("attenuation 5 bucket rows + 1 pooled row", len(a) == 6, f"got {len(a)}")
    ab = a[a.scope == "bucket"]
    check("5 decision buckets", len(ab) == 5, str(ab.bucket.tolist()))
    thr = float(a.downgrade_threshold_rho.iloc[0])
    print(f"  rho_minute by bucket: "
          f"{dict(zip(a.bucket, a.rho_minute.round(4)))}   threshold {thr}")
    check("downgrade threshold == 0.50", near(thr, 0.50, 1e-12))
    check("all 5 decision buckets rho_minute < 0.50", bool((ab.rho_minute < thr).all()),
          f"max {ab.rho_minute.max():.4f}")
    check("attenuation rho_minute spans 0.317..0.490",
          near(ab.rho_minute.min(), 0.317, 1e-3)
          and near(ab.rho_minute.max(), 0.490, 1e-3),
          f"{ab.rho_minute.min():.4f}..{ab.rho_minute.max():.4f}")
    check("reference curve is USD-SOFR-1D / citivelo_excel_rl",
          set(a.reference_curve) == {"USD-SOFR-1D"}
          and set(a.reference_source) == {"citivelo_excel_rl"})

    dr = load("r0b_dense_rho.csv")
    pooled12 = dr[(dr.grid == "12 tenors (D1's grid)") & (dr.bucket == "POOLED")].iloc[0]
    print(f"  headline rho = POOLED / 12-tenor / rho_minute = "
          f"{pooled12.rho_minute:.6f}")
    check("headline rho == 0.405", near(pooled12.rho_minute, 0.405, 5e-4),
          f"{pooled12.rho_minute:.6f}")
    # two independently-written files must agree on the headline rho
    ap = a[a.scope != "bucket"].iloc[0]
    check("attenuation.csv POOLED rho agrees with r0b_dense_rho POOLED/12-tenor",
          near(ap.rho_minute, pooled12.rho_minute, 1e-4),
          f"{ap.rho_minute:.6f} vs {pooled12.rho_minute:.6f}")

    d1 = load("r0_d1_rho.csv")
    check("r0_d1_rho 5 buckets", len(d1) == 5, f"got {len(d1)}")
    check("r0_d1_rho all below 0.50", bool((d1.rho_minute < 0.50).all()))

    # --- coverage / decomps -------------------------------------------------
    cov = load("r0b_coverage.csv")
    allrow = cov[cov.bucket == "ALL"].iloc[0]
    print(f"  signed DV01 share: R0 {allrow.r0_signed_dv01:.4f} -> "
          f"R0b {allrow.r0b_signed_dv01:.4f}")
    check("R0 signs ~91.7% of DV01", near(allrow.r0_signed_dv01, 0.917, 1e-3))
    check("R0b signs ~57.7% of DV01", near(allrow.r0b_signed_dv01, 0.577, 1e-3))
    check("R0b signs strictly fewer than R0",
          allrow.r0b_signed_dv01 < allrow.r0_signed_dv01)
    check("r0b_coverage n_prints ALL == 292525", int(allrow.n_prints) == 292525,
          str(allrow.n_prints))

    xc = load("r0b_xcorr.csv")
    check("r0b_xcorr 12 rows (2 clocks x 6 scopes)", len(xc) == 12, f"got {len(xc)}")
    sd = load("r0b_sign_decomp.csv")
    check("r0b_sign_decomp 3 sources", len(sd) == 3, str(sd.source.tolist()))
    vd = load("r0b_variance_decomp.csv")
    check("r0b_variance_decomp 2 cell definitions", len(vd) == 2)
    print(f"  predicted agreement {vd.pred_agreement.iloc[0]:.4f} vs measured "
          f"{vd.measured_agreement.iloc[0]:.4f}")
    check("predicted agreement 0.822 vs measured 0.676",
          near(vd.pred_agreement.iloc[0], 0.822, 1e-3)
          and near(vd.measured_agreement.iloc[0], 0.676, 1e-3))

    # --- the two PNGs: present, non-empty, real PNGs -------------------------
    for name, nbytes in (("r0_betas.png", 339176), ("r0b_betas.png", 413764)):
        raw = (DATA / name).read_bytes()
        print(f"\n{name}  {len(raw)} bytes  magic={raw[:8]!r}")
        check(f"{name} exact size", len(raw) == nbytes, f"got {len(raw)}")
        check(f"{name} is a real PNG", raw[:8] == b"\x89PNG\r\n\x1a\n")


# ----------------------------------------------- universe / package recovery --
def verify_universe() -> None:
    banner("2. Universe and package recovery  (window U: 610 days, 2024-03-01..2026-08-07)")

    u = (DATA / "universe_exclusions_610d.txt").read_text(
        encoding="utf-8", errors="replace")
    print(f"\nuniverse_exclusions_610d.txt   {len(u)} chars, "
          f"{len(u.splitlines())} lines")
    for label, pat in [
        ("units 1,437,838", r"units\s+1,437,838"),
        ("kept 1,082,393 (75.28%)", r"kept\s+1,082,393\s+\(75\.28%\)"),
        ("DV01 total 80,660,906,449", r"DV01 proxy total\s+80,660,906,449"),
        ("DV01 kept 45,941,783,080 (56.96%)",
         r"DV01 proxy kept\s+45,941,783,080\s+\(56\.96%\)"),
        ("610 days", r"days\s+610"),
        ("UNORIENTABLE_PKG 39.973637", r"UNORIENTABLE_PKG\s+272373\s+768706\s+3\.224310e\+10\s+39\.973637"),
        ("PKG-4+ 22.567462", r"UNORIENTABLE_PKG / PKG-4\+.*22\.567462"),
    ]:
        check(label, re.search(pat, u) is not None)

    s = (DATA / "pkg_recovery_seam_SUPERSEDED.txt").read_text(encoding="utf-8")
    print(f"\npkg_recovery_seam_SUPERSEDED.txt   {len(s.splitlines())} lines")
    check("carries the superseded 71.92%", "71.92%" in s)
    check("labels its own gate CRUDE / upper bound",
          "CRUDE gate" in s and "upper bound only" in s)
    check("ladder-weightable does NOT move (+0.00 pp)",
          re.search(r"ladder-weightable\s+56\.96%\s*->\s*56\.96%\s*\(\+0\.00 pp\)", s)
          is not None)
    check("filename itself flags the retraction",
          "SUPERSEDED" in (DATA / "pkg_recovery_seam_SUPERSEDED.txt").name)

    # the standing number lives in-tree, referenced not copied
    pp = ROOT / "scratch" / "ppfix_results.txt"
    check("scratch/ppfix_results.txt referenced in place (not copied here)",
          pp.exists() and not (DATA / "ppfix_results.txt").exists())
    t = pp.read_text(encoding="utf-8")
    for label, pat in [
        ("standing retention 57.89%", r"retained DV01, identified only : 57\.89%"),
        ("if ambiguity ignored 72.40% (NOT the standing number)",
         r"retained DV01 if ambiguity ignored: 72\.40%"),
        ("ambiguous share of PKG-4+ DV01 = 64.22", r"PKG_SIGNS_AMBIGUOUS\s+27461.*64\.22"),
        ("TOTAL ambiguous 64.219%", r"TOTAL identified 4\.138%\s+ambiguous 64\.219%"),
        ("ambiguity 61.45 at 4 legs", r"^4\s+9866\s+0\.0667\s+0\.4387\s+61\.4535"),
        ("ambiguity 97.25 at 8+ legs", r"^8\+\s+9716\s+0\.0043\s+0\.0054\s+97\.2520"),
        ("match 45.45% in the lowest margin band",
         r"margin \[\s*0\.0,\s*0\.05\)\s+n=\s*33\s+match\s+45\.45%"),
        ("match 99.17% in the highest margin band",
         r"margin \[\s*5\.0,\s*inf\)\s+n=\s*606\s+match\s+99\.17%"),
    ]:
        check(label, re.search(pat, t, re.M) is not None)

    # the control: match rate is FLAT across tie-out bands
    tie = [float(x) for x in re.findall(r"tieout \[[^)]+\)\s+n=\s*\d+\s+match\s+([\d.]+)%", t)]
    print(f"  match rate by tie-out band: {tie}")
    check("5 tie-out bands found", len(tie) == 5, str(tie))
    check("tie-out bands are FLAT (spread < 11pp) -- the margin is not redundant",
          (max(tie) - min(tie)) < 11.0, f"spread {max(tie) - min(tie):.2f} pp")
    mar = [float(x) for x in re.findall(r"margin \[[^)]+\)\s+n=\s*\d+\s+match\s+([\d.]+)%", t)]
    check("5 margin bands found", len(mar) == 5, str(mar))
    print(f"  match rate by margin band:  {mar}")
    check("margin bands are MONOTONE and span >50pp",
          mar == sorted(mar) and (max(mar) - min(mar)) > 50.0,
          f"spread {max(mar) - min(mar):.2f} pp")

    # --- the derived bucket table -------------------------------------------
    r = load("bucket_retention_DERIVED.csv")
    check("10 tenor buckets", len(r) == 10, f"got {len(r)}")
    check("source_md_line recorded on every row",
          r.source_md_line.notna().all()
          and r.source_md_line.str.contains("package-exclusion-skew.md").all())
    g01 = float(r.loc[r.bucket == "0-1Y", "retention_factor"].iloc[0])
    g20 = float(r.loc[r.bucket == "15-20Y", "retention_factor"].iloc[0])
    print(f"  retention 0-1Y {g01}  15-20Y {g20}  ratio {g01 / g20:.4f}x")
    check("retention 0-1Y == 0.761", near(g01, 0.761, 1e-12))
    check("retention 15-20Y == 0.495", near(g20, 0.495, 1e-12))
    check("distortion == 1.54x", near(g01 / g20, 1.54, 5e-3), f"{g01 / g20:.4f}")
    check("0-1Y is the max and 15-20Y the min",
          g01 == r.retention_factor.max() and g20 == r.retention_factor.min())
    implied = 1.0 - r.excl_rate_pct / 100.0
    check("retention == 1 - excl_rate/100 (relation the parse does not impose)",
          float((implied - r.retention_factor).abs().max()) <= 6e-4,
          f"max dev {float((implied - r.retention_factor).abs().max()):.6f}")
    # z-invariance is the reason levels are forbidden and z is not
    check("exclusion rate spans 26.65 pp",
          near(r.excl_rate_pct.max() - r.excl_rate_pct.min(), 26.65, 5e-3),
          f"{r.excl_rate_pct.max() - r.excl_rate_pct.min():.2f}")


# ------------------------------------------------------------------ S1 / S2 --
def verify_signals() -> None:
    banner("3. S1 / S2  (IN-TREE, commit c0b7d0f0; window S: 2024-03-01..2025-08-31)")

    out = ROOT / "BT" / "dd_signals" / "out"
    for f in ("costs.csv", "s1_results.csv", "s1_population.csv",
              "s1_oracle_ceiling.csv", "s1_plumbing.txt", "s1_validate.txt",
              "s2_results.csv", "s2_panel.parquet", "s2_panel_description.csv",
              "s2_validate.txt", "s2_z_cross_correlation.csv"):
        check(f"in-tree {f} exists and is NOT duplicated into data/",
              (out / f).exists() and not (DATA / f).exists())

    # --- S1 ------------------------------------------------------------------
    s1 = pd.read_csv(out / "s1_results.csv")
    print(f"\nBT/dd_signals/out/s1_results.csv   shape={s1.shape}")
    print(f"    columns: {list(s1.columns)}")
    q = s1[(s1.spec == "primary") & (s1.venue == "D2C")]
    print(f"  headline scope = primary x D2C: {len(q)} cells, "
          f"{q.tenor.nunique()} tenors x {q.k.nunique()} horizons")
    check("35 primary D2C cells (7 tenors x 5 horizons)",
          len(q) == 35 and q.tenor.nunique() == 7 and q.k.nunique() == 5)
    check("zero significant beta cells", int(q.beta_significant.sum()) == 0)
    check("zero significant edge cells", int(q.edge_significant.sum()) == 0)
    print(f"  max |beta_t| = {q.beta_t.abs().max():.4f}   criticals "
          f"{q.crit_beta.min():.4f}..{q.crit_beta.max():.4f}")
    check("largest |t| == 1.66", near(q.beta_t.abs().max(), 1.66, 5e-3),
          f"{q.beta_t.abs().max():.4f}")
    check("size-corrected criticals 2.51..2.63",
          near(q.crit_beta.min(), 2.51, 6e-3) and near(q.crit_beta.max(), 2.63, 6e-3),
          f"{q.crit_beta.min():.4f}..{q.crit_beta.max():.4f}")
    check("edge below the cell's own hurdle in 35 of 35",
          int((q.edge_bps_per_trade < q.kill_ceiling_bps).sum()) == 35)

    t10 = q[q.tenor == "10Y"].sort_values("k")
    edges = [round(float(x), 3) for x in t10.edge_bps_per_trade]
    hurdle = float(t10.kill_ceiling_bps.iloc[0])
    print(f"  10Y D2C edges by k: {edges}   hurdle {hurdle:.4f}")
    check("10Y D2C edges == [0.000, 0.031, 0.117, 0.045, 0.084]",
          edges == [0.0, 0.031, 0.117, 0.045, 0.084], str(edges))
    check("10Y D2C hurdle == 0.659", near(hurdle, 0.659, 5e-4), f"{hurdle:.4f}")
    check("0.659 / 0.117 == 5.6x short", near(hurdle / 0.117, 5.6, 0.05),
          f"{hurdle / 0.117:.2f}x")
    # the honesty point: 0.117 is the 10Y cell, NOT the max over 35
    mx = q.loc[q.edge_bps_per_trade.idxmax()]
    print(f"  max edge over all 35: {mx.edge_bps_per_trade:.4f} at "
          f"{mx.tenor} k={mx.k} vs hurdle {mx.kill_ceiling_bps:.4f} "
          f"({mx.kill_ceiling_bps / mx.edge_bps_per_trade:.1f}x short)")
    check("0.117 is NOT the max over the 35 cells (max is 0.174 at 20Y k=5)",
          near(mx.edge_bps_per_trade, 0.174, 5e-4) and mx.tenor == "20Y"
          and int(mx.k) == 5,
          f"{mx.edge_bps_per_trade:.4f} {mx.tenor} k={mx.k}")
    check("even the max edge is short of its own hurdle",
          mx.edge_bps_per_trade < mx.kill_ceiling_bps)
    # the sign-error columns exist and are the retracted ones
    check("s1_results carries the sign-error columns flagged in PROVENANCE 5.3",
          {"beta_sign_expected", "sign_ok", "verdict"} <= set(s1.columns))
    check("beta_sign_expected is -1 everywhere (the ERRONEOUS prereg sign)",
          set(q.beta_sign_expected.unique()) == {-1},
          str(sorted(q.beta_sign_expected.unique())))
    # the MDE column trap
    print(f"  10Y mde_bps by k: {[round(float(x), 3) for x in t10.mde_bps]}")
    check("S1_RESULT's 'MDE / hurdle 0.659' row is mde_bps, not the ratio",
          [round(float(x), 3) for x in t10.mde_bps]
          == [0.159, 0.240, 0.313, 0.395, 0.441],
          str([round(float(x), 3) for x in t10.mde_bps]))

    oc = pd.read_csv(out / "s1_oracle_ceiling.csv")
    print(f"\ns1_oracle_ceiling.csv   shape={oc.shape}")
    check("oracle ceiling parses, has oracle_edge_bps", "oracle_edge_bps" in oc.columns)
    pop = pd.read_csv(out / "s1_population.csv")
    print(f"s1_population.csv   shape={pop.shape}")
    check("s1_population parses", len(pop) == 14, f"got {len(pop)}")

    # --- S2 ------------------------------------------------------------------
    s2 = pd.read_csv(out / "s2_results.csv")
    print(f"\nBT/dd_signals/out/s2_results.csv   shape={s2.shape}")
    print(f"    columns: {list(s2.columns)[:12]} ...")
    p = s2[s2.cell == "POOLED_UNCONDITIONAL"].iloc[0]
    print(f"  pooled: beta_z={p.beta_z:+.4f}  t_dk={p.t_z_dk:+.4f}  "
          f"edge={p.edge_bps:+.4f} bp  n_obs={p.n_obs}  n_days={p.n_days}  "
          f"verdict={p.verdict}")
    check("S2 pooled beta == +0.024", near(p.beta_z, 0.024, 5e-4), f"{p.beta_z:.5f}")
    check("S2 pooled t == +0.04", near(p.t_z_dk, 0.04, 5e-3), f"{p.t_z_dk:.5f}")
    check("S2 pooled edge == -0.32 bp", near(p.edge_bps, -0.32, 5e-3),
          f"{p.edge_bps:.5f}")
    check("S2 pooled edge is NEGATIVE (clears no cost of any size)", p.edge_bps < 0)
    check("S2 pooled verdict UNINFORMATIVE_COST", p.verdict == "UNINFORMATIVE_COST")

    bk = s2[s2.cell.str.startswith("BUCKET::")]
    vc = bk.verdict.value_counts().to_dict()
    print(f"  pre-registered per-bucket cells: {len(bk)}   verdicts {vc}")
    check("9 pre-registered bucket cells", len(bk) == 9, f"got {len(bk)}")
    check("8 of 9 UNINFORMATIVE_POWER",
          vc.get("UNINFORMATIVE_POWER") == 8, str(vc))
    check("no bucket cell is a PASS/DEAD",
          set(bk.verdict) <= {"UNINFORMATIVE_POWER", "UNINFORMATIVE_COST"}, str(vc))
    check("no S2 cell anywhere is a PASS",
          not s2.verdict.str.contains("PASS").any(),
          str(s2.verdict.unique().tolist()))

    pl = s2[s2.cell == "PLACEBO_FLOW_LEADS_RETURN"].iloc[0]
    print(f"  placebo (flow shifted FORWARD 5 sessions): beta={pl.beta_z:.3f} "
          f"t={pl.t_z_dk:.3f} edge={pl.edge_bps:.3f}  verdict={pl.verdict}")
    check("placebo fires at t == -5.19 and is labelled DIAGNOSTIC",
          near(pl.t_z_dk, -5.19, 5e-3) and pl.verdict == "DIAGNOSTIC",
          f"t={pl.t_z_dk:.4f}")

    # the withdrawn 'powered null': the uncorrected MDE columns are present
    print(f"  pooled mde_edge = {p.mde_edge_bps:.4f} bp vs kill "
          f"{p.kill_threshold_bps:.4f} bp")
    check("uncorrected pooled MDE 1.847 < kill 2.154 (the WITHDRAWN 'powered' claim)",
          near(p.mde_edge_bps, 1.847, 5e-3) and near(p.kill_threshold_bps, 2.154, 5e-3),
          f"{p.mde_edge_bps:.4f} vs {p.kill_threshold_bps:.4f}")
    check("size-corrected MDE 2.239 would exceed the kill threshold",
          2.239 > float(p.kill_threshold_bps))

    v2 = (out / "s2_validate.txt").read_text(encoding="utf-8")
    check("s2_validate records DK rejecting a true null at 7.8% vs nominal 5%",
          "7.8%" in v2)

    panel = pd.read_parquet(out / "s2_panel.parquet")
    print(f"\ns2_panel.parquet   shape={panel.shape}  (the notebook MAY recompute "
          f"from this)")
    check("s2_panel parses", len(panel) > 0)

    c = pd.read_csv(out / "costs.csv")
    print(f"costs.csv   shape={c.shape}")
    check("costs.csv parses and carries the S1 and S2 hurdles",
          {"round_trip_used_bps", "kill_threshold_used_bps", "bucket"} <= set(c.columns)
          and c.instrument.str.startswith("S1").any())


# ------------------------------------------------------------------- docs ----
def verify_retractions() -> None:
    banner("4. Retraction register cross-references resolve")

    docs = ROOT / "docs" / "dealer_direction"
    cites = [
        (docs / "signals" / "S_PREREG.md", 129, "79.12"),
        (docs / "INDICATOR.md", 528, "79.12"),
        (docs / "2026-08-11-package-exclusion-skew.md", 24, "79.12"),
        (docs / "2026-08-11-package-exclusion-skew.md", 415, "79.12"),
    ]
    for path, line, tok in cites:
        lines = path.read_text(encoding="utf-8").splitlines()
        ok = tok in lines[line - 1]
        check(f"{path.name}:{line} carries {tok}", ok,
              "" if ok else lines[line - 1][:70])

    for path in (docs / "INDICATOR.md", docs / "2026-08-11-package-exclusion-skew.md"):
        txt = path.read_text(encoding="utf-8")
        check(f"{path.name} carries a SUPERSEDED block naming 57.89%",
              "SUPERSEDED 2026-08-11 by measurement" in txt and "57.89%" in txt)
    sp = (docs / "signals" / "S_PREREG.md").read_text(encoding="utf-8")
    check("S_PREREG.md is NOT annotated (it is the pre-registration)",
          "SUPERSEDED" not in sp)

    dev = (docs / "signals" / "S_DEVIATIONS.md").read_text(encoding="utf-8")
    check("S_DEVIATIONS D1 records the S1 sign error",
          "THE PRE-REGISTRATION CONTAINS A SIGN ERROR IN S1" in dev)
    check("D1 records the 11-of-35 convention dependence",
          "11\n  of 35 cells" in dev or "11 of 35" in dev.replace("\n  ", " "))
    check("S_DEVIATIONS D2 withdraws the 'powered null'",
          "not as a powered null" in dev and "That claim is withdrawn" in dev)

    # PROVENANCE itself must name every file in data/
    prov = (DATA / "PROVENANCE.md").read_text(encoding="utf-8")
    missing = [p.name for p in sorted(DATA.iterdir())
               if p.name != "PROVENANCE.md" and p.name not in prov]
    check("PROVENANCE.md names every file in data/", not missing, str(missing))
    for tok in ("79.12", "71.92", "72.40", "57.89", "sign error",
                "powered null", "RETRACTED", "SUPERSEDED", "WITHDRAWN"):
        check(f"PROVENANCE.md carries {tok!r}", tok in prov)


def main() -> int:
    print(f"data dir: {DATA}")
    files = sorted(p for p in DATA.iterdir() if p.is_file())
    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} files, {total / 1024 / 1024:.2f} MB total\n")
    for p in files:
        print(f"  {p.stat().st_size:>9,}  {p.name}")

    for fn in (verify_r0, verify_universe, verify_signals, verify_retractions):
        try:
            fn()
        except Exception:
            traceback.print_exc()
            FAILS.append(f"EXCEPTION in {fn.__name__}")

    banner(f"RESULT: {NCHECK - len(FAILS)}/{NCHECK} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  FAIL  {f}")
        return 1
    print("  all assertions passed")
    print(f"  data/ total {total / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
