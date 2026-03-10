import datetime as dt

from SDRUtils._swappulse_scripts import ingest_listed_vs_swaption_vol as ingest_mod


class _RecordingSmileMDP:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def fetch_bulk_sabr_smile(self, request: dict) -> dict[str, dict[dt.date, object]]:
        self.requests.append(request)
        as_of_date = request["timestamps"][0]
        return {
            symbol: {as_of_date: {"symbol": symbol, "as_of_date": as_of_date}}
            for symbol in request["globex_symbols"]
        }


def test_fetch_bulk_sabr_smiles_batched_caps_each_request_at_three_symbols() -> None:
    mdp = _RecordingSmileMDP()
    as_of_date = dt.date(2026, 3, 5)

    out = ingest_mod._fetch_bulk_sabr_smiles_batched(
        mdp=mdp,
        globex_symbols=["TU_07", "FV_07", "TY_07", "TN_07", "US_07", "UL_07", "SR3_7"],
        as_of_date=as_of_date,
        force_refresh=True,
    )

    assert [len(request["globex_symbols"]) for request in mdp.requests] == [3, 3, 1]
    assert all(len(request["globex_symbols"]) <= 3 for request in mdp.requests)
    assert set(out) == {"TU_07", "FV_07", "TY_07", "TN_07", "US_07", "UL_07", "SR3_7"}
    assert out["UL_07"][as_of_date] == {"symbol": "UL_07", "as_of_date": as_of_date}


def test_build_smile_request_maps_skips_unsupported_180d_constant_maturity_symbols() -> None:
    request_map = ingest_mod.build_smile_request_maps()

    assert "TU_90" in request_map
    assert "SR3_90" in request_map
    assert "TU_180" not in request_map
    assert "SR3_180" not in request_map
    assert not any(symbol.endswith("_180") for symbol in request_map)


def test_fetch_daily_listed_snapshot_rows_batches_ust_and_stir_smile_requests(monkeypatch) -> None:
    as_of_date = dt.date(2026, 3, 5)
    ust_mdp = _RecordingSmileMDP()
    stir_mdp = _RecordingSmileMDP()

    monkeypatch.setattr(
        ingest_mod,
        "build_smile_request_maps",
        lambda: {
            "TU_07": ("TU", "1W"),
            "FV_14": ("FV", "2W"),
            "TY_30": ("TY", "1M"),
            "US_60": ("US", "2M"),
            "SR3_7": ("SFR", "1W"),
            "SR3_14": ("SFR", "2W"),
            "SR3_30": ("SFR", "1M"),
            "SR3_60": ("SFR", "2M"),
        },
    )
    monkeypatch.setattr(ingest_mod, "USTFutureOptionMDP", lambda *args, **kwargs: ust_mdp)
    monkeypatch.setattr(ingest_mod, "STIRFutureOptionMDP", lambda *args, **kwargs: stir_mdp)
    monkeypatch.setattr(
        ingest_mod,
        "_build_snapshot_row_from_ust_smile",
        lambda **kwargs: {
            "product": kwargs["product"],
            "expiry_label": kwargs["expiry_label"],
            "product_class": "UST",
        },
    )
    monkeypatch.setattr(
        ingest_mod,
        "_build_snapshot_row_from_stir_smile",
        lambda **kwargs: {
            "product": kwargs["product"],
            "expiry_label": kwargs["expiry_label"],
            "product_class": "STIR",
        },
    )

    rows = ingest_mod._fetch_daily_listed_snapshot_rows(
        as_of_date=as_of_date,
        force_refresh=True,
    )

    assert [len(request["globex_symbols"]) for request in ust_mdp.requests] == [3, 1]
    assert [len(request["globex_symbols"]) for request in stir_mdp.requests] == [3, 1]
    assert all(len(request["globex_symbols"]) <= 3 for request in ust_mdp.requests + stir_mdp.requests)
    assert len(rows) == 8
