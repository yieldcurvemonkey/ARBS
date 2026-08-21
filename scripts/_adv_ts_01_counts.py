"""Adversarial pass 1: reconcile the report's counts and dissect deletion-orth."""
from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import etf_tsgrid_lib as L

DATA = L.DATA
g = pd.read_csv(DATA / "tsgrid_grid.csv")
real = g[g.kind == "real"]
noctrl = real[real.signal != "resid"]
plac = g[g.kind == "placebo"]
print("real %d  real-minus-control %d  placebo %d" % (len(real), len(noctrl), len(plac)))
print("gross>0: real-minus-control %d/%d = %.4f" %
      ((noctrl.gross_bp > 0).sum(), len(noctrl), (noctrl.gross_bp > 0).mean()))
print("gross>0: placebo %d/%d = %.4f" % ((plac.gross_bp > 0).sum(), len(plac), (plac.gross_bp > 0).mean()))
print("gross>0: holdings only %d/%d = %.4f" % (
    (real[real.signal.isin(L.HOLDINGS_SIGNALS)].gross_bp > 0).sum(),
    len(real[real.signal.isin(L.HOLDINGS_SIGNALS)]),
    (real[real.signal.isin(L.HOLDINGS_SIGNALS)].gross_bp > 0).mean()))
print("gross>0: control %d/%d" % ((real[real.signal == 'resid'].gross_bp > 0).sum(), 960))

# duplicate (lag-inert) cells
key = ["signal", "orth", "mark", "entry", "hold", "exit"]
dup = g.groupby(key)["gross_bp"].nunique()
print("\ncoordinate groups with identical gross across lag:", int((dup == 1).sum()), "of", len(dup))
per_sig = g.groupby(["signal"] + key[1:])["gross_bp"].nunique().reset_index()
print(per_sig.groupby("signal")["gross_bp"].apply(lambda s: (s == 1).sum()).to_string())

# n_dates distribution per signal -- how many cells rest on a tiny sample
print("\nn_dates by signal (min / median / max):")
print(g.groupby("signal")["n_dates"].agg(["min", "median", "max", "count"]).to_string())

print("\ncells with n_dates < 200, by signal:")
print(g[g.n_dates < 200].groupby(["signal", "orth"]).size().to_string())
