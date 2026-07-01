# Scrape.do Amazon Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入 Scrape.do Amazon Scraper API，提供 PDP、Offer Listing、Search 三个结构化 Amazon 数据补充场景。

**Architecture:** 新增独立 `opscli.scrape_do` provider，按现有 Keepa / Google Trends / Canopy 风格实现 `scenarios/run/job-status/export`。HTTP 客户端只负责 Scrape.do REST 调用和 token 脱敏；`ScrapeDoApiManager` 负责任务落盘、响应行提取、XLSX 导出、上传与结果返回；CLI 通过远端 MCP adapter 调用，MCP 暴露同名工具并隐藏本地路径与原始响应。

**Tech Stack:** Python 3.10、Typer、FastMCP、httpx、openpyxl、pytest、respx

## Global Constraints

- 不接入 Scrape.do raw HTML endpoint，只支持 `/plugin/amazon/pdp`、`/plugin/amazon/offer-listing`、`/plugin/amazon/search`。
- 默认不传 `include_html=true`，也不把 HTML 暴露到 MCP 公共结果。
- Scrape.do token 不能写入 `params.json`、`raw.json`、`result.json`、日志、MCP 返回或错误消息。
- Amazon Scraper API 每个 token 并发限制为 1，请求执行层必须串行化。
- 失败 HTTP 请求和 Scrape.do 业务错误必须保留可诊断信息，但不得包含 token。
- 测试不能发起真实网络请求；HTTP 使用 `respx` 或 monkeypatch mock。
- 新增模块遵循 `opscli/{module_name}/`、`tests/{module_name}/`、`opscli/cli.py` 单行注册约束。
- CLI 正式命令走远端 MCP adapter；本地直接执行能力在 MCP tool / service 层。

---

## File Structure

Create:
- `opscli/scrape_do/__init__.py` — 模块包入口。
- `opscli/scrape_do/config.py` — 环境变量、默认输出目录、超时、重试配置。
- `opscli/scrape_do/accounts.py` — Scrape.do token 来源，优先 OPS 集成账号 `scrape_do`，兜底 `OPSCLI_SCRAPEDO_TOKEN`。
- `opscli/scrape_do/domain/__init__.py` — domain 包入口。
- `opscli/scrape_do/domain/exceptions.py` — `ScrapeDoConfigError`、`ScrapeDoApiError`。
- `opscli/scrape_do/domain/models.py` — request/result/export dataclass。
- `opscli/scrape_do/api/__init__.py` — api 包入口。
- `opscli/scrape_do/api/scenarios.py` — 三个 Amazon 场景定义、参数构造与校验。
- `opscli/scrape_do/api/client.py` — httpx AsyncClient 封装、单 token 并发锁、错误映射、响应头成本提取。
- `opscli/scrape_do/export/__init__.py` — export 包入口。
- `opscli/scrape_do/export/xlsx.py` — PDP / offers / search 行导出。
- `opscli/scrape_do/services/__init__.py` — service 包入口。
- `opscli/scrape_do/services/api_manager.py` — 场景运行、落盘、导出、上传、job status。
- `opscli/scrape_do/remote_adapter.py` — CLI 到远端 MCP tool 的适配器。
- `opscli/scrape_do/cli.py` — 正式 CLI 命令面。
- `opscli/mcp/tools/scrape_do.py` — MCP tools。
- `opscli/skills/templates/ops-scrape-do/SKILL_MCP.md` — MCP 使用规范。
- `tests/scrape_do/test_scenarios.py`
- `tests/scrape_do/test_client.py`
- `tests/scrape_do/test_api_manager.py`
- `tests/scrape_do/test_cli_remote.py`
- `tests/mcp/test_scrape_do_tools.py`

Modify:
- `opscli/cli.py` — 注册 `scrape-do` 命令组。
- `opscli/mcp/server.py` — 注册 `scrape_do` MCP tools。
- `opscli/skills/templates/manifest.json` — 加入 `ops-scrape-do` 模板条目。

---

### Task 1: 场景注册、配置和凭证来源

**Files:**
- Create: `opscli/scrape_do/__init__.py`
- Create: `opscli/scrape_do/config.py`
- Create: `opscli/scrape_do/accounts.py`
- Create: `opscli/scrape_do/domain/__init__.py`
- Create: `opscli/scrape_do/domain/exceptions.py`
- Create: `opscli/scrape_do/domain/models.py`
- Create: `opscli/scrape_do/api/__init__.py`
- Create: `opscli/scrape_do/api/scenarios.py`
- Create: `opscli/scrape_do/services/__init__.py`
- Test: `tests/scrape_do/test_scenarios.py`

**Interfaces:**
- Produces: `ScrapeDoScenarioRequest`, `ScrapeDoScenarioResult`, `ScrapeDoCredential`, `ScrapeDoCredentialProvider`, `get_scenario()`, `list_scenarios()`.
- Later tasks consume: `scenario.build_params(params=request.params, site=site, token=credential.token)` and `scenario.endpoint`.

- [ ] **Step 1: Write the failing scenario tests**

Create `tests/scrape_do/test_scenarios.py`:

```python
import pytest

from opscli.scrape_do.api.scenarios import get_scenario, list_scenarios
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError


def test_list_scenarios_contains_three_structured_amazon_endpoints():
    scenarios = list_scenarios()
    ids = {item["scenario_id"] for item in scenarios}

    assert ids == {"amazon-pdp", "amazon-offer-listing", "amazon-search"}
    assert all("raw-html" not in item["scenario_id"] for item in scenarios)


def test_amazon_pdp_builds_params_without_html():
    scenario = get_scenario("amazon-pdp")

    params = scenario.build_params(
        params={"asin": "B0C7BKZ883", "zipcode": "90210", "language": "EN"},
        site="US",
        token="secret-token",
    )

    assert params == {
        "token": "secret-token",
        "asin": "B0C7BKZ883",
        "geocode": "US",
        "zipcode": "90210",
        "language": "EN",
    }
    assert "include_html" not in params


def test_amazon_offer_listing_rejects_zipcode_and_country_name_together():
    scenario = get_scenario("amazon-offer-listing")

    with pytest.raises(ScrapeDoConfigError, match="zipcode 和 countryName 不能同时传"):
        scenario.build_params(
            params={"asin": "B0DGJ7HYG1", "zipcode": "90210", "countryName": "United States"},
            site="US",
            token="secret-token",
        )


def test_amazon_search_requires_keyword_and_defaults_page():
    scenario = get_scenario("amazon-search")

    params = scenario.build_params(
        params={"keyword": "laptop stands", "device": "mobile", "super": True},
        site="us",
        token="secret-token",
    )

    assert params == {
        "token": "secret-token",
        "keyword": "laptop stands",
        "geocode": "US",
        "page": 1,
        "device": "mobile",
        "super": "true",
    }


def test_amazon_search_rejects_empty_keyword():
    scenario = get_scenario("amazon-search")

    with pytest.raises(ScrapeDoConfigError, match="缺少参数：keyword"):
        scenario.build_params(params={}, site="US", token="secret-token")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/scrape_do/test_scenarios.py -v
```

Expected: FAIL because `opscli.scrape_do` package does not exist.

- [ ] **Step 3: Add domain exceptions and models**

Create `opscli/scrape_do/domain/exceptions.py`:

```python
"""Scrape.do 领域异常。"""

from __future__ import annotations


class ScrapeDoError(Exception):
    """Scrape.do 模块基础异常。"""


class ScrapeDoConfigError(ScrapeDoError):
    """Scrape.do 配置或参数错误。"""


class ScrapeDoApiError(ScrapeDoError):
    """Scrape.do API 调用错误。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        response_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response_excerpt = response_excerpt
```

Create `opscli/scrape_do/domain/models.py`:

```python
"""Scrape.do 数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScrapeDoCredential:
    """Scrape.do API token 记录。"""

    name: str
    token: str
    source: str

    def to_public_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source, "has_token": bool(self.token)}


@dataclass
class ScrapeDoExportResult:
    """单次任务导出文件信息。"""

    path: str
    filename: str
    url: str | None = None
    format: str = "xlsx"
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapeDoScenarioRequest:
    """Scrape.do 场景执行请求。"""

    scenario: str
    site: str = "US"
    params: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    output_dir: str | None = None
    export_format: str = "xls"
    timeout_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapeDoScenarioResult:
    """Scrape.do 场景执行结果。"""

    job_id: str
    scenario: str
    site: str
    row_count: int
    root_dir: str
    params_path: str
    raw_path: str
    result_path: str
    export: ScrapeDoExportResult | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)
    billing: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["export"] = self.export.to_dict() if self.export else None
        return payload

    @classmethod
    def empty(
        cls,
        *,
        job_id: str,
        scenario: str,
        site: str,
        root_dir: Path,
        params_path: Path,
        raw_path: Path,
        result_path: Path,
    ) -> "ScrapeDoScenarioResult":
        return cls(
            job_id=job_id,
            scenario=scenario,
            site=site,
            row_count=0,
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
        )
```

Create package init files:

```python
# opscli/scrape_do/__init__.py
"""Scrape.do Amazon Scraper provider。"""
```

