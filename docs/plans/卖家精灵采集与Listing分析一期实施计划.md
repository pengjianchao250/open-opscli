# 卖家精灵采集与 Listing 分析一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增卖家精灵采集 CLI 与两个 Skill 模板，支持围绕 ASIN 和显式关键词采集高频词、关键词挖掘数据、页面证据，并为 Listing 表达与一致性分析提供标准化材料。

**Architecture:** 新增 `opscli/seller_sprite` 作为和 `opscli/amazon` 平级的正式 CLI 模块；采集模块负责 Playwright 页面操作、接口响应归档、HTML/Markdown/截图留存和标准化 JSON 输出。Skill 层只指导 Agent 调用正式 CLI 与约束分析输出，不直接实现采集逻辑。

**Tech Stack:** Python 3.10、Typer、Playwright、httpx、html2text、dataclasses、`opscli.config.CONFIG_DIR`。

---

## 文件结构

创建或修改以下文件：

- Create: `opscli/seller_sprite/__init__.py`，模块包入口。
- Create: `opscli/seller_sprite/cli.py`，兼容项目新增模块规范，转发到 `commands/cli.py`。
- Create: `opscli/seller_sprite/commands/__init__.py`，命令包入口。
- Create: `opscli/seller_sprite/commands/cli.py`，定义 `collect`、`frequency`、`keyword-mining`、`archive`、`schema` 命令。
- Create: `opscli/seller_sprite/domain/__init__.py`，领域包入口。
- Create: `opscli/seller_sprite/domain/exceptions.py`，卖家精灵模块业务异常。
- Create: `opscli/seller_sprite/domain/models.py`，输入参数、标准化结果、归档 manifest 数据模型。
- Create: `opscli/seller_sprite/scraping/__init__.py`，采集包入口。
- Create: `opscli/seller_sprite/scraping/api_recorder.py`，记录 Playwright response JSON。
- Create: `opscli/seller_sprite/scraping/archiver.py`，保存截图、HTML、Markdown 和 JSON。
- Create: `opscli/seller_sprite/scraping/captcha.py`，验证码检测与 provider 预留。
- Create: `opscli/seller_sprite/scraping/scraper.py`，Playwright 持久化 profile、页面触发和响应采集。
- Create: `opscli/seller_sprite/services/__init__.py`，服务包入口。
- Create: `opscli/seller_sprite/services/manager.py`，编排采集、标准化和落盘。
- Modify: `opscli/cli.py`，注册 `seller-sprite` 子命令。
- Modify: `pyproject.toml`，新增 `html2text>=2025.4.15`。
- Create: `opscli/skills/templates/ops-seller-sprite/SKILL.md`。
- Create: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`。
- Create: `opscli/skills/templates/ops-seller-sprite/data/VERSION.json`。
- Create: `opscli/skills/templates/ops-amazon-listing-analysis/SKILL.md`。
- Create: `opscli/skills/templates/ops-amazon-listing-analysis/data/VERSION.json`。

不创建测试文件；本仓库当前指令禁止 TDD 和单测类测试行为。

---

### Task 1: 接入模块骨架与依赖

**Files:**
- Create: `opscli/seller_sprite/__init__.py`
- Create: `opscli/seller_sprite/cli.py`
- Create: `opscli/seller_sprite/commands/__init__.py`
- Create: `opscli/seller_sprite/domain/__init__.py`
- Create: `opscli/seller_sprite/scraping/__init__.py`
- Create: `opscli/seller_sprite/services/__init__.py`
- Modify: `opscli/cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 创建包入口文件**

写入 `opscli/seller_sprite/__init__.py`：

```python
"""卖家精灵采集模块。"""
```

写入 `opscli/seller_sprite/commands/__init__.py`：

```python
"""卖家精灵 CLI 命令包。"""
```

写入 `opscli/seller_sprite/domain/__init__.py`：

```python
"""卖家精灵领域模型包。"""
```

写入 `opscli/seller_sprite/scraping/__init__.py`：

```python
"""卖家精灵页面采集与归档包。"""
```

写入 `opscli/seller_sprite/services/__init__.py`：

```python
"""卖家精灵业务编排包。"""
```

- [ ] **Step 2: 创建模块 CLI 转发入口**

写入 `opscli/seller_sprite/cli.py`：

```python
"""seller-sprite CLI 子命令入口。"""

from opscli.seller_sprite.commands.cli import app

__all__ = ["app"]
```

- [ ] **Step 3: 修改顶级 CLI 注册**

在 `opscli/cli.py` 顶部导入区新增：

```python
from opscli.seller_sprite.cli import app as seller_sprite_app
```

在模块注册区新增：

```python
app.add_typer(seller_sprite_app, name="seller-sprite")
```

- [ ] **Step 4: 新增 Markdown 转换依赖**

在 `pyproject.toml` 的 `[project].dependencies` 中新增：

```toml
"html2text>=2025.4.15",
```

- [ ] **Step 5: 做导入验证**

运行：

```bash
python -c "from opscli.seller_sprite.cli import app; print('seller_sprite cli ok')"
```

预期输出：

```text
seller_sprite cli ok
```

- [ ] **Step 6: 提交骨架**

```bash
git add opscli/seller_sprite opscli/cli.py pyproject.toml
git commit -m "feat: add seller sprite module skeleton"
```

---

### Task 2: 定义异常和数据模型

**Files:**
- Create: `opscli/seller_sprite/domain/exceptions.py`
- Create: `opscli/seller_sprite/domain/models.py`

- [ ] **Step 1: 定义模块异常**

写入 `opscli/seller_sprite/domain/exceptions.py`：

