"""Prove the warmed cache is readable with NO Excel: the state the other agents need.

An offline reader is the contract. ``CitiVeloQuotes(offline=True)`` refuses to
construct a client, so anything this returns came off disk - if it raises, the
cache is not actually serving the request and the warm did not land where a
reader looks for it.

Also builds the 15:00 / 16:00 seam frame the downstream study wants, as a
worked example rather than a claim.
"""

import datetime
import pathlib
import sys

import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402

uni = pd.read_csv(DATA / "intraday_universe.csv")
isins = list(uni["isin"].astype(str))

q = CitiVeloQuotes(offline=True)
tags = [f"RATES.BOND.{i}.YIELD" for i in isins]
frame = q.frame(tags, "HOURLY",
                start=datetime.datetime(2026, 7, 1), end=datetime.datetime(2026, 8, 20))
print(f"OFFLINE HOURLY read: {frame.shape[0]} rows x {frame.shape[1]} tags, "
      f"{frame.index.min()} .. {frame.index.max()}")

# The seam, as a worked frame: one row per (date, bond) with both marks.
idx = pd.Series(frame.index)
at15 = frame[(idx.dt.hour == 15).to_numpy()]
at16 = frame[(idx.dt.hour == 16).to_numpy()]
at15.index = pd.Series(at15.index).dt.date
at16.index = pd.Series(at16.index).dt.date
common = at15.index.intersection(at16.index)
seam = (at16.loc[common] - at15.loc[common]) * 100.0   # bp
seam = seam.dropna(axis=1, how="all")
print(f"\nSEAM frame (16:00 minus 15:00, bp): {seam.shape[0]} dates x {seam.shape[1]} bonds")
print("cross-sectional stdev of the 15->16 move, bp, per date (last 8):")
print(seam.std(axis=1).tail(8).round(3).to_string())
print(f"\npooled mean |15->16 move| = {seam.abs().stack().mean():.3f} bp, "
      f"stdev = {seam.stack().std():.3f} bp, n = {seam.stack().size:,}")

seam.to_csv(DATA / "intraday_seam_1500_1600_sample.csv")
print("wrote", DATA / "intraday_seam_1500_1600_sample.csv")

mi = q.frame([f"RATES.BOND.{isins[0]}.YIELD"], "MI01")
print(f"\nOFFLINE MI01 read for {isins[0]}: {len(mi)} rows"
      + (f", {mi.index.min()} .. {mi.index.max()}" if len(mi) else " (nothing cached yet)"))
