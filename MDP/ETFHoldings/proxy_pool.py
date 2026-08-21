"""Rotating SOCKS5 exits, so no single IP takes the whole request budget.

Why
---
BlackRock's holdings endpoint is behind an Akamai WAF that counts per source IP.
Measured 2026-08-20: a six-worker backfill got 143 documents and was then served
``403 Access Denied`` for every subsequent request, and the block was **IP-level** --
plain ``curl`` from the same machine was refused identically, so it was neither a TLS
fingerprint nor a header problem and no amount of dressing the request would have fixed
it. From behind any of the eight NordVPN US exits the repo's Barchart fetchers already
use, the same request returned 200 while the direct address was still blocked.

So the fix is the one the Barchart path in ``MDP/USTFutures/USTFuturesMDP.py`` and
``SDRUtils/_swappulse_scripts/ingest_listed_option_oi_volume.py`` already uses: hold a
pool of exits and spread the load across it. Credentials resolve the same way
(``NORDVPN_USER`` / ``NORDVPN_PASS``, with the same in-repo defaults), so this module
adds no new secret and no new dependency -- ``socksio`` and ``requests[socks]`` are
already installed.

What is different here
----------------------
Barchart's chooser picks **one** proxy and holds it for a TTL. That suits a burst of a
few calls. This is a 20,000-request backfill, so a single held exit would simply move
the 143-request cliff from one IP to another. Instead:

* every request takes the next healthy exit, round robin, so each sees 1/N of the rate;
* each exit has its **own** token bucket, so aggregate throughput scales with the pool
  while per-IP rate stays under what tripped the WAF;
* a 403 benches that exit for a cooldown and rotation continues on the rest, rather
  than the whole run stopping for one unhappy edge node; and
* if every exit is benched the caller is told, loudly, instead of being handed a stream
  of refusals to record as data.

The pool deliberately includes the direct connection (``None``) as one more "exit".
It is the fastest one when it works, and it is benched by the same rule when it does not.
"""

from __future__ import annotations

import itertools
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

#: The US exits the repo's Barchart fetchers use. ``None`` is the direct connection.
DEFAULT_HOSTS: Tuple[Optional[str], ...] = (
    "atlanta.us.socks.nordhold.net",
    "chicago.us.socks.nordhold.net",
    "dallas.us.socks.nordhold.net",
    "los-angeles.us.socks.nordhold.net",
    "new-york.us.socks.nordhold.net",
    "phoenix.us.socks.nordhold.net",
    "san-francisco.us.socks.nordhold.net",
    "us.socks.nordhold.net",
    None,
)


def build_socks5h(host: str) -> Dict[str, str]:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
    return {"http": url, "https": url}


@dataclass
class _Exit:
    host: Optional[str]
    proxies: Optional[Dict[str, str]]
    session: requests.Session = field(default_factory=requests.Session)
    next_ok: float = 0.0          # monotonic time this exit may next be used
    benched_until: float = 0.0    # monotonic time this exit comes off the bench
    n_ok: int = 0
    n_blocked: int = 0

    @property
    def label(self) -> str:
        return self.host or "direct"


