"""
Filters are used to filter events based on some kind of trigger. For example a structural break filter can be
used to filter events where a structural break occurs. This event is then used to measure the return from the event
to some event horizon, say a day.
"""

import numpy as np
import pandas as pd


# Snippet 2.4, page 39, The Symmetric CUSUM Filter.
def cusum_filter(raw_time_series, threshold, time_stamps=True):
    """
    Advances in Financial Machine Learning, Snippet 2.4, page 39.

    The Symmetric Dynamic/Fixed CUSUM Filter.

    The CUSUM filter is a quality-control method, designed to detect a shift in the mean value of a measured quantity
    away from a target value. The filter is set up to identify a sequence of upside or downside divergences from any
    reset level zero. We sample a bar t if and only if S_t >= threshold, at which point S_t is reset to 0.

    One practical aspect that makes CUSUM filters appealing is that multiple events are not triggered by raw_time_series
    hovering around a threshold level, which is a flaw suffered by popular market signals such as Bollinger Bands.
    It will require a full run of length threshold for raw_time_series to trigger an event.

    Once we have obtained this subset of event-driven bars, we will let the ML algorithm determine whether the occurrence
    of such events constitutes actionable intelligence. Below is an implementation of the Symmetric CUSUM filter.

    Note: As per the book this filter is applied to closing prices but we extended it to also work on other
    time series such as volatility.

    :param raw_time_series: (pd.Series) Close prices (or other time series, e.g. volatility).
    :param threshold: (float or pd.Series) When the abs(change) is larger than the threshold, the function captures
                      it as an event, can be dynamic if threshold is pd.Series
    :param time_stamps: (bool) Default is to return a DateTimeIndex, change to false to have it return a list.
    :return: (datetime index vector) Vector of datetimes when the events occurred. This is used later to sample.
    """

    if not isinstance(raw_time_series, pd.Series):
        raw_time_series = pd.Series(raw_time_series)

    price_diff = raw_time_series.diff().dropna()
    if price_diff.empty:
        return pd.DatetimeIndex([]) if time_stamps else []

    if isinstance(threshold, pd.Series):
        aligned_threshold = threshold.reindex(price_diff.index).ffill()
    else:
        aligned_threshold = pd.Series(float(threshold), index=price_diff.index)

    positive_cusum = 0.0
    negative_cusum = 0.0
    sampled_events = []

    for timestamp, change in price_diff.items():
        limit = aligned_threshold.loc[timestamp]
        if pd.isna(change) or pd.isna(limit):
            continue

        limit = abs(float(limit))
        if limit == 0.0:
            continue

        positive_cusum = max(0.0, positive_cusum + float(change))
        negative_cusum = min(0.0, negative_cusum + float(change))

        if negative_cusum < -limit:
            negative_cusum = 0.0
            sampled_events.append(timestamp)
        elif positive_cusum > limit:
            positive_cusum = 0.0
            sampled_events.append(timestamp)

    if time_stamps:
        return pd.DatetimeIndex(sampled_events)
    return sampled_events


def z_score_filter(raw_time_series, mean_window, std_window, z_score=3, time_stamps=True):
    """
    Filter which implements z_score filter
    (https://stackoverflow.com/questions/22583391/peak-signal-detection-in-realtime-timeseries-data)

    :param raw_time_series: (pd.Series) Close prices (or other time series, e.g. volatility).
    :param mean_window: (int): Rolling mean window
    :param std_window: (int): Rolling std window
    :param z_score: (float): Number of standard deviations to trigger the event
    :param time_stamps: (bool) Default is to return a DateTimeIndex, change to false to have it return a list.
    :return: (datetime index vector) Vector of datetimes when the events occurred. This is used later to sample.
    """

    if not isinstance(raw_time_series, pd.Series):
        raw_time_series = pd.Series(raw_time_series)

    rolling_mean = raw_time_series.rolling(window=mean_window).mean()
    rolling_std = raw_time_series.rolling(window=std_window).std()
    upper_bound = rolling_mean + z_score * rolling_std

    sampled_events = raw_time_series[raw_time_series >= upper_bound].index

    if time_stamps:
        return pd.DatetimeIndex(sampled_events)
    return list(sampled_events)
