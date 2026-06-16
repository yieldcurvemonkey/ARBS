"""
Kalshi LOB collection and reconstruction runner.

Main entry point for:
    1. Collecting live LOB data (WebSocket + REST)
    2. Reconstructing full order books from saved data
    3. Querying the reconstructed LOB database

Usage:
    # Collect data for BTC markets (REST-only, 5 minutes)
    conda run -n stir python -m OBI.kalshi_lob.runner collect --duration 300 --filter btc

    # Collect with WebSocket (full pipeline)
    conda run -n stir python -m OBI.kalshi_lob.runner collect --ws --duration 3600

    # Reconstruct today's data
    conda run -n stir python -m OBI.kalshi_lob.runner reconstruct --date today

    # Query LOB for a specific market
    conda run -n stir python -m OBI.kalshi_lob.runner query --ticker KXBTC-... --date 2026-06-04
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OBI.kalshi_lob.collector import KalshiLOBCollector
from OBI.kalshi_lob.reconstructor import reconstruct_date
from OBI.kalshi_lob.storage import LOBStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def collect(
    duration: float = 300,
    use_ws: bool = False,
    filter_str: Optional[str] = None,
    max_markets: int = 100,
    snapshot_interval: float = 900,
    poll_interval: float = 10,
    storage_dir: Optional[str] = None,
    api_key_id: str = "",
    private_key_path: Optional[str] = None,
):
    """Run data collection."""
    private_key_pem = None
    if private_key_path:
        private_key_pem = Path(private_key_path).read_text()

    storage = LOBStorage(Path(storage_dir) if storage_dir else None)
    collector = KalshiLOBCollector(
        api_key_id=api_key_id,
        private_key_pem=private_key_pem,
        storage=storage,
        snapshot_interval_seconds=snapshot_interval,
        max_markets=max_markets,
    )

    if filter_str:
        all_tickers = collector.discover_active_markets()
        filtered = [t for t in all_tickers if filter_str.lower() in t.lower()]
        collector.market_tickers = set(filtered)
        collector.auto_discover = False
        logger.info(f"Filtered to {len(filtered)} markets matching '{filter_str}'")

    if use_ws:
        collector.run(duration_seconds=duration)
    else:
        collector.run_rest_only(duration_seconds=duration, poll_interval=poll_interval)

    logger.info(f"Collection stats: {collector.stats()}")


def reconstruct(
    date_str: str = "today",
    storage_dir: Optional[str] = None,
    emit_every_delta: bool = True,
    tickers: Optional[List[str]] = None,
):
    """Reconstruct LOB from stored data."""
    if date_str == "today":
        date = datetime.date.today()
    else:
        date = datetime.date.fromisoformat(date_str)

    storage = LOBStorage(Path(storage_dir) if storage_dir else None)
    result = reconstruct_date(
        storage, date,
        market_tickers=tickers,
        emit_every_delta=emit_every_delta,
    )

    if result.empty:
        logger.warning(f"No data to reconstruct for {date}")
        return

    logger.info(f"Reconstructed {len(result)} LOB rows")
    logger.info(f"Markets: {result['market_ticker'].nunique()}")
    logger.info(f"Time range: {result['ts'].min()} — {result['ts'].max()}")

    for side in ("yes", "no"):
        s = result[result["side"] == side]
        if not s.empty:
            logger.info(f"  {side}: {len(s)} levels, depth range [{s['qty'].min():.0f}, {s['qty'].max():.0f}]")


def query(
    ticker: str,
    date_str: str = "today",
    storage_dir: Optional[str] = None,
    last_n: int = 20,
):
    """Query reconstructed LOB data."""
    if date_str == "today":
        date = datetime.date.today()
    else:
        date = datetime.date.fromisoformat(date_str)

    storage = LOBStorage(Path(storage_dir) if storage_dir else None)
    lob = storage.read_lob(date, market_ticker=ticker)

    if lob.empty:
        logger.warning(f"No LOB data for {ticker} on {date}")
        logger.info(f"Available dates: {storage.list_dates('lob')}")
        return

    logger.info(f"LOB data for {ticker} on {date}: {len(lob)} rows")
    logger.info(f"Time range: {lob['ts'].min()} — {lob['ts'].max()}")
    logger.info(f"Unique timestamps: {lob['ts'].nunique()}")

    last_ts = lob["ts"].max()
    last_book = lob[lob["ts"] == last_ts].sort_values(["side", "price"])
    print(f"\nLatest book state ({last_ts}):")
    print(last_book.to_string(index=False))

    trades = storage.read_trades(date)
    if not trades.empty:
        t = trades[trades["market_ticker"] == ticker]
        if not t.empty:
            print(f"\nTrades ({len(t)} total):")
            print(t.tail(last_n).to_string(index=False))


def status(storage_dir: Optional[str] = None):
    """Show what data is available."""
    storage = LOBStorage(Path(storage_dir) if storage_dir else None)
    for stream in ["deltas", "snapshots", "trades", "lob"]:
        dates = storage.list_dates(stream)
        if dates:
            print(f"{stream}: {len(dates)} dates ({dates[0]} — {dates[-1]})")
        else:
            print(f"{stream}: no data")


def main():
    parser = argparse.ArgumentParser(description="Kalshi LOB Collector & Reconstructor")
    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", help="Collect live LOB data")
    p_collect.add_argument("--duration", type=float, default=300)
    p_collect.add_argument("--ws", action="store_true", help="Use WebSocket (else REST-only)")
    p_collect.add_argument("--filter", type=str, default=None, help="Filter market tickers")
    p_collect.add_argument("--max-markets", type=int, default=100)
    p_collect.add_argument("--snapshot-interval", type=float, default=900)
    p_collect.add_argument("--poll-interval", type=float, default=10)
    p_collect.add_argument("--dir", type=str, default=None)
    p_collect.add_argument("--api-key", type=str, default="dcd3316c-192d-4d1e-9049-832d46fd9564")
    p_collect.add_argument("--key-path", type=str, default=None)

    p_recon = sub.add_parser("reconstruct", help="Reconstruct LOB from saved data")
    p_recon.add_argument("--date", type=str, default="today")
    p_recon.add_argument("--dir", type=str, default=None)
    p_recon.add_argument("--tickers", nargs="*", default=None)
    p_recon.add_argument("--no-emit-every", action="store_true")

    p_query = sub.add_parser("query", help="Query reconstructed LOB")
    p_query.add_argument("--ticker", type=str, required=True)
    p_query.add_argument("--date", type=str, default="today")
    p_query.add_argument("--dir", type=str, default=None)
    p_query.add_argument("--last", type=int, default=20)

    p_status = sub.add_parser("status", help="Show available data")
    p_status.add_argument("--dir", type=str, default=None)

    args = parser.parse_args()

    if args.command == "collect":
        collect(
            duration=args.duration,
            use_ws=args.ws,
            filter_str=args.filter,
            max_markets=args.max_markets,
            snapshot_interval=args.snapshot_interval,
            poll_interval=args.poll_interval,
            storage_dir=args.dir,
            api_key_id=args.api_key,
            private_key_path=args.key_path,
        )
    elif args.command == "reconstruct":
        reconstruct(
            date_str=args.date,
            storage_dir=args.dir,
            emit_every_delta=not args.no_emit_every,
            tickers=args.tickers,
        )
    elif args.command == "query":
        query(
            ticker=args.ticker,
            date_str=args.date,
            storage_dir=args.dir,
            last_n=args.last,
        )
    elif args.command == "status":
        status(storage_dir=args.dir)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
