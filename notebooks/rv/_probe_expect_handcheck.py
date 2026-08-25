"""Independent hand-check of the two numbers the study leans on.

Neither of these uses the study's own book-building code. The point is that a
checking tool written by the same hand as the thing it checks will agree with it
whether or not either is right, so both figures are re-derived from the raw
settle panel with plain pandas.
"""
from __future__ import annotations

import io
import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fed_detachment_prices as PX  # noqa: E402
import fed_expected_sentiment as E  # noqa: E402

PX.seed_local_cache()
syms = PX.sr3_universe(pd.Timestamp("2018-01-01").date(),
                       pd.Timestamp("2026-08-24").date(), max_rank=4)
panel = PX.settle_panel(syms)
sessions = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")
weeks = pd.date_range("2018-05-11", "2026-08-21", freq="W-FRI")

print("=" * 74)
print("CHECK 1: the roll fabrication, re-derived with plain pandas")
print("=" * 74)
rows = []
for w in weeks:
    i = int(np.searchsorted(sessions, np.datetime64(w), side="right"))
    if i >= len(sessions):
        continue
    e = pd.Timestamp(sessions[i])
    rows.append({"week": w, "entry": e, "sym": PX.rank_symbol(e.date(), 3)})
df = pd.DataFrame(rows).set_index("week")
df["px"] = [panel.at[r.entry, r.sym] if r.sym in panel.columns
            and r.entry in panel.index else np.nan for r in df.itertuples()]
df["prev_entry"] = df["entry"].shift(1)
df["prev_sym"] = df["sym"].shift(1)
df["rolled"] = df["sym"] != df["prev_sym"]
df.loc[df.index[0], "rolled"] = False

# TWO single-contract comparators, because over the interval
# [entry_{i-1}, entry_i] the book HELD the outgoing contract while the incoming
# one is what it is about to hold. They differ on a roll week by definition, and
# a fabrication number that only holds for one of them is not a measurement.
def _px(sym, when):
    try:
        v = panel.at[pd.Timestamp(when), sym]
    except KeyError:
        return np.nan
    return float(v) if pd.notna(v) else np.nan


naive, held, incoming = [], [], []
for i, r in enumerate(df.itertuples()):
    if pd.isna(r.prev_entry) or pd.isna(r.px) or r.prev_sym is None:
        naive.append(np.nan); held.append(np.nan); incoming.append(np.nan); continue
    prev_px = df.loc[df["entry"] == r.prev_entry, "px"]
    naive.append((r.px - float(prev_px.iloc[0])) / 0.01 if len(prev_px) else np.nan)
    a_h, b_h = _px(r.prev_sym, r.prev_entry), _px(r.prev_sym, r.entry)
    a_i, b_i = _px(r.sym, r.prev_entry), _px(r.sym, r.entry)
    held.append((b_h - a_h) / 0.01 if np.isfinite(a_h) and np.isfinite(b_h) else np.nan)
    incoming.append((b_i - a_i) / 0.01 if np.isfinite(a_i) and np.isfinite(b_i) else np.nan)
df["naive_bp"], df["held_bp"], df["incoming_bp"] = naive, held, incoming
ok = df.dropna(subset=["naive_bp"])
roll = ok[ok["rolled"]]
flat = ok[~ok["rolled"]]
fab_h = (roll["naive_bp"] - roll["held_bp"]).dropna()
fab_i = (roll["naive_bp"] - roll["incoming_bp"]).dropna()
print(f"  weeks {len(ok)}, roll weeks {len(roll)}")
print(f"  naive roll mean  {roll['naive_bp'].mean():+.4f}bp   flat mean {flat['naive_bp'].mean():+.4f}bp")
print(f"  held  roll mean  {roll['held_bp'].mean():+.4f}bp   (the contract actually held)")
print(f"  incoming roll mean {roll['incoming_bp'].mean():+.4f}bp   (the one about to be held)")
print(f"  fabricated vs HELD:     mean {fab_h.mean():+.4f}bp  total {fab_h.sum():+.4f}bp")
print(f"  fabricated vs INCOMING: mean {fab_i.mean():+.4f}bp  total {fab_i.sum():+.4f}bp")
print(f"  disagreement on FLAT weeks: "
      f"{float((flat['naive_bp'] - flat['held_bp']).abs().max()):.3e}bp (held), "
      f"{float((flat['naive_bp'] - flat['incoming_bp']).abs().max()):.3e}bp (incoming)")

