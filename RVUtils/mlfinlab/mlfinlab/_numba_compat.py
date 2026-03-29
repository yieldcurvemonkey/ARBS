"""Compatibility helpers for environments where numba is unavailable."""

from __future__ import annotations

from contextlib import contextmanager

try:
    from numba import float64, int64, jit, njit, objmode, prange

    NUMBA_AVAILABLE = True
except ModuleNotFoundError:
    NUMBA_AVAILABLE = False

    class _DummyNumbaType:
        def __getitem__(self, _item):
            return self

    float64 = _DummyNumbaType()
    int64 = _DummyNumbaType()

    def _passthrough_decorator(*args, **kwargs):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        def decorator(func):
            return func

        return decorator

    jit = _passthrough_decorator
    njit = _passthrough_decorator

    def prange(*args):
        return range(*args)

    @contextmanager
    def objmode(*_args, **_kwargs):
        yield