```python
# opscli/scrape_do/domain/__init__.py
"""Scrape.do domain package。"""
```

```python
# opscli/scrape_do/api/__init__.py
"""Scrape.do API package。"""
```

```python
# opscli/scrape_do/services/__init__.py
"""Scrape.do service package。"""

from opscli.scrape_do.services.api_manager import ScrapeDoApiManager

__all__ = ["ScrapeDoApiManager"]
```

- [ ] **Step 4: Add config and token provider**

Create `opscli/scrape_do/config.py`:

```python
"""Scrape.do API 配置。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR

SCRAPE_DO_BASE_URL = "https://api.scrape.do"
ENV_TOKEN = "OPSCLI_SCRAPEDO_TOKEN"
ENV_ACCOUNT_NAME = "OPSCLI_SCRAPEDO_ACCOUNT_NAME"
ENV_OUTPUT_DIR = "OPSCLI_SCRAPEDO_OUTPUT_DIR"
ENV_TIMEOUT_SECONDS = "OPSCLI_SCRAPEDO_TIMEOUT_SECONDS"
ENV_ACCOUNT_CACHE_TTL_SECONDS = "OPSCLI_SCRAPEDO_ACCOUNT_CACHE_TTL_SECONDS"

DEFAULT_ACCOUNT_NAME = "default"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "scrape_do" / "api_runs"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_ACCOUNT_CACHE_TTL_SECONDS = 600


@dataclass(frozen=True)
class ScrapeDoSettings:
    """Scrape.do API 运行配置。"""

    account_name: str = DEFAULT_ACCOUNT_NAME
    token: str | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    account_cache_ttl_seconds: int = DEFAULT_ACCOUNT_CACHE_TTL_SECONDS

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["output_dir"] = str(self.output_dir)
        payload["has_token"] = bool(self.token)
        payload.pop("token", None)
        return payload


def load_settings() -> ScrapeDoSettings:
    values = _load_env_values()
    output_dir = Path(values.get(ENV_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).expanduser()
    return ScrapeDoSettings(
        account_name=values.get(ENV_ACCOUNT_NAME) or DEFAULT_ACCOUNT_NAME,
        token=values.get(ENV_TOKEN) or None,
        output_dir=output_dir,
        timeout_seconds=_parse_int(values.get(ENV_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS),
        account_cache_ttl_seconds=_parse_int(
            values.get(ENV_ACCOUNT_CACHE_TTL_SECONDS),
            DEFAULT_ACCOUNT_CACHE_TTL_SECONDS,
        ),
    )


def _load_env_values() -> dict[str, str]:
    values = _read_dotenv()
    for key in [ENV_TOKEN, ENV_ACCOUNT_NAME, ENV_OUTPUT_DIR, ENV_TIMEOUT_SECONDS, ENV_ACCOUNT_CACHE_TTL_SECONDS]:
        value = os.environ.get(key)
        if value:
            values[key] = value
    return values


def _read_dotenv() -> dict[str, str]:
    current = Path.cwd().resolve()
    for directory in [current, *current.parents]:
        dotenv = directory / ".env"
        if dotenv.exists():
            return _parse_dotenv(dotenv)
    return {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _parse_int(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
```

Create `opscli/scrape_do/accounts.py`:

```python
"""Scrape.do token 来源。"""

from __future__ import annotations

import time

from opscli.scrape_do.config import ScrapeDoSettings, load_settings
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError
from opscli.scrape_do.domain.models import ScrapeDoCredential
from opscli.shared.integration_accounts import IntegrationAccountBundle, IntegrationAccountClient, IntegrationAccountError

_REMOTE_BUNDLE_CACHE: dict[str, tuple[float, IntegrationAccountBundle]] = {}


class ScrapeDoCredentialProvider:
    """读取 Scrape.do token，优先远端集成账号，兜底环境变量。"""

    def __init__(
        self,
        settings: ScrapeDoSettings | None = None,
        integration_client: IntegrationAccountClient | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.integration_client = integration_client or IntegrationAccountClient()
        self._remote_bundle: IntegrationAccountBundle | None = None
        self._remote_error: IntegrationAccountError | None = None

    def get_default(self, *, refresh: bool = False) -> ScrapeDoCredential:
        credential = self._get_remote_default(refresh=refresh)
        if credential:
            return credential
        if self.settings.token:
            return ScrapeDoCredential(name=self.settings.account_name, token=self.settings.token, source="env")
        if self._remote_error:
            message = str(self._remote_error)
            if "暂不支持的平台" in message or "platform" in message.lower():
                raise ScrapeDoConfigError(
                    "OPS 集成账号接口暂不支持平台 scrape_do，请先在 OPS 后端开通 scrape_do 平台配置，"
                    "或临时设置 OPSCLI_SCRAPEDO_TOKEN。"
                )
            raise ScrapeDoConfigError(
                f"获取 Scrape.do 集成账号失败：{self._remote_error}。请检查 OPS 授权，或设置 OPSCLI_SCRAPEDO_TOKEN。"
            )
        raise ScrapeDoConfigError("缺少 Scrape.do token：请配置 OPS 集成账号 scrape_do，或设置 OPSCLI_SCRAPEDO_TOKEN")

    def _get_remote_default(self, *, refresh: bool = False) -> ScrapeDoCredential | None:
        bundle = self._load_remote_bundle(refresh=refresh)
        if not bundle or not bundle.accounts:
            return None
        default_name = bundle.default_account or self.settings.account_name
        for item in bundle.accounts:
            if item.name == default_name:
                return ScrapeDoCredential(name=item.name, token=item.password, source="integration_account")
        raise ScrapeDoConfigError(f"Scrape.do 集成账号中不存在默认账号：{default_name}")

    def _load_remote_bundle(self, *, refresh: bool = False) -> IntegrationAccountBundle | None:
        if not refresh and self._remote_bundle is not None:
            return self._remote_bundle
        cached = _REMOTE_BUNDLE_CACHE.get("scrape_do")
        if not refresh and cached and time.time() - cached[0] < self.settings.account_cache_ttl_seconds:
            self._remote_bundle = cached[1]
            self._remote_error = None
            return self._remote_bundle
        try:
            self._remote_bundle = self.integration_client.get_accounts("scrape_do")
            self._remote_error = None
            _REMOTE_BUNDLE_CACHE["scrape_do"] = (time.time(), self._remote_bundle)
        except IntegrationAccountError as exc:
            self._remote_error = exc
            self._remote_bundle = None
        return self._remote_bundle
```

- [ ] **Step 5: Add scenario registry**

Create `opscli/scrape_do/api/scenarios.py`:

```python
"""Scrape.do Amazon Scraper 场景注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError

ScenarioBuilder = Callable[[dict[str, Any], str, str], dict[str, Any]]


@dataclass(frozen=True)
class ScrapeDoScenario:
    """单个 Scrape.do 场景定义。"""

    scenario_id: str
    title: str
    endpoint: str
    required_params: tuple[str, ...]
    param_builder: ScenarioBuilder
    description: str
    sample_params: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("param_builder", None)
        return payload

    def build_params(self, *, params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
        self._validate_required(params)
        return self.param_builder(params, site, token)

    def _validate_required(self, params: dict[str, Any]) -> None:
        missing = [key for key in self.required_params if not _text(params.get(key))]
        if missing:
            raise ScrapeDoConfigError(f"场景 {self.scenario_id} 缺少参数：{', '.join(missing)}")


def list_scenarios() -> list[dict[str, Any]]:
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> ScrapeDoScenario:
    key = str(scenario_id or "").strip()
    scenario = SCENARIOS.get(key)
    if not scenario:
        raise ScrapeDoConfigError(f"未知 Scrape.do 场景：{scenario_id}")
    return scenario


def _pdp_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    payload = _base_params(params, site, token)
    payload["asin"] = _text(params.get("asin")).upper()
    _copy_optional(payload, params, {"language": "language", "device": "device"})
    _copy_super(payload, params)
    return payload


def _offer_listing_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    payload = _base_params(params, site, token)
    payload["asin"] = _text(params.get("asin")).upper()
    _copy_optional(payload, params, {"device": "device"})
    _copy_super(payload, params)
    return payload


def _search_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    payload = _base_params(params, site, token)
    payload["keyword"] = _text(params.get("keyword"))
    payload["page"] = _positive_int(params.get("page"), 1, "page")
    _copy_optional(payload, params, {"language": "language", "device": "device"})
    _copy_super(payload, params)
    return payload


def _base_params(params: dict[str, Any], site: str, token: str) -> dict[str, Any]:
    zipcode = _text(params.get("zipcode"))
    country_name = _text(params.get("countryName") or params.get("country_name"))
    if zipcode and country_name:
        raise ScrapeDoConfigError("zipcode 和 countryName 不能同时传")
    payload = {"token": token, "geocode": _normalize_site(site)}
    if zipcode:
        payload["zipcode"] = zipcode
    if country_name:
        payload["countryName"] = country_name
    return payload


def _copy_optional(payload: dict[str, Any], params: dict[str, Any], mapping: dict[str, str]) -> None:
    for source, target in mapping.items():
        value = _text(params.get(source))
        if value:
            payload[target] = value


def _copy_super(payload: dict[str, Any], params: dict[str, Any]) -> None:
    if "super" not in params:
        return
    payload["super"] = "true" if _parse_bool(params.get("super"), "super") else "false"


def _normalize_site(site: Any) -> str:
    text = _text(site or "US").upper()
    if text == "UK":
        return "GB"
    if not text:
        return "US"
    return text


def _positive_int(value: Any, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ScrapeDoConfigError(f"参数 {name} 必须是正整数：{value}") from exc
    if parsed <= 0:
        raise ScrapeDoConfigError(f"参数 {name} 必须是正整数：{value}")
    return parsed


def _parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ScrapeDoConfigError(f"参数 {name} 必须是布尔值：{value}")


def _text(value: Any) -> str:
    return str(value or "").strip()


SCENARIOS: dict[str, ScrapeDoScenario] = {
    "amazon-pdp": ScrapeDoScenario(
        scenario_id="amazon-pdp",
        title="Amazon PDP 商品详情",
        endpoint="/plugin/amazon/pdp",
        required_params=("asin",),
        param_builder=_pdp_params,
        description="按 ASIN 获取 Amazon 商品详情、价格、评分、图片、描述、BSR 和规格。",
        sample_params={"asin": "B0C7BKZ883", "zipcode": "90210", "language": "EN"},
    ),
    "amazon-offer-listing": ScrapeDoScenario(
        scenario_id="amazon-offer-listing",
        title="Amazon 全部卖家报价",
        endpoint="/plugin/amazon/offer-listing",
        required_params=("asin",),
        param_builder=_offer_listing_params,
        description="按 ASIN 获取全部卖家报价、Buy Box、FBA/Prime、运费、配送和库存。",
        sample_params={"asin": "B0DGJ7HYG1", "zipcode": "90210"},
    ),
    "amazon-search": ScrapeDoScenario(
        scenario_id="amazon-search",
        title="Amazon 搜索结果与类目页",
        endpoint="/plugin/amazon/search",
        required_params=("keyword",),
        param_builder=_search_params,
        description="按关键词获取 Amazon 搜索结果、价格、评分、广告标识、Prime 和排名位置。",
        sample_params={"keyword": "laptop stands", "page": 1, "language": "EN"},
    ),
}
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
pytest tests/scrape_do/test_scenarios.py -v
```