```python
"""卖家精灵模块异常定义。"""

from __future__ import annotations


class SellerSpriteError(Exception):
    """卖家精灵模块统一异常基类。"""

    code = "SELLER_SPRITE_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict:
        """转换为 CLI 统一错误输出结构。"""
        return {
            "code": self.code,
            "message": self.message,
        }


class InvalidAsinError(SellerSpriteError):
    """ASIN 参数不合法。"""

    code = "SELLER_SPRITE_INVALID_ASIN"


class InvalidCollectOptionError(SellerSpriteError):
    """采集参数不合法。"""

    code = "SELLER_SPRITE_INVALID_COLLECT_OPTION"


class SellerSpriteDependencyError(SellerSpriteError):
    """采集依赖未安装。"""

    code = "SELLER_SPRITE_DEPENDENCY_ERROR"


class SellerSpriteCaptchaRequiredError(SellerSpriteError):
    """页面触发验证码，需要人工或打码服务处理。"""

    code = "SELLER_SPRITE_CAPTCHA_REQUIRED"


class SellerSpriteResponseError(SellerSpriteError):
    """卖家精灵接口响应缺失或结构不符合预期。"""

    code = "SELLER_SPRITE_RESPONSE_ERROR"
```

- [ ] **Step 2: 定义模型**

写入 `opscli/seller_sprite/domain/models.py`：

```python
"""卖家精灵采集数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SellerSpriteCollectOptions:
    """卖家精灵采集输入参数。"""

    asin: str | None = None
    keyword: str | None = None
    site: str = "us"
    period: str = "30d"
    limit: int = 50
    archive: bool = True
    url: str | None = None

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteFrequencyTerm:
    """高频词条目。"""

    keyword: str
    frequency: int
    percentage: float

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteKeywordItem:
    """关键词挖掘标准化条目。"""

    keyword: str
    keyword_cn: str
    keyword_jp: str
    departments: list[dict[str, Any]]
    trends: list[dict[str, Any]]
    searches: int | None
    purchases: int | None
    purchase_rate: float | None
    impressions: int | None
    clicks: int | None
    cvs_share_rate: float | None
    products: int | None
    ad_products: int | None
    supply_demand_ratio: float | None
    avg_price: float | None
    avg_reviews: int | None
    avg_rating: float | None
    bid: float | None
    phrase_ppc: float | None
    exact_ppc: float | None
    broad_ppc: float | None
    title_density: int | None
    spr: int | None
    relevancy: float | None
    absolute_relevancy: int | None
    amazon_choice: bool | None
    monopoly_asins: list[dict[str, Any]]
    monopoly_click_rate: float | None
    related_products: list[dict[str, Any]]

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return asdict(self)


@dataclass
class SellerSpriteArchiveManifest:
    """单次采集归档索引。"""

    run_id: str
    root_dir: Path
    files: dict[str, str] = field(default_factory=dict)
    captcha_required: bool = False
    missing_sections: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为 JSON 友好的字典。"""
        return {
            "run_id": self.run_id,
            "root_dir": str(self.root_dir),
            "files": self.files,
            "captcha_required": self.captcha_required,
            "missing_sections": self.missing_sections,
            "errors": self.errors,
        }


@dataclass
class SellerSpriteCollectResult:
    """卖家精灵采集结果聚合对象。"""

    asin: str | None
    keyword: str | None
    site: str
    period: str
    limit: int
    run_id: str
    frequency_terms: list[SellerSpriteFrequencyTerm] = field(default_factory=list)
    keyword_items: list[SellerSpriteKeywordItem] = field(default_factory=list)
    keyword_trends: list[dict[str, Any]] = field(default_factory=list)
    competitor_asins: list[dict[str, Any]] = field(default_factory=list)
    market_summary: dict[str, Any] = field(default_factory=dict)
    archive_manifest: SellerSpriteArchiveManifest | None = None

    def to_dict(self) -> dict:
        """转换为 CLI 输出结构。"""
        return {
            "asin": self.asin,
            "keyword": self.keyword,
            "site": self.site,
            "period": self.period,
            "limit": self.limit,
            "run_id": self.run_id,
            "frequency_terms": [item.to_dict() for item in self.frequency_terms],
            "keyword_items": [item.to_dict() for item in self.keyword_items],
            "keyword_trends": self.keyword_trends,
            "competitor_asins": self.competitor_asins,
            "market_summary": self.market_summary,
            "archive_manifest": self.archive_manifest.to_dict() if self.archive_manifest else None,
        }
```

- [ ] **Step 3: 做模型导入验证**

运行：

```bash
python -c "from opscli.seller_sprite.domain.models import SellerSpriteCollectResult; print(SellerSpriteCollectResult.__name__)"
```

预期输出：

```text
SellerSpriteCollectResult
```

- [ ] **Step 4: 提交模型**

```bash
git add opscli/seller_sprite/domain
git commit -m "feat: add seller sprite domain models"
```

---

### Task 3: 实现归档、接口记录和验证码预留

**Files:**
- Create: `opscli/seller_sprite/scraping/api_recorder.py`
- Create: `opscli/seller_sprite/scraping/archiver.py`
- Create: `opscli/seller_sprite/scraping/captcha.py`

- [ ] **Step 1: 实现接口响应记录器**

写入 `opscli/seller_sprite/scraping/api_recorder.py`：

