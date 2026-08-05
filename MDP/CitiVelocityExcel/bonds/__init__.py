r"""Citi Velocity bonds: universe, conventions, and both pricing backends.

``RATES.BOND`` has zero children in the DAG, so bonds are a two-step mechanism:
``CVCURVEBOND`` returns the ISIN universe for a country, and
``RATES.BOND.<ISIN>.<value>`` returns one bond's timeseries. Velocity supplies
quotes only - no ``CVD*`` pricer is entitled - so every analytic here is built
in rateslib 2.1.1 and QuantLib 1.41 from those quotes.

Layout
------
``universe``     ``BondDescriptor``, the description parser, ``BondUniverse``
``conventions``  the per-country ``BondConvention`` table, with provenance
``rl_bonds``     ``build_rl_bond`` / ``rl_bond_metrics``
``ql_bonds``     ``build_ql_bond`` / ``ql_bond_metrics`` / ``ql_asset_swap_spread``

``cross_currency_asw_legs`` lives in ``universe`` rather than ``ql_bonds``: it
answers a catalog question ("which ``ASW_4_<CCY>`` tags were validated for this
ISIN") and needs no QuantLib. It is re-exported from both.

Both backends report ``bps`` and ``dv01`` POSITIVE for a long position. See
``rl_bonds``'s module docstring for why one convention was forced.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.bonds.conventions import (
    BOND_CONVENTIONS,
    BondConvention,
    approximate_countries,
    conventions_for,
    country_for_currency,
    supported_countries,
)
from MDP.CitiVelocityExcel.bonds.ql_bonds import (
    build_ql_bond,
    ql_asset_swap_spread,
    ql_bond_metrics,
    to_ql_date,
)
from MDP.CitiVelocityExcel.bonds.rl_bonds import (
    build_rl_bond,
    pseudo_issue_date,
    rl_bond_metrics,
    rl_settlement_date,
)
from MDP.CitiVelocityExcel.bonds.universe import (
    ASW_CURRENCIES,
    BondDescriptor,
    BondUniverse,
    cross_currency_asw_legs,
    fetch_universe,
    parse_bond_description,
)

__all__ = [
    "ASW_CURRENCIES",
    "BOND_CONVENTIONS",
    "BondConvention",
    "BondDescriptor",
    "BondUniverse",
    "approximate_countries",
    "build_ql_bond",
    "build_rl_bond",
    "conventions_for",
    "country_for_currency",
    "cross_currency_asw_legs",
    "fetch_universe",
    "parse_bond_description",
    "pseudo_issue_date",
    "ql_asset_swap_spread",
    "ql_bond_metrics",
    "rl_bond_metrics",
    "rl_settlement_date",
    "supported_countries",
    "to_ql_date",
]
