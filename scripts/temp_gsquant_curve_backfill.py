from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from BT.misc import ql_cal_date_range

import datetime 
import QuantLib as ql

if __name__ == "__main__":
    curve_mdp = IRSwapsMDP(source="GSQUANT_RL")

    dates = ql_cal_date_range(ql.UnitedStates(ql.UnitedStates.GovernmentBond), start=datetime.date(2026, 3, 30), end=datetime.date(2026, 4, 10), to_date=True)
    errors = []
    for d in dates:
        try:
            print(curve_mdp._get_curve(curve_name="USD-OIS", timestamp=d))
        except Exception as e:
            errors.append((d, str(e)))

    print(errors)