Expected: PASS.

Commit:

```bash
git add opscli/scrape_do tests/scrape_do/test_scenarios.py
git commit -m "feat: add scrape.do scenario registry"
```

---

### Task 2: Scrape.do HTTP client with token-safe errors and single-token concurrency

**Files:**
- Create: `opscli/scrape_do/api/client.py`
- Test: `tests/scrape_do/test_client.py`

**Interfaces:**
- Consumes: `SCRAPE_DO_BASE_URL`, `ScrapeDoApiError`.
- Produces: `ScrapeDoApiClient.get_json(endpoint: str, params: dict[str, Any]) -> ScrapeDoApiResponse`.

- [ ] **Step 1: Write failing client tests**

Create `tests/scrape_do/test_client.py`:

```python
import asyncio

import httpx
import pytest
import respx

from opscli.scrape_do.api.client import ScrapeDoApiClient, _redact_token
from opscli.scrape_do.domain.exceptions import ScrapeDoApiError


def _run(coro):
    return asyncio.run(coro)


@respx.mock
async def test_get_json_returns_payload_and_billing_headers():
    route = respx.get("https://api.scrape.do/plugin/amazon/pdp").mock(
        return_value=httpx.Response(
            200,
            json={"asin": "B0C7BKZ883", "status": "success"},
            headers={"Scrape.do-Request-Cost": "1", "Scrape.do-Remaining-Credits": "99"},
        )
    )

    async with ScrapeDoApiClient(timeout_seconds=10) as client:
        result = await client.get_json(
            "/plugin/amazon/pdp",
            {"token": "secret-token", "asin": "B0C7BKZ883", "geocode": "US"},
        )

    assert route.called
    assert result.payload["asin"] == "B0C7BKZ883"
    assert result.billing == {"request_cost": 1, "remaining_credits": 99}
    assert "secret-token" not in result.safe_url
    assert "token=***" in result.safe_url


@respx.mock
async def test_get_json_maps_scrape_do_error_without_leaking_token():
    respx.get("https://api.scrape.do/plugin/amazon/pdp").mock(
        return_value=httpx.Response(400, json={"error": "invalid_zipcode", "message": "bad zip"})
    )

    async with ScrapeDoApiClient(timeout_seconds=10) as client:
        with pytest.raises(ScrapeDoApiError) as excinfo:
            await client.get_json(
                "/plugin/amazon/pdp",
                {"token": "secret-token", "asin": "B0C7BKZ883", "geocode": "US", "zipcode": "bad"},
            )

    error = excinfo.value
    assert error.status_code == 400
    assert error.error_code == "invalid_zipcode"
    assert "bad zip" in str(error)
    assert "secret-token" not in str(error)
    assert "secret-token" not in (error.response_excerpt or "")


def test_redact_token_handles_query_strings():
    assert _redact_token("https://api.scrape.do/plugin/amazon/pdp?token=abc&asin=B0") == (
        "https://api.scrape.do/plugin/amazon/pdp?token=%2A%2A%2A&asin=B0"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/scrape_do/test_client.py -v
```

Expected: FAIL because `opscli.scrape_do.api.client` does not exist.

- [ ] **Step 3: Implement client**

Create `opscli/scrape_do/api/client.py`:

```python
"""Scrape.do HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from opscli.scrape_do.config import SCRAPE_DO_BASE_URL, DEFAULT_TIMEOUT_SECONDS
from opscli.scrape_do.domain.exceptions import ScrapeDoApiError

_TOKEN_LOCKS: dict[str, asyncio.Lock] = {}
_TOKEN_LOCKS_GUARD = asyncio.Lock()


@dataclass(frozen=True)
class ScrapeDoApiResponse:
    """Scrape.do API 响应和计费头。"""

    payload: dict[str, Any]
    billing: dict[str, Any]
    safe_url: str


class ScrapeDoApiClient:
    """Scrape.do JSON API 客户端，按 token 串行化请求。"""

    def __init__(self, *, base_url: str = SCRAPE_DO_BASE_URL, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ScrapeDoApiClient":
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def get_json(self, endpoint: str, params: dict[str, Any]) -> ScrapeDoApiResponse:
        token = str(params.get("token") or "")
        lock = await _lock_for_token(token)
        async with lock:
            return await self._get_json(endpoint, params)

    async def _get_json(self, endpoint: str, params: dict[str, Any]) -> ScrapeDoApiResponse:
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        close_after = self._client is None
        url = f"{self.base_url}{endpoint}"
        try:
            response = await client.get(url, params=params)
            safe_url = _redact_token(str(response.request.url))
            payload = _parse_json_response(response, safe_url=safe_url)
            if response.status_code >= 400:
                raise _api_error_from_payload(response.status_code, payload, safe_url=safe_url)
            if not isinstance(payload, dict):
                raise ScrapeDoApiError("Scrape.do API 响应不是 JSON 对象", status_code=response.status_code)
            _raise_business_error(payload, status_code=response.status_code, safe_url=safe_url)
            return ScrapeDoApiResponse(payload=payload, billing=_billing_from_headers(response.headers), safe_url=safe_url)
        except ScrapeDoApiError:
            raise
        except httpx.HTTPError as exc:
            request_url = getattr(getattr(exc, "request", None), "url", "")
            raise ScrapeDoApiError(f"Scrape.do API 请求失败：{exc}", response_excerpt=_redact_token(str(request_url))) from exc
        finally:
            if close_after:
                await client.aclose()


def _parse_json_response(response: httpx.Response, *, safe_url: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ScrapeDoApiError(
            "Scrape.do API 响应不是合法 JSON",
            status_code=response.status_code,
            response_excerpt=_redact_token(response.text[:1000]) or safe_url,
        ) from exc


def _api_error_from_payload(status_code: int, payload: Any, *, safe_url: str) -> ScrapeDoApiError:
    if isinstance(payload, dict):
        error_code = str(payload.get("error") or payload.get("code") or "").strip() or None
        message = str(payload.get("message") or payload.get("errorMessage") or f"Scrape.do API 返回 HTTP {status_code}")
        excerpt = json.dumps(_strip_token_fields(payload), ensure_ascii=False)[:1000]
        return ScrapeDoApiError(message, status_code=status_code, error_code=error_code, response_excerpt=excerpt)
    return ScrapeDoApiError(f"Scrape.do API 返回 HTTP {status_code}", status_code=status_code, response_excerpt=safe_url)


def _raise_business_error(payload: dict[str, Any], *, status_code: int, safe_url: str) -> None:
    status = str(payload.get("status") or "").lower()
    if status == "error" or payload.get("error"):
        error_code = str(payload.get("error") or "").strip() or None
        message = str(payload.get("errorMessage") or payload.get("message") or "Scrape.do API 返回业务错误")
        excerpt = json.dumps(_strip_token_fields(payload), ensure_ascii=False)[:1000]
        raise ScrapeDoApiError(message, status_code=status_code, error_code=error_code, response_excerpt=excerpt or safe_url)


def _billing_from_headers(headers: httpx.Headers) -> dict[str, Any]:
    return {
        "request_cost": _optional_int(headers.get("Scrape.do-Request-Cost")),
        "remaining_credits": _optional_int(headers.get("Scrape.do-Remaining-Credits")),
    }


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def _lock_for_token(token: str) -> asyncio.Lock:
    key = token or "__missing__"
    async with _TOKEN_LOCKS_GUARD:
        lock = _TOKEN_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _TOKEN_LOCKS[key] = lock
        return lock


def _redact_token(url: str) -> str:
    if not url:
        return url
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "***" if key.lower() == "token" else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _strip_token_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_token_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if str(key).replace("-", "_").lower() in {"token", "api_key", "authorization"}:
            result[key] = "***"
        else:
            result[key] = _strip_token_fields(item)
    return result
```

