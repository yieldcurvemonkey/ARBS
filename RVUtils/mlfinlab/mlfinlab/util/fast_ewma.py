"""
This module contains an implementation of an exponentially weighted moving average based on sample size.
The inspiration and context for this code was from a blog post by writen by Maksim Ivanov:
https://towardsdatascience.com/financial-machine-learning-part-0-bars-745897d4e4ba
"""

# Imports
import numpy as np
from mlfinlab._numba_compat import NUMBA_AVAILABLE, float64, int64, jit


def _ewma_impl(arr_in, window):
    """
    Exponentially weighted moving average specified by a decay ``window`` to provide better adjustments for
    small windows via:
        y[t] = (x[t] + (1-a)*x[t-1] + (1-a)^2*x[t-2] + ... + (1-a)^n*x[t-n]) /
               (1 + (1-a) + (1-a)^2 + ... + (1-a)^n).

    :param arr_in: (np.ndarray), (float64) A single dimensional numpy array
    :param window: (int64) The decay window, or 'span'
    :return: (np.ndarray) The EWMA vector, same length / shape as ``arr_in``
    """

    values = np.asarray(arr_in, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("ewma expects a one-dimensional array")
    if window < 1:
        raise ValueError("window must be at least 1")
    if values.size == 0:
        return values.copy()

    alpha = 2.0 / (float(window) + 1.0)
    decay = 1.0 - alpha

    result = np.empty(values.shape[0], dtype=np.float64)
    weighted_sum = values[0]
    normalizer = 1.0
    result[0] = values[0]

    for idx in range(1, values.shape[0]):
        weighted_sum = values[idx] + decay * weighted_sum
        normalizer = 1.0 + decay * normalizer
        result[idx] = weighted_sum / normalizer

    return result


if NUMBA_AVAILABLE:
    ewma = jit((float64[:], int64), nopython=False, nogil=True)(_ewma_impl)
else:
    ewma = _ewma_impl
