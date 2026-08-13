import pandas as pd
from SDRUtils.dealer_direction import health
IN = "method=asof max_lag=60s allow_future=False on_miss=raise"
HOLE = "method=asof max_lag=7200s allow_future=False on_miss=raise"
prov = pd.DataFrame({
    "unit_key": list("ABCDE"),
    "snapshot_policy": [IN, IN, IN, HOLE, IN],
    "snapshot_lag_seconds": [5.0, 300.0, None, 4000.0, 61.0],
})
for m in health.snapshot_lag_metrics(prov):
    print(f"{m.name:34s} value={m.value!r:12s} status={m.status}")
print(health.snapshot_lag_distribution(prov).to_string(index=False))