- [ ] **Step 4: Run test and commit**

Run:

```bash
pytest tests/scrape_do/test_client.py -v
```

Expected: PASS.

Commit:

```bash
git add opscli/scrape_do/api/client.py tests/scrape_do/test_client.py
git commit -m "feat: add scrape.do api client"
```

---

### Task 3: XLSX export and row normalization

**Files:**
- Create: `opscli/scrape_do/export/__init__.py`
- Create: `opscli/scrape_do/export/xlsx.py`
- Test: `tests/scrape_do/test_export.py`

**Interfaces:**
- Produces: `extract_rows(scenario: str, payload: dict[str, Any]) -> list[dict[str, Any]]` and `export_rows_to_xlsx(...) -> ScrapeDoExportResult`.
- Later tasks consume: row extraction in `ScrapeDoApiManager.run()`.

- [ ] **Step 1: Write failing export tests**

Create `tests/scrape_do/test_export.py`:

```python
from pathlib import Path

from opscli.scrape_do.export.xlsx import extract_rows, export_rows_to_xlsx


def test_extract_rows_normalizes_pdp_payload():
    rows = extract_rows(
        "amazon-pdp",
        {
            "asin": "B0C7BKZ883",
            "brand": "Gogoonike",
            "name": "Laptop Stand",
            "price": 14.99,
            "list_price": 39.99,
            "currency": "USD",
            "rating": 4.6,
            "total_ratings": 2712,
            "is_prime": True,
            "best_seller_rankings": [{"category": "Laptop Stands", "rank": 2}],
            "technical_details": {"Material": "Aluminum"},
        },
    )

    assert rows == [
        {
            "asin": "B0C7BKZ883",
            "brand": "Gogoonike",
            "title": "Laptop Stand",
            "price": 14.99,
            "list_price": 39.99,
            "currency": "USD",
            "rating": 4.6,
            "total_ratings": 2712,
            "is_prime": True,
            "best_seller_rankings": '[{"category":"Laptop Stands","rank":2}]',
            "technical_details": '{"Material":"Aluminum"}',
        }
    ]


def test_extract_rows_normalizes_offer_listing_payload():
    rows = extract_rows(
        "amazon-offer-listing",
        {
            "asin": "B0DGJ7HYG1",
            "offers": [
                {
                    "sellerId": "SELLER1",
                    "merchantName": "6ave",
                    "condition": "New",
                    "listingPrice": {"currencyCode": "USD", "amount": 196.98},
                    "shipping": {"currencyCode": "USD", "amount": 0},
                    "isBuyBoxWinner": False,
                    "isFulfilledByAmazon": False,
                    "primeInformation": {"isPrime": False},
                    "quantity": 30,
                }
            ],
        },
    )

    assert rows[0]["asin"] == "B0DGJ7HYG1"
    assert rows[0]["seller_id"] == "SELLER1"
    assert rows[0]["listing_price"] == 196.98
    assert rows[0]["shipping_price"] == 0
    assert rows[0]["total_price"] == 196.98


def test_extract_rows_normalizes_search_payload():
    rows = extract_rows(
        "amazon-search",
        {
            "keyword": "laptop stands",
            "page": 2,
            "products": [
                {
                    "asin": "B0CBL1TQMP",
                    "title": "Portable Stand",
                    "price": {"currencyCode": "USD", "amount": 18.99},
                    "rating": {"value": 4.4, "count": 2340},
                    "isSponsored": True,
                    "isPrime": True,
                    "position": 2,
                    "badge": None,
                }
            ],
        },
    )

    assert rows[0]["keyword"] == "laptop stands"
    assert rows[0]["page"] == 2
    assert rows[0]["asin"] == "B0CBL1TQMP"
    assert rows[0]["price"] == 18.99
    assert rows[0]["rating"] == 4.4
    assert rows[0]["rating_count"] == 2340
    assert rows[0]["is_sponsored"] is True


def test_export_rows_to_xlsx_writes_file(tmp_path: Path):
    export = export_rows_to_xlsx(
        rows=[{"asin": "B0C7BKZ883", "title": "Laptop Stand"}],
        output_path=tmp_path / "job.xlsx",
        scenario="amazon-pdp",
        site="US",
        params={"asin": "B0C7BKZ883"},
    )

    assert Path(export.path).exists()
    assert export.filename == "job.xlsx"
    assert export.url.startswith("file:")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/scrape_do/test_export.py -v
```

Expected: FAIL because export module does not exist.

- [ ] **Step 3: Implement export normalization**

Create `opscli/scrape_do/export/__init__.py`:

```python
"""Scrape.do export package。"""
```

Create `opscli/scrape_do/export/xlsx.py`:

```python
"""Scrape.do XLSX 导出。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError
from opscli.scrape_do.domain.models import ScrapeDoExportResult

EXCEL_CELL_LIMIT = 32767


@dataclass(frozen=True)
class ExportColumn:
    title: str
    source: str


FIELD_TITLES = {
    "asin": "ASIN",
    "site": "站点",
    "keyword": "关键词",
    "page": "页码",
    "position": "页内排名",
    "brand": "品牌",
    "title": "标题",
    "url": "URL",
    "thumbnail": "主图",
    "image_url": "图片",
    "price": "价格",
    "list_price": "标价",
    "shipping_price": "运费",
    "total_price": "总价",
    "currency": "币种",
    "rating": "评分",
    "rating_count": "评分数",
    "total_ratings": "总评分数",
    "review_count_text": "评论数文本",
    "is_sponsored": "广告位",
    "is_prime": "Prime",
    "badge": "Badge",
    "seller_id": "Seller ID",
    "merchant_name": "卖家名称",
    "condition": "商品状态",
    "is_buybox_winner": "Buy Box",
    "is_fba": "FBA",
    "ships_from": "发货地",
    "delivery_date": "配送日期",
    "quantity": "库存数量",
    "description": "描述",
    "shipping_info": "配送信息",
    "best_seller_rankings": "BSR",
    "technical_details": "技术规格",
}


def extract_rows(scenario: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if scenario == "amazon-pdp":
        return [_pdp_row(payload)] if payload else []
    if scenario == "amazon-offer-listing":
        asin = str(payload.get("asin") or "")
        offers = payload.get("offers")
        if not isinstance(offers, list):
            return []
        return [_offer_row(asin, offer) for offer in offers if isinstance(offer, dict)]
    if scenario == "amazon-search":
        keyword = str(payload.get("keyword") or "")
        page = payload.get("page")
        products = payload.get("products")
        if not isinstance(products, list):
            return []
        return [_search_row(keyword, page, product) for product in products if isinstance(product, dict)]
    return [_normalize_row(payload)]


def export_rows_to_xlsx(
    *,
    rows: list[dict[str, Any]],
    output_path: Path,
    scenario: str,
    site: str = "US",
    params: dict[str, Any] | None = None,
) -> ScrapeDoExportResult:
    try:
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:
        raise ScrapeDoConfigError("缺少 openpyxl 依赖，无法导出 XLSX") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title=_safe_sheet_title(f"{scenario}-{site}"))
    header_fill = PatternFill("solid", fgColor="EAF2F8")
    header_font = Font(bold=True)
    columns = _columns_from_rows(rows)

    header_cells = []
    for column in columns:
        cell = WriteOnlyCell(sheet, value=column.title)
        cell.font = header_font
        cell.fill = header_fill
        header_cells.append(cell)
    sheet.append(header_cells)

    for row in rows:
        normalized = _normalize_row(row)
        sheet.append([_cell_value(normalized.get(column.source)) for column in columns])

    for column_index, column in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(column_index)].width = min(max(len(column.title) + 2, 12), 48)

    workbook.save(output_path)
    resolved = output_path.resolve()
    return ScrapeDoExportResult(path=str(resolved), filename=resolved.name, url=resolved.as_uri())


def _pdp_row(payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "asin": payload.get("asin"),
        "brand": payload.get("brand"),
        "title": payload.get("name") or payload.get("title"),
        "url": payload.get("url"),
        "thumbnail": payload.get("thumbnail"),
        "price": payload.get("price"),
        "list_price": payload.get("list_price"),
        "currency": payload.get("currency"),
        "rating": payload.get("rating"),
        "total_ratings": payload.get("total_ratings"),
        "is_prime": payload.get("is_prime"),
        "description": payload.get("description"),
        "shipping_info": _json_cell(payload.get("shipping_info")),
        "best_seller_rankings": _json_cell(payload.get("best_seller_rankings")),
        "technical_details": _json_cell(payload.get("technical_details")),
    }
    return {key: value for key, value in row.items() if value is not None and value != ""}


def _offer_row(asin: str, offer: dict[str, Any]) -> dict[str, Any]:
    listing_price = _money_amount(offer.get("listingPrice"))
    shipping_price = _money_amount(offer.get("shipping"))
    currency = _money_currency(offer.get("listingPrice")) or _money_currency(offer.get("shipping"))
    prime = offer.get("primeInformation") if isinstance(offer.get("primeInformation"), dict) else {}
    shipping_time = offer.get("shippingTime") if isinstance(offer.get("shippingTime"), dict) else {}
    row = {
        "asin": asin,
        "seller_id": offer.get("sellerId"),
        "merchant_name": offer.get("merchantName"),
        "condition": offer.get("condition"),
        "listing_price": listing_price,
        "shipping_price": shipping_price,
        "total_price": _sum_money(listing_price, shipping_price),
        "currency": currency,
        "is_buybox_winner": offer.get("isBuyBoxWinner"),
        "is_fba": offer.get("isFulfilledByAmazon"),
        "is_prime": prime.get("isPrime"),
        "ships_from": offer.get("shipsFrom"),
        "delivery_date": shipping_time.get("deliveryDate"),
        "quantity": offer.get("quantity"),
    }
    return {key: value for key, value in row.items() if value is not None and value != ""}


def _search_row(keyword: str, page: Any, product: dict[str, Any]) -> dict[str, Any]:
    rating = product.get("rating") if isinstance(product.get("rating"), dict) else {}
    price = product.get("price")
    row = {
        "keyword": keyword,
        "page": page,
        "position": product.get("position"),
        "asin": product.get("asin"),
        "title": product.get("title"),
        "url": product.get("url"),
        "image_url": product.get("imageUrl"),
        "price": _money_amount(price),
        "currency": _money_currency(price),
        "rating": rating.get("value"),
        "rating_count": rating.get("count"),
        "review_count_text": product.get("reviewCount"),
        "is_sponsored": product.get("isSponsored"),
        "is_prime": product.get("isPrime"),
        "badge": product.get("badge"),
    }
    return {key: value for key, value in row.items() if value is not None and value != ""}


def _money_amount(value: Any) -> Any:
    return value.get("amount") if isinstance(value, dict) else None


def _money_currency(value: Any) -> Any:
    return value.get("currencyCode") if isinstance(value, dict) else None


def _sum_money(left: Any, right: Any) -> Any:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left + right
    if isinstance(left, (int, float)):
        return left
    return None


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[ExportColumn]:
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    if not keys:
        keys = ["value"]
    return [ExportColumn(FIELD_TITLES.get(key, key), key) for key in keys]


def _normalize_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {str(key): _json_cell(value) for key, value in row.items()}
    return {"value": _json_cell(row)}


def _json_cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _cell_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = _json_cell(value)
    if isinstance(value, str) and len(value) > EXCEL_CELL_LIMIT:
        return value[: EXCEL_CELL_LIMIT - 3] + "..."
    return value


def _safe_sheet_title(value: str) -> str:
    text = "".join("-" if char in r"[]:*?/\\" else char for char in value)
    return (text or "scrape-do")[:31]
```

