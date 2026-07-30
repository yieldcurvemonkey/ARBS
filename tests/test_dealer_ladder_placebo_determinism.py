"""The sign-shuffle placebo must not depend on the row order it is handed.

Found 2026-07-30 by re-running the placebo suite over the same config and comparing: five of
six arms reproduced bit-identically and `sign shuffle within session` moved from -0.4476
(n=1636) to -0.4644 (n=1631). The other five are order-independent transforms; this one spends
a seeded RNG positionally, so a different row order lands different signs on different prints.

That matters because the suite is read as a DISTANCE from the reference. An arm that moves
between runs makes that distance partly noise, and the pre-written expectation for this arm
("destroyed; survival means intensity not direction") cannot be judged against a moving number.

Two defences, both tested here: `data._PRINTS_SQL` now carries a total ORDER BY, and the
shuffle orders its own groups rather than trusting the caller.
"""
import numpy as np
import pandas as pd

from BT.dealer_ladder import data, study


def _prints(n=60, seed=1):
    """Two sessions of prints with unique keys, in a fixed reference order."""
    rng = np.random.default_rng(seed)
    ts = pd.to_datetime(
        ["2026-03-10 14:00:00+00:00"] * (n // 2) + ["2026-03-11 14:00:00+00:00"] * (n - n // 2)
    ) + pd.to_timedelta(np.arange(n), unit="m")
    return pd.DataFrame({
        "unit_key": [f"u{i:04d}" for i in range(n)],
        "bucket_key": ["SR3H26"] * n,
        "visibility_timestamp": ts,
        "delta_dv01": rng.normal(size=n) * 1000.0,
    })


def test_shuffle_is_invariant_to_incoming_row_order():
    """The property that broke: same data, different sequence, same answer."""
    base = _prints()
    shuffled_rows = base.sample(frac=1.0, random_state=7).reset_index(drop=True)

    a = study.placebo_sign_shuffle(base, seed=0)
    b = study.placebo_sign_shuffle(shuffled_rows, seed=0)

    merged = a[["unit_key", "delta_dv01"]].merge(
        b[["unit_key", "delta_dv01"]], on="unit_key", suffixes=("_a", "_b"))
    assert len(merged) == len(base)
    assert np.allclose(merged["delta_dv01_a"], merged["delta_dv01_b"]), (
        "the same print received a different sign purely because the frame arrived "
        "in a different order")


def test_shuffle_is_reproducible_across_calls():
    base = _prints()
    a = study.placebo_sign_shuffle(base, seed=0)
    b = study.placebo_sign_shuffle(base, seed=0)
    assert np.allclose(a["delta_dv01"], b["delta_dv01"])


def test_shuffle_preserves_magnitudes_and_the_multiset_of_signs_per_session():
    """It must kill direction WITHOUT changing intensity — that is the whole design."""
    base = _prints()
    out = study.placebo_sign_shuffle(base, seed=0)
    assert np.allclose(np.sort(np.abs(base["delta_dv01"])),
                       np.sort(np.abs(out["delta_dv01"])))
    day = pd.to_datetime(base["visibility_timestamp"]).dt.tz_convert(
        "America/New_York").dt.date
    for d in pd.unique(day):
        m = (day == d).to_numpy()
        assert sorted(np.sign(base["delta_dv01"].to_numpy()[m])) == \
            sorted(np.sign(out["delta_dv01"].to_numpy()[m]))


def test_different_seeds_give_different_shuffles():
    """Guards the opposite failure: a shuffle that is stable because it does nothing."""
    base = _prints(n=200)
    a = study.placebo_sign_shuffle(base, seed=0)
    b = study.placebo_sign_shuffle(base, seed=99)
    assert not np.allclose(a["delta_dv01"], b["delta_dv01"])


def test_prints_query_orders_totally():
    """Without a total ORDER BY, two runs can return the same rows in a different sequence."""
    sql = data._PRINTS_SQL.lower()
    assert "order by" in sql, "_PRINTS_SQL has no ORDER BY — row order is not guaranteed"
    tail = sql.split("order by", 1)[1]
    for key in ("visibility_timestamp", "unit_key", "bucket_key"):
        assert key in tail, f"ORDER BY does not include {key}, so it is not a total order"
