from SDRUtils.products.usd.linear_base import (
    TenorSegment,
    LinearProductType,
    RateIndex,
    BasisType,
    USDLinearClassification,
    BasisSwapClassification,
)


def test_tenor_segment_enum():
    assert TenorSegment.SHORT.value == "SHORT"
    assert TenorSegment.MEDIUM.value == "MEDIUM"


def test_rate_index_enum():
    assert RateIndex.SOFR.value == "SOFR"
    assert RateIndex.FED_FUNDS.value == "FED_FUNDS"


def test_basis_type_enum():
    assert BasisType.SOFR_FF.value == "SOFR_FF"
    assert BasisType.SOFR_TENOR.value == "SOFR_TENOR"
    assert BasisType.CMS.value == "CMS"
    assert BasisType.SIFMA.value == "SIFMA"
    assert BasisType.OBFR_SOFR.value == "OBFR_SOFR"
    assert BasisType.XCCY.value == "XCCY"


def test_classify_tenor_segment():
    assert TenorSegment.from_years(0.5) == TenorSegment.SHORT
    assert TenorSegment.from_years(2.0) == TenorSegment.SHORT
    assert TenorSegment.from_years(3.0) == TenorSegment.SHORT
    assert TenorSegment.from_years(3.01) == TenorSegment.MEDIUM
    assert TenorSegment.from_years(10.0) == TenorSegment.MEDIUM
    assert TenorSegment.from_years(30.0) == TenorSegment.MEDIUM