- [ ] **Step 4: Run test and commit**

Run:

```bash
pytest tests/scrape_do/test_export.py -v
```

Expected: PASS.

Commit:

```bash
git add opscli/scrape_do/export tests/scrape_do/test_export.py
git commit -m "feat: add scrape.do exports"
```

---

### Task 4: API manager with task persistence, safe payloads, upload, and status/export

**Files:**
- Create: `opscli/scrape_do/services/api_manager.py`
- Modify: `opscli/scrape_do/services/__init__.py`
- Test: `tests/scrape_do/test_api_manager.py`

**Interfaces:**
- Consumes: `ScrapeDoApiClient`, `ScrapeDoCredentialProvider`, `extract_rows`, `export_rows_to_xlsx`.
- Produces: `ScrapeDoApiManager.scenarios()`, `ScrapeDoApiManager.run(request)`, `ScrapeDoApiManager.job_status(job_id)`.

- [ ] **Step 1: Write failing manager tests**

Create `tests/scrape_do/test_api_manager.py`:

```python
import json
from pathlib import Path

import pytest

from opscli.scrape_do.domain.models import ScrapeDoCredential, ScrapeDoScenarioRequest
from opscli.scrape_do.services.api_manager import ScrapeDoApiManager


class FakeCredentialProvider:
    def get_default(self):
        return ScrapeDoCredential(name="default", token="secret-token", source="test")


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_json(self, endpoint, params):
        self.calls.append((endpoint, params))
        from opscli.scrape_do.api.client import ScrapeDoApiResponse

        assert params["token"] == "secret-token"
        return ScrapeDoApiResponse(
            payload={
                "asin": "B0C7BKZ883",
                "status": "success",
                "brand": "Gogoonike",
                "name": "Laptop Stand",
                "price": 14.99,
            },
            billing={"request_cost": 1, "remaining_credits": 99},
            safe_url="https://api.scrape.do/plugin/amazon/pdp?token=%2A%2A%2A&asin=B0C7BKZ883",
        )


class DisabledUploadClient:
    enabled = False

    def __init__(self, *args, **kwargs):
        pass


def test_run_writes_safe_files_and_export(monkeypatch, tmp_path: Path):
    from opscli.scrape_do.services import api_manager as module

    monkeypatch.setattr(module, "ScrapeDoApiClient", FakeClient)
    monkeypatch.setattr(module, "FileUploadClient", DisabledUploadClient)
    manager = ScrapeDoApiManager(api_key_provider=FakeCredentialProvider())

    result = pytest.run(asyncio=True)(manager.run)(
        ScrapeDoScenarioRequest(
            scenario="amazon-pdp",
            site="US",
            params={"asin": "B0C7BKZ883"},
            output_dir=str(tmp_path),
            job_id="scrape-do-job",
        )
    )

    assert result.job_id == "scrape-do-job"
    assert result.row_count == 1
    assert result.billing == {"request_cost": 1, "remaining_credits": 99}
    assert Path(result.export.path).exists()

    params_text = Path(result.params_path).read_text(encoding="utf-8")
    raw_text = Path(result.raw_path).read_text(encoding="utf-8")
    result_text = Path(result.result_path).read_text(encoding="utf-8")
    assert "secret-token" not in params_text
    assert "secret-token" not in raw_text
    assert "secret-token" not in result_text
    assert "token" not in json.loads(params_text)["normalized_params"]

    status = manager.job_status("scrape-do-job")
    assert status["job_id"] == "scrape-do-job"
    assert status["row_count"] == 1
```

If the project has no `pytest.run` helper, use this exact helper instead at the top of the file:

```python
import asyncio


def _run(coro):
    return asyncio.run(coro)
```

and call:

```python
result = _run(manager.run(ScrapeDoScenarioRequest(...)))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/scrape_do/test_api_manager.py -v
```

Expected: FAIL because `ScrapeDoApiManager` does not exist.

- [ ] **Step 3: Implement manager**

Create `opscli/scrape_do/services/api_manager.py`:

