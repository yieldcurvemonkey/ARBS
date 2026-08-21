# tests/test_ir_clearing_house_basis_mdp.py
import datetime
import sys
import types

import pandas as pd
import pytest


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

    def test_fetch_clearing_house_basis_merges_on_date_index_and_uses_passed_credentials(self, monkeypatch: pytest.MonkeyPatch):
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import fetch_clearing_house_basis

        session_calls = []
        dataset_calls = []

        class _FakeDataset:
            def __init__(self, name):
                assert name == "IR_SWAP_RATES_V1_STANDARD"

            def get_data(self, start, end, assetId):
                dataset_calls.append({"start": start, "end": end, "assetId": assetId})
                return (
                    pd.DataFrame(
                        {
                            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03"]),
                            "assetId": ["asset_a", "asset_a", "asset_b", "asset_b"],
                            "rate": [0.0400, 0.0410, 0.0390, 0.0385],
                        }
                    ).set_index("date")
                )

        class _FakeSession:
            class Scopes:
                @staticmethod
                def get_default():
                    return ["read_product_data"]

            @staticmethod
            def use(client_id, client_secret, scopes):
                session_calls.append(
                    {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "scopes": scopes,
                    }
                )

        gs_quant_mod = types.ModuleType("gs_quant")
        gs_quant_data_mod = types.ModuleType("gs_quant.data")
        gs_quant_session_mod = types.ModuleType("gs_quant.session")
        gs_quant_data_mod.Dataset = _FakeDataset
        gs_quant_session_mod.GsSession = _FakeSession
        gs_quant_mod.data = gs_quant_data_mod
        gs_quant_mod.session = gs_quant_session_mod

        monkeypatch.setitem(sys.modules, "gs_quant", gs_quant_mod)
        monkeypatch.setitem(sys.modules, "gs_quant.data", gs_quant_data_mod)
        monkeypatch.setitem(sys.modules, "gs_quant.session", gs_quant_session_mod)

        result = fetch_clearing_house_basis(
            asset_id_a="asset_a",
            asset_id_b="asset_b",
            start=datetime.date(2026, 1, 1),
            end=datetime.date(2026, 1, 3),
            gs_client_id="client-id",
            gs_secret_key="client-secret",
        )

        assert session_calls == [
            {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scopes": ["read_product_data"],
            }
        ]
        assert dataset_calls == [
            {
                "start": datetime.date(2026, 1, 1),
                "end": datetime.date(2026, 1, 3),
                "assetId": ["asset_a", "asset_b"],
            }
        ]
        assert list(result.columns) == ["rate_a", "rate_b", "basis_bps"]
        assert list(result.index) == [pd.Timestamp("2026-01-02")]
        assert result.index.name == "date"
        assert result.iloc[0]["basis_bps"] == pytest.approx((0.0410 - 0.0390) * 10_000)


class TestIRClearingHouseBasisSwapsMDP:
    def test_construction(self):
        from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP
        mdp = IRClearingHouseBasisSwapsMDP(coverage_path="dummy.xlsx", gs_client_id="test", gs_secret_key="test")
        assert mdp.source == "GSQUANT_CH_BASIS"
        assert mdp._gs_client_id == "test"
        assert mdp._gs_secret_key == "test"

    def test_get_pricer_reads_the_cache_and_signs_basis_as_a_minus_b(self, tmp_path, monkeypatch):
        """get_pricer must return clearing_house_a MINUS clearing_house_b.

        The test this replaces asserted the opposite. It pinned a defect: the
        production call passed pair['asset_id_b'] (CME) in as the fetcher's
        asset_id_a, so basis_bps was CME-LCH while the request keys, the
        meta_data and the docstring all said LCH-CME. Measured ground truth is
        USD SOFR 10y on 2026-08-10 = -2.00 bp LCH-CME (LCH 0.04288489, CME
        0.04308489).
        """
        from Caching.DiskCacheMixin import DiskCacheMixin
        from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP
        from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import CCPBasisCache

        monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path)
        cache = CCPBasisCache(cache_name="TEST_CCP_BASIS_LEGACY")
        day = datetime.date(2026, 1, 2)
        cache.put_leg("USD", "SOFR", "10y", "LCH", day, 0.04288489)
        cache.put_leg("USD", "SOFR", "10y", "CME", day, 0.04308489)
        for ch in ("LCH", "CME"):
            cache.mark_warm("USD", "SOFR", "10y", ch, day, day)

        mdp = IRClearingHouseBasisSwapsMDP(gs_client_id="cid", gs_secret_key="secret", cache=cache)
        assert mdp._gs_client_id == "cid" and mdp._gs_secret_key == "secret"

        pricer = mdp.get_pricer(
            {
                "tenor": "10y",
                "index": "SOFR",
                "start_date": day,
                "end_date": day,
            }
        )
        row = pricer.basis_data.iloc[0]
        assert row["rate_a"] == pytest.approx(0.04288489)  # LCH == clearing_house_a
        assert row["rate_b"] == pytest.approx(0.04308489)  # CME == clearing_house_b
        assert row["basis_bps"] == pytest.approx(-2.0, abs=1e-4)
        assert row["basis_bps"] == pytest.approx((row["rate_a"] - row["rate_b"]) * 1e4)
        assert pricer.meta_data["sign_convention"] == "LCH minus CME"

    def test_get_pricer_is_offline_by_default(self, tmp_path, monkeypatch):
        """Every call used to hit the network. A cold window must now raise."""
        import requests

        from Caching.DiskCacheMixin import DiskCacheMixin
        from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP
        from MDP.IRClearingHouseBasisSwaps.ccp_basis_cache import CCPBasisCacheMiss

        def _blocked(self, method, url, *a, **kw):
            raise AssertionError(f"network attempted: {method} {url}")

        monkeypatch.setattr(requests.Session, "request", _blocked)
        monkeypatch.setattr(DiskCacheMixin, "CACHE_ROOT", tmp_path)

        mdp = IRClearingHouseBasisSwapsMDP()
        with pytest.raises(CCPBasisCacheMiss):
            mdp.get_pricer(
                {"tenor": "10y", "start_date": datetime.date(2026, 1, 1), "end_date": datetime.date(2026, 1, 2)}
            )
