"""
Live execution engines for Polymarket and Kalshi.

Submit real orders via venue APIs.  Both inherit from BaseExecutionEngine
for shared signal generation and risk management.
"""
from __future__ import annotations

import datetime
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from OBI.config import ExecutionConfig
from OBI.execution.base import BaseExecutionEngine, Fill, OrderRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Polymarket live execution
# ---------------------------------------------------------------------------

class PolymarketExecutionEngine(BaseExecutionEngine):
    """Live execution on Polymarket CLOB using py-clob-client for EIP-712 signing."""

    CLOB_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"

    def __init__(self, config: ExecutionConfig):
        super().__init__(config)
        self._clob_client = None
        self._init_clob_client(config)

    def _init_clob_client(self, config: ExecutionConfig):
        """Initialize py-clob-client with proper authentication."""
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        if not config.poly_api_key:
            self._clob_client = ClobClient(self.CLOB_URL, chain_id=config.poly_chain_id)
            logger.info("Polymarket client initialized (Level 0 — read-only)")
            return

        if config.poly_api_secret and config.poly_api_passphrase:
            creds = ApiCreds(
                api_key=config.poly_api_key,
                api_secret=config.poly_api_secret,
                api_passphrase=config.poly_api_passphrase,
            )
            self._clob_client = ClobClient(
                self.CLOB_URL,
                chain_id=config.poly_chain_id,
                key=config.poly_api_key,
                creds=creds,
                funder=config.poly_funder or None,
            )
            logger.info("Polymarket client initialized (Level 2 — full trading)")
        else:
            self._clob_client = ClobClient(
                self.CLOB_URL,
                chain_id=config.poly_chain_id,
                key=config.poly_api_key,
                funder=config.poly_funder or None,
            )
            try:
                creds = self._clob_client.create_or_derive_api_creds()
                self._clob_client = ClobClient(
                    self.CLOB_URL,
                    chain_id=config.poly_chain_id,
                    key=config.poly_api_key,
                    creds=creds,
                    funder=config.poly_funder or None,
                )
                logger.info("Polymarket client initialized (Level 2 — derived creds)")
            except Exception as e:
                logger.warning(f"Could not derive L2 creds ({e}), using L1")

    def fetch_orderbook(self, contract_id: str) -> Dict[str, pd.DataFrame]:
        if self._clob_client:
            try:
                book = self._clob_client.get_order_book(contract_id)
                bids = pd.DataFrame(
                    [{"price": float(o.price), "quantity": float(o.size)} for o in book.bids],
                    columns=["price", "quantity"],
                )
                asks = pd.DataFrame(
                    [{"price": float(o.price), "quantity": float(o.size)} for o in book.asks],
                    columns=["price", "quantity"],
                )
                return {"bids": bids, "asks": asks}
            except Exception:
                pass
        from MDP.EventContracts.polymarket_orderbook import fetch_orderbook
        return fetch_orderbook(contract_id)

    def submit_order(self, order: OrderRequest) -> Optional[Fill]:
        """Submit EIP-712 signed order to Polymarket CLOB via py-clob-client."""
        from py_clob_client.clob_types import OrderArgs

        now = datetime.datetime.now(datetime.timezone.utc)

        if not self._clob_client:
            logger.error("No CLOB client initialized")
            return None

        side = "BUY" if order.side == "YES" else "SELL"

        order_args = OrderArgs(
            token_id=order.contract_id,
            price=order.price,
            size=order.quantity,
            side=side,
        )

        try:
            resp = self._clob_client.create_and_post_order(order_args)
            if resp and hasattr(resp, "id"):
                order_id = resp.id
            elif isinstance(resp, dict):
                order_id = resp.get("orderID") or resp.get("id", str(uuid.uuid4())[:8])
            else:
                order_id = str(uuid.uuid4())[:8]

            fee_rate = 0.02
            try:
                fee_rate = self._clob_client.get_fee_rate_bps() / 10000
            except Exception:
                pass

            return Fill(
                order_id=str(order_id),
                contract_id=order.contract_id,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                timestamp=now,
                fees=order.quantity * order.price * fee_rate,
            )
        except Exception as e:
            logger.error(f"Polymarket order failed: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        if not self._clob_client:
            return False
        try:
            self._clob_client.cancel(order_id)
            return True
        except Exception as e:
            logger.warning(f"Cancel failed: {e}")
            return False

    def cancel_all(self) -> bool:
        if not self._clob_client:
            return False
        try:
            self._clob_client.cancel_all()
            return True
        except Exception as e:
            logger.warning(f"Cancel all failed: {e}")
            return False

    def get_active_contracts(self) -> List[Dict[str, Any]]:
        """Search for active up/down contracts on Polymarket for the configured asset."""
        asset_keywords = getattr(self.config, "asset_keywords", ["btc", "bitcoin"])
        search_query = getattr(self.config, "asset_search_query", "bitcoin")
        try:
            if self._clob_client:
                markets = self._clob_client.get_markets()
                if isinstance(markets, list):
                    return [
                        m for m in markets
                        if isinstance(m, dict)
                        and any(kw in str(m.get("question", "")).lower()
                                for kw in asset_keywords)
                    ]
            from MDP.EventContracts.polymarket_orderbook import search_markets
            markets = search_markets(query=search_query, active=True, limit=50)
            return [
                m for m in markets
                if any(kw in (m.get("question", "") + m.get("title", "")).lower()
                       for kw in asset_keywords)
                and any(kw in (m.get("question", "") + m.get("title", "")).lower()
                        for kw in ["up", "down", "above", "below", "higher", "lower"])
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch Polymarket contracts: {e}")
            return []

    def get_contract_expiry(self, contract_id: str) -> Optional[datetime.datetime]:
        try:
            from MDP.EventContracts.polymarket_orderbook import fetch_market_info
            info = fetch_market_info(contract_id)
            end = info.get("endDate") or info.get("end_date_iso")
            if end:
                return pd.Timestamp(end).to_pydatetime()
        except Exception:
            pass
        return None

    def get_balance(self) -> Optional[float]:
        """Get USDC balance on Polymarket."""
        if not self._clob_client:
            return None
        try:
            bal = self._clob_client.get_balance_allowance()
            return float(bal.get("balance", 0)) if isinstance(bal, dict) else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Kalshi live execution
# ---------------------------------------------------------------------------

class KalshiExecutionEngine(BaseExecutionEngine):
    """Live execution on Kalshi."""

    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self, config: ExecutionConfig):
        super().__init__(config)
        self._api_key_id = config.kalshi_api_key_id
        self._private_key_pem = self._load_private_key(config.kalshi_private_key_path)

    def _load_private_key(self, path: str) -> Optional[str]:
        if not path:
            default = Path(__file__).resolve().parents[1] / "MDP" / "EventContracts" / "arbs_mdp.txt"
            if default.exists():
                return default.read_text()
            return None
        p = Path(path)
        if p.exists():
            return p.read_text()
        return None

    def _auth_headers(self, method: str, path: str) -> Dict[str, str]:
        from MDP.EventContracts.kalshi_fetcher import build_kalshi_auth_headers
        return build_kalshi_auth_headers(method, path, self._api_key_id, self._private_key_pem)

    def fetch_orderbook(self, contract_id: str) -> Dict[str, pd.DataFrame]:
        from MDP.EventContracts.kalshi_fetcher import fetch_orderbook
        book = fetch_orderbook(
            contract_id,
            depth=20,
            api_key_id=self._api_key_id,
            private_key_pem=self._private_key_pem,
        )
        return {
            "bids": book.get("yes", pd.DataFrame(columns=["price", "quantity"])),
            "asks": book.get("no", pd.DataFrame(columns=["price", "quantity"])),
        }

    def submit_order(self, order: OrderRequest) -> Optional[Fill]:
        now = datetime.datetime.now(datetime.timezone.utc)
        path = "/trade-api/v2/portfolio/orders"

        payload = {
            "ticker": order.contract_id,
            "action": "buy",
            "side": order.side.lower(),
            "type": order.order_type,
            "count": int(order.quantity),
        }
        if order.order_type == "limit":
            payload["yes_price"] = int(order.price * 100)

        try:
            headers = self._auth_headers("POST", path)
            headers["Content-Type"] = "application/json"
            resp = requests.post(
                f"{self.BASE_URL}/portfolio/orders",
                json=payload,
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            order_data = data.get("order", {})

            return Fill(
                order_id=order_data.get("order_id", str(uuid.uuid4())[:8]),
                contract_id=order.contract_id,
                side=order.side,
                quantity=order.quantity,
                price=order.price,
                timestamp=now,
                fees=order.quantity * order.price * 0.07,
            )
        except Exception as e:
            logger.error(f"Kalshi order failed: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        try:
            headers = self._auth_headers("DELETE", path)
            resp = requests.delete(
                f"{self.BASE_URL}/portfolio/orders/{order_id}",
                headers=headers,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_active_contracts(self) -> List[Dict[str, Any]]:
        """Get active up/down contracts on Kalshi for the configured asset."""
        series_ticker = getattr(self.config, "asset_series_ticker", "KXBTC")
        asset_keywords = getattr(self.config, "asset_keywords", ["btc"])
        try:
            path = "/trade-api/v2/markets"
            params = {
                "status": "open",
                "series_ticker": series_ticker,
                "limit": 50,
            }
            headers = self._auth_headers("GET", path)
            resp = requests.get(
                f"{self.BASE_URL}/markets",
                params=params,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            markets = resp.json().get("markets", [])
            return [
                m for m in markets
                if any(kw in m.get("ticker", "").lower() for kw in asset_keywords)
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch Kalshi contracts: {e}")
            return []

    def get_contract_expiry(self, contract_id: str) -> Optional[datetime.datetime]:
        try:
            from MDP.EventContracts.kalshi_fetcher import fetch_market_metadata
            meta = fetch_market_metadata(contract_id)
            if meta:
                exp = meta.get("close_time") or meta.get("expiration_time")
                if exp:
                    return pd.Timestamp(exp).to_pydatetime()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_execution_engine(config: ExecutionConfig) -> BaseExecutionEngine:
    """Create the appropriate execution engine based on config."""
    from OBI.execution.paper import PaperExecutionEngine

    if config.mode == "paper":
        engine = PaperExecutionEngine(config)
        if config.venue == "polymarket":
            from MDP.EventContracts.polymarket_orderbook import fetch_orderbook
            class PolyFetcher:
                @staticmethod
                def fetch_orderbook(cid):
                    return fetch_orderbook(cid)
            engine.set_venue_fetcher(PolyFetcher())
        return engine
    elif config.mode == "live":
        if config.venue == "polymarket":
            return PolymarketExecutionEngine(config)
        elif config.venue == "kalshi":
            return KalshiExecutionEngine(config)
    raise ValueError(f"Unknown mode/venue: {config.mode}/{config.venue}")
