import sys, datetime as dt
sys.path.insert(0, '.')
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
# Check the specific contracts/dates the notebook uses for delta queries
contracts = ["SFRZ26", "SFRH27"]
test_dates = [
    dt.date(2025, 6, 24), dt.date(2025, 9, 1), dt.date(2025, 9, 17),
    dt.date(2025, 9, 26), dt.date(2026, 3, 9), dt.date(2026, 3, 19),
    dt.date(2026, 4, 3), dt.date(2026, 5, 26), dt.date(2026, 6, 2),
]
with mdp:
    for c in contracts:
        missing = []
        for d in test_dates:
            key = mdp._build_get_data_cache_key("sabr_smile", {
                "endpoint": "sabr_smile", "symbol": c, "as_of": d,
            })
            if key and mdp._threadsafe_cache_get(key) is None:
                missing.append(d.isoformat())
        status = f"{len(missing)} missing" if missing else "all cached"
        print(f"{c}: {status}  {missing[:5]}")
