"""Run the pre-registered primary book through the engine and tie it out."""
import pathlib
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fed_detachment_data as D
import fed_detachment_engine as E
import fed_detachment_grid as G
import fed_detachment_prices as PX

pd.set_option("display.width", 220)
cfg = D.PRIMARY
zc, zs, _ = D.load_sides(cfg)
bank = G.build_signal_bank(zc, zs, cfg)
sup = G.common_support(bank)
syms = PX.sr3_universe(sup.min().date(), sup.max().date() + pd.Timedelta(weeks=12), 4)
panel = PX.settle_panel(syms)
sessions = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")
d = bank[(cfg.construction, cfg.lead_k)].reindex(sup)
trades = D.schedule(d, cfg, sessions)
book, reasons = D.price_book(trades, panel, cfg)
print("book:", len(book), reasons)

mdp = E.open_mdp()
print("\nG-E2 direction check on a known trade:")
row = book.iloc[0]
print(E.gate_direction(panel, row["symbols"], row["entry_date"], row["exit_date"], mdp=mdp))

rep = E.replay(book, panel, mdp=mdp, show_progress=False)
print(f"\nengine closed {len(rep)} positions, warmed {rep.attrs.get('warmed')} cache entries")
tie = E.tie_out(book, rep)
print(tie.to_string(index=False))
print("\nG-E1:", E.gate_engine_tie_out(tie))
