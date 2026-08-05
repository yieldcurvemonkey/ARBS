r"""Citi Velocity as a first-class ARBS market-data source, over the Excel add-in.

The add-in is the only sanctioned client: its REST endpoints require a request
signature produced inside ``Citi.Velocity.Web.dll`` from DPAPI-sealed material, so
we drive the add-in rather than impersonate it. That means every fetch runs
through a **human-logged-in Excel** - there is no headless path.

Velocity supplies quotes only. The ``CVD*`` pricers, ``CVCALCDERIVATIVES``,
``CVLADDER``, ``CVSCENARIOANALYSIS`` and every portfolio function are not
entitled. So all curve stripping, cube construction and bond analytics in this
package are built in rateslib and QuantLib **from Citi quotes**.

Layers
------
``com_client``   the COM bridge: connect, write, poll, read, parse
``block_parser`` pure parsers for the blocks the add-in writes (no COM)
``catalog``      the harvested ``RATES.*`` grammar and path-consistent generation
``tags``         typed tag builders derived from that catalog
``cache``        incremental parquet store keyed ``(tag, freq, price_point)``
``source``       the ``citivelo_excel`` MDP source over cached-then-live tags
``mdp``          ``CitiVelocityMDP.get_pricer`` -> a snapshot that builds curves,
                 cubes and bonds on demand in both rateslib and QuantLib
``curves`` / ``vol`` / ``bonds`` / ``inflation`` / ``xccy`` / ``options``
                 the analytics built from those quotes
``testing``      a faithful fake of the Excel COM surface, for hermetic tests

Distinct from the existing ``citivelo`` source in ``MDP/IRSwaps``: that one builds
a rateslib USD-SOFR curve from a hand-saved workbook and is pinned by 930 warmed
CurveStore partitions plus the dealer-ladder study. Nothing here changes it.
"""

from __future__ import annotations

from MDP.CitiVelocityExcel.block_parser import (
    MetadataRow,
    TshistBlock,
    parse_curve_block,
    parse_metadata_block,
    parse_tshist_block,
)
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, Coverage, default_cache_dir
from MDP.CitiVelocityExcel.catalog import BondRef, CitiVeloCatalog, sort_tenors
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import (
    AddInNotSignedInError,
    AsyncTimeoutError,
    CatalogError,
    CitiVelocityError,
    ExcelDiedError,
    ExcelNotRunningError,
    FrequencyError,
    UnknownTagError,
)
from MDP.CitiVelocityExcel.excel_constants import FREQUENCIES, PRICE_POINTS

__all__ = [
    "AddInNotSignedInError",
    "AsyncTimeoutError",
    "BondRef",
    "CatalogError",
    "CitiVelocityError",
    "CitiVelocityExcelClient",
    "CitiVeloCatalog",
    "CitiVeloTagCache",
    "Coverage",
    "ExcelDiedError",
    "ExcelNotRunningError",
    "FREQUENCIES",
    "FrequencyError",
    "MetadataRow",
    "PRICE_POINTS",
    "TshistBlock",
    "UnknownTagError",
    "default_cache_dir",
    "parse_curve_block",
    "parse_metadata_block",
    "parse_tshist_block",
    "sort_tenors",
]
