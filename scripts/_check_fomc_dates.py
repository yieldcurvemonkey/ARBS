"""Quick check of FOMC dates near regime shifts."""
from SDRUtils.analytics.fomc import load_fomc_schedule
import datetime
import pandas as pd

sched = load_fomc_schedule('USD-SOFR-1D')
sched['effective_date'] = pd.to_datetime(sched['effective_date']).dt.date

print('Mar 2023 area:')
mask = (sched['effective_date'] >= datetime.date(2023, 1, 1)) & (sched['effective_date'] <= datetime.date(2023, 12, 31))
print(sched.loc[mask, ['meeting_label', 'effective_date']].to_string(index=False))

print()
print('Sep 2024 area:')
mask = (sched['effective_date'] >= datetime.date(2024, 6, 1)) & (sched['effective_date'] <= datetime.date(2025, 6, 30))
print(sched.loc[mask, ['meeting_label', 'effective_date']].to_string(index=False))
