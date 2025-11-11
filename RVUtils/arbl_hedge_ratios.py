# ABOUTME: Arbitrage hedge ratio calculations
# ABOUTME: Computes optimal hedge ratios for relative value trades
# https://github.com/hudson-and-thames/arbitragelab/blob/32ccd567e8541965a35293a67944945f6d377f65/arbitragelab/hedge_ratios/linear.py#L13

"""
The module implements OLS (Ordinary Least Squares) and TLS (Total Least Squares) hedge ratio calculations.
"""
# pylint: disable=invalid-name

from typing import Tuple
import polars as pl
import numpy as np
from sklearn.linear_model import LinearRegression
from scipy.odr import ODR, Model, RealData


def get_ols_hedge_ratio(price_data: pl.DataFrame, dependent_variable: str, add_constant: bool = False) -> \
        Tuple[dict, pl.DataFrame, pl.Series, pl.Series]:
    """
    Get OLS hedge ratio: y = beta*X.

    :param price_data: (pl.DataFrame) Data Frame with security prices.
    :param dependent_variable: (str) Column name which represents the dependent variable (y).
    :param add_constant: (bool) Boolean flag to add constant in regression setting.
    :return: (Tuple) Hedge ratios, X, and y and OLS fit residuals.
    """

    ols_model = LinearRegression(fit_intercept=add_constant)

    X = price_data.clone()
    X = X.drop(dependent_variable)
    exogenous_variables = X.columns
    X_values = X.to_numpy()
    if X.shape[1] == 1:
        X_values = X_values.reshape(-1, 1)

    y = price_data[dependent_variable].clone()
    y_values = y.to_numpy()

    ols_model.fit(X_values, y_values)
    residuals = y - ols_model.predict(X_values)

    hedge_ratios = ols_model.coef_
    hedge_ratios_dict = dict(zip([dependent_variable] + exogenous_variables, np.insert(hedge_ratios, 0, 1.0)))

    return hedge_ratios_dict, X, y, residuals


def _linear_f_no_constant(beta: np.array, x_variable: np.array) -> np.array:
    """
    This is the helper linear model that is used in the Orthogonal Regression.

    :param beta: (np.array) Model beta coefficient.
    :param x_variable: (np.array) Model X vector.
    :return: (np.array) Vector result of equation calculation.
    """

    _, b = beta[0], beta[1:]
    b.shape = (b.shape[0], 1)

    return (x_variable * b).sum(axis=0)


def _linear_f_constant(beta: np.array, x_variable: np.array) -> np.array:
    """
    This is the helper linear model that is used in the Orthogonal Regression.

    :param beta: (np.array) Model beta coefficient.
    :param x_variable: (np.array) Model X vector.
    :return: (np.array) Vector result of equation calculation.
    """

    a, b = beta[0], beta[1:]
    b.shape = (b.shape[0], 1)

    return a + (x_variable * b).sum(axis=0)


def get_tls_hedge_ratio(price_data: pl.DataFrame, dependent_variable: str, add_constant: bool = False) -> \
        Tuple[dict, pl.DataFrame, pl.Series, pl.Series]:
    """
    Get Total Least Squares (TLS) hedge ratio using Orthogonal Regression.

    :param price_data: (pl.DataFrame) Data Frame with security prices.
    :param dependent_variable: (str) Column name which represents the dependent variable (y).
    :param add_constant: (bool) Boolean flag to add constant in regression setting.
    :return: (Tuple) Hedge ratios dict, X, and y and fit residuals.
    """

    X = price_data.clone()
    X = X.drop(dependent_variable)
    y = price_data[dependent_variable].clone()

    linear = Model(_linear_f_constant) if add_constant is True else Model(_linear_f_no_constant)
    mydata = RealData(X.to_numpy().T, y.to_numpy())
    myodr = ODR(mydata, linear, beta0=np.ones(X.shape[1] + 1))
    res_co = myodr.run()

    hedge_ratios = res_co.beta[1:]  # We don't need constant
    X_np = X.to_numpy()
    residuals = y - res_co.beta[0] - (X_np * hedge_ratios).sum(axis=1) if add_constant is True else y - (
            X_np * hedge_ratios).sum(axis=1)
    hedge_ratios_dict = dict(zip([dependent_variable] + X.columns, np.insert(hedge_ratios, 0, 1.0)))

    return hedge_ratios_dict, X, y, residuals