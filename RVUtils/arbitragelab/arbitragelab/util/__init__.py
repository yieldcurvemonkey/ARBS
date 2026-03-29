"""Utility exports."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "DataImporter": ("arbitragelab.util.data_importer", "DataImporter"),
        "IndexedHighlight": ("arbitragelab.util.indexed_highlight", "IndexedHighlight"),
        "get_classification_data": (
            "arbitragelab.util.generate_dataset",
            "get_classification_data",
        ),
        "SpreadModelingHelper": (
            "arbitragelab.util.spread_modeling_helper",
            "SpreadModelingHelper",
        ),
        "BaseFuturesRoller": ("arbitragelab.util.rollers", "BaseFuturesRoller"),
        "CrudeOilFutureRoller": ("arbitragelab.util.rollers", "CrudeOilFutureRoller"),
        "NBPFutureRoller": ("arbitragelab.util.rollers", "NBPFutureRoller"),
        "RBFutureRoller": ("arbitragelab.util.rollers", "RBFutureRoller"),
    },
)