```python
"""卖家精灵接口响应记录器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SellerSpriteApiRecorder:
    """记录 Playwright 捕获到的 JSON 响应。"""

    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}

    async def capture_json_response(self, response, *, section: str, url_keyword: str) -> None:
        """按 URL 关键词捕获 JSON 响应。

        Args:
            response: Playwright response 对象。
            section: 响应所属业务分区，例如 frequency 或 keyword_mining。
            url_keyword: URL 中用于匹配接口的关键词。
        """
        if url_keyword not in response.url:
            return
        try:
            payload = await response.json()
        except Exception:
            return
        self.responses[section] = {
            "url": response.url,
            "status": response.status,
            "payload": payload,
        }

    def get_payload(self, section: str) -> dict[str, Any] | None:
        """读取指定分区的响应 payload。"""
        item = self.responses.get(section)
        if not item:
            return None
        payload = item.get("payload")
        return payload if isinstance(payload, dict) else None

    def save_all(self, target_dir: Path) -> dict[str, str]:
        """将已捕获响应写入目录，返回文件索引。"""
        target_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        for section, item in self.responses.items():
            path = target_dir / f"{section}.json"
            path.write_text(
                json.dumps(item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            files[f"{section}_response"] = str(path)
        return files
```

- [ ] **Step 2: 实现页面归档器**

写入 `opscli/seller_sprite/scraping/archiver.py`：

```python
"""卖家精灵页面归档工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SellerSpriteArchiver:
    """保存截图、HTML、Markdown 和 JSON 文件。"""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    async def archive_page(self, page, *, section: str) -> dict[str, str]:
        """归档当前页面状态。

        Args:
            page: Playwright page 对象。
            section: 归档分区名称。
        """
        section_dir = self.root_dir / section
        section_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = section_dir / "screenshot.png"
        html_path = section_dir / "page.html"
        markdown_path = section_dir / "page.md"

        await page.screenshot(path=str(screenshot_path), full_page=True)
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        markdown_path.write_text(self.html_to_markdown(html), encoding="utf-8")

        return {
            f"{section}_screenshot": str(screenshot_path),
            f"{section}_html": str(html_path),
            f"{section}_markdown": str(markdown_path),
        }

    def html_to_markdown(self, html: str) -> str:
        """将 HTML 转为 Markdown。"""
        try:
            import html2text
        except ModuleNotFoundError:
            return html
        converter = html2text.HTML2Text()
        converter.body_width = 0
        converter.ignore_images = False
        converter.ignore_links = False
        return converter.handle(html)

    def save_json(self, *, section: str, filename: str, payload: dict[str, Any]) -> str:
        """保存 JSON 文件并返回路径。"""
        section_dir = self.root_dir / section
        section_dir.mkdir(parents=True, exist_ok=True)
        path = section_dir / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(path)
```

- [ ] **Step 3: 实现验证码预留**

写入 `opscli/seller_sprite/scraping/captcha.py`：

```python
"""卖家精灵验证码检测与 provider 预留。"""

from __future__ import annotations

from pathlib import Path


class SellerSpriteCaptchaProvider:
    """图形验证码识别 provider 协议预留。"""

    def solve_image(self, image_path: Path) -> str:
        """识别图形验证码。

        当前一期不自动识别验证码，后续接入超级鹰时实现该方法。
        """
        raise NotImplementedError("当前版本未启用自动验证码识别")


class SellerSpriteCaptchaDetector:
    """检测卖家精灵页面是否出现验证码。"""

    DEFAULT_SELECTORS = [
        "input[name*='captcha']",
        "img[src*='captcha']",
        ".captcha",
        "#captcha",
    ]

    async def detect(self, page) -> bool:
        """检查页面中是否存在常见验证码元素。"""
        for selector in self.DEFAULT_SELECTORS:
            try:
                handle = await page.query_selector(selector)
            except Exception:
                handle = None
            if handle is not None:
                return True
        return False
```

- [ ] **Step 4: 做导入验证**

运行：

```bash
python -c "from opscli.seller_sprite.scraping.archiver import SellerSpriteArchiver; print(SellerSpriteArchiver.__name__)"
```

预期输出：

```text
SellerSpriteArchiver
```

- [ ] **Step 5: 提交归档能力**

```bash
git add opscli/seller_sprite/scraping
git commit -m "feat: add seller sprite archive helpers"
```

---

### Task 4: 实现标准化与业务编排

**Files:**
- Create: `opscli/seller_sprite/services/manager.py`

- [ ] **Step 1: 实现 Manager**

写入 `opscli/seller_sprite/services/manager.py`：

