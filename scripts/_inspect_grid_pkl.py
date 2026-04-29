"""Inspect the closed positions log from the cached_only grid run."""
import pickle, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

p = Path("data/screener_results/sfr_convex_screener_backtest_grid/f_daily_rebalance/backtest.pkl")
with p.open("rb") as fh:
    data = pickle.load(fh)
print(data["summary"])
print("---trades_df---")
import pandas as pd
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
print(data["trades_df"])
