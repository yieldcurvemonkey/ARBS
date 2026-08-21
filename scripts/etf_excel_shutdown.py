"""Close Excel cleanly, rescuing anything a human left open, and report what happened.

``quit_excel`` without ``force`` rescues before it quits: a dirty workbook with a
path is saved in place and one without is written into the recovery directory.
Expect ZERO rescues here - the only workbooks this job opened are its own scratch
sheets, which carry the package's marker and are skipped as disposable. A
NON-zero count means a person opened something while the backfill was running,
and that belongs in the report rather than in a log nobody reads.
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("etf_shutdown")


def main() -> int:
    from MDP.CitiVelocityExcel import memory_guard, supervisor

    before = memory_guard.excel_memory_mb()
    pids = supervisor.excel_pids()
    log.info("before shutdown: %s EXCEL.EXE pid(s) %s at %s MB", len(pids), pids, before)
    if not pids:
        log.info("nothing to close.")
        print("EXCEL_PIDS_AFTER=0 RESCUED=0")
        return 0

    rescued = supervisor.quit_excel(logger=log)          # force stays FALSE
    after = supervisor.excel_pids()
    log.info("rescued %d workbook(s): %s", len(rescued), [str(p) for p in rescued])
    log.info("after shutdown: %d EXCEL.EXE pid(s) %s, memory %s MB",
             len(after), after, memory_guard.excel_memory_mb())
    print(f"EXCEL_PIDS_AFTER={len(after)} RESCUED={len(rescued)} "
          f"MB_BEFORE={before} PATHS={[str(p) for p in rescued]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