mod = E.roll_placebo(panel, weeks, sessions, rank=3)
print("\n  study's own roll_placebo, for comparison:")
print(f"     roll weeks {mod['roll_weeks']}  naive roll mean {mod['naive_roll_mean_bp']:+.4f}bp")
print(f"     held roll mean {mod['held_roll_mean_bp']:+.4f}bp  "
      f"incoming roll mean {mod['incoming_roll_mean_bp']:+.4f}bp")
print(f"     fabricated vs HELD     mean {mod['fabricated_mean_bp']:+.4f}bp  "
      f"total {mod['fabricated_total_bp']:+.4f}bp")
print(f"     fabricated vs INCOMING mean {mod['fabricated_mean_vs_incoming_bp']:+.4f}bp  "
      f"total {mod['fabricated_total_vs_incoming_bp']:+.4f}bp")
agree = (abs(mod["fabricated_total_bp"] - float(fab_h.sum())) < 1e-6
         and abs(mod["fabricated_mean_bp"] - float(fab_h.mean())) < 1e-9
         and abs(mod["fabricated_total_vs_incoming_bp"] - float(fab_i.sum())) < 1e-6
         and abs(mod["fabricated_mean_vs_incoming_bp"] - float(fab_i.mean())) < 1e-9)
print(f"\n  INDEPENDENT DERIVATION AGREES ON BOTH COMPARATORS: {agree}")
assert agree, "the independent derivation disagrees with roll_placebo"

print("\n" + "=" * 74)
print("CHECK 2: the pre-registered trade book, three trades priced by hand")
print("=" * 74)
zc, _ = E.load_composite()
cfg = E.PRIMARY
s = E.build_signal(zc, cfg)
s = s[(s.index >= pd.Timestamp("2018-05-11")) & (s.index <= pd.Timestamp("2026-08-21"))]
trades = E.schedule_trades(s, cfg, sessions)
book, _r = E.price_trades(trades, panel, cfg)
print(f"  study book: {len(book)} trades, total {book['pnl_bp'].sum():+.4f}bp, "
      f"avg {book['pnl_bp'].mean():+.4f}bp")

worst = 0.0
for k in (0, len(book) // 2, len(book) - 1):
    r = book.iloc[k]
    sym = r["symbols"]
    pe = float(panel.at[pd.Timestamp(r["entry_date"]), sym])
    px = float(panel.at[pd.Timestamp(r["exit_date"]), sym])
    hand = r["side"] * (px - pe) / 0.01 - 0.50
    worst = max(worst, abs(hand - float(r["pnl_bp"])))
    print(f"    {str(pd.Timestamp(r['signal_date']).date())}  {sym}  "
          f"side {int(r['side']):+d}  {pe:.4f} -> {px:.4f}  "
          f"hand {hand:+.4f}bp  book {float(r['pnl_bp']):+.4f}bp")
print(f"\n  worst hand-vs-book difference: {worst:.3e}bp")

# and the whole book, vectorised, from the panel
hand_all = []
for r in book.itertuples():
    pe = float(panel.at[pd.Timestamp(r.entry_date), r.symbols])
    px = float(panel.at[pd.Timestamp(r.exit_date), r.symbols])
    hand_all.append(r.side * (px - pe) / 0.01 - 0.50)
hand_all = np.asarray(hand_all)
print(f"  whole book re-priced by hand: total {hand_all.sum():+.4f}bp   "
      f"worst diff {np.abs(hand_all - book['pnl_bp'].to_numpy(float)).max():.3e}bp")

print("\n" + "=" * 74)
print("CHECK 3: every trade's two marks come from ONE contract")
print("=" * 74)
n_cross = 0
for r in book.itertuples():
    e_sym = PX.rank_symbol(pd.Timestamp(r.entry_date).date(), 3)
    x_sym = PX.rank_symbol(pd.Timestamp(r.exit_date).date(), 3)
    if e_sym != r.symbols:
        n_cross += 1
    # the rank MAY have rolled during the hold; what matters is that the book
    # used the ENTRY contract at both ends, which is what r.symbols says
print(f"  trades whose booked symbol is not the rank-3 contract at ENTRY: {n_cross}")
rolled_during = sum(1 for r in book.itertuples()
                    if PX.rank_symbol(pd.Timestamp(r.exit_date).date(), 3) != r.symbols)
print(f"  trades during which the RANK rolled away from the held contract: "
      f"{rolled_during} of {len(book)}")
print("  (those are exactly the trades a rank-diff construction would have")
print("   mispriced, and this book prices them on the contract it opened.)")
