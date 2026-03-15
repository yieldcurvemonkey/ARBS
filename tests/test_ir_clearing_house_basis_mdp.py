# tests/test_ir_clearing_house_basis_mdp.py
import pytest
import datetime


class TestGSQuantFetcher:
    def test_parse_coverage_name(self):
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import parse_coverage_name
        result = parse_coverage_name("USD Swap SOFR 1y ATM 0b to 5y CME Cleared")
        assert result["ccy"] == "USD"
        assert result["index"] == "SOFR"
        assert result["tenor"] == "5y"
        assert result["clearing_house"] == "CME"

    def test_find_asset_pair(self):
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import find_asset_pair
        import pandas as pd
        coverage = pd.DataFrame({
            "name": [
                "USD Swap SOFR 1y ATM 0b to 5y CME Cleared",
                "USD Swap SOFR 1y ATM 0b to 5y LCH Cleared",
                "EUR Swap LIBOR 6m ATM 0b to 10y EUREX Cleared",
            ],
            "assetId": ["asset_cme_5y", "asset_lch_5y", "asset_eur_10y"],
        })
        pair = find_asset_pair(coverage, ccy="USD", index="SOFR", tenor="5y", clearing_house_a="LCH", clearing_house_b="CME")
        assert pair["asset_id_a"] == "asset_lch_5y"
        assert pair["asset_id_b"] == "asset_cme_5y"


class TestIRClearingHouseBasisSwapsMDP:
    def test_construction(self):
        from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP
        mdp = IRClearingHouseBasisSwapsMDP(coverage_path="dummy.xlsx", gs_client_id="test", gs_secret_key="test")
        assert mdp.source == "GSQUANT_CH_BASIS"
