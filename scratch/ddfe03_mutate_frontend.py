"""Mutation battery for the dealer-direction front end.

A green suite is not evidence. Nineteen of thirty-one mutants survived one
module's tests on the backend work, including one that let a published z-score
be published exactly inverted while every test passed -- because every test was
comparative and a global sign flip cancels inside all of them.

So each mutation below is a specific lie the code could tell, and the run is a
failure unless the suite goes RED for every one of them. The source is restored
in a ``finally``; nothing is left mutated on disk.

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ddfe03_mutate_frontend.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

DASH = pathlib.Path(__file__).resolve().parents[1] / "SDRUtils" / "dashboard"
SRC = DASH / "src"

# (label, file, old, new, test pattern that MUST go red)
MUTATIONS = [
    (
        "the direction words are swapped -- RECEIVED reads as short duration",
        "features/usd-swaps-tape-v2/utils/dealerDirection.ts",
        "'Dealer RECEIVED fixed — customer paid fixed, dealer is long duration.'\n      : 'Dealer PAID fixed — customer received fixed, dealer is short duration.'",
        "'Dealer PAID fixed — customer received fixed, dealer is short duration.'\n      : 'Dealer RECEIVED fixed — customer paid fixed, dealer is long duration.'",
        "dealerDirection",
    ),
    (
        "the tone is inverted -- received renders amber",
        "features/usd-swaps-tape-v2/utils/dealerDirection.ts",
        "const tone: DirectionTone = raw === DIRECTION_RECEIVED ? 'received' : 'paid'",
        "const tone: DirectionTone = raw === DIRECTION_RECEIVED ? 'paid' : 'received'",
        "dealerDirection",
    ),
    (
        "the label is inverted -- RECEIVED renders as PAID",
        "features/usd-swaps-tape-v2/utils/dealerDirection.ts",
        "label: raw === DIRECTION_RECEIVED ? 'RCVD' : 'PAID',",
        "label: raw === DIRECTION_RECEIVED ? 'PAID' : 'RCVD',",
        "dealerDirection",
    ),
    (
        "conviction reads p, not |2p-1| -- a coin flip bands as medium",
        "features/usd-swaps-tape-v2/utils/dealerDirection.ts",
        "const conviction = weight == null ? null : Math.abs(weight)",
        "const conviction = p == null ? null : Math.abs(p)",
        "dealerDirection",
    ),
    (
        "the CVD-unsafe pair is restored",
        "features/usd-swaps-tape-v2/utils/dealerDirection.ts",
        "received: 'bg-sky-900/40 text-sky-200 ring-1 ring-sky-400/40',",
        "received: 'bg-emerald-900/40 text-emerald-200 ring-1 ring-emerald-400/40',",
        "dealerDirection",
    ),
    (
        "an unknown row renders as an abstention -- 'we declined' on a trade "
        "nobody looked at",
        "features/usd-swaps-tape-v2/utils/dealerDirection.ts",
        "      known: false,\n      label: '—',",
        "      known: true,\n      label: 'n/a',",
        "dealerDirection",
    ),
    (
        "the level endpoint accepts a list of buckets",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "  if (all.length > 1 || all[0]!.includes(',')) {",
        "  if (false) {",
        "direction/__tests__",
    ),
    (
        "a missing bucket defaults to every bucket",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "  if (all.length === 0) {",
        "  if (false) {",
        "direction/__tests__",
    ),
    (
        "the all-bucket payload gains a level column",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "export const STANDARDISED_COLUMNS = [\n  'bucket_key', 'visibility_date', 'observed',",
        "export const STANDARDISED_COLUMNS = [\n  'bucket_key', 'visibility_date', 'observed', 'delta_dv01',",
        "direction/__tests__",
    ),
    (
        "assertNoLevelKeys becomes a no-op",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "export function assertNoLevelKeys(rows: Record<string, unknown>[]): void {",
        "export function assertNoLevelKeys(rows: Record<string, unknown>[]): void {\n  return;",
        "direction/__tests__",
    ),
    (
        "the level keys stop being bucket-suffixed on the wire",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "      out[LEVEL_KEY.test(k) ? `${k}__${s}` : k] = v",
        "      out[k] = v",
        "direction/__tests__",
    ),
    (
        "the slug drops the plus, so 30Y+ collides with 30Y",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "  return bucket.replace(/-/g, '_').replace(/\\+/g, 'plus')",
        "  return bucket.replace(/-/g, '_')",
        "direction/__tests__",
    ),
    (
        "'UNKNOWN' is accepted as a venue class, serving an empty series",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "  if (!VENUE_CLASSES.includes(venueClass)) {",
        "  if (false) {",
        "direction/__tests__",
    ),
    (
        "the sample floor is not enforced",
        "app/api/usd-swaps-tape-v2/direction/route.logic.ts",
        "  if (from < SAMPLE_FLOOR) {",
        "  if (false) {",
        "direction/__tests__",
    ),
    (
        "the panel guard becomes a no-op",
        "features/usd-swaps-tape-v2/components/AnalyticsPanel/DealerLadderPanel.helpers.ts",
        "export function assertNotCrossBucketLevel(rows: Record<string, unknown>[]): void {",
        "export function assertNotCrossBucketLevel(rows: Record<string, unknown>[]): void {\n  return;",
        "DealerLadderPanel",
    ),
    (
        "the diverging ramp puts a HUE at the midpoint",
        "features/usd-swaps-tape-v2/components/AnalyticsPanel/DealerLadderPanel.helpers.ts",
        "  return mix(DIRECTION_NEUTRAL, z >= 0 ? DIRECTION_SKY : DIRECTION_AMBER, t)",
        "  return mix(DIRECTION_AMBER, DIRECTION_SKY, (z / (2 * Z_CLAMP)) + 0.5)",
        "DealerLadderPanel",
    ),
    (
        "the ramp poles are swapped -- +z renders amber",
        "features/usd-swaps-tape-v2/components/AnalyticsPanel/DealerLadderPanel.helpers.ts",
        "  return mix(DIRECTION_NEUTRAL, z >= 0 ? DIRECTION_SKY : DIRECTION_AMBER, t)",
        "  return mix(DIRECTION_NEUTRAL, z >= 0 ? DIRECTION_AMBER : DIRECTION_SKY, t)",
        "DealerLadderPanel",
    ),
    (
        "a missing cell renders as z = 0 rather than as nothing",
        "features/usd-swaps-tape-v2/components/AnalyticsPanel/DealerLadderPanel.helpers.ts",
        "  if (z == null) return 'transparent'",
        "  if (z == null) z = 0",
        "DealerLadderPanel",
    ),
    (
        "fmtSignedDv01 drops the sign",
        "features/usd-swaps-tape-v2/components/AnalyticsPanel/DealerLadderPanel.helpers.ts",
        "  const sign = v > 0 ? '+' : v < 0 ? '−' : ''",
        "  const sign = ''",
        "DealerLadderPanel",
    ),
    (
        "the join key becomes unit_key",
        "lib/dealer-direction-join.ts",
        "    join: `LEFT JOIN ${DD_UNIT} dd ON dd.package_id = d.package_id`,",
        "    join: `LEFT JOIN ${DD_UNIT} dd ON dd.unit_key = d.package_id`,",
        "dealer-direction-tables",
    ),
    (
        "the join becomes an INNER join, silently dropping unpriced days",
        "lib/dealer-direction-join.ts",
        "    join: `LEFT JOIN ${DD_UNIT} dd ON dd.package_id = d.package_id`,",
        "    join: `JOIN ${DD_UNIT} dd ON dd.package_id = d.package_id`,",
        "dealer-direction-tables",
    ),
]


def run(pattern: str) -> bool:
    """True when the suite PASSES."""
    # errors="replace": jest prints em-dashes and the console is cp1252 here,
    # and a decode error in the reader thread is a distracting traceback even
    # though `returncode` survives it.
    r = subprocess.run(
        ["npm.cmd", "test", "--", "--testPathPatterns=" + pattern],
        cwd=str(DASH), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900)
    return r.returncode == 0


def main() -> int:
    survivors, killed = [], []
    print(f"{len(MUTATIONS)} mutations\n", flush=True)

    # Validate the harness against a known answer FIRST: unmutated, green.
    for pattern in sorted({m[4] for m in MUTATIONS}):
        if not run(pattern):
            print(f"BASELINE RED for {pattern!r} -- the harness cannot score "
                  "anything until the clean tree passes.")
            return 2
    print("baseline: all patterns green\n", flush=True)

    for i, (label, rel, old, new, pattern) in enumerate(MUTATIONS, 1):
        path = SRC / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"[{i:2d}] SKIP  (anchor not found) {label}")
            survivors.append((label, "ANCHOR NOT FOUND"))
            continue
        if original.count(old) != 1:
            print(f"[{i:2d}] SKIP  (anchor x{original.count(old)}) {label}")
            survivors.append((label, "ANCHOR AMBIGUOUS"))
            continue
        try:
            path.write_text(original.replace(old, new), encoding="utf-8")
            passed = run(pattern)
        finally:
            path.write_text(original, encoding="utf-8")
        if passed:
            print(f"[{i:2d}] SURVIVED  {label}", flush=True)
            survivors.append((label, "SURVIVED"))
        else:
            print(f"[{i:2d}] killed    {label}", flush=True)
            killed.append(label)

    print(f"\n{len(killed)}/{len(MUTATIONS)} killed")
    if survivors:
        print("\nSURVIVORS -- each is a lie the suite would not catch:")
        for label, why in survivors:
            print(f"  - [{why}] {label}")
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
