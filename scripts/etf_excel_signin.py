"""Bring Excel up and get the Citi Velocity add-in signed in, then let go.

Sign-in is a property of the EXCEL PROCESS, not of any one COM client, so this
runs as its own process: it launches, presses the ribbon Login button until the
add-in authenticates, proves the session with ``=CVTODAY()``, closes its own
scratch workbook and exits. Excel stays up and signed in for the backfill.

Doing it this way puts the ~5-15 minute sign-in in parallel with building the
universe, instead of in series with it.
"""

from __future__ import annotations

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("etf_excel_signin")


def main() -> int:
    from MDP.CitiVelocityExcel import memory_guard, supervisor

    mb = memory_guard.excel_memory_mb()
    log.info("memory gate: EXCEL.EXE total working set = %s MB", mb)
    if mb is None:
        log.error("memory probe FAILED - refusing to touch Excel.")
        return 2
    if mb > 0.0:
        # Something is already running. Do not launch a second one, and do not
        # terminate someone's session: just check the gate and try to use it.
        log.warning("Excel is ALREADY running at %.0f MB - not launching another.", mb)
        memory_guard.assert_safe_to_connect(what="the ETF intraday backfill sign-in")
    else:
        pid = supervisor.launch_excel(logger=log)
        log.info("launched EXCEL.EXE pid=%s; waiting for the add-in", pid)
        time.sleep(20.0)

    started = time.time()
    client = supervisor.wait_for_addin(
        timeout=30 * 60.0, poll=25.0, press_login=True, workbook_tag="ETFWARM", logger=log
    )
    log.info("SIGNED IN after %.1f min", (time.time() - started) / 60.0)
    try:
        probe = client.fetch_timeseries(
            ["RATES.OIS.USD_SOFR.PAR.10Y"], "DAILY", period="1W", price_point="CLOSE"
        )
        got = probe.get("RATES.OIS.USD_SOFR.PAR.10Y")
        log.info("live probe: SOFR 10Y 1W -> %s rows, last=%s",
                 0 if got is None else len(got),
                 None if got is None or got.empty else (got.index[-1], float(got.iloc[-1])))
    except Exception as exc:  # noqa: BLE001
        log.warning("live probe raised %s: %s", type(exc).__name__, exc)
    finally:
        client.close()
    log.info("released the client; Excel stays up and signed in. mem=%.0f MB",
             memory_guard.excel_memory_mb() or -1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
