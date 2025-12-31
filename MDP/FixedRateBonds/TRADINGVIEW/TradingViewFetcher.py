import pandas as pd 
import datetime
from tvDatafeed import TvDatafeed, Interval


def fetch_cusip_history_timeseries(cusip: str, start: datetime.date, end: datetime.date, val_to_return="close") -> pd.Series:
    tv = TvDatafeed()
    df = tv.get_hist(symbol=cusip, exchange="OTCB", interval=Interval.in_daily, n_bars=10000)
    ts: pd.Series = df[(df.index.date >= start) & (df.index.date <= end)][val_to_return]

    if end == datetime.date.today():
        live = tv.get_hist(symbol=cusip, exchange="OTCB", interval=Interval.in_1_minute, n_bars=1)
        return pd.concat([ts, live[val_to_return]])

    return ts