```python
"""卖家精灵采集业务编排层。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR
from opscli.seller_sprite.domain.exceptions import InvalidAsinError, InvalidCollectOptionError, SellerSpriteResponseError
from opscli.seller_sprite.domain.models import (
    SellerSpriteArchiveManifest,
    SellerSpriteCollectOptions,
    SellerSpriteCollectResult,
    SellerSpriteFrequencyTerm,
    SellerSpriteKeywordItem,
)
from opscli.seller_sprite.scraping.scraper import SellerSpriteScraper


class SellerSpriteManager:
    """协调卖家精灵页面采集、标准化和本地落盘。"""

    def __init__(self, *, base_dir: Path | None = None, scraper: SellerSpriteScraper | None = None) -> None:
        self.base_dir = Path(base_dir or CONFIG_DIR)
        self.data_dir = self.base_dir / "seller_sprite"
        self.runs_dir = self.data_dir / "runs"
        self.scraper = scraper or SellerSpriteScraper()

    def collect(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """按 ASIN 和显式关键词执行完整采集。"""
        self._validate_collect_options(options, require_asin=True, require_keyword=True)
        run_id = self._build_run_id()
        run_dir = self.runs_dir / run_id
        raw = self.scraper.collect(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def collect_frequency(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """只采集高频词。"""
        self._validate_collect_options(options, require_asin=False, require_keyword=True)
        run_id = self._build_run_id()
        run_dir = self.runs_dir / run_id
        raw = self.scraper.collect_frequency(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def collect_keyword_mining(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """只采集关键词挖掘结果。"""
        self._validate_collect_options(options, require_asin=False, require_keyword=True)
        run_id = self._build_run_id()
        run_dir = self.runs_dir / run_id
        raw = self.scraper.collect_keyword_mining(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def archive_url(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """只归档指定页面 URL。"""
        if not options.url:
            raise InvalidCollectOptionError("archive 命令必须提供 --url")
        run_id = self._build_run_id()
        run_dir = self.runs_dir / run_id
        raw = self.scraper.archive_url(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def schema(self) -> dict:
        """输出当前卖家精灵标准化字段契约。"""
        return {
            "collect_options": {
                "asin": "string|null",
                "keyword": "string|null",
                "site": "string",
                "period": "string",
                "limit": "integer",
                "archive": "boolean",
                "url": "string|null",
            },
            "frequency_term": {
                "keyword": "string",
                "frequency": "integer",
                "percentage": "number",
            },
            "keyword_item": {
                "keyword": "string",
                "keyword_cn": "string",
                "keyword_jp": "string",
                "departments": "array<object>",
                "trends": "array<object>",
                "searches": "integer|null",
                "purchases": "integer|null",
                "purchase_rate": "number|null",
                "impressions": "integer|null",
                "clicks": "integer|null",
                "cvs_share_rate": "number|null",
                "products": "integer|null",
                "ad_products": "integer|null",
                "supply_demand_ratio": "number|null",
                "avg_price": "number|null",
                "avg_reviews": "integer|null",
                "avg_rating": "number|null",
                "bid": "number|null",
                "phrase_ppc": "number|null",
                "exact_ppc": "number|null",
                "broad_ppc": "number|null",
                "title_density": "integer|null",
                "spr": "integer|null",
                "relevancy": "number|null",
                "monopoly_asins": "array<object>",
                "related_products": "array<object>",
            },
        }

    def _validate_collect_options(
        self,
        options: SellerSpriteCollectOptions,
        *,
        require_asin: bool,
        require_keyword: bool,
    ) -> None:
        """校验采集参数，保证命令输入边界稳定。"""
        if require_asin and not options.asin:
            raise InvalidAsinError("collect 命令必须提供 --asin")
        if options.asin:
            asin = options.asin.strip().upper()
            if len(asin) != 10 or not asin.isalnum():
                raise InvalidAsinError("ASIN 必须是 10 位字母或数字")
            options.asin = asin
        if require_keyword and not options.keyword:
            raise InvalidCollectOptionError("必须提供 --keyword")
        if options.limit < 1 or options.limit > 200:
            raise InvalidCollectOptionError("--limit 范围必须是 1-200")
        if options.period != "30d":
            raise InvalidCollectOptionError("一期仅支持 --period 30d")

    def _build_result(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_id: str,
        run_dir: Path,
        raw: dict[str, Any],
    ) -> SellerSpriteCollectResult:
        """将原始接口响应转换为标准化结果。"""
        archive = SellerSpriteArchiveManifest(
            run_id=run_id,
            root_dir=run_dir,
            files=raw.get("files", {}),
            captcha_required=bool(raw.get("captcha_required", False)),
            missing_sections=list(raw.get("missing_sections", [])),
            errors=list(raw.get("errors", [])),
        )
        return SellerSpriteCollectResult(
            asin=options.asin,
            keyword=options.keyword,
            site=options.site,
            period=options.period,
            limit=options.limit,
            run_id=run_id,
            frequency_terms=self._normalize_frequency(raw.get("frequency")),
            keyword_items=self._normalize_keyword_items(raw.get("keyword_mining"), limit=options.limit),
            keyword_trends=self._extract_keyword_trends(raw.get("keyword_mining"), limit=options.limit),
            competitor_asins=self._extract_competitor_asins(raw.get("keyword_mining"), limit=options.limit),
            market_summary=self._build_market_summary(raw.get("keyword_mining")),
            archive_manifest=archive,
        )

    def _normalize_frequency(self, payload: dict[str, Any] | None) -> list[SellerSpriteFrequencyTerm]:
        """标准化高频词接口响应。"""
        if not payload:
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            raise SellerSpriteResponseError("高频词接口缺少 data 数组")
        terms: list[SellerSpriteFrequencyTerm] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            terms.append(
                SellerSpriteFrequencyTerm(
                    keyword=str(item.get("keyword", "")),
                    frequency=int(item.get("frequency") or 0),
                    percentage=float(item.get("percentage") or 0),
                )
            )
        return terms

    def _normalize_keyword_items(self, payload: dict[str, Any] | None, *, limit: int) -> list[SellerSpriteKeywordItem]:
        """标准化关键词挖掘接口响应。"""
        items = self._keyword_items(payload)[:limit]
        normalized: list[SellerSpriteKeywordItem] = []
        for item in items:
            normalized.append(
                SellerSpriteKeywordItem(
                    keyword=str(item.get("keyword", "")),
                    keyword_cn=str(item.get("keywordCn", "")),
                    keyword_jp=str(item.get("keywordJp", "")),
                    departments=list(item.get("departments") or []),
                    trends=list(item.get("trends") or []),
                    searches=item.get("searches"),
                    purchases=item.get("purchases"),
                    purchase_rate=item.get("purchaseRate"),
                    impressions=item.get("impressions"),
                    clicks=item.get("clicks"),
                    cvs_share_rate=item.get("cvsShareRate"),
                    products=item.get("products"),
                    ad_products=item.get("adProducts"),
                    supply_demand_ratio=item.get("supplyDemandRatio"),
                    avg_price=item.get("avgPrice"),
                    avg_reviews=item.get("avgReviews"),
                    avg_rating=item.get("avgRating"),
                    bid=item.get("bid"),
                    phrase_ppc=item.get("phrasePpc"),
                    exact_ppc=item.get("exactPpc"),
                    broad_ppc=item.get("broadPpc"),
                    title_density=item.get("titleDensity"),
                    spr=item.get("spr"),
                    relevancy=item.get("relevancy"),
                    absolute_relevancy=item.get("absoluteRelevancy"),
                    amazon_choice=item.get("amazonChoice"),
                    monopoly_asins=list(item.get("monopolyAsinDtos") or []),
                    monopoly_click_rate=item.get("monopolyClickRate"),
                    related_products=list(item.get("gkDatas") or []),
                )
            )
        return normalized

    def _keyword_items(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        """读取关键词挖掘 items。"""
        if not payload:
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SellerSpriteResponseError("关键词挖掘接口缺少 data 对象")
        items = data.get("items")
        if not isinstance(items, list):
            raise SellerSpriteResponseError("关键词挖掘接口缺少 items 数组")
        return [item for item in items if isinstance(item, dict)]

    def _extract_keyword_trends(self, payload: dict[str, Any] | None, *, limit: int) -> list[dict[str, Any]]:
        """提取关键词趋势数据。"""
        return [
            {
                "keyword": item.get("keyword"),
                "trends": item.get("trends") or [],
            }
            for item in self._keyword_items(payload)[:limit]
        ]

    def _extract_competitor_asins(self, payload: dict[str, Any] | None, *, limit: int) -> list[dict[str, Any]]:
        """提取关键词关联竞品 ASIN。"""
        competitors: list[dict[str, Any]] = []
        for item in self._keyword_items(payload)[:limit]:
            keyword = item.get("keyword")
            for asin_item in item.get("monopolyAsinDtos") or []:
                if isinstance(asin_item, dict):
                    row = dict(asin_item)
                    row["source_keyword"] = keyword
                    competitors.append(row)
        return competitors

    def _build_market_summary(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        """生成给 Agent 快速读取的市场摘要。"""
        items = self._keyword_items(payload)
        return {
            "total": payload.get("data", {}).get("total") if payload else None,
            "item_count": len(items),
            "top_keywords": [item.get("keyword") for item in items[:10]],
        }

    def _save_result(self, run_dir: Path, result: SellerSpriteCollectResult) -> None:
        """写入 result.json 和 manifest.json。"""
        run_dir.mkdir(parents=True, exist_ok=True)
        result_path = run_dir / "result.json"
        manifest_path = run_dir / "manifest.json"
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = result.archive_manifest.to_dict() if result.archive_manifest else {}
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_run_id(self) -> str:
        """生成本地采集批次 ID。"""
        return datetime.now().strftime("%Y%m%d-%H%M%S")
```