```python
"""Scrape.do API 场景执行和落盘。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.scrape_do.accounts import ScrapeDoCredentialProvider
from opscli.scrape_do.api.client import ScrapeDoApiClient
from opscli.scrape_do.api.scenarios import get_scenario, list_scenarios
from opscli.scrape_do.config import ScrapeDoSettings, load_settings
from opscli.scrape_do.domain.exceptions import ScrapeDoConfigError
from opscli.scrape_do.domain.models import ScrapeDoScenarioRequest, ScrapeDoScenarioResult
from opscli.scrape_do.export.xlsx import export_rows_to_xlsx, extract_rows
from opscli.shared.file_uploads import FileUploadClient, FileUploadError


class ScrapeDoApiManager:
    """执行 Scrape.do API 场景并保存请求和响应数据。"""

    def __init__(
        self,
        *,
        settings: ScrapeDoSettings | None = None,
        api_key_provider: ScrapeDoCredentialProvider | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.jwt = jwt
        self.session_id = session_id
        self.api_key_provider = api_key_provider or ScrapeDoCredentialProvider()

    def scenarios(self) -> list[dict[str, Any]]:
        return list_scenarios()

    async def run(self, request: ScrapeDoScenarioRequest) -> ScrapeDoScenarioResult:
        export_format = _normalize_export_format(request.export_format)
        scenario = get_scenario(request.scenario)
        site = _normalize_site(request.site)
        job_id = request.job_id or _build_job_id(request, site)
        root_dir = self._build_root_dir(request, job_id)
        root_dir.mkdir(parents=True, exist_ok=True)
        params_path = root_dir / "params.json"
        raw_path = root_dir / "raw.json"
        result_path = root_dir / "result.json"

        credential = self.api_key_provider.get_default()
        normalized_params = scenario.build_params(params=request.params, site=site, token=credential.token)
        safe_params = _strip_sensitive(normalized_params)
        warnings: list[dict[str, Any]] = []

        _write_json(
            params_path,
            {
                "job_id": job_id,
                "request": request.to_dict(),
                "scenario": scenario.to_public_dict(),
                "site": site,
                "normalized_params": safe_params,
                "account": credential.to_public_dict(),
                "settings": self.settings.to_public_dict(),
                "export_format": export_format,
            },
        )

        timeout = request.timeout_seconds or self.settings.timeout_seconds
        async with ScrapeDoApiClient(timeout_seconds=timeout) as client:
            response = await client.get_json(scenario.endpoint, normalized_params)

        raw_payload = {
            "job_id": job_id,
            "scenario": request.scenario,
            "site": site,
            "endpoint": scenario.endpoint,
            "request_url": response.safe_url,
            "request_params": safe_params,
            "response": _strip_html(response.payload),
            "billing": response.billing,
            "warnings": warnings,
        }
        _write_json(raw_path, raw_payload)

        rows = extract_rows(request.scenario, response.payload)
        rows = [{"site": site, **row} for row in rows]
        export = export_rows_to_xlsx(
            rows=rows,
            output_path=root_dir / f"{job_id}.xlsx",
            scenario=request.scenario,
            site=site,
            params=request.params,
        )
        _upload_export_if_enabled(
            export=export,
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            warnings=warnings,
            jwt=self.jwt,
            session_id=self.session_id,
        )

        result = ScrapeDoScenarioResult(
            job_id=job_id,
            scenario=request.scenario,
            site=site,
            row_count=len(rows),
            root_dir=str(root_dir),
            params_path=str(params_path),
            raw_path=str(raw_path),
            result_path=str(result_path),
            export=export,
            data=rows,
            request={"method": "GET", "endpoint": scenario.endpoint, "params": safe_params, "export_format": export_format},
            billing=response.billing,
            warnings=warnings,
        )
        _write_json(result_path, result.to_dict())
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        root_dir = self.settings.output_dir / job_id
        result_path = root_dir / "result.json"
        if not result_path.exists():
            raise ScrapeDoConfigError(f"任务不存在：{job_id}")
        return json.loads(result_path.read_text(encoding="utf-8"))

    def _build_root_dir(self, request: ScrapeDoScenarioRequest, job_id: str) -> Path:
        base_dir = Path(request.output_dir).expanduser() if request.output_dir else self.settings.output_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / job_id


def _normalize_export_format(value: str) -> str:
    text = (value or "").strip().lower()
    if text in {"", "xls", "xlsx"}:
        return "xls"
    raise ScrapeDoConfigError(f"不支持的导出格式：{value}。Scrape.do 当前仅支持 xls/xlsx 表格导出。")


def _normalize_site(value: Any) -> str:
    text = str(value or "US").strip().upper()
    return "GB" if text == "UK" else text or "US"


def _build_job_id(request: ScrapeDoScenarioRequest, site: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    target = _target_label(request.params)
    parts = ["ScrapeDo", _scenario_label(request.scenario), site, target, timestamp, suffix]
    return "-".join(part for part in parts if part)


def _scenario_label(scenario: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", scenario) if part)


def _target_label(params: dict[str, Any] | None) -> str:
    if not isinstance(params, dict):
        return ""
    value = params.get("asin") or params.get("keyword")
    if value is None:
        return ""
    text = str(value).strip().replace(" ", "-")
    text = re.sub(r"[^A-Za-z0-9\-]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")[:64]


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "_").lower()
        if normalized in {"token", "api_key", "authorization"}:
            continue
        result[key] = _strip_sensitive(item)
    return result


def _strip_html(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_html(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: _strip_html(item) for key, item in value.items() if str(key).lower() != "html"}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _upload_export_if_enabled(*, export, job_id: str, scenario: str, site: str, warnings: list[dict[str, Any]], jwt: str | None, session_id: str | None) -> None:
    client = FileUploadClient(jwt=jwt, session_id=session_id)
    if not client.enabled:
        return
    try:
        uploaded = client.upload_file(
            Path(export.path),
            purpose="scrape_do_export",
            folder="scrape-do/exports",
            metadata={"job_id": job_id, "scenario": scenario, "site": site},
        )
    except FileUploadError as exc:
        warnings.append({"stage": "file_upload", "message": "导出文件上传失败，已保留服务端本地文件", "error": str(exc)})
        return
    export.url = uploaded.url
```

- [ ] **Step 4: Fix test helper and run tests**

If Step 1 used `pytest.run`, replace it with `_run` because this repository uses local `_run` helpers:

```python
import asyncio


def _run(coro):
    return asyncio.run(coro)
```

Run:

```bash
pytest tests/scrape_do/test_api_manager.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add opscli/scrape_do/services tests/scrape_do/test_api_manager.py
git commit -m "feat: add scrape.do api manager"
```

---

### Task 5: MCP tools and public result sanitization

**Files:**
- Create: `opscli/mcp/tools/scrape_do.py`
- Modify: `opscli/mcp/server.py`
- Create: `opscli/skills/templates/ops-scrape-do/SKILL_MCP.md`
- Modify: `opscli/skills/templates/manifest.json`
- Test: `tests/mcp/test_scrape_do_tools.py`

**Interfaces:**
- Consumes: `ScrapeDoApiManager`, `ScrapeDoScenarioRequest`.
- Produces MCP tools: `scrape_do_spec_must_read`, `scrape_do_scenarios`, `scrape_do_run`, `scrape_do_job_status`, `scrape_do_export`.

- [ ] **Step 1: Write failing MCP tests**

Create `tests/mcp/test_scrape_do_tools.py`:

```python
import asyncio
from pathlib import Path

from fastmcp import Client

from opscli.mcp.server import mcp
from opscli.mcp.tools import scrape_do as scrape_do_tools
from opscli.scrape_do.domain.models import ScrapeDoExportResult, ScrapeDoScenarioResult


def _run(coro):
    return asyncio.run(coro)


class DummyManager:
    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    def scenarios(self):
        return [{"scenario_id": "amazon-pdp", "title": "Amazon PDP 商品详情"}]

    async def run(self, request):
        self.__class__.last_request = request
        result = ScrapeDoScenarioResult.empty(
            job_id="job-1",
            scenario=request.scenario,
            site=request.site,
            root_dir=Path("/tmp/job-1"),
            params_path=Path("/tmp/job-1/params.json"),
            raw_path=Path("/tmp/job-1/raw.json"),
            result_path=Path("/tmp/job-1/result.json"),
        )
        result.row_count = 1
        result.export = ScrapeDoExportResult(path="/tmp/job-1.xlsx", filename="job-1.xlsx")
        result.data = [{"asin": "B0C7BKZ883", "title": "Laptop Stand"}]
        result.request = {"params": {"token": "secret-token", "asin": "B0C7BKZ883"}}
        result.billing = {"request_cost": 1, "remaining_credits": 99}
        return result

    def job_status(self, job_id):
        return {
            "job_id": job_id,
            "row_count": 1,
            "root_dir": f"/tmp/{job_id}",
            "params_path": f"/tmp/{job_id}/params.json",
            "raw_path": f"/tmp/{job_id}/raw.json",
            "result_path": f"/tmp/{job_id}/result.json",
            "request": {"params": {"token": "secret-token", "asin": "B0C7BKZ883"}},
            "response": {"asin": "B0C7BKZ883"},
            "export": {"path": f"/tmp/{job_id}.xlsx", "filename": f"{job_id}.xlsx", "url": None},
        }


def test_scrape_do_tools_are_registered():
    async def scenario():
        async with Client(mcp) as client:
            return await client.list_tools()

    names = [tool.name for tool in _run(scenario())]

    assert "scrape_do_spec_must_read" in names
    assert "scrape_do_scenarios" in names
    assert "scrape_do_run" in names
    assert "scrape_do_job_status" in names
    assert "scrape_do_export" in names


def test_scrape_do_scenarios_uses_manager(monkeypatch):
    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DummyManager)

    result = _run(scrape_do_tools.scrape_do_scenarios())

    assert result["success"] is True
    assert result["data"][0]["scenario_id"] == "amazon-pdp"


def test_scrape_do_run_hides_token_paths_and_raw(monkeypatch):
    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DummyManager)

    result = _run(
        scrape_do_tools.scrape_do_run(
            scenario="amazon-pdp",
            site="US",
            params='{"asin":"B0C7BKZ883"}',
            export_format="xls",
        )
    )

    assert result["success"] is True
    data = result["data"]
    assert data["job_id"] == "job-1"
    assert DummyManager.last_request.params == {"asin": "B0C7BKZ883"}
    assert "params_path" not in data
    assert "raw_path" not in data
    assert "result_path" not in data
    assert "root_dir" not in data
    assert "secret-token" not in str(data)
    assert "token" not in str(data)
    assert data["data_preview"][0]["asin"] == "B0C7BKZ883"


def test_scrape_do_job_status_hides_internal_paths_and_response(monkeypatch):
    monkeypatch.setattr("opscli.scrape_do.services.ScrapeDoApiManager", DummyManager)

    result = _run(scrape_do_tools.scrape_do_job_status("job-1"))

    assert result["success"] is True
    data = result["data"]
    assert "root_dir" not in data
    assert "params_path" not in data
    assert "raw_path" not in data
    assert "result_path" not in data
    assert "response" not in data
    assert "path" not in data["export"]
    assert "secret-token" not in str(data)
    assert any(item["stage"] == "export_url_unavailable" for item in data["warnings"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/mcp/test_scrape_do_tools.py -v
```

