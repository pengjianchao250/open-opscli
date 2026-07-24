"""版本更新检查模块测试。"""

import json
import time
from unittest.mock import patch

import httpx
import pytest
import respx

from opscli.shared.update_check import (
    _CACHE_TTL,
    _fetch_latest_version,
    _refresh_cache_async,
    _parse_version,
    _read_cache,
    _write_cache,
    check_and_notify,
    is_newer_available,
)


class TestParseVersion:
    """版本号解析测试。"""

    def test_standard_three_parts(self):
        """标准三段版本号 "0.0.72" 解析为 (0, 0, 72)。"""
        assert _parse_version("0.0.72") == (0, 0, 72)

    def test_two_parts_padded(self):
        """两段版本号 "1.0" 补零为 (1, 0, 0)。"""
        assert _parse_version("1.0") == (1, 0, 0)

    def test_v_prefix_stripped(self):
        """"v1.2.3" 去掉前缀解析为 (1, 2, 3)。"""
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_single_part(self):
        """单段版本号 "5" 补零为 (5, 0, 0)。"""
        assert _parse_version("5") == (5, 0, 0)

    def test_non_digit_part_treated_as_zero(self):
        """非数字段解析为 0。"""
        assert _parse_version("1.0a.3") == (1, 0, 3)

    def test_whitespace_trimmed(self):
        """前后空格被去除。"""
        assert _parse_version("  1.2.3  ") == (1, 2, 3)


class TestIsNewerAvailable:
    """版本比较测试。"""

    def test_patch_bump_is_newer(self):
        """补丁版本升级：0.0.72 < 0.0.73 返回 True。"""
        assert is_newer_available("0.0.72", "0.0.73") is True

    def test_equal_versions_not_newer(self):
        """版本号相等返回 False。"""
        assert is_newer_available("0.0.72", "0.0.72") is False

    def test_older_version_not_newer(self):
        """当前版本更高时返回 False。"""
        assert is_newer_available("0.0.73", "0.0.72") is False

    def test_major_bump_is_newer(self):
        """主版本号升级：0.9.9 < 1.0.0 返回 True。"""
        assert is_newer_available("0.9.9", "1.0.0") is True

    def test_minor_bump_is_newer(self):
        """次版本号升级：1.2.0 < 1.3.0 返回 True。"""
        assert is_newer_available("1.2.0", "1.3.0") is True


class TestCache:
    """缓存读写测试。"""

    def test_write_and_read(self, tmp_path):
        """写入缓存后读取，验证数据完整。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            _write_cache("0.0.73")
            result = _read_cache()
            assert result is not None
            assert result["latest_version"] == "0.0.73"
            assert isinstance(result["checked_at"], float)

    def test_read_expired_returns_none(self, tmp_path):
        """缓存过期（超过 24 小时）返回 None。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        cache_file.write_text(json.dumps({
            "latest_version": "0.0.73",
            "checked_at": time.time() - _CACHE_TTL - 1,
        }))
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            assert _read_cache() is None

    def test_read_missing_file_returns_none(self, tmp_path):
        """缓存文件不存在返回 None。"""
        cache_file = tmp_path / "nonexistent.json"
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            assert _read_cache() is None

    def test_read_corrupt_json_returns_none(self, tmp_path):
        """缓存文件 JSON 格式错误返回 None。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        cache_file.write_text("{invalid json")
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            assert _read_cache() is None

    def test_read_missing_fields_returns_none(self, tmp_path):
        """缓存文件缺少必要字段返回 None。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        cache_file.write_text(json.dumps({"checked_at": time.time()}))
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            assert _read_cache() is None

    def test_write_creates_parent_directory(self, tmp_path):
        """写入时自动创建父目录。"""
        cache_file = tmp_path / "subdir" / "pypi_version_cache.json"
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            _write_cache("0.0.74")
            assert cache_file.exists()


