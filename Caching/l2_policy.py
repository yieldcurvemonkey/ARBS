r"""Whether a store's Supabase L2 tier is on, read at call time and parsed strictly.

Two deliberate departures from ``Caching.supabase_engine``, both of them fixes
for a failure this repo has actually had.

**Read at call time, not import time.**
``supabase_engine`` evaluates ``SUPABASE_ENABLED`` and ``_DATABASE_URL`` as
module globals, so setting ``ARBS_SUPABASE_ENABLED`` *after* anything under
``Caching/`` has loaded does nothing. That is why four scripts open with
``os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")`` as their literal first
statement, why ``citivelo_curve_service.py``'s ``sync`` subcommand re-setting it
to ``"1"`` is a no-op if the module was already imported, and why
``citivelo_excel_warm.py --push-l2`` never did anything. A function that reads
the environment when asked has none of that.

**Parse strictly: an unrecognised token raises.**
``_env_enabled`` treats a closed falsy set ``{0,false,f,no,n,off}`` as disabled
and *everything else* as enabled. So ``ARBS_SUPABASE_ENABLED=disabled``,
``=none``, ``=nope`` or any typo silently mean **enabled**, and "enabled" here
means "pointed at production with hard-coded superuser credentials". The
failure mode of a mistyped opt-out must not be a live production connection, so
this vocabulary is closed on both sides and anything outside it is an error that
names the accepted values.

Three states rather than two, because ``ARBS_SUPABASE_ENABLED`` is
all-or-nothing - it kills reads *and* writes, so a service that must write
cannot use it defensively, and a consumer that only wants to read history
cannot say so.

    off         no engine is built, no DDL runs, nothing is read or written
    read        pull a missing partition from L2; never write
    read_write  pull, and push what is written locally

The default is :attr:`L2Mode.OFF` for every store that uses this. That is the
opposite of ``supabase_engine``'s default and it is the point: a new tier gets
the safe default because nothing depends on the unsafe one yet.
"""

from __future__ import annotations

import enum
import os
from typing import Optional

__all__ = [
    "L2Mode",
    "L2ModeError",
    "SWAPTION_CUBE_L2_ENV",
    "parse_l2_mode",
    "env_l2_mode",
    "swaption_cube_l2_mode",
]


class L2ModeError(ValueError):
    """An L2 mode env var was set to something outside the accepted vocabulary."""


class L2Mode(enum.Enum):
    OFF = "off"
    READ = "read"
    READ_WRITE = "read_write"

    @property
    def reads(self) -> bool:
        return self is not L2Mode.OFF

    @property
    def writes(self) -> bool:
        return self is L2Mode.READ_WRITE


#: Note ``disabled`` / ``none`` / ``null`` are OFF here. Under ``_env_enabled``
#: every one of them means ENABLED, which is the trap this closes.
_OFF_TOKENS = frozenset({"", "0", "off", "false", "f", "no", "n", "none", "null", "disabled"})
_READ_TOKENS = frozenset({"read", "ro", "readonly", "read_only", "read-only", "pull"})
_RW_TOKENS = frozenset(
    {"1", "on", "true", "t", "yes", "y", "rw", "readwrite", "read_write", "read-write", "push"}
)

_ACCEPTED = ", ".join(sorted(t for t in (_OFF_TOKENS | _READ_TOKENS | _RW_TOKENS) if t))


def parse_l2_mode(raw: Optional[str], *, var_name: str = "<env>") -> L2Mode:
    """Map an env-var value to a mode, or raise naming the accepted vocabulary."""
    token = (raw or "").strip().lower()
    if token in _OFF_TOKENS:
        return L2Mode.OFF
    if token in _READ_TOKENS:
        return L2Mode.READ
    if token in _RW_TOKENS:
        return L2Mode.READ_WRITE
    raise L2ModeError(
        f"{var_name}={raw!r} is not a recognised L2 mode. Accepted (case-insensitive): "
        f"{_ACCEPTED}. Unset or empty means off. This is deliberately strict: a typo "
        f"in an opt-out must not silently resolve to 'connect to production'."
    )


def env_l2_mode(var_name: str) -> L2Mode:
    """Current mode for ``var_name``, read from the environment right now."""
    return parse_l2_mode(os.environ.get(var_name), var_name=var_name)


#: Gate for :class:`Caching.swaption_cube_store.SwaptionCubeStore`'s L2 tier.
SWAPTION_CUBE_L2_ENV = "ARBS_SWAPTION_CUBE_L2"


def swaption_cube_l2_mode() -> L2Mode:
    """L2 mode for the swaption cube store. Off unless asked."""
    return env_l2_mode(SWAPTION_CUBE_L2_ENV)
