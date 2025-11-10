"""Asset abstraction for polymorphic return calculation."""

from .Base import Asset, AssetTransition
from .PriceFuture import PriceFuture

__all__ = ['Asset', 'AssetTransition', 'PriceFuture']