class TestFetchLatestVersion:
    """PyPI 版本查询测试。"""

    @respx.mock
    def test_success(self):
        """PyPI 返回正确版本号。"""
        respx.get("https://pypi.org/pypi/aukeys-opscli/json").mock(
            return_value=httpx.Response(200, json={
                "info": {"version": "0.0.99"},
            })
        )
        assert _fetch_latest_version() == "0.0.99"

    @respx.mock
    def test_network_error_returns_none(self):
        """网络异常返回 None。"""
        respx.get("https://pypi.org/pypi/aukeys-opscli/json").mock(
            side_effect=httpx.ConnectError("连接失败")
        )
        assert _fetch_latest_version() is None

    @respx.mock
    def test_http_error_returns_none(self):
        """HTTP 错误状态码返回 None。"""
        respx.get("https://pypi.org/pypi/aukeys-opscli/json").mock(
            return_value=httpx.Response(500)
        )
        assert _fetch_latest_version() is None

    @respx.mock
    def test_bad_json_returns_none(self):
        """返回非预期 JSON 结构返回 None。"""
        respx.get("https://pypi.org/pypi/aukeys-opscli/json").mock(
            return_value=httpx.Response(200, json={"unexpected": True})
        )
        assert _fetch_latest_version() is None


class TestCheckAndNotify:
    """集成测试：check_and_notify 完整流程。"""

    def test_cache_hit_no_update(self, tmp_path, capsys):
        """缓存命中且无新版本，不输出。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        cache_file.write_text(json.dumps({
            "latest_version": "0.0.72",
            "checked_at": time.time(),
        }))
        with (
            patch("opscli.shared.update_check._CACHE_FILE", cache_file),
            patch("opscli.shared.update_check.get_version", return_value="0.0.72"),
        ):
            check_and_notify()
            # stderr 输出通过 rich Console(stderr=True)，需检查 captured stderr
            captured = capsys.readouterr()
            assert "新版本" not in captured.out

    def test_cache_hit_with_update(self, tmp_path, capsys):
        """缓存命中且有新版本，输出提示。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        cache_file.write_text(json.dumps({
            "latest_version": "0.0.99",
            "checked_at": time.time(),
        }))
        with (
            patch("opscli.shared.update_check._CACHE_FILE", cache_file),
            patch("opscli.shared.update_check.get_version", return_value="0.0.72"),
        ):
            check_and_notify()
            captured = capsys.readouterr()
            assert "0.0.72" in captured.err
            assert "0.0.99" in captured.err
            assert "pip install" in captured.err

    def test_no_cache_triggers_background_refresh_no_output(self, tmp_path, capsys):
        """无缓存：仅触发后台刷新，本次不阻塞、不同步输出提示。

        后台化改造后，缓存缺失时 check_and_notify 不再同步请求 PyPI，
        而是委托 _refresh_cache_async 后台刷新，故本次调用无 stderr 输出。
        """
        cache_file = tmp_path / "pypi_version_cache.json"
        with (
            patch("opscli.shared.update_check._CACHE_FILE", cache_file),
            patch("opscli.shared.update_check.get_version", return_value="0.0.72"),
            patch("opscli.shared.update_check._refresh_cache_async") as mock_refresh,
        ):
            check_and_notify()
            # 确认走了后台刷新分支，且本次未同步打印提示
            mock_refresh.assert_called_once()
            captured = capsys.readouterr()
            assert captured.err == ""

    @respx.mock
    def test_refresh_cache_async_writes_cache(self, tmp_path):
        """后台刷新线程：PyPI 返回新版本时异步写入缓存。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        respx.get("https://pypi.org/pypi/aukeys-opscli/json").mock(
            return_value=httpx.Response(200, json={
                "info": {"version": "0.0.80"},
            })
        )
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            # 显式 join 后台线程，确保断言时刷新已完成（生产为 daemon 不 join）
            _refresh_cache_async().join(timeout=5)
            data = json.loads(cache_file.read_text())
            assert data["latest_version"] == "0.0.80"

    @respx.mock
    def test_refresh_cache_async_unreachable_no_write(self, tmp_path):
        """后台刷新线程：PyPI 不可达时不写缓存、不抛异常。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        respx.get("https://pypi.org/pypi/aukeys-opscli/json").mock(
            side_effect=httpx.ConnectError("不可达")
        )
        with patch("opscli.shared.update_check._CACHE_FILE", cache_file):
            _refresh_cache_async().join(timeout=5)
            assert not cache_file.exists()

    def test_exception_silent(self, tmp_path, capsys):
        """get_version 抛异常时静默无输出，不影响命令执行。"""
        cache_file = tmp_path / "pypi_version_cache.json"
        with (
            patch("opscli.shared.update_check._CACHE_FILE", cache_file),
            patch("opscli.shared.update_check.get_version", side_effect=RuntimeError("异常")),
        ):
            # 不应抛出异常
            check_and_notify()
            captured = capsys.readouterr()
            assert captured.err == ""
