from SDRUtils.products.usd.upi_classifier import classify_rate_index
from SDRUtils.products.usd.linear_base import RateIndex, LinearProductType, BasisType


class TestClassifyRateIndex:
    def test_sofr_ois(self):
        result = classify_rate_index(
            upi_underlier="USD-SOFR-OIS Compound",
            upi_fisn="NA/Swap OIS USD",
        )
        assert result.rate_index == RateIndex.SOFR
        assert result.product_type == LinearProductType.OIS
        assert result.basis_type is None

    def test_sofr_compound(self):
        result = classify_rate_index(
            upi_underlier="USD-SOFR-COMPOUND",
            upi_fisn="NA/Swap OIS USD",
        )
        assert result.rate_index == RateIndex.SOFR_COMPOUND
        assert result.product_type == LinearProductType.OIS

    def test_fed_funds_ois(self):
        result = classify_rate_index(
            upi_underlier="USD-Federal Funds-OIS Compound",
            upi_fisn="NA/Swap OIS USD",
        )
        assert result.rate_index == RateIndex.FED_FUNDS
        assert result.product_type == LinearProductType.OIS

    def test_fed_funds_h15_compound(self):
        result = classify_rate_index(
            upi_underlier="USD-Federal Funds-H.15-OIS-COMPOUND",
            upi_fisn="NA/Swap OIS USD",
        )
        assert result.rate_index == RateIndex.FED_FUNDS_COMPOUND
        assert result.product_type == LinearProductType.OIS

    def test_sofr_ff_basis(self):
        result = classify_rate_index(
            upi_underlier="USD-Federal Funds-OIS Compound vs USD-SOFR-OIS Compound",
            upi_fisn="NA/Swap Flt Flt USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.SOFR_FF

    def test_sofr_ff_basis_h15(self):
        result = classify_rate_index(
            upi_underlier="USD-Federal Funds-H.15-OIS-COMPOUND vs USD-SOFR-COMPOUND",
            upi_fisn="NA/Swap Flt Flt OIS USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.SOFR_FF

    def test_sofr_tenor_basis(self):
        result = classify_rate_index(
            upi_underlier="USD-SOFR vs USD-SOFR",
            upi_fisn="NA/Swap Flt Flt USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.SOFR_TENOR

    def test_ff_tenor_basis(self):
        result = classify_rate_index(
            upi_underlier="USD-Federal Funds-H.15 vs USD-Federal Funds-H.15",
            upi_fisn="NA/Swap Flt Flt USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.FF_TENOR

    def test_cms_basis(self):
        result = classify_rate_index(
            upi_underlier="USD-ISDA-Swap Rate vs USD-ISDA-Swap Rate",
            upi_fisn="NA/Swap Flt Flt USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.CMS

    def test_sifma_basis(self):
        result = classify_rate_index(
            upi_underlier="USD-SIFMA Municipal Swap Index vs USD-SIFMA Municipal Swap Index",
            upi_fisn="NA/Swap Flt Flt USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.SIFMA

    def test_obfr_sofr_basis(self):
        result = classify_rate_index(
            upi_underlier="USD-Overnight Bank Funding Rate vs USD-SOFR-COMPOUND",
            upi_fisn="NA/Swap Flt Flt USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.OBFR_SOFR

    def test_xccy_basis(self):
        result = classify_rate_index(
            upi_underlier="JPY-TONA-OIS Compound vs USD-SOFR-OIS Compound",
            upi_fisn="NA/Swap Flt Flt JPY USD",
        )
        assert result.product_type == LinearProductType.BASIS
        assert result.basis_type == BasisType.XCCY

    def test_unknown_underlier_returns_none(self):
        result = classify_rate_index(
            upi_underlier="UNKNOWN-PRODUCT",
            upi_fisn="NA/Swap OIS USD",
        )
        assert result.rate_index is None
        assert result.product_type is None

    def test_nan_underlier_returns_none(self):
        result = classify_rate_index(upi_underlier=None, upi_fisn=None)
        assert result.rate_index is None
