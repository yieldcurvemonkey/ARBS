"""Test compatibility shims for the vendored arbitragelab suite."""

from __future__ import annotations

import matplotlib
import numpy as np
import pyvinecopulib as pv

matplotlib.use("Agg", force=True)

# NumPy 2.x removed a few aliases still used by the vendored test suite.
if not hasattr(np, "NaN"):
    np.NaN = np.nan
if not hasattr(np, "Inf"):
    np.Inf = np.inf
if not hasattr(np, "NINF"):
    np.NINF = -np.inf
if not hasattr(np, "product"):
    np.product = np.prod

# pyvinecopulib 0.7 moved structured construction to Vinecop.from_structure() and
# tightened several method signatures to numpy arrays only. The vendored code and
# tests use the older constructor and accept pandas inputs.
_REAL_VINECOP = pv.Vinecop


class VinecopCompat:
    """Small wrapper that restores the older Vinecop call surface."""

    def __init__(self, *args, **kwargs):
        if "structure" in kwargs and not args:
            self._inner = _REAL_VINECOP.from_structure(
                structure=kwargs["structure"],
                pair_copulas=kwargs.get("pair_copulas", []),
                var_types=kwargs.get("var_types", []),
            )
        elif "matrix" in kwargs and not args:
            self._inner = _REAL_VINECOP.from_structure(
                matrix=kwargs["matrix"],
                pair_copulas=kwargs.get("pair_copulas", []),
                var_types=kwargs.get("var_types", []),
            )
        else:
            self._inner = _REAL_VINECOP(*args, **kwargs)

    @staticmethod
    def _to_numpy(data):
        return data.to_numpy() if hasattr(data, "to_numpy") else data

    @classmethod
    def from_structure(cls, *args, **kwargs):
        instance = cls.__new__(cls)
        instance._inner = _REAL_VINECOP.from_structure(*args, **kwargs)
        return instance

    @classmethod
    def from_data(cls, *args, **kwargs):
        instance = cls.__new__(cls)
        if args:
            args = list(args)
            args[0] = cls._to_numpy(args[0])
            instance._inner = _REAL_VINECOP.from_data(*args, **kwargs)
        else:
            kwargs["data"] = cls._to_numpy(kwargs["data"])
            instance._inner = _REAL_VINECOP.from_data(**kwargs)
        return instance

    def select(self, data, controls=None):
        data = self._to_numpy(data)
        if controls is None:
            return self._inner.select(data)
        return self._inner.select(data, controls)

    def aic(self, data=None, num_threads=1):
        if data is None:
            return self._inner.aic()
        return self._inner.aic(self._to_numpy(data), num_threads)

    def bic(self, data=None, num_threads=1):
        if data is None:
            return self._inner.bic()
        return self._inner.bic(self._to_numpy(data), num_threads)

    def loglik(self, data=None, num_threads=1):
        if data is None:
            return self._inner.loglik()
        return self._inner.loglik(self._to_numpy(data), num_threads)

    def pdf(self, u, num_threads=1):
        return self._inner.pdf(self._to_numpy(u), num_threads)

    def cdf(self, u, N=10000, num_threads=1, seeds=None):
        seeds = [] if seeds is None else seeds
        return self._inner.cdf(self._to_numpy(u), N, num_threads, seeds)

    def simulate(self, n, qrn=False, num_threads=1, seeds=None):
        seeds = [] if seeds is None else seeds
        return self._inner.simulate(n, qrn, num_threads, seeds)

    def __getattr__(self, name):
        return getattr(self._inner, name)


pv.Vinecop = VinecopCompat
