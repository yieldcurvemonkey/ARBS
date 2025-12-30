from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

from SDRUtils.packages.base import PackageDetector
from SDRUtils.products.base import ProductModule


@dataclass
class SDRModuleRegistry:
    products: Dict[str, ProductModule] = field(default_factory=dict)
    packages: Dict[str, PackageDetector] = field(default_factory=dict)

    def register_product(self, product: ProductModule) -> None:
        self.products[product.name] = product

    def register_package(self, package: PackageDetector) -> None:
        self.packages[package.package_type] = package

    def get_product(self, name: str) -> Optional[ProductModule]:
        return self.products.get(name)

    def get_package(self, package_type: str) -> Optional[PackageDetector]:
        return self.packages.get(package_type)

    def iter_products(self) -> Iterable[ProductModule]:
        return self.products.values()

    def iter_packages(self) -> Iterable[PackageDetector]:
        return self.packages.values()


registry = SDRModuleRegistry()
