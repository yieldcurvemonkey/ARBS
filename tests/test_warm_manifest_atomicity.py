r"""A manifest write that fails must not destroy the manifest.

Both UST warm runners saved progress with ``Path.write_text``, which opens with
truncate. When the write then fails the old file is already gone, so what is left
is a zero-byte file — the resume state destroyed by the act of recording it.

Observed 2026-08-13, not hypothetical: the disk filled mid-save with
``OSError: [Errno 28] No space left on device`` and **754 completed chunks, about
nineteen hours of work, became an empty file**. They were only recoverable because
the store itself could be re-read and the manifest reconstructed from it, which is
luck rather than design.

Both runners now write to a temp file in the same directory, fsync, and
``os.replace``, which is atomic on Windows and POSIX alike.
"""

from __future__ import annotations

import json

import pytest


def _load(module, monkeypatch, tmp_path):
    """Point a runner's manifest at tmp_path and hand back (save, path)."""
    if module == "value":
        import scripts.citivelo_ust_10y_value_warm as m

        p = tmp_path / "value_manifest.json"
        monkeypatch.setattr(m, "_manifest_path", lambda: p)
        return m._save, p, m

    import scripts.citivelo_ust_timeseries_warm as m

    p = tmp_path / "ts_manifest.json"
    monkeypatch.setattr(m, "MANIFEST", p)
    return m._save_manifest, p, m


MODULES = ["value", "ts"]


@pytest.mark.parametrize("module", MODULES)
def test_a_manifest_round_trips(module, monkeypatch, tmp_path):
    save, path, _ = _load(module, monkeypatch, tmp_path)
    payload = {"done": {"issues|912828XB1|2016-08-07": {"sig": "abc", "rows": 250}}, "failed": {}}
    save(payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload


@pytest.mark.parametrize("module", MODULES)
def test_a_failed_write_leaves_the_PREVIOUS_manifest_intact(module, monkeypatch, tmp_path):
    """The whole point. A disk that fills during the second save must not cost the
    first one — which is exactly what truncate-then-write did."""
    save, path, mod = _load(module, monkeypatch, tmp_path)
    good = {"done": {"issues|A|2016-08-07": {"sig": "s", "rows": 1}}, "failed": {}}
    save(good)

    def _explode(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(mod.json, "dump", _explode)
    with pytest.raises(OSError):
        save({"done": {"issues|B|2016-08-07": {}}, "failed": {}})

    assert path.stat().st_size > 0, "the previous manifest was truncated"
    assert json.loads(path.read_text(encoding="utf-8")) == good


@pytest.mark.parametrize("module", MODULES)
def test_a_failed_write_leaves_no_temp_file_behind(module, monkeypatch, tmp_path):
    """An unattended job saves every ten chunks; a temp file per failure would
    accumulate silently on the very disk that just ran out."""
    save, path, mod = _load(module, monkeypatch, tmp_path)
    save({"done": {}, "failed": {}})

    def _explode(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(mod.json, "dump", _explode)
    for _ in range(3):
        with pytest.raises(OSError):
            save({"done": {"x": 1}, "failed": {}})

    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"temp files left behind: {leftovers}"


@pytest.mark.parametrize("module", MODULES)
def test_the_first_ever_save_creates_the_directory(module, monkeypatch, tmp_path):
    """The manifest lives beside the tag cache, which may not exist yet."""
    nested = tmp_path / "a" / "b"
    if module == "value":
        import scripts.citivelo_ust_10y_value_warm as m

        p = nested / "m.json"
        monkeypatch.setattr(m, "_manifest_path", lambda: p)
        m._save({"done": {}, "failed": {}})
    else:
        import scripts.citivelo_ust_timeseries_warm as m

        p = nested / "m.json"
        monkeypatch.setattr(m, "MANIFEST", p)
        m._save_manifest({"fetch": {}, "build": {}})
    assert p.exists()
