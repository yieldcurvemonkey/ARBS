from __future__ import annotations

import datetime
from typing import Any

from Query.Base.BaseQuery import BaseQuery


def resolve_query(
    q: BaseQuery,
    *,
    timestamp: datetime.datetime,
    pricer_or_curve: Any,
) -> BaseQuery:
    """
    Centralize resolution behind BaseQuery.resolve_query().

    Contract:
      - resolve_query returns a Query (BaseQuery) instance
      - it "cleans up/hydrates" the user-supplied query

    If resolve_query isn't implemented, returns q unchanged.
    """
    if not hasattr(q, "resolve_query"):
        return q
    q2 = q.resolve_query(timestamp, pricer_or_curve=pricer_or_curve)
    if not isinstance(q2, BaseQuery):
        raise TypeError(f"{type(q).__name__}.resolve_query must return BaseQuery, got {type(q2)}")
    return q2


def resolve_for_request(q: BaseQuery, *, timestamp: datetime.datetime) -> BaseQuery:
    """
    Used by request builders to build MDP requests.

    If resolve_query does not require market data, it should tolerate pricer_or_curve=None.
    We provide a fallback value if None is not accepted.
    """
    try:
        return resolve_query(q, timestamp=timestamp, pricer_or_curve=None)
    except Exception:
        # fallback: some implementations require a non-None object
        return resolve_query(q, timestamp=timestamp, pricer_or_curve={})
