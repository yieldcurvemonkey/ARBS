import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
print("step 1: paths set")
import _usd_swaps_common as sdr
print("step 2: sdr imported")
from SDRUtils.analytics.seasonality import add_event_classifications, analyze_seasonality_by_event, get_fomc_dates, get_imm_dates, get_month_end_dates, get_quarter_end_dates
print("step 3: seasonality imported")
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
print("step 4: central bank dates imported")
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
print("step 5: IRSwapsMDP imported")
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
print("step 6: IRSwapQuery imported")
print("ALL IMPORTS OK")
