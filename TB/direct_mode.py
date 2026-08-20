r"""Whether a timeseries request bypasses every cache and reads the vendor directly.

Why this is not a bare boolean
------------------------------
It is spelled as a parsed, closed vocabulary for the same reason
:mod:`Caching.l2_policy` is: **the failure mode of a typo must not be "silently
use the cached path"**. ``direct="of"``, ``direct="no-cache"`` or
``direct="bypass"`` would all be truthy-or-falsy by accident under a bare
``bool()``, and the caller would never learn which. Here anything outside the
vocabulary raises and the message names what is accepted.

Two states, not three
---------------------
``l2_policy`` has three (``off`` / ``read`` / ``read_write``) because an L2 tier
can meaningfully read without writing. Direct mode has no such axis: it exists
precisely to touch no store at all, so its write policy is a constant, not a
setting.

    off     the normal cached path, unchanged in every respect
    live    read straight from the vendor; write NOTHING, anywhere

A "fetch live and also bank it" state was considered and deliberately left out.
Banking a live or partial intraday print into a store whose other consumers
assume settled end-of-day data is the exact cache-poisoning hazard this repo has
measured (``CitiVeloTagCache`` merges "incoming wins", so the poisoned value
wins), and nobody asked for it - the request was for *no* caching. The
vocabulary can grow a third token later without breaking the two that exist.

Note the corollary for reads: under ``live`` a request may still *fetch* more
tags than it strictly needs (a par-rate reprice needs the whole par grid), but
none of them is ever written down.
"""

from __future__ import annotations

import enum
from typing import Optional, Union

__all__ = ["DirectMode", "DirectModeError", "parse_direct_mode"]


class DirectModeError(ValueError):
    """A ``direct=`` argument was set to something outside the accepted vocabulary."""


class DirectMode(enum.Enum):
    OFF = "off"
    LIVE = "live"

    @property
    def enabled(self) -> bool:
        """True when caches must be bypassed for this request."""
        return self is DirectMode.LIVE

    @property
    def writes(self) -> bool:
        """Always False. Stated as a property so the write policy is greppable.

        A direct read persists nothing: not the vendor tag cache, not the
        computed-timeseries store, not its DuckDB mirror, not Supabase L2.
        """
        return False


#: ``cached`` is spelled here on purpose: it is the word a reader reaches for
#: when they mean "off", and having it mean something other than OFF would be a
#: trap.
_OFF_TOKENS = frozenset(
    {"", "off", "0", "false", "f", "no", "n", "none", "null", "disabled", "cached", "cache"}
)
_LIVE_TOKENS = frozenset(
    {"1", "on", "true", "t", "yes", "y", "live", "direct", "addin", "add_in", "add-in", "bypass"}
)

_ACCEPTED = ", ".join(sorted(t for t in (_OFF_TOKENS | _LIVE_TOKENS) if t))


def parse_direct_mode(
    raw: Union[None, bool, str, DirectMode],
    *,
    param_name: str = "direct",
) -> DirectMode:
    """Map a ``direct=`` argument to a :class:`DirectMode`, or raise naming the vocabulary.

    ``None`` and ``False`` mean :attr:`DirectMode.OFF`; ``True`` means
    :attr:`DirectMode.LIVE`. Strings are matched case-insensitively after
    stripping.

    Raises
    ------
    DirectModeError
        For anything else, including a plausible-looking near-miss. This is
        deliberately strict: a mistyped opt-IN must not silently resolve to
        "serve from cache", because the caller would then believe a cached
        number was live.
    """
    if isinstance(raw, DirectMode):
        return raw
    if raw is None or raw is False:
        return DirectMode.OFF
    if raw is True:
        return DirectMode.LIVE
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _OFF_TOKENS:
            return DirectMode.OFF
        if token in _LIVE_TOKENS:
            return DirectMode.LIVE
        raise DirectModeError(
            f"{param_name}={raw!r} is not a recognised direct mode. Accepted "
            f"(case-insensitive): {_ACCEPTED}. Unset, None or False mean off. This is "
            "deliberately strict: a typo in an opt-in must not silently resolve to "
            "'serve from cache', because you would then believe a cached number was live."
        )
    raise DirectModeError(
        f"{param_name}={raw!r} (type {type(raw).__name__}) is not a recognised direct mode. "
        f"Pass a bool, None, a DirectMode, or one of: {_ACCEPTED}."
    )


def resolve_direct_mode(
    call_value: Union[None, bool, str, DirectMode],
    instance_default: Optional[DirectMode],
    *,
    param_name: str = "direct",
) -> DirectMode:
    """Per-call argument wins when given; otherwise the instance default; else OFF.

    ``None`` at the call site means "not specified", which is why ``False`` and
    ``None`` are distinguishable here even though both parse to
    :attr:`DirectMode.OFF` - passing ``direct=False`` explicitly overrides an
    instance default of ``live``.
    """
    if call_value is not None:
        return parse_direct_mode(call_value, param_name=param_name)
    return instance_default or DirectMode.OFF
