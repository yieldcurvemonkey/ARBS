# ABOUTME: Adapter module for bridging Query and Signals layers
# ABOUTME: Converts Query results (MockFuture objects) into signal-consumable DataFrames
"""
Adapter Module

Bridges the gap between Query layer and Signals layer:
- Query layer: Product-specific queries returning MockFuture objects
- Signals layer: Needs specific DataFrame format (price, next_price, roll_date)
- Adapter: Transforms Query outputs into Signal inputs

Modules:
- FuturesAdapter: Adapter for futures queries
- Base: Abstract base classes

Usage:
    from Adapter.FuturesAdapter import FuturesAdapter
    from Query.Futures.FuturesQuery import FuturesQuery

    # Create adapter with market data
    adapter = FuturesAdapter(mdp)

    # Convert queries to signal format
    queries = [FuturesQuery(contract='SFRZ4'), ...]
    df = adapter.convert(queries, as_of_date)

    # Use with signals
    carry_signal = CarrySignal()
    alphas = carry_signal.generate_batch(df, as_of_date)

Architecture:
    Query Layer (Product):  FuturesQuery → MockFuture objects
                                ↓
    Adapter Layer:         FuturesAdapter.convert()
                                ↓
    Signal Layer (Alpha):  DataFrame → CarrySignal → alphas
"""

__version__ = "0.1.0"
