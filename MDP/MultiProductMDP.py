"""
MultiProductMDP: A composite MDP for cross-product backtesting.

This module provides a wrapper that allows multiple MarketDataProviders (MDPs)
to be used together, routing requests to the appropriate MDP based on the
product type specified in the request.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from MDP.MarketDataProvider import MarketDataProvider


class MultiProductMDP(MarketDataProvider):
    """
    Composite MDP that routes requests to product-specific MDPs.

    This class enables cross-product backtesting by mapping product identifiers
    to their corresponding MarketDataProviders. When a request comes in, it's
    routed to the appropriate MDP based on the product field.

    Parameters
    ----------
    mdps : Dict[str, MarketDataProvider]
        Mapping of product identifiers to their MDPs.
        Common products: "IRS", "STIRFUTURE", "FRB"
    default_product : str, optional
        Product to use when no product is specified in the request.
        Defaults to the first product in the mdps dict.

    Examples
    --------
    >>> from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    >>> from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    >>>
    >>> multi_mdp = MultiProductMDP({
    ...     "IRS": IRSwapsMDP("SDR_INTRADAY-RL"),
    ...     "STIRFUTURE": STIRFutureMDP("BARCHART_STIRF-RL"),
    ... })
    >>>
    >>> # Now use multi_mdp in QueryDrivenBacktest
    >>> bt = QueryDrivenBacktest(
    ...     time_grid=my_grid,
    ...     mdp=multi_mdp,
    ...     strategy=my_strategy,
    ... )
    """

    def __init__(
        self,
        mdps: Dict[str, MarketDataProvider],
        default_product: Optional[str] = None,
        **kwargs: Any,
    ):
        if not mdps:
            raise ValueError("mdps dict must contain at least one MDP")

        # Use first product as default if not specified
        self._default_product = default_product or next(iter(mdps.keys()))
        self._mdps = mdps

        # Call parent init with a composite source name
        source = f"MultiProduct[{','.join(sorted(mdps.keys()))}]"
        super().__init__(source, **kwargs)

    @staticmethod
    def _canonical_product(product: str) -> str:
        alias_map = {
            "IRSWAPTIONS": "IRSWAPTION",
        }
        return alias_map.get(product, product)

    @property
    def mdps(self) -> Dict[str, MarketDataProvider]:
        """Return the mapping of products to MDPs."""
        return self._mdps

    @property
    def products(self) -> list[str]:
        """Return list of supported product identifiers."""
        return list(self._mdps.keys())

    @property
    def default_product(self) -> str:
        """Return the default product identifier."""
        return self._default_product

    def get_mdp_for_product(self, product: str) -> MarketDataProvider:
        """
        Get the MDP for a specific product.

        Parameters
        ----------
        product : str
            Product identifier (e.g., "IRS", "STIRFUTURE", "FRB")

        Returns
        -------
        MarketDataProvider
            The MDP configured for this product

        Raises
        ------
        KeyError
            If no MDP is registered for the product
        """
        canonical = self._canonical_product(product)
        if product not in self._mdps and canonical not in self._mdps:
            raise KeyError(f"No MDP registered for product '{product}'. " f"Available products: {sorted(self._mdps.keys())}")
        return self._mdps.get(product, self._mdps[canonical])

    def get(self, product: str) -> MarketDataProvider:
        return self.get_mdp_for_product(product=product)

    def get_pricer(self, request: Any) -> Any:
        """
        Get a pricer by routing to the appropriate product-specific MDP.

        The request dict should contain a 'product' key to determine routing.
        If no product is specified, uses the default product.

        Parameters
        ----------
        request : dict
            Request dict. Should contain 'product' key for routing.
            All other keys are passed to the underlying MDP.

        Returns
        -------
        Any
            The pricer returned by the product-specific MDP
        """
        if not isinstance(request, dict):
            raise TypeError(f"request must be a dict, got {type(request)}")

        # Extract product from request, use default if not specified
        req = dict(request)
        product = self._canonical_product(req.pop("product", self._default_product))

        mdp = self.get_mdp_for_product(product)
        return mdp.get_pricer(req)

    def __repr__(self) -> str:
        products = ", ".join(f"{k}: {type(v).__name__}" for k, v in self._mdps.items())
        return f"MultiProductMDP({{{products}}})"

    # Context manager support for MDPs that need it
    def __enter__(self):
        for mdp in self._mdps.values():
            if hasattr(mdp, "__enter__"):
                mdp.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        for mdp in self._mdps.values():
            if hasattr(mdp, "__exit__"):
                mdp.__exit__(exc_type, exc, tb)


# Type alias for either a single MDP or a product-to-MDP mapping
MDPLike = Union[MarketDataProvider, Dict[str, MarketDataProvider]]


def ensure_multi_mdp(mdp: MDPLike) -> MultiProductMDP:
    """
    Convert an MDP-like object to a MultiProductMDP.

    Parameters
    ----------
    mdp : MDPLike
        Either a single MarketDataProvider or a dict mapping products to MDPs.

    Returns
    -------
    MultiProductMDP
        A MultiProductMDP instance. If input is already a MultiProductMDP,
        returns it unchanged.

    Examples
    --------
    >>> # From dict
    >>> multi = ensure_multi_mdp({"IRS": irs_mdp, "STIRFUTURE": stir_mdp})
    >>>
    >>> # From single MDP (requires default_product to be inferred or specified)
    >>> multi = ensure_multi_mdp(irs_mdp)  # Will use "IRS" if MDP has product attr
    """
    if isinstance(mdp, MultiProductMDP):
        return mdp

    if isinstance(mdp, dict):
        return MultiProductMDP(mdp)

    # Support both MarketDataProvider subclasses and duck-typed objects with get_pricer
    if isinstance(mdp, MarketDataProvider) or hasattr(mdp, "get_pricer"):
        # For single MDP, try to infer product from MDP class name
        cls_name = type(mdp).__name__.upper()
        if "IRSWAPTION" in cls_name:
            return MultiProductMDP({"IRSWAPTION": mdp}, default_product="IRSWAPTION")
        elif "IRSWAP" in cls_name or "IRS" in cls_name:
            return MultiProductMDP({"IRS": mdp}, default_product="IRS")
        elif "STIR" in cls_name:
            return MultiProductMDP({"STIRFUTURE": mdp}, default_product="STIRFUTURE")
        elif "BOND" in cls_name or "FRB" in cls_name:
            return MultiProductMDP({"FRB": mdp}, default_product="FRB")
        else:
            # Fallback: use generic key
            return MultiProductMDP({"_default": mdp}, default_product="_default")

    raise TypeError(f"Cannot convert {type(mdp)} to MultiProductMDP")
