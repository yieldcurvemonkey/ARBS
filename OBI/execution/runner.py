"""
Execution loop runner.

Polls for active contracts, runs OBI signal generation, and manages
the trade lifecycle for both paper and live modes.
"""
from __future__ import annotations

import datetime
import logging
import signal
import time
from typing import Optional

from OBI.config import ExecutionConfig
from OBI.execution.base import BaseExecutionEngine
from OBI.execution.live import create_execution_engine

logger = logging.getLogger(__name__)


class ExecutionRunner:
    """Main loop that drives the execution engine."""

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.engine: BaseExecutionEngine = create_execution_engine(config)
        self._stop = False

    def run(self, max_iterations: Optional[int] = None):
        """Start the execution loop.

        max_iterations: stop after N iterations (None = run until stopped)
        """
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        self.engine.state.is_running = True
        logger.info(
            f"Starting OBI execution | mode={self.config.mode} venue={self.config.venue} "
            f"capital={self.config.capital} threshold={self.config.entry_threshold}"
        )

        iteration = 0
        while not self._stop:
            if max_iterations is not None and iteration >= max_iterations:
                break

            try:
                self._tick()
            except Exception as e:
                logger.error(f"Tick error: {e}", exc_info=True)

            iteration += 1
            time.sleep(self.config.poll_interval_ms / 1000)

        self.engine.state.is_running = False
        self._print_summary()

    def _tick(self):
        """One iteration: find contracts, evaluate signals, manage positions."""
        contracts = self.engine.get_active_contracts()
        if not contracts:
            return

        for contract in contracts:
            cid = contract.get("id") or contract.get("ticker") or contract.get("token_id", "")
            if not cid:
                continue

            expiry = self.engine.get_contract_expiry(cid)
            if expiry:
                now = datetime.datetime.now(datetime.timezone.utc)
                remaining = (expiry - now).total_seconds()
                duration_secs = self.config.contract_duration_minutes * 60

                if remaining < self.config.contract_duration_minutes * 60 * 0.1:
                    continue

                pct_elapsed = 1 - (remaining / duration_secs) if duration_secs > 0 else 1.0
                if pct_elapsed > 0.80:
                    continue
                if pct_elapsed < (self.config.contract_duration_minutes * 60 - remaining) / duration_secs * 0.1:
                    pass

            self.engine.process_contract(cid)

        self._check_expirations()

    def _check_expirations(self):
        """Resolve expired positions."""
        now = datetime.datetime.now(datetime.timezone.utc)
        expired = []
        for cid, pos in self.engine.state.positions.items():
            if pos.expiry_time and now >= pos.expiry_time:
                expired.append(cid)

        for cid in expired:
            logger.info(f"Contract expired: {cid} — resolution pending")

    def _handle_stop(self, signum, frame):
        logger.info("Shutdown signal received")
        self._stop = True

    def _print_summary(self):
        summary = self.engine.get_performance_summary()
        logger.info("=" * 50)
        logger.info("EXECUTION SUMMARY")
        for k, v in summary.items():
            logger.info(f"  {k}: {v}")
        logger.info("=" * 50)

    def stop(self):
        self._stop = True