- [ ] **Step 2: 做 Manager 导入验证**

运行：

```bash
python -c "from opscli.seller_sprite.services.manager import SellerSpriteManager; print(SellerSpriteManager().schema()['collect_options']['limit'])"
```

预期输出：

```text
integer
```

- [ ] **Step 3: 提交编排层**

```bash
git add opscli/seller_sprite/services/manager.py
git commit -m "feat: add seller sprite manager"
```

---

### Task 5: 实现 Playwright 采集器

**Files:**
- Create: `opscli/seller_sprite/scraping/scraper.py`

- [ ] **Step 1: 实现 Scraper**

写入 `opscli/seller_sprite/scraping/scraper.py`：

```python
"""卖家精灵 Playwright 采集器。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR
from opscli.seller_sprite.domain.exceptions import SellerSpriteCaptchaRequiredError, SellerSpriteDependencyError
from opscli.seller_sprite.domain.models import SellerSpriteCollectOptions
from opscli.seller_sprite.scraping.api_recorder import SellerSpriteApiRecorder
from opscli.seller_sprite.scraping.archiver import SellerSpriteArchiver
from opscli.seller_sprite.scraping.captcha import SellerSpriteCaptchaDetector


class SellerSpriteScraper:
    """基于 Playwright 的卖家精灵采集器。"""

    KEYWORD_MINING_URL = "https://www.sellersprite.com/v3/keyword-miner"
    DEFAULT_TIMEOUT_MS = 120000
    DEFAULT_WAIT_MS = 3000

    def __init__(self, *, headless: bool = False, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.profile_dir = CONFIG_DIR / "seller_sprite" / "browser_profile"
        self.captcha_detector = SellerSpriteCaptchaDetector()

    def collect(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步执行完整采集。"""
        return asyncio.run(self.collect_async(options=options, run_id=run_id, run_dir=run_dir))

    def collect_frequency(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步执行高频词采集。"""
        return asyncio.run(self.collect_frequency_async(options=options, run_id=run_id, run_dir=run_dir))

    def collect_keyword_mining(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步执行关键词挖掘采集。"""
        return asyncio.run(self.collect_keyword_mining_async(options=options, run_id=run_id, run_dir=run_dir))

    def archive_url(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步归档指定 URL。"""
        return asyncio.run(self.archive_url_async(options=options, run_id=run_id, run_dir=run_dir))

    async def collect_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """完整采集高频词与关键词挖掘数据。"""
        raw_frequency = await self.collect_frequency_async(options=options, run_id=run_id, run_dir=run_dir)
        raw_keyword = await self.collect_keyword_mining_async(options=options, run_id=run_id, run_dir=run_dir)
        return {
            "frequency": raw_frequency.get("frequency"),
            "keyword_mining": raw_keyword.get("keyword_mining"),
            "files": {**raw_frequency.get("files", {}), **raw_keyword.get("files", {})},
            "captcha_required": raw_frequency.get("captcha_required") or raw_keyword.get("captcha_required"),
            "missing_sections": raw_frequency.get("missing_sections", []) + raw_keyword.get("missing_sections", []),
            "errors": raw_frequency.get("errors", []) + raw_keyword.get("errors", []),
        }

    async def collect_frequency_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """采集高频词接口响应。"""
        return await self._collect_section(
            options=options,
            run_dir=run_dir,
            section="frequency",
            response_url_keyword="frequency",
        )

    async def collect_keyword_mining_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """采集关键词挖掘接口响应。"""
        return await self._collect_section(
            options=options,
            run_dir=run_dir,
            section="keyword_mining",
            response_url_keyword="keyword",
        )

    async def archive_url_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """打开并归档指定 URL。"""
        async with self._browser_page() as page:
            archiver = SellerSpriteArchiver(run_dir)
            await page.goto(options.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            captcha_required = await self.captcha_detector.detect(page)
            files = await archiver.archive_page(page, section="archive")
            return {
                "files": files,
                "captcha_required": captcha_required,
                "missing_sections": [],
                "errors": [],
            }

    async def _collect_section(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_dir: Path,
        section: str,
        response_url_keyword: str,
    ) -> dict[str, Any]:
        """打开关键词挖掘页并捕获指定分区接口响应。"""
        async with self._browser_page() as page:
            recorder = SellerSpriteApiRecorder()
            archiver = SellerSpriteArchiver(run_dir)
            page.on(
                "response",
                lambda response: asyncio.create_task(
                    recorder.capture_json_response(
                        response,
                        section=section,
                        url_keyword=response_url_keyword,
                    )
                ),
            )
            await page.goto(self.KEYWORD_MINING_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            captcha_required = await self.captcha_detector.detect(page)
            files = await archiver.archive_page(page, section=section)
            if captcha_required:
                return {
                    section: None,
                    "files": files,
                    "captcha_required": True,
                    "missing_sections": [section],
                    "errors": [{"code": SellerSpriteCaptchaRequiredError.code, "message": "页面出现验证码"}],
                }
            await self._fill_keyword_form(page, options)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            files.update(recorder.save_all(run_dir / section))
            payload = recorder.get_payload(section)
            return {
                section: payload,
                "files": files,
                "captcha_required": False,
                "missing_sections": [] if payload else [section],
                "errors": [] if payload else [{"code": "SELLER_SPRITE_RESPONSE_MISSING", "message": f"{section} 响应未捕获"}],
            }

    async def _fill_keyword_form(self, page, options: SellerSpriteCollectOptions) -> None:
        """填写关键词查询表单并触发查询。"""
        keyword_input = await page.query_selector("input")
        if keyword_input is not None and options.keyword:
            await keyword_input.fill(options.keyword)
        query_button = await page.query_selector("button:has-text('立即查询')")
        if query_button is not None:
            await query_button.click()

    def _load_playwright(self):
        """延迟导入 Playwright，避免未安装时影响其他模块。"""
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:
            raise SellerSpriteDependencyError(
                "缺少 playwright 依赖，请安装 `pip install opscli` 并执行 `playwright install chromium`"
            ) from exc
        return async_playwright

    def _browser_page(self):
        """创建持久化浏览器上下文。"""
        async_playwright = self._load_playwright()

        class _PageContext:
            def __init__(self, outer: SellerSpriteScraper):
                self.outer = outer
                self.playwright = None
                self.context = None
                self.page = None

            async def __aenter__(self):
                self.playwright = await async_playwright().start()
                self.outer.profile_dir.mkdir(parents=True, exist_ok=True)
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.outer.profile_dir),
                    headless=self.outer.headless,
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                return self.page

            async def __aexit__(self, exc_type, exc, tb):
                if self.context is not None:
                    await self.context.close()
                if self.playwright is not None:
                    await self.playwright.stop()

        return _PageContext(self)
```

