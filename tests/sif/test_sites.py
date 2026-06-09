import pytest

from opscli.sif.sites import SifSiteNotSupportedError, normalize_site


def test_normalize_site_supports_country_names():
    assert normalize_site("美国") == "US"
    assert normalize_site("美国站") == "US"
    assert normalize_site("GB") == "UK"
    assert normalize_site("英国站") == "UK"
    assert normalize_site("加拿大") == "CA"
    assert normalize_site("法国") == "FR"
    assert normalize_site("西班牙") == "ES"
    assert normalize_site("意大利") == "IT"
    assert normalize_site("澳大利亚") == "AU"
    assert normalize_site("墨西哥") == "MX"
    assert normalize_site("阿联酋") == "AE"
    assert normalize_site("巴西") == "BR"
    assert normalize_site("沙特") == "SA"


def test_normalize_site_rejects_unknown_site():
    with pytest.raises(SifSiteNotSupportedError):
        normalize_site("未知站")