Expected: FAIL because MCP tool module does not exist / not registered.

- [ ] **Step 3: Implement MCP tool module**

Create `opscli/mcp/tools/scrape_do.py`:

```python
"""Scrape.do MCP 工具模块。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.skills.packaging import get_builtin_templates_dir

from .helpers import _err, _get_auth_pair, _ok, _parse_json_arg

MAX_PUBLIC_DATA_PREVIEW_ROWS = 20


def _scrape_do_skill_dir() -> Path:
    return get_builtin_templates_dir() / "ops-scrape-do"


async def scrape_do_spec_must_read() -> dict:
    """读取 Scrape.do MCP 使用规范。"""
    spec_path = _scrape_do_skill_dir() / "SKILL_MCP.md"
    if not spec_path.exists():
        return _err(FileNotFoundError(f"Scrape.do MCP 规范文档不存在：{spec_path}。请检查 opscli 安装是否完整。"), tool="MCP → scrape_do_spec_must_read()")
    try:
        content = spec_path.read_text(encoding="utf-8")
        return _ok({"spec": content, "source": str(spec_path), "sources": [str(spec_path)]})
    except Exception as exc:
        return _err(exc, tool="MCP → scrape_do_spec_must_read()")


async def scrape_do_scenarios() -> dict:
    """列出 Scrape.do 支持的接口场景。"""
    try:
        from opscli.scrape_do.services import ScrapeDoApiManager

        return _ok(ScrapeDoApiManager().scenarios())
    except Exception as exc:
        return _err(exc, tool="MCP → scrape_do_scenarios()")


async def scrape_do_run(
    scenario: str,
    params: dict[str, Any] | str | None = None,
    site: str = "US",
    export_format: str = "xls",
    output_dir: str | None = None,
    job_id: str | None = None,
    timeout_seconds: int | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """执行 Scrape.do 场景并保存请求参数、原始响应、规范化结果和导出 XLSX。"""
    call_params = {"scenario": scenario, "site": site, "export_format": export_format, "job_id": job_id, "timeout_seconds": timeout_seconds}
    try:
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        from opscli.scrape_do.domain.models import ScrapeDoScenarioRequest
        from opscli.scrape_do.services import ScrapeDoApiManager

        parsed_params = _parse_json_arg(params, dict) or {}
        request = ScrapeDoScenarioRequest(
            scenario=scenario,
            site=site,
            params=parsed_params,
            output_dir=output_dir,
            job_id=job_id,
            export_format=export_format,
            timeout_seconds=timeout_seconds,
        )
        result = await ScrapeDoApiManager(jwt=jw, session_id=sid).run(request)
        return _ok(_public_result(result.to_dict()))
    except Exception as exc:
        return _err(exc, tool="MCP → scrape_do_run(...)", call_params=call_params)


async def scrape_do_job_status(job_id: str) -> dict:
    """读取 Scrape.do 任务结果。"""
    try:
        from opscli.scrape_do.services import ScrapeDoApiManager

        return _ok(_public_result(ScrapeDoApiManager().job_status(job_id)))
    except Exception as exc:
        return _err(exc, tool="MCP → scrape_do_job_status(...)", call_params={"job_id": job_id})


async def scrape_do_export(job_id: str) -> dict:
    """读取 Scrape.do 任务导出文件信息。"""
    try:
        from opscli.scrape_do.services import ScrapeDoApiManager

        status = ScrapeDoApiManager().job_status(job_id)
        export = _public_export_payload(status.get("export"))
        if not export.get("url"):
            raise ValueError(f"任务导出文件没有可下载地址：{job_id}")
        return _ok(export)
    except Exception as exc:
        return _err(exc, tool="MCP → scrape_do_export(...)", call_params={"job_id": job_id})


_ALL_TOOLS = [scrape_do_spec_must_read, scrape_do_scenarios, scrape_do_run, scrape_do_job_status, scrape_do_export]


def _public_result(payload: dict[str, Any]) -> dict[str, Any]:
    public = _strip_sensitive(payload)
    if isinstance(public, dict):
        for key in ["root_dir", "params_path", "raw_path", "result_path", "response"]:
            public.pop(key, None)
        _sanitize_public_export(public)
        _compact_public_data(public)
        public["warnings"] = _public_warnings(public.get("warnings"))
    return public


def _compact_public_data(public: dict[str, Any]) -> None:
    data = public.get("data")
    if isinstance(data, list):
        public["data_preview"] = data[:MAX_PUBLIC_DATA_PREVIEW_ROWS]
        public.pop("data", None)


def _sanitize_public_export(public: dict[str, Any]) -> None:
    export = public.get("export")
    if not isinstance(export, dict):
        return
    export.pop("path", None)
    url = export.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        export["url"] = None
        url = None
    if url:
        return
    warnings = public.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings.append({"stage": "export_url_unavailable", "message": "当前任务导出文件没有可下载地址，请稍后重试或联系管理员检查上传链路。"})
    public["warnings"] = warnings


def _public_export_payload(export: Any) -> dict[str, Any]:
    if not isinstance(export, dict):
        raise ValueError("任务无导出文件")
    payload = _strip_sensitive(export)
    if not isinstance(payload, dict):
        raise ValueError("任务导出结构不合法")
    payload.pop("path", None)
    url = payload.get("url")
    if isinstance(url, str) and url.startswith("file://"):
        payload["url"] = None
    return payload


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    blocked = {"token", "api_key", "authorization", "raw_response", "request_params", "normalized_params", "settings"}
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).replace("-", "_").lower()
        if normalized in blocked:
            continue
        result[key] = _strip_sensitive(item)
    return result


def _public_warnings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    warnings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        stage = item.get("stage")
        message = item.get("message")
        if stage == "file_upload":
            warnings.append({"stage": stage, "message": message or "导出文件上传失败，已保留服务端本地文件"})
        elif message:
            warnings.append({"stage": stage, "message": message})
    return warnings


def register(mcp) -> None:
    """向 FastMCP 实例注册 Scrape.do 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)
```

- [ ] **Step 4: Register MCP tools and add spec template**

Modify `opscli/mcp/server.py` imports and registration:

```python
from opscli.mcp.tools import scrape_do as _scrape_do_tools
```

Add near other provider registrations:

```python
_scrape_do_tools.register(_telemetry_mcp)
```

Create `opscli/skills/templates/ops-scrape-do/SKILL_MCP.md`:

```markdown
# ops-scrape-do MCP 使用规范

用于调用 Scrape.do Amazon Scraper API 的结构化 JSON 能力。当前只开放三个非原始 HTML 场景：

- `amazon-pdp`：按 ASIN 获取 PDP 商品详情。
- `amazon-offer-listing`：按 ASIN 获取全部卖家报价和 Buy Box 信息。
- `amazon-search`：按关键词获取搜索结果和类目页同结构结果。

## 必读规则

1. 首次使用先调用 `scrape_do_spec_must_read` 和 `scrape_do_scenarios`。
2. 不要请求 raw HTML endpoint；本工具不会暴露 `/plugin/amazon/`。
3. 不要在参数中传 token；token 由 OPS 集成账号 `scrape_do` 或服务端环境变量托管。
4. `zipcode` 与 `countryName` 不能同时传。
5. Scrape.do Amazon API 每个 token 并发限制为 1；批量任务会串行执行。
6. `super=true` 会使用更高成本代理，只有普通请求失败或业务明确要求时使用。

## 示例

```json
{
  "scenario": "amazon-pdp",
  "site": "US",
  "params": {"asin": "B0C7BKZ883", "zipcode": "90210"}
}
```

```json
{
  "scenario": "amazon-offer-listing",
  "site": "US",
  "params": {"asin": "B0DGJ7HYG1"}
}
```

```json
{
  "scenario": "amazon-search",
  "site": "US",
  "params": {"keyword": "laptop stands", "page": 1, "language": "EN"}
}
```
```

Modify `opscli/skills/templates/manifest.json`, add a `skills.ops-scrape-do` entry:

```json
"ops-scrape-do": {
  "source": true,
  "wheel": true,
  "binary": true,
  "binary_full": true,
  "tier": "experimental",
  "reason": "Scrape.do Amazon Scraper 已接入正式 CLI 代理远端 MCP 模式，可作为补充数据源实验 Skill 使用"
}
```

- [ ] **Step 5: Run MCP tests and commit**

Run:

```bash
pytest tests/mcp/test_scrape_do_tools.py -v
```

Expected: PASS.

Commit:

```bash
git add opscli/mcp/tools/scrape_do.py opscli/mcp/server.py opscli/skills/templates/ops-scrape-do/SKILL_MCP.md opscli/skills/templates/manifest.json tests/mcp/test_scrape_do_tools.py
git commit -m "feat: expose scrape.do mcp tools"
```

