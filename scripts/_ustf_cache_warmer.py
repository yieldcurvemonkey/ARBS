import datetime, logging, sys, os
os.chdir(r\"C:\Users\chris\clee\ARBS\")
sys.path.insert(0, r\"C:\Users\chris\clee\ARBS\")
logging.basicConfig(level=logging.INFO, format=\"%(asctime)s [%(levelname)s] %(message)s\")
log = logging.getLogger(\"ustf-warmer\")
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from MDP.USTFutures.treasury_conversion_factors import resolve_delivery_contract
from TB.USTFuturesTB import USTFuturesTB
from TB.TimeseriesBuilder import TimeseriesBuilder
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureValue import USTFutureValue
today = datetime.date.today()
start = today - datetime.timedelta(days=7)
roots = [\"TU\", \"FV\", \"TY\", \"UXY\", \"US\", \"WN\"]
symbols = []
for root in roots:
    try:
        _, imm_date, _ = resolve_delivery_contract(root, today)
        mc = {3:\"H\",6:\"M\",9:\"U\",12:\"Z\"}[imm_date.month]
        symbols.append(f\"{root}{mc}{imm_date.year%100:02d}\")
    except Exception as e:
        log.warning(\"Failed to resolve %s: %s\", root, e)
mdp = USTFuturesMDP(source=\"BARCHART_USTF-RL\")
tb = TimeseriesBuilder(ustfutures_tb=USTFuturesTB(mdp, show_tqdm=True))
queries = [USTFutureQuery(symbol=s, value=USTFutureValue.PRICE) for s in symbols]
log.info(\"Warming: %s to %s, %s\", start, today, symbols)
df = tb.get_timeseries(start=start, end=today, queries=queries, n_jobs=1)
log.info(\"Done: %s\", df.shape)
