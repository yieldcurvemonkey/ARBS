"""Asset abstraction for polymorphic return calculation."""

from .Base import Asset, AssetTransition
from .PriceFuture import PriceFuture
from .RollableFuture import RollableFuture

__all__ = ['Asset', 'AssetTransition', 'PriceFuture', 'RollableFuture']
