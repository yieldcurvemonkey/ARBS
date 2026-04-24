import pandas as pd

df = pd.read_parquet(
    "C:/Users/chris/clee/ARBS/sdr_cache/classification_cache/"
    "usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
    "curve1_fly1_mms1_invoice1_mac1_spreadover1/2026/04/2026-04-23/4355.parquet"
)

subset = df[
    df["trade_id"].astype(str).isin(
        {"2844466371000000101", "2844466372000000201"}
    )
]
print("Available cols (UPI/product):")
for c in df.columns:
    if "upi" in c.lower() or "product" in c.lower() or "identifier" in c.lower():
        print("  ", c)

print()
print("Subset values for key fields:")
fields = [
    "trade_id", "execution_timestamp", "effective_date", "expiration_date",
    "tenor_years", "tenor_label", "fixed_rate", "forward_label",
    "package_type", "package_id", "package_legs",
    "Unique Product Identifier", "UPI Underlier Name",
    "Platform identifier", "Cleared", "rate_index", "notional_currency",
    "estimated_pv01",
]
present = [f for f in fields if f in subset.columns]
print(subset[present].to_string(index=False))