- [ ] **Step 2: 做 Scraper 导入验证**

运行：

```bash
python -c "from opscli.seller_sprite.scraping.scraper import SellerSpriteScraper; print(SellerSpriteScraper.KEYWORD_MINING_URL)"
```

预期输出包含：

```text
sellersprite.com
```

- [ ] **Step 3: 提交采集器**

```bash
git add opscli/seller_sprite/scraping/scraper.py
git commit -m "feat: add seller sprite playwright scraper"
```

---

### Task 6: 实现 CLI 命令

**Files:**
- Create: `opscli/seller_sprite/commands/cli.py`

- [ ] **Step 1: 写入 CLI 命令**

写入 `opscli/seller_sprite/commands/cli.py`：

```python
"""seller-sprite CLI 子命令定义。"""

from __future__ import annotations

import json

import typer

from opscli.seller_sprite.domain.exceptions import SellerSpriteError
from opscli.seller_sprite.domain.models import SellerSpriteCollectOptions
from opscli.seller_sprite.services.manager import SellerSpriteManager

app = typer.Typer(help="卖家精灵关键词与 Listing 分析材料采集")


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _error_payload(command: str, exc: Exception) -> dict:
    """统一错误输出。"""
    if isinstance(exc, SellerSpriteError):
        error = exc.to_dict()
    else:
        error = {
            "code": "SELLER_SPRITE_ERROR",
            "message": str(exc),
        }
    return {
        "success": False,
        "command": command,
        "data": None,
        "error": error,
    }


@app.command("collect")
def collect(
    asin: str = typer.Option(..., "--asin", help="Amazon ASIN，作为 Listing 分析对象"),
    keyword: str = typer.Option(..., "--keyword", help="卖家精灵关键词挖掘入口词"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，一期仅支持 30d"),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="关键词采集条数，默认 50"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档截图、HTML、Markdown 和接口响应"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """围绕 ASIN 和显式关键词执行完整采集。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect(
            SellerSpriteCollectOptions(
                asin=asin,
                keyword=keyword,
                site=site,
                period=period,
                limit=limit,
                archive=archive,
            )
        )
        payload = {"success": True, "command": "seller-sprite collect", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite collect", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("frequency")
def frequency(
    keyword: str = typer.Option(..., "--keyword", help="卖家精灵关键词挖掘入口词"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，一期仅支持 30d"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档页面证据"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """采集高频词。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect_frequency(
            SellerSpriteCollectOptions(keyword=keyword, site=site, period=period, archive=archive)
        )
        payload = {"success": True, "command": "seller-sprite frequency", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite frequency", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("keyword-mining")
def keyword_mining(
    keyword: str = typer.Option(..., "--keyword", help="卖家精灵关键词挖掘入口词"),
    site: str = typer.Option("us", "--site", help="站点，默认 us"),
    period: str = typer.Option("30d", "--period", help="时间窗口，一期仅支持 30d"),
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="关键词采集条数，默认 50"),
    archive: bool = typer.Option(True, "--archive/--no-archive", help="是否归档页面证据"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """采集关键词挖掘结果。"""
    manager = SellerSpriteManager()
    try:
        result = manager.collect_keyword_mining(
            SellerSpriteCollectOptions(keyword=keyword, site=site, period=period, limit=limit, archive=archive)
        )
        payload = {"success": True, "command": "seller-sprite keyword-mining", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite keyword-mining", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("archive")
def archive(
    url: str = typer.Option(..., "--url", help="需要归档的卖家精灵页面 URL"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """归档指定页面。"""
    manager = SellerSpriteManager()
    try:
        result = manager.archive_url(SellerSpriteCollectOptions(url=url))
        payload = {"success": True, "command": "seller-sprite archive", "data": result.to_dict(), "error": None}
    except Exception as exc:
        _emit(_error_payload("seller-sprite archive", exc), pretty)
        raise typer.Exit(1)
    _emit(payload, pretty)


@app.command("schema")
def schema(pretty: bool = typer.Option(False, "--pretty", help="格式化输出")):
    """输出当前字段契约。"""
    manager = SellerSpriteManager()
    payload = {
        "success": True,
        "command": "seller-sprite schema",
        "data": manager.schema(),
        "error": None,
    }
    _emit(payload, pretty)
```

