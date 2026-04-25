import pandas as pd

df = pd.read_parquet(
    "C:/Users/chris/clee/ARBS/sdr_cache/classification_cache/"
    "usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
    "curve1_fly1_mms1_invoice1_mac1_spreadover1/2026/04/2026-04-23/4355.parquet"
)

ids = {
    "2844459942000000501",
    "2844466371000000101",  # orphan 10Y
    "2844466372000000201",  # 20Y paired with the first one
}
subset = df[df["trade_id"].astype(str).isin(ids)].copy()
print(subset[[
    "trade_id", "execution_timestamp", "tenor_label", "forward_label",
    "effective_date", "fixed_rate", "estimated_pv01", "package_type",
    "package_id", "platform_identifier",
    "unique_product_identifier",
]].to_string(index=False))
