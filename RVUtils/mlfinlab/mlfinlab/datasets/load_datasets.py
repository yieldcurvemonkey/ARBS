"""
The module implementing various functions loading tick, dollar, stock data sets which can be used as
sandbox data.
"""

from importlib import resources

import pandas as pd


def _load_packaged_csv(filename: str, datetime_column: str) -> pd.DataFrame:
    """Load one of the CSV fixtures bundled with the package."""

    dataset_path = resources.files("mlfinlab.datasets").joinpath("data", filename)
    dataset = pd.read_csv(dataset_path, parse_dates=[datetime_column])
    dataset = dataset.set_index(datetime_column)
    dataset.index.name = datetime_column
    return dataset


def load_stock_prices() -> pd.DataFrame:
    """
    Loads stock prices data sets consisting of
    EEM, EWG, TIP, EWJ, EFA, IEF, EWQ, EWU, XLB, XLE, XLF, LQD, XLK, XLU, EPP, FXI, VGK, VPL, SPY, TLT, BND, CSJ,
    DIA starting from 2008 till 2016.

    :return: (pd.DataFrame) The stock_prices data frame.
    """

    stock_prices = _load_packaged_csv("stock_prices.csv", "Date")
    stock_prices.index.name = "date"
    return stock_prices


def load_tick_sample() -> pd.DataFrame:
    """
    Loads E-Mini S&P 500 futures tick data sample.

    :return: (pd.DataFrame) Frame with tick data sample.
    """

    tick_sample = _load_packaged_csv("tick_data.csv", "Date and Time")
    tick_sample.index.name = "date_time"
    return tick_sample


def load_dollar_bar_sample() -> pd.DataFrame:
    """
    Loads E-Mini S&P 500 futures dollar bars data sample.

    :return: (pd.DataFrame) Frame with dollar bar data sample.
    """

    return _load_packaged_csv("dollar_bar_sample.csv", "date_time")


def generate_multi_asset_data_set(start_date: pd.Timestamp = pd.Timestamp(2008, 1, 1),
                                  end_date: pd.Timestamp = pd.Timestamp(2020, 1, 1)) -> tuple:
    # pylint: disable=invalid-name
    """
    Generates multi-asset dataset from stock prices labelled by triple-barrier method.

    :param start_date: (pd.Timestamp) Dataset start date.
    :param end_date: (pd.Timestamp) Dataset end date.
    :return: (tuple) Tuple of dictionaries (asset: data) for X, y, cont contract used to label the dataset.
    """

    raise NotImplementedError(
        "generate_multi_asset_data_set is not implemented in this vendored mlfinlab snapshot."
    )
