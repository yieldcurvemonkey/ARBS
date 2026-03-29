"""Tear sheet exports."""

from arbitragelab._lazy import attach_lazy_exports

__all__, __getattr__, __dir__ = attach_lazy_exports(
    __name__,
    {
        "TearSheet": ("arbitragelab.tearsheet.tearsheet", "TearSheet"),
    },
)
