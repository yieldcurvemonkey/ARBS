"""
Central registry for SDR product and package modules.

This module provides a global registry for discovering and accessing
registered products and package detectors. Products are registered
by name and can also be looked up by currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, TYPE_CHECKING

from SDRUtils.packages.base import PackageDetector

if TYPE_CHECKING:
    from SDRUtils.products.base import ProductModule


@dataclass
class SDRModuleRegistry:
    """
    Central registry for SDR products and package detectors.

    Products are registered by their unique name (e.g., "USD-SOFR-OIS")
    and can also be looked up by currency or product type.

    Package detectors are registered by their package type (e.g., "FLY", "CURVE").
    """

    products: Dict[str, ProductModule] = field(default_factory=dict)
    packages: Dict[str, PackageDetector] = field(default_factory=dict)

    # Secondary indices for faster lookups
    _products_by_currency: Dict[str, List[ProductModule]] = field(default_factory=dict)
    _products_by_type: Dict[str, List[ProductModule]] = field(default_factory=dict)

    def register_product(self, product: ProductModule) -> None:
        """
        Register a product module.

        Args:
            product: ProductModule instance to register
        """
        self.products[product.name] = product

        # Update secondary indices
        if product.currency:
            if product.currency not in self._products_by_currency:
                self._products_by_currency[product.currency] = []
            self._products_by_currency[product.currency].append(product)

        if product.product_type:
            if product.product_type not in self._products_by_type:
                self._products_by_type[product.product_type] = []
            self._products_by_type[product.product_type].append(product)

    def register_package(self, package: PackageDetector) -> None:
        """
        Register a package detector.

        Args:
            package: PackageDetector instance to register
        """
        self.packages[package.package_type] = package

    def get_product(self, name: str) -> Optional[ProductModule]:
        """
        Get a product by name.

        Args:
            name: Product name (e.g., "USD-SOFR-OIS")

        Returns:
            ProductModule or None if not found
        """
        return self.products.get(name)

    def get_package(self, package_type: str) -> Optional[PackageDetector]:
        """
        Get a package detector by type.

        Args:
            package_type: Package type (e.g., "FLY", "CURVE")

        Returns:
            PackageDetector or None if not found
        """
        return self.packages.get(package_type)

    def get_products_by_currency(self, currency: str) -> List[ProductModule]:
        """
        Get all products for a specific currency.

        Args:
            currency: Currency code (e.g., "USD", "EUR")

        Returns:
            List of ProductModule instances for that currency
        """
        return self._products_by_currency.get(currency.upper(), [])

    def get_products_by_type(self, product_type: str) -> List[ProductModule]:
        """
        Get all products of a specific type.

        Args:
            product_type: Product type (e.g., "OIS_SWAP", "SWAPTION")

        Returns:
            List of ProductModule instances of that type
        """
        return self._products_by_type.get(product_type, [])

    def iter_products(self) -> Iterable[ProductModule]:
        """Iterate over all registered products."""
        return self.products.values()

    def iter_packages(self) -> Iterable[PackageDetector]:
        """Iterate over all registered package detectors."""
        return self.packages.values()

    def list_products(self) -> List[str]:
        """Get list of all registered product names."""
        return list(self.products.keys())

    def list_packages(self) -> List[str]:
        """Get list of all registered package types."""
        return list(self.packages.keys())

    def list_currencies(self) -> List[str]:
        """Get list of all currencies with registered products."""
        return list(self._products_by_currency.keys())

    def list_product_types(self) -> List[str]:
        """Get list of all product types with registered products."""
        return list(self._products_by_type.keys())

    def summary(self) -> Dict[str, object]:
        """
        Get a summary of registered modules.

        Returns:
            Dict with counts and lists of registered modules
        """
        return {
            "products": {
                "count": len(self.products),
                "names": self.list_products(),
                "currencies": self.list_currencies(),
                "types": self.list_product_types(),
            },
            "packages": {
                "count": len(self.packages),
                "types": self.list_packages(),
            },
        }


# Global registry instance
registry = SDRModuleRegistry()


def get_registry() -> SDRModuleRegistry:
    """Get the global registry instance."""
    return registry