---

### Task 6: Public CLI and remote adapter

**Files:**
- Create: `opscli/scrape_do/remote_adapter.py`
- Create: `opscli/scrape_do/cli.py`
- Modify: `opscli/cli.py`
- Test: `tests/scrape_do/test_cli_remote.py`

**Interfaces:**
- Consumes: MCP tool names from Task 5.
- Produces CLI commands: `opscli scrape-do scenarios`, `run`, `job-status`, `export`.

- [ ] **Step 1: Write failing CLI tests**

Create `tests/scrape_do/test_cli_remote.py`:

```python
"""Scrape.do 正式 CLI 远端调用测试。"""

import json

from typer.testing import CliRunner

from opscli.scrape_do import cli as scrape_do_cli

runner = CliRunner()


def test_public_scrape_do_run_uses_remote_adapter(monkeypatch):
    captured = {}

    class FakeAdapter:
        def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"success": True, "data": {"job_id": "public-job"}, "error": None}

    monkeypatch.setattr(scrape_do_cli, "ScrapeDoRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(
        scrape_do_cli.app,
        [
            "run",
            "amazon-pdp",
            "--site",
            "JP",
            "--params",
            json.dumps({"asin": "B07YRMT36L"}),
            "--export-format",
            "xlsx",
            "--timeout-seconds",
            "45",
        ],
    )

    assert result.exit_code == 0
    assert captured["kwargs"] == {
        "scenario": "amazon-pdp",
        "site": "JP",
        "params": {"asin": "B07YRMT36L"},
        "job_id": None,
        "export_format": "xlsx",
        "timeout_seconds": 45,
    }
    assert '"job_id": "public-job"' in result.stdout


def test_public_scrape_do_queries_use_remote_adapter(monkeypatch):
    class FakeAdapter:
        def scenarios(self):
            return {"success": True, "data": [{"scenario_id": "amazon-pdp"}]}

        def job_status(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "state": "succeeded"}}

        def export(self, job_id):
            return {"success": True, "data": {"job_id": job_id, "filename": "scrape-do-job-1.xlsx"}}

    monkeypatch.setattr(scrape_do_cli, "ScrapeDoRemoteAdapter", lambda: FakeAdapter())

    scenarios_result = runner.invoke(scrape_do_cli.app, ["scenarios"])
    status_result = runner.invoke(scrape_do_cli.app, ["job-status", "job-1"])
    export_result = runner.invoke(scrape_do_cli.app, ["export", "job-1"])

    assert scenarios_result.exit_code == 0
    assert '"scenario_id": "amazon-pdp"' in scenarios_result.stdout
    assert status_result.exit_code == 0
    assert '"job_id": "job-1"' in status_result.stdout
    assert export_result.exit_code == 0
    assert '"filename": "scrape-do-job-1.xlsx"' in export_result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/scrape_do/test_cli_remote.py -v
```

Expected: FAIL because `opscli.scrape_do.cli` does not exist.

- [ ] **Step 3: Implement remote adapter and CLI**

Create `opscli/scrape_do/remote_adapter.py`:

```python
"""Scrape.do 远端 MCP 适配层。"""

from __future__ import annotations

from typing import Any

from opscli.shared.remote_mcp_adapter import RemoteMcpAdapter


class ScrapeDoRemoteAdapter(RemoteMcpAdapter):
    """将正式 CLI 命令映射到远端 Scrape.do MCP tools。"""

    def scenarios(self) -> dict[str, Any]:
        return self.call_tool("scrape_do_scenarios", {})

    def run(
        self,
        *,
        scenario: str,
        site: str,
        params: dict[str, Any],
        job_id: str | None,
        export_format: str,
        timeout_seconds: int | None,
    ) -> dict[str, Any]:
        return self.call_tool(
            "scrape_do_run",
            {
                "scenario": scenario,
                "site": site,
                "params": params,
                "job_id": job_id,
                "export_format": export_format,
                "timeout_seconds": timeout_seconds,
            },
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self.call_tool("scrape_do_job_status", {"job_id": job_id})

    def export(self, job_id: str) -> dict[str, Any]:
        return self.call_tool("scrape_do_export", {"job_id": job_id})
```

Create `opscli/scrape_do/cli.py`:

```python
"""Scrape.do 正式 CLI。"""

from __future__ import annotations

import json
from typing import Any

import typer

from opscli.scrape_do.remote_adapter import ScrapeDoRemoteAdapter

app = typer.Typer(help="Scrape.do Amazon Scraper 远端 MCP 正式命令面。")


@app.command("scenarios")
def scenarios() -> None:
    """列出远端命令面支持的 Scrape.do 场景。"""
    payload = ScrapeDoRemoteAdapter().scenarios()
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("run")
def run_scenario(
    scenario: str = typer.Argument(..., help="场景 ID，如 amazon-pdp、amazon-offer-listing、amazon-search"),
    site: str = typer.Option("US", "--site", help="站点，如 US、JP、DE、GB"),
    params: str = typer.Option("{}", "--params", help="场景参数 JSON 字符串"),
    job_id: str | None = typer.Option(None, "--job-id", help="指定任务 ID"),
    export_format: str = typer.Option("xls", "--export-format", help="导出格式：xls/xlsx"),
    timeout_seconds: int | None = typer.Option(None, "--timeout-seconds", help="请求超时时间秒数"),
) -> None:
    """按正式公共命令契约执行 Scrape.do 场景。"""
    payload = ScrapeDoRemoteAdapter().run(
        scenario=scenario,
        site=site,
        params=_parse_params(params),
        job_id=job_id,
        export_format=export_format,
        timeout_seconds=timeout_seconds,
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("job-status")
def job_status(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Scrape.do 任务结果。"""
    payload = ScrapeDoRemoteAdapter().job_status(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("export")
def export(job_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """读取 Scrape.do 任务导出文件信息。"""
    payload = ScrapeDoRemoteAdapter().export(job_id)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_params(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"params 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise typer.BadParameter("params 必须是 JSON 对象")
    return parsed
```

Modify `opscli/cli.py`:

```python
from opscli.scrape_do.cli import app as scrape_do_app
```

Add one registration line:

```python
app.add_typer(scrape_do_app, name="scrape-do")
```

- [ ] **Step 4: Run CLI tests and commit**

Run:

```bash
pytest tests/scrape_do/test_cli_remote.py -v
```

Expected: PASS.

Commit:

```bash
git add opscli/scrape_do/remote_adapter.py opscli/scrape_do/cli.py opscli/cli.py tests/scrape_do/test_cli_remote.py
git commit -m "feat: add scrape.do cli"
```

---

### Task 7: Integration regression and full verification

**Files:**
- Modify as needed only if tests reveal mismatches in files created by earlier tasks.
- Test: all Scrape.do and MCP registration tests.

**Interfaces:**
- Verifies all user-facing commands and tools are registered and token-safe.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/scrape_do tests/mcp/test_scrape_do_tools.py -v
```

Expected: PASS.

- [ ] **Step 2: Run nearby provider regression tests**

Run:

```bash
pytest tests/mcp/test_google_trends_tools.py tests/mcp/test_keepa_tools.py tests/mcp/test_beta_tools.py tests/google_trends tests/keepa tests/canopy -v
```

Expected: PASS or existing unrelated failures only. If any failure is caused by Scrape.do registration/import changes, fix it before continuing.

- [ ] **Step 3: Verify CLI import and help**

Run:

```bash
python -m opscli.cli --help
python -m opscli.cli scrape-do --help
```

Expected: both commands exit 0 and the second lists `scenarios`, `run`, `job-status`, `export`.

- [ ] **Step 4: Verify no token literals in generated code paths**

Run:

```bash
rg "secret-token|<SDO-token>|include_html=true|raw-html" opscli/scrape_do opscli/mcp/tools/scrape_do.py tests/scrape_do tests/mcp/test_scrape_do_tools.py
```

Expected:
- `secret-token` appears only in tests.
- `<SDO-token>` does not appear in runtime code.
- `include_html=true` does not appear in runtime code.
- `raw-html` appears only in tests/spec text as a negative assertion or documentation saying it is not supported.

- [ ] **Step 5: Commit final fixes**

If Step 1-4 required changes:

```bash
git add opscli tests
git commit -m "test: verify scrape.do integration"
```

If no changes were needed, do not create an empty commit.

---

## Self-Review

- Spec coverage: The plan covers independent provider module, three structured Amazon endpoints, token source, token-safe HTTP client, single-token serialization, row normalization, XLSX export, task persistence, MCP tools, public CLI, skill spec, and registration.
- Placeholder scan: No implementation step uses TBD/TODO/fill-in placeholders. Every code-writing step includes exact code blocks or exact file modifications.
- Type consistency: `ScrapeDoScenarioRequest`, `ScrapeDoScenarioResult`, `ScrapeDoExportResult`, `ScrapeDoApiManager`, `ScrapeDoRemoteAdapter`, and MCP tool names are defined before later tasks consume them.
- Scope check: ASIN Data Collector integration is intentionally deferred to a later plan after the provider is independently testable.
