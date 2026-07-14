"""Shared IMM date resolution for IRSwap and STIRFuture query patterns."""

from __future__ import annotations

import datetime
from typing import Union

from rateslib.scheduling import get_imm, next_imm


def resolve_imm_token(
    token: str,
    ref_date: Union[datetime.date, datetime.datetime],
) -> Union[datetime.date, datetime.datetime]:
    """Resolve an IMM token to a concrete date.

    Accepted formats:
      - "IMM_1"  .. "IMM_N"   → Nth quarterly IMM date after ref_date
      - "IMM_H26"             → specific IMM by month-code + 2-digit year
      - "IMM_H2026"           → same, 4-digit year normalised to 2-digit
    """
    raw = token.strip().upper()
    if not raw.startswith("IMM_"):
        raise ValueError(f"Not an IMM token: {token!r}")

    suffix = raw.split("IMM_")[-1]

    if suffix.isnumeric():
        offset = int(suffix) - 1
        ref_is_date = isinstance(ref_date, datetime.date) and not isinstance(
            ref_date, datetime.datetime
        )
        imm: Union[datetime.date, datetime.datetime] = ref_date + datetime.timedelta(days=1)
        if ref_is_date:
            imm = datetime.datetime(imm.year, imm.month, imm.day)
        for _ in range(offset + 1):
            imm = next_imm(imm)
        if ref_is_date:
            return imm.date() if isinstance(imm, datetime.datetime) else imm
        return imm

    code = suffix
    if len(code) == 5 and code[0].isalpha() and code[1:].isdigit():
        code = code[0] + code[3:]
    return get_imm(code=code)


def resolve_imm_tenor(
    tenor: str,
    ref_date: Union[datetime.date, datetime.datetime],
) -> tuple[Union[datetime.date, datetime.datetime], Union[datetime.date, datetime.datetime]]:
    """Resolve an IMM tenor string like "IMM_1xIMM_2" to (effective, maturity)."""
    if "x" not in tenor:
        raise ValueError(f"Expected 'x' separator in IMM tenor: {tenor!r}")
    eff_tok, mat_tok = tenor.split("x", 1)
    return resolve_imm_token(eff_tok, ref_date), resolve_imm_token(mat_tok, ref_date)
