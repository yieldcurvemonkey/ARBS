"""Run Kalshi LOB collector as a long-running daemon.

Usage:
    python scripts/run_kalshi_lob_collector.py
"""
import sys
import logging
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(
            Path.home() / ".cache" / "arbs" / "kalshi_lob" / "collector.log",
            mode="a",
        ),
    ],
)

from OBI.kalshi_lob.collector import KalshiLOBCollector
from OBI.kalshi_lob.storage import LOBStorage

KALSHI_API_KEY_ID = "dcd3316c-192d-4d1e-9049-832d46fd9564"

storage = LOBStorage()
collector = KalshiLOBCollector(
    api_key_id=KALSHI_API_KEY_ID,
    storage=storage,
    snapshot_interval_seconds=900,
    max_markets=500,
)

collector.run(duration_seconds=86400)