- [ ] **Step 2: 检查 CLI 帮助可显示**

运行：

```bash
opscli seller-sprite --help
```

预期看到命令：

```text
collect
frequency
keyword-mining
archive
schema
```

- [ ] **Step 3: 检查 schema 输出**

运行：

```bash
opscli seller-sprite schema --pretty
```

预期 JSON 中包含：

```json
"keyword_item"
```

- [ ] **Step 4: 提交 CLI**

```bash
git add opscli/seller_sprite/commands/cli.py
git commit -m "feat: add seller sprite cli commands"
```

---

### Task 7: 新增 ops-seller-sprite Skill

**Files:**
- Create: `opscli/skills/templates/ops-seller-sprite/SKILL.md`
- Create: `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`
- Create: `opscli/skills/templates/ops-seller-sprite/data/VERSION.json`

- [ ] **Step 1: 创建版本文件**

写入 `opscli/skills/templates/ops-seller-sprite/data/VERSION.json`：

```json
{
  "name": "ops-seller-sprite",
  "version": "v0.1.0"
}
```

- [ ] **Step 2: 写入 CLI Skill**

写入 `opscli/skills/templates/ops-seller-sprite/SKILL.md`：

```markdown
---
name: ops-seller-sprite
description: 使用 opscli seller-sprite 命令采集卖家精灵关键词挖掘、高频词、页面截图、Markdown 和接口证据
version: v0.1.0
---

# ops-seller-sprite

使用 `opscli seller-sprite` 子命令采集卖家精灵数据。所有采集动作必须通过正式 CLI 命令执行，禁止在 Skill 内直接请求卖家精灵接口。

## 使用原则

- 用户提供 ASIN 和关键词时，优先使用 `collect`。
- 只调试高频词时，使用 `frequency`。
- 只调试关键词列表时，使用 `keyword-mining`。
- 需要留存页面证据时，使用默认开启的归档能力。
- 不从卖家精灵 AI 报告复用成品分析结论。

## 核心命令

```bash
opscli seller-sprite collect --asin B00MA2T9BC --keyword bed --site us --period 30d --limit 50 --pretty
opscli seller-sprite frequency --keyword bed --site us --period 30d --pretty
opscli seller-sprite keyword-mining --keyword bed --site us --period 30d --limit 50 --pretty
opscli seller-sprite archive --url https://www.sellersprite.com/v3/keyword-miner --pretty
opscli seller-sprite schema --pretty
```

## 输出读取

命令返回的 `data.archive_manifest.root_dir` 是本次采集目录。Agent 后续应优先读取：

- `result.json`
- `manifest.json`
- 高频词和关键词挖掘接口响应 JSON
- 页面 Markdown
- 页面截图路径

## 当前边界

- 不自动根据 ASIN 推导关键词。
- 不自动识别验证码。
- 不自动生成完整 Listing 上线文案。
- 不自动刊登或替换 Listing。
```

- [ ] **Step 3: 写入 MCP Skill**

写入 `opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md`：

```markdown
---
name: ops-seller-sprite
mcp-version: v1.0.0
description: 使用 opscli MCP 工具采集卖家精灵关键词挖掘、高频词、页面截图、Markdown 和接口证据
---

# ops-seller-sprite (MCP 预留)

当前一期以 CLI 命令为主。MCP 模式保留同名 Skill 文档，用于后续接入 `seller_sprite_*` tools 时对齐调用语义。

## 预期工具

```python
seller_sprite_collect(asin="B00MA2T9BC", keyword="bed", site="us", period="30d", limit=50)
seller_sprite_frequency(keyword="bed", site="us", period="30d")
seller_sprite_keyword_mining(keyword="bed", site="us", period="30d", limit=50)
seller_sprite_schema()
```

## 当前边界

如果当前 MCP Server 未暴露 `seller_sprite_*` tools，应改用 CLI 模式的 `opscli seller-sprite ...` 命令。
```

