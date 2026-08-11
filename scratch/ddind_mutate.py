"""Mutate indicator.py and confirm the test suite goes red for each defect.

A green suite is evidence only if it can go red. Each mutation below is a
specific way the indicator could be wrong while still producing a complete,
plausible daily frame -- which is the failure mode the whole module is built
against.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

SRC = pathlib.Path(__file__).resolve().parents[1] / "SDRUtils/dealer_direction/indicator.py"
TEST = "tests/test_dealer_direction_indicator.py"
REPO = SRC.parents[2]

MUTATIONS = [
    ("M1  weight check accepts p-weighting",
     'def _assert_weight_is_2p_minus_1(rows) -> None:\n    if not',
     'def _assert_weight_is_2p_minus_1(rows) -> None:\n    return\n    if not'),
    ("M2  venue_class dropped from the key",
     'INDICATOR_KEYS = ("bucket_space", "bucket_key", "visibility_date",\n'
     '                  "venue_class", "series")',
     'INDICATOR_KEYS = ("bucket_space", "bucket_key", "visibility_date",\n'
     '                  "series")'),
    ("M3  stamping on execution is not caught",
     'def _assert_stamped_on_visibility(rows) -> None:\n    if "visibility_timestamp"',
     'def _assert_stamped_on_visibility(rows) -> None:\n    return\n    if "visibility_timestamp"'),
    ("M4  bucket map right edge moved (10Y -> 10-15Y)",
     '(10.0, "7-10Y"),', '(9.5, "7-10Y"),'),
    ("M5  cross_section returns instead of refusing",
     '    def cross_section(self, date=None):\n        """Refuses. One day\'s levels across buckets is the forbidden read."""\n'
     '        raise CrossSectionalLevelComparison(_CROSS_SECTION_MESSAGE)',
     '    def cross_section(self, date=None):\n        """Refuses. One day\'s levels across buckets is the forbidden read."""\n'
     '        return self._cells'),
    ("M6  the drift flag never trips",
     '        flag = bool(pinned or (measured and abs(tstat) > DRIFT_T_THRESHOLD))',
     '        flag = False'),
    ("M7  z pooled across venue classes",
     'def _group_keys() -> list:\n    return ["bucket_space", "bucket_key", "venue_class", "series"]',
     'def _group_keys() -> list:\n    return ["bucket_space", "bucket_key", "series"]'),
    ("M8  sample floor removed",
     'SAMPLE_FLOOR = datetime.date(2024, 7, 1)',
     'SAMPLE_FLOOR = datetime.date(2000, 1, 1)'),
    ("M9  cumulate returns instead of refusing",
     '    def cumulate(self, *args, **kwargs):\n        """Refuses. The offsetting compression print does not exist."""\n'
     '        raise CumulationRefused(_CUMULATION_MESSAGE)',
     '    def cumulate(self, *args, **kwargs):\n        """Refuses. The offsetting compression print does not exist."""\n'
     '        return self._cells'),
    ("M10 level column loses its bucket suffix",
     '    return f"{_LEVEL_BASES[basis]}__{_slug(bucket_key)}"',
     '    return _LEVEL_BASES[basis]'),
    ("M11 z uses the whole sample, not a trailing window",
     '        roll = lvl.rolling(z_window_obs, min_periods=z_min_obs)',
     '        roll = lvl.expanding(min_periods=z_min_obs) if False else '
     'lvl.rolling(len(lvl), min_periods=z_min_obs, center=True)'),
    ("M12 a missing coverage row is tolerated",
     '    gaps = merged["coverage_frac"].isna()\n    if gaps.any():',
     '    gaps = merged["coverage_frac"].isna()\n    if False:'),
    ("M13 the ADF standardisation is removed",
     '    x = (x - float(np.mean(x))) / sd\n    lags =',
     '    lags ='),
    ("M14 the roll-up stops checking a unit is one print",
     'def _assert_unit_constant(rows) -> None:\n    """One unit',
     'def _assert_unit_constant(rows) -> None:\n    return\n    """One unit'),
    ("M15 the coverage smoother is replaced by the day's own fraction",
     "        smooth = cf.rolling(coverage_smooth_obs,\n"
     "                            min_periods=coverage_smooth_obs).mean()",
     "        smooth = cf"),
]

original = SRC.read_text()
backup = pathlib.Path(tempfile.gettempdir()) / "indicator_backup.py"
backup.write_text(original)
print(f"backup -> {backup}\n")

results = []
try:
    for name, old, new in MUTATIONS:
        if old not in original:
            results.append((name, "NOT APPLIED - anchor not found", -1))
            print(f"{name:52s} ANCHOR NOT FOUND")
            continue
        SRC.write_text(original.replace(old, new, 1))
        p = subprocess.run(
            [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p",
             "no:cacheprovider"],
            cwd=REPO, capture_output=True, text=True)
        tail = [ln for ln in p.stdout.splitlines()
                if " passed" in ln or " failed" in ln or "error" in ln.lower()]
        summary = tail[-1] if tail else "NO SUMMARY"
        killed = p.returncode != 0
        results.append((name, summary, p.returncode))
        print(f"{name:52s} {'KILLED ' if killed else 'SURVIVED'} | {summary}")
finally:
    SRC.write_text(original)
    print(f"\nrestored {SRC}; identical = {SRC.read_text() == original}")

survivors = [r for r in results if r[2] == 0]
print(f"\n{len(results) - len(survivors)}/{len(results)} mutations killed")
if survivors:
    print("SURVIVORS:")
    for n, s, _ in survivors:
        print(f"  {n}: {s}")
