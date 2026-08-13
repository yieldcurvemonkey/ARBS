"""Dealer-direction inference on the CFTC Part 43 USD swap tape.

Per-trade direction with a calibrated probability, a signed key-rate DV01
profile, and the aggregated dealer risk ladder.

Design: ``docs/dealer_direction/DESIGN.md``.
Measurements and decisions: ``docs/dealer_direction/LEDGER.md``.

``SDRUtils.stir_flow`` is the frozen predecessor. It is imported from, never
edited -- the tie-out needs it runnable unchanged.
"""
