"""Mechanically extract the per-tenor-bucket retention table from the markdown
source of record, so the notebook plots parsed numbers rather than hand-typed ones.

SOURCE (single source of truth, committed in-tree):
    docs/dealer_direction/2026-08-11-package-exclusion-skew.md
      - the DV01-by-bucket table  (header row starts "| bucket | tape DV01 |")
      - the "retention factor" row and the "vs. the best bucket" row

OUTPUT:
    notebooks/dealer_direction/data/bucket_retention_DERIVED.csv

The extraction is checked against a relation that must hold if the parse is
right and that no step of the parse imposes:
    retention_factor == 1 - excl_rate_pct/100     (to the doc's 3 d.p. rounding)
That is a known answer independent of the transcription, so a mis-aligned
column or a dropped bucket fails it.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pandas as pd

ROOT = pathlib.Path(r"C:\Users\chris\clee\ARBS-dd")
SRC = ROOT / "docs" / "dealer_direction" / "2026-08-11-package-exclusion-skew.md"
DST = ROOT / "notebooks" / "dealer_direction" / "data" / "bucket_retention_DERIVED.csv"

BUCKETS = [
    "0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y",
    "7-10Y", "10-15Y", "15-20Y", "20-30Y", "30Y+",
]


def _cells(line: str) -> list[str]:
    parts = [c.strip() for c in line.strip().strip("|").split("|")]
    return parts


def _num(tok: str) -> float:
    """Strip markdown bold, unicode minus, thousands, 'bn'/'%' and parse."""
    t = tok.replace("*", "").replace("\u2212", "-").replace("\u2013", "-")
    t = t.replace("bn", "").replace("%", "").replace(",", "").strip()
    if t in ("", "-", "\u2014"):
        return float("nan")
    return float(t)


def main() -> int:
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines()

    # ---- table 1: the DV01-by-bucket table -------------------------------
    hdr_i = None
    for i, ln in enumerate(lines):
        if ln.startswith("| bucket | tape DV01 |"):
            hdr_i = i
            break
    if hdr_i is None:
        print("FAIL: DV01-by-bucket header not found", file=sys.stderr)
        return 1
    header_src_line = hdr_i + 1  # 1-indexed, for provenance

    rows = {}
    for ln in lines[hdr_i + 2:]:          # +2 skips the |---| separator
        if not ln.startswith("|"):
            break
        c = _cells(ln)
        b = c[0].replace("*", "").strip()
        if b not in BUCKETS:
            print(f"FAIL: unexpected bucket label {b!r}", file=sys.stderr)
            return 1
        rows[b] = dict(
            tape_dv01_bn=_num(c[1]),
            tape_share_pct=_num(c[2]),
            retained_share_pct=_num(c[3]),
            delta_pp=_num(c[4]),
            delta_relative_pct=_num(c[5]),
            excl_rate_pct=_num(c[6]),
            excl_of_which_pkg4plus_pct=_num(c[7]),
            excl_of_which_asset_swap_pct=_num(c[8]),
        )

    # ---- table 2: the retention-factor row -------------------------------
    ret_i = vsb_i = None
    for i, ln in enumerate(lines):
        if ln.startswith("| **retention factor**"):
            ret_i = i
        elif ln.startswith("| vs. the best bucket"):
            vsb_i = i
    if ret_i is None or vsb_i is None:
        print("FAIL: retention-factor rows not found", file=sys.stderr)
        return 1
    ret_src_line, vsb_src_line = ret_i + 1, vsb_i + 1

    # the bucket order of that block comes from its own header, not assumed
    for j in range(ret_i - 1, -1, -1):
        if lines[j].startswith("| bucket |"):
            order = [c.replace("*", "").strip() for c in _cells(lines[j])[1:]]
            break
    else:
        print("FAIL: header for the retention-factor block not found", file=sys.stderr)
        return 1
    if order != BUCKETS:
        print(f"FAIL: retention block bucket order {order}", file=sys.stderr)
        return 1

    ret_vals = [_num(c) for c in _cells(lines[ret_i])[1:]]
    vsb_vals = [_num(c) for c in _cells(lines[vsb_i])[1:]]
    for b, r, v in zip(order, ret_vals, vsb_vals):
        rows[b]["retention_factor"] = r
        rows[b]["vs_best_bucket"] = v

    df = pd.DataFrame([{"bucket": b, **rows[b]} for b in BUCKETS])

    # ---- known-answer checks ---------------------------------------------
    if len(df) != 10:
        print(f"FAIL: {len(df)} buckets, expected 10", file=sys.stderr)
        return 1

    implied = 1.0 - df["excl_rate_pct"] / 100.0
    worst = (implied - df["retention_factor"]).abs().max()
    print("check A  retention_factor == 1 - excl_rate/100")
    for b, i_, r_ in zip(df["bucket"], implied, df["retention_factor"]):
        print(f"   {b:>7}  implied {i_:.4f}  doc {r_:.3f}  d={abs(i_ - r_):.5f}")
    if worst > 0.0006:                    # doc rounds the factor to 3 d.p.
        print(f"FAIL: max |implied - doc| = {worst:.6f}", file=sys.stderr)
        return 1
    print(f"   PASS max deviation {worst:.6f} <= 0.0006 (3 d.p. rounding)")

    best = df["retention_factor"].max()
    worst_v = (df["retention_factor"] / best - df["vs_best_bucket"]).abs().max()
    print(f"check B  vs_best_bucket == retention/{best:.3f}: "
          f"max dev {worst_v:.4f}")
    if worst_v > 0.006:
        print(f"FAIL: vs_best_bucket inconsistent ({worst_v:.6f})", file=sys.stderr)
        return 1
    print("   PASS")

    # composition: retained_share must be the retention-weighted tape share
    w = df["tape_share_pct"] * df["retention_factor"]
    recon = 100.0 * w / w.sum()
    worst_c = (recon - df["retained_share_pct"]).abs().max()
    print("check C  retained_share == renormalised tape_share x retention")
    for b, r_, d_ in zip(df["bucket"], recon, df["retained_share_pct"]):
        print(f"   {b:>7}  recon {r_:6.2f}  doc {d_:6.2f}  d={abs(r_ - d_):.3f}")
    if worst_c > 0.06:
        print(f"FAIL: composition reconciliation off by {worst_c:.4f} pp",
              file=sys.stderr)
        return 1
    print(f"   PASS max deviation {worst_c:.4f} pp")

    # headline claims the notebook will quote
    r01 = float(df.loc[df.bucket == "0-1Y", "retention_factor"].iloc[0])
    r1520 = float(df.loc[df.bucket == "15-20Y", "retention_factor"].iloc[0])
    print(f"check D  0-1Y {r01} / 15-20Y {r1520} -> ratio {r01 / r1520:.3f}x")
    assert (r01, r1520) == (0.761, 0.495), (r01, r1520)
    assert abs(r01 / r1520 - 1.54) < 0.005, r01 / r1520
    print("   PASS  matches the documented 0.761 / 0.495 / 1.54x")

    df.insert(0, "source_md_line", "")
    df["source_md_line"] = (
        f"{SRC.name}:{header_src_line} (cols 2-9), "
        f":{ret_src_line} (retention_factor), :{vsb_src_line} (vs_best_bucket)"
    )
    DST.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(DST, index=False)
    print(f"\nwrote {DST}  shape={df.shape}")

    back = pd.read_csv(DST)
    assert back.shape == df.shape, (back.shape, df.shape)
    assert abs(float(back.loc[back.bucket == "0-1Y", "retention_factor"].iloc[0]) - 0.761) < 1e-12
    print("re-parse OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