- [ ] **Step 4: 检查模板可被发现**

运行：

```bash
opscli skills list --pretty
```

预期不报错。若未安装模板，使用：

```bash
opscli skills install ops-seller-sprite --runtime codex --force --pretty
```

预期 JSON 中包含：

```json
"name": "ops-seller-sprite"
```

- [ ] **Step 5: 提交采集 Skill**

```bash
git add opscli/skills/templates/ops-seller-sprite
git commit -m "feat: add seller sprite skill template"
```

---

### Task 8: 新增 ops-amazon-listing-analysis Skill

**Files:**
- Create: `opscli/skills/templates/ops-amazon-listing-analysis/SKILL.md`
- Create: `opscli/skills/templates/ops-amazon-listing-analysis/data/VERSION.json`

- [ ] **Step 1: 创建版本文件**

写入 `opscli/skills/templates/ops-amazon-listing-analysis/data/VERSION.json`：

```json
{
  "name": "ops-amazon-listing-analysis",
  "version": "v0.1.0"
}
```

- [ ] **Step 2: 写入业务分析 Skill**

写入 `opscli/skills/templates/ops-amazon-listing-analysis/SKILL.md`：

```markdown
---
name: ops-amazon-listing-analysis
description: 基于 ASIN 和卖家精灵采集材料，输出 Amazon Listing 表达与一致性优化建议
version: v0.1.0
---

# ops-amazon-listing-analysis

围绕 Amazon ASIN 做 Listing 表达与一致性优化分析。该 Skill 不负责直接采集网页数据，采集动作必须调用 `ops-seller-sprite` 或 `opscli seller-sprite`。

## 输入要求

用户必须提供：

- Amazon ASIN
- 显式关键词

标准采集命令：

```bash
opscli seller-sprite collect --asin <ASIN> --keyword <KEYWORD> --site us --period 30d --limit 50 --pretty
```

## 分析材料

优先读取采集结果中的：

- 高频词
- 关键词列表
- 关键词趋势
- PPC 与 ABA 相关字段
- 竞品 ASIN
- 页面 Markdown
- 截图路径

## 输出范围

只能输出：

- 问题定位
- 优化方向
- 修改示例

## 禁止输出

- 完整可直接上线文案
- 自动替换现有 Listing
- 多语言重写
- 自动刊登操作
- 没有证据支撑的确定性结论

## 输出格式

```markdown
## 问题定位

- 问题：...
- 依据：...

## 优化方向

- 方向：...
- 依据：...

## 修改示例

- 原表达：...
- 示例：...
- 说明：该示例仅用于方向参考，不是完整上线文案。
```
```

- [ ] **Step 3: 检查模板可被发现**

运行：

```bash
opscli skills install ops-amazon-listing-analysis --runtime codex --force --pretty
```

预期 JSON 中包含：

```json
"name": "ops-amazon-listing-analysis"
```

- [ ] **Step 4: 提交分析 Skill**

```bash
git add opscli/skills/templates/ops-amazon-listing-analysis
git commit -m "feat: add amazon listing analysis skill"
```

---

### Task 9: 文档同步与人工验证

**Files:**
- Modify: `README.md`
- Modify: `docs/design/卖家精灵采集与Listing分析一期设计.md` only if implementation changes command names or output paths.

- [ ] **Step 1: 在 README 模块概述中补充 seller-sprite**

在 `README.md` 当前模块列表中加入：

```markdown
seller-sprite（卖家精灵关键词与 Listing 分析材料采集）
```

在快速开始区域加入：

```bash
opscli seller-sprite schema --pretty
opscli seller-sprite collect --asin B00MA2T9BC --keyword bed --site us --period 30d --limit 50 --pretty
```

- [ ] **Step 2: 做命令级人工验证**

运行：

```bash
opscli seller-sprite schema --pretty
```

预期：

```text
返回 success=true，data 中包含 collect_options、frequency_term、keyword_item。
```

运行：

```bash
opscli seller-sprite collect --asin INVALID --keyword bed --pretty
```

预期：

```text
返回 success=false，error.code 为 SELLER_SPRITE_INVALID_ASIN。
```

- [ ] **Step 3: 做工作区检查**

运行：

```bash
git status --short
```

预期：

```text
只显示本任务预期修改文件，不能包含无关文件。
```

- [ ] **Step 4: 提交文档同步**

```bash
git add README.md docs/design/卖家精灵采集与Listing分析一期设计.md
git commit -m "docs: document seller sprite workflow"
```

---

## 自检

设计覆盖情况：

- `opscli/seller_sprite` 模块：Task 1 到 Task 6 覆盖。
- Playwright 统一框架：Task 5 覆盖。
- 高频词与关键词挖掘接口字段：Task 2、Task 4 覆盖。
- 默认 `limit=50` 且允许用户控制：Task 4、Task 6 覆盖。
- 截图、HTML、Markdown、接口 JSON 归档：Task 3、Task 5 覆盖。
- 输出目录使用 `CONFIG_DIR / seller_sprite / runs`：Task 4 覆盖。
- 验证码先预留：Task 3、Task 5 覆盖。
- `ops-seller-sprite` Skill：Task 7 覆盖。
- `ops-amazon-listing-analysis` Skill：Task 8 覆盖。
- 一期不自动推导关键词、不复用卖家精灵 AI 报告、不自动刊登：Task 7、Task 8 覆盖。

计划不包含占位标记、自动补丁式兼容方案、TDD 或单测命令。
