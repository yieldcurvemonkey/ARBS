from MDP.MarketDataProvider import MarketDataProvider
from MDP.MultiProductMDP import ensure_multi_mdp


class IRSwaptionMDP(MarketDataProvider):
    def __init__(self):
        super().__init__("FAKE")

    def get_pricer(self, request):
        return {"ok": True, **request}


def test_ensure_multi_mdp_inferrs_irswaption_before_irs():
    mdp = IRSwaptionMDP()
    multi = ensure_multi_mdp(mdp)
    assert multi.default_product == "IRSWAPTION"
    assert "IRSWAPTION" in multi.products
    assert "IRS" not in multi.products


def test_alias_lookup_irswaptions_routes_to_irswaption():
    mdp = IRSwaptionMDP()
    multi = ensure_multi_mdp(mdp)
    assert multi.get_mdp_for_product("IRSWAPTIONS") is multi.get_mdp_for_product("IRSWAPTION")
    out = multi.get_pricer({"product": "IRSWAPTIONS", "foo": 1})
    assert out["foo"] == 1

