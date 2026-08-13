"""The convention checker, checked.

`scripts/settle_xccy_conventions.py` is about to be pointed at live Citi data and asked to decide
the **sign of a trading strategy**. A checker that is itself wrong returns a confident wrong answer
and nothing announces it. So it is run first against synthetic wires whose answer is known: one
that follows the market convention, one that is inverted, and one that is ambiguous.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "settle_xccy", Path(__file__).resolve().parents[2] / "scripts" / "settle_xccy_conventions.py"
)
settle = importlib.util.module_from_spec(_SPEC)


@pytest.fixture(scope="module", autouse=True)
def _load():
    sys.modules["settle_xccy"] = settle
    _SPEC.loader.exec_module(settle)


class _FakeQuotes:
    """A wire that returns a basis with a chosen sign and a crisis blow-out."""

    def __init__(self, sign: int = 1, base_leg_flat: bool = True):
        self.sign = sign
        self.base_leg_flat = base_leg_flat

    def frame(self, tags, freq, start=None, end=None):
        idx = pd.bdate_range("2006-01-02", "2026-08-01")
        out = {}
        for t in tags:
            if "EUR.USD" in t:
                level = -20.0
            elif "USD.JPY" in t:
                level = -40.0
            elif "GBP.USD" in t:
                level = -10.0
            else:
                level = -15.0
            s = pd.Series(level, index=idx, dtype=float)
            # dollar squeezes: the basis widens NEGATIVE
            s.loc["2008-09-15":"2008-12-31"] = level - 80.0
            s.loc["2020-03-01":"2020-04-15"] = level - 60.0
            s = s + np.random.default_rng(0).normal(scale=0.5, size=len(idx))
            if "BASE_LEG" in t and self.base_leg_flat:
                s = pd.Series(0.0, index=idx, dtype=float)
            else:
                s = s * self.sign
            out[t] = s
        return pd.DataFrame(out, index=idx)


def _run(monkeypatch, quotes) -> int:
    class _Mod:
        CitiVeloQuotes = lambda self=None: quotes  # noqa: E731

    import types

    fake = types.ModuleType("MDP.CitiVelocityExcel.quotes")
    fake.CitiVeloQuotes = lambda: quotes
    monkeypatch.setitem(sys.modules, "MDP.CitiVelocityExcel.quotes", fake)
    monkeypatch.setattr(sys, "argv", ["settle_xccy_conventions.py"])
    return settle.main()


def test_market_convention_wire_is_accepted(monkeypatch, caplog):
    """A wire that matches the market must be reported as sign=+1."""
    with caplog.at_level("INFO"):
        rc = _run(monkeypatch, _FakeQuotes(sign=+1))
    text = caplog.text
    assert rc == 0
    assert "sign=+1" in text
    assert "MATCHES" in text
    assert "INVERTED" not in text.replace("INVERTED (widened positive)", "")


def test_inverted_wire_is_caught(monkeypatch, caplog):
    """The whole point: a wire that signs the basis the other way must be flagged, not accepted."""
    with caplog.at_level("INFO"):
        rc = _run(monkeypatch, _FakeQuotes(sign=-1))
    text = caplog.text
    assert rc == 0
    assert "sign=-1" in text
    assert "INVERTED" in text


def test_the_two_sign_tests_agree_on_a_clean_wire(monkeypatch, caplog):
    """Level and crisis are independent tests; on a clean wire they must not disagree."""
    with caplog.at_level("INFO"):
        _run(monkeypatch, _FakeQuotes(sign=+1))
    text = caplog.text
    assert "level    matches" in text
    assert "crisis   matches" in text


def test_leg_detection_finds_the_spread_leg(monkeypatch, caplog):
    with caplog.at_level("INFO"):
        _run(monkeypatch, _FakeQuotes(sign=+1, base_leg_flat=True))
    assert "SPREAD_LEG carries it" in caplog.text


def test_leg_detection_flags_two_live_legs(monkeypatch, caplog):
    """If both legs carry a spread the convention is not what the module assumes — say so."""
    with caplog.at_level("INFO"):
        _run(monkeypatch, _FakeQuotes(sign=+1, base_leg_flat=False))
    assert "both legs non-trivial" in caplog.text