class ProxyPool:
    """Round-robin exits with a per-exit rate limit and per-exit bench on refusal."""

    def __init__(
        self,
        hosts: Tuple[Optional[str], ...] = DEFAULT_HOSTS,
        *,
        per_exit_rate: float = 0.75,
        bench_seconds: float = 900.0,
        transient_bench_seconds: float = 90.0,
        retry_dead_after: float = 300.0,
        preflight: bool = True,
        preflight_timeout: float = 12.0,
    ):
        self._lock = threading.RLock()
        self.per_exit_gap = 1.0 / max(1e-6, per_exit_rate)
        self.bench_seconds = bench_seconds
        self.transient_bench_seconds = transient_bench_seconds

        # An exit that fails preflight is BENCHED, not dropped. Measured within twenty
        # minutes on one afternoon: all eight SOCKS hosts answered 200, then all eight
        # refused every connection, then the direct address -- which had been WAF-blocked
        # -- started working again. Availability here is a weather system, and a pool
        # fixed at startup ends up permanently one-ninth of its real size because of how
        # the weather happened to be during the first two seconds of the run.
        exits: List[_Exit] = []
        n_up = 0
        for h in hosts:
            proxies = None
            if h is not None:
                try:
                    proxies = build_socks5h(h)
                except Exception:
                    continue
            ex = _Exit(host=h, proxies=proxies)
            if preflight and not self._preflight(ex, preflight_timeout):
                ex.benched_until = time.monotonic() + retry_dead_after
            else:
                n_up += 1
            exits.append(ex)

        if not exits:
            raise RuntimeError("No exits configured at all -- check the hosts list.")
        if n_up == 0:
            raise RuntimeError(
                "No exit passed preflight: every SOCKS host refused AND the direct "
                "connection failed. Check NORDVPN_USER/NORDVPN_PASS and the network."
            )
        random.shuffle(exits)
        self.exits = exits
        self.retry_dead_after = retry_dead_after
        self._cycle = itertools.cycle(range(len(exits)))
        print(f"proxy pool: {n_up}/{len(exits)} exits up at start "
              f"(the rest are benched and retried, not dropped)", flush=True)

    @staticmethod
    def _preflight(ex: _Exit, timeout: float, attempts: int = 3) -> bool:
        """Is this exit usable? Retried, because a one-shot probe under-counts the pool.

        Measured: probing all nine exits once each with a 12 s timeout admitted **two**;
        the same hosts had all answered 200 moments earlier. A cold SOCKS handshake to a
        distant edge node is routinely slower than one round trip, and dropping an exit
        on that basis quietly shrinks aggregate throughput by 4x -- which on a
        20,000-request backfill is the difference between an hour and half a day.
        """
        for i in range(attempts):
            try:
                r = ex.session.get(
                    "https://api.ipify.org?format=json",
                    proxies=ex.proxies, timeout=timeout * (1 + i), headers={"Connection": "close"},
                )
                r.raise_for_status()
                return True
            except Exception:
                time.sleep(0.5 * (i + 1))
        return False

    # ------------------------------------------------------------------ scheduling

    def acquire(self, *, wait_timeout: float = 1800.0) -> _Exit:
        """Next exit that is neither benched nor inside its own rate gap.

        Blocks until one is available. Raises when the whole pool is benched for longer
        than ``wait_timeout`` -- the caller must hear that rather than keep requesting.
        """
        deadline = time.monotonic() + wait_timeout
        while True:
            with self._lock:
                now = time.monotonic()
                best: Optional[_Exit] = None
                best_at = float("inf")
                for _ in range(len(self.exits)):
                    ex = self.exits[next(self._cycle)]
                    ready = max(ex.next_ok, ex.benched_until)
                    if ready <= now:
                        ex.next_ok = now + self.per_exit_gap * random.uniform(0.8, 1.3)
                        return ex
                    if ready < best_at:
                        best, best_at = ex, ready
                sleep_for = min(5.0, max(0.05, best_at - now)) if best else 1.0
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Every exit is benched. Pool state: "
                    f"{ {e.label: (e.n_ok, e.n_blocked) for e in self.exits} }"
                )
            time.sleep(sleep_for)

    def report_ok(self, ex: _Exit) -> None:
        with self._lock:
            ex.n_ok += 1

    def report_blocked(self, ex: _Exit, *, transient: bool = False) -> None:
        """Bench an exit. ``transient=True`` for a connection error rather than a refusal.

        The two are different weather. A 403 is a WAF decision about this IP and will
        outlast several minutes; a SOCKS connection error is usually the edge node being
        briefly unreachable and clears in under two. Benching both for fifteen minutes
        would have retired the entire proxy pool over one bad minute.
        """
        with self._lock:
            ex.n_blocked += 1
            ex.benched_until = time.monotonic() + (
                self.transient_bench_seconds if transient else self.bench_seconds
            )

    def status(self) -> str:
        with self._lock:
            now = time.monotonic()
            parts = []
            for e in self.exits:
                tag = "" if e.benched_until <= now else f" BENCHED {e.benched_until - now:.0f}s"
                parts.append(f"{e.label}:{e.n_ok}/{e.n_blocked}{tag}")
            return "  ".join(parts)

    @property
    def n_live(self) -> int:
        now = time.monotonic()
        return sum(1 for e in self.exits if e.benched_until <= now)
