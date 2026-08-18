"""The daily Citi swaption value manifest stays broad and offline-first."""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib

import pytest

from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure


REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "citivelo_swaption_eod_warm.py"


def _load():
    spec = importlib.util.spec_from_file_location("_citivelo_swaption_eod_warm", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_covers_the_surface_and_every_package_type(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_surface_shorthands", lambda _days: ("1Yx10Y", "5Yx10Y"))
    queries = mod.build_queries(days=[dt.date(2026, 8, 14)])

    exact = [
        q for q in queries
        if q.shorthand == "5Yx10Y" and q.structure == IRSwaptionStructure.STRADDLE
    ]
    assert len(exact) == 1

    for shorthand in ("1Yx10Y", "5Yx10Y"):
        covered = {q.structure for q in queries if q.shorthand == shorthand}
        assert set(IRSwaptionStructure).issubset(covered)
    assert len(queries) == 2 * len(IRSwaptionStructure)


def test_offline_cube_miss_refuses_the_excel_fallback():
    from MDP.CitiVelocityExcel.errors import CitiVelocityError
    from MDP.IRSwaptions.CITIVELO.provider import _cube_for_date

    with pytest.raises(CitiVelocityError, match="offline_only=True"):
        _cube_for_date(
            currency="USD",
            when=dt.date(2026, 8, 14),
            cube=None,
            cubes=None,
            snapshot=None,
            expiries=None,
            tenors=None,
            offsets_bp=None,
            strict=False,
            client=None,
            offline_only=True,
            stored={},
        )
