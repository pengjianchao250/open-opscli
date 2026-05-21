"""Skill 远端数据更新器。

负责从运营系统后端拉取最新的 ops-dataset-query 数据，
通过"先写临时目录、再原子替换"的策略安全地更新本地 Skill 数据文件。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.auth.exceptions import AuthError
from opscli.skills.domain.exceptions import SkillRemoteError
from opscli.skills.domain.models import SkillRecord, SkillUpgradeResult


class SkillsUpdater:
    """Skill 数据更新器，从远端拉取最新数据并更新本地安装。

    当前仅支持 ops-dataset-query 这一个 Skill 的远端更新。
    更新流程采用临时目录 + 原子替换策略，确保更新失败不会损坏已有数据。
    """

    # 运营系统后端 API 端点
    MANIFEST_ENDPOINT = "/v1/data-metrics/datasets/skill/manifest"                    # 版本清单
    FIELDS_ENDPOINT = "/v1/data-metrics/datasets/skill/export"                        # 字段数据导出
    DATASETS_ENDPOINT = "/v1/data-metrics/datasets/skill/export-datasets"             # 数据集导出
    SELECT_COLUMNS_ENDPOINT = "/v1/data-metrics/datasets/skill/export-select-columns" # 查询组件关联导出
    CATALOG_ENDPOINT = "/v1/data-metrics/datasets/skill/catalog"                      # AI 业务语义索引
    QUERY_METADATA_ENDPOINT = "/v1/data-metrics/datasets/query-metadata"              # 查询元数据
    RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT = "http://127.0.0.1:8000/api/opencalw/default-question-templates"  # Rufus 默认题库

    def build_remote_summary(self, skill_name: str) -> dict:
        """构建远端状态摘要，供 `skills status` 与调试输出复用。"""
        manifest = self.fetch_manifest(skill_name)
        return {
            "skill_name": skill_name,
            "ops_url": OPS_URL,
            "manifest_endpoint": f"{OPS_URL}{self.MANIFEST_ENDPOINT}",
            "manifest": manifest,
        }

    def fetch_manifest(self, skill_name: str) -> dict | None:
        """获取远端 Skill 的版本清单（manifest）。

        当前仅支持 ops-dataset-query，其他 Skill 返回 None。

        Returns:
            manifest 数据字典，包含 version 等字段；不存在时返回 None
        """
        if skill_name != "ops-dataset-query":
            return None

        response = self._get(self.MANIFEST_ENDPOINT)
        payload = self._parse_json_response(response, endpoint=self.MANIFEST_ENDPOINT)
        return payload.get("data")

    def compare_versions(self, current: str, remote: str) -> int:
        """比较两个语义化版本号。

        支持带 "v" 前缀的版本号（如 v1.2.3），最多解析三段（major.minor.patch）。

        Returns:
            -1 表示 current < remote（需要更新）
             0 表示相等
             1 表示 current > remote
        """
        def parse(value: str) -> tuple[int, int, int]:
            """将版本字符串解析为 (major, minor, patch) 三元组。"""
            normalized = value.strip()
            if normalized.startswith("v"):
                normalized = normalized[1:]
            parts = normalized.split(".")
            ints = [int(part) if part.isdigit() else 0 for part in parts[:3]]
            # 不足三段的补零，如 "1.2" → (1, 2, 0)
            while len(ints) < 3:
                ints.append(0)
            return ints[0], ints[1], ints[2]

        current_parts = parse(current or "v0.0.0")
        remote_parts = parse(remote or "v0.0.0")
        if current_parts < remote_parts:
            return -1
        if current_parts > remote_parts:
            return 1
        return 0

    def fetch_upgrade_data(self, skill_name: str, on_step: Callable[[str], None] | None = None) -> dict:
        """从远端拉取 Skill 升级所需的全部数据，仅执行一次。

        Args:
            skill_name: Skill 名称（当前仅支持 ops-dataset-query）
            on_step: 可选进度回调

        Returns:
            包含 manifest / fields_csv / datasets_csv / select_columns_csv / dataset_catalog / query_metadata / field_count 的字典
        """
        def _step(msg: str) -> None:
            if on_step:
                on_step(msg)

        _step("检查远端版本...")
        manifest = self.fetch_manifest(skill_name)
        if not manifest:
            raise ValueError("远端 manifest 不存在")

        _step("拉取字段数据...")
        fields_csv = self._get(self.FIELDS_ENDPOINT).text
        _step("拉取数据集列表...")
        datasets_csv = self._get(self.DATASETS_ENDPOINT).text
        _step("拉取查询组件关联数据...")
        select_columns_csv = self._fetch_select_columns_csv()
        _step("拉取数据集业务索引...")
        dataset_catalog = self.fetch_dataset_catalog()
        _step("拉取查询元数据...")
        query_metadata = self._parse_json_response(
            self._get(self.QUERY_METADATA_ENDPOINT),
            endpoint=self.QUERY_METADATA_ENDPOINT,
        )
        field_count = self._extract_field_count(query_metadata=query_metadata, manifest=manifest)

        return {
            "manifest": manifest,
            "fields_csv": fields_csv,
            "datasets_csv": datasets_csv,
            "select_columns_csv": select_columns_csv,
            "dataset_catalog": dataset_catalog,
            "query_metadata": query_metadata,
            "field_count": field_count,
        }

    def fetch_dataset_catalog(self) -> dict:
        """拉取 AI 业务语义索引。

        旧版后端可能尚未部署 catalog 接口；此时不阻断 CSV 和 metadata 升级，
        而是写入空索引，保持客户端向后兼容。
        """
        try:
            payload = self._parse_json_response(
                self._get(self.CATALOG_ENDPOINT),
                endpoint=self.CATALOG_ENDPOINT,
            )
        except SkillRemoteError as exc:
            if exc.status_code == 404:
                return {
                    "version": "v0.0.0",
                    "intent_count": 0,
                    "intents": [],
                    "query_strategy": {},
                }
            raise

        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def apply_upgrade_data(
        self,
        record: SkillRecord,
        data: dict,
        force: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> SkillUpgradeResult:
        """将已拉取的远端数据写入指定 Skill 目录。

        采用"先写临时目录、再原子替换"的策略，确保更新失败不会损坏已有数据。

        Args:
            record: 本地已安装的 Skill 记录
            data: fetch_upgrade_data() 返回的数据字典
            force: 为 True 时即使版本号相同也强制更新
            on_step: 可选进度回调
        """
        def _step(msg: str) -> None:
            if on_step:
                on_step(msg)

        manifest = data["manifest"]
        remote_version = str(manifest.get("version", "v0.0.0"))
        current_version = record.version
        # 始终执行更新：数据集权限是动态的，不依赖版本号变化
        needs_update = force or self.compare_versions(current_version, remote_version) <= 0

        if not needs_update:
            return SkillUpgradeResult(
                name=record.name,
                from_version=current_version,
                to_version=remote_version,
                runtime=record.runtime,
                target_dir=record.root,
                updated=False,
                field_count=data.get("field_count", 0),
            )

        data_dir = record.root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # 先写入临时目录，再原子替换，确保更新过程安全
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "dataset_fields.csv").write_text(data["fields_csv"], encoding="utf-8")
            (tmp_path / "datasets.csv").write_text(data["datasets_csv"], encoding="utf-8")
            (tmp_path / "dataset_select_columns.csv").write_text(data["select_columns_csv"], encoding="utf-8")
            (tmp_path / "dataset_catalog.json").write_text(
                json.dumps(data.get("dataset_catalog") or {}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (tmp_path / "query_metadata.json").write_text(
                json.dumps(data["query_metadata"].get("data"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (tmp_path / "VERSION.json").write_text(
                json.dumps(
                    {
                        "name": record.name,
                        "version": remote_version,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            # 原子替换：Path.replace() 在同文件系统上是原子操作
            for filename in [
                "dataset_fields.csv",
                "datasets.csv",
                "dataset_select_columns.csv",
                "dataset_catalog.json",
                "query_metadata.json",
                "VERSION.json",
            ]:
                (tmp_path / filename).replace(data_dir / filename)

        return SkillUpgradeResult(
            name=record.name,
            from_version=current_version,
            to_version=remote_version,
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
            field_count=data.get("field_count", 0),
        )

    def upgrade_ops_dataset_query(
        self,
        record: SkillRecord,
        force: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> SkillUpgradeResult:
        """执行 ops-dataset-query Skill 的数据升级（单次完整流程，向后兼容）。

        流程：
        1. 拉取远端 manifest 获取最新版本号
        2. 对比本地版本，判断是否需要更新
        3. 如需更新，拉取所有数据文件（CSV + JSON）
        4. 先写入临时目录，再原子替换到目标目录，避免中途失败导致数据损坏

        Args:
            record: 本地已安装的 Skill 记录
            force: 为 True 时即使版本号相同也强制更新
            on_step: 可选进度回调，每个阶段开始时调用，参数为描述字符串
        """
        data = self.fetch_upgrade_data(record.name, on_step=on_step)
        return self.apply_upgrade_data(record, data, force=force, on_step=on_step)

    def upgrade_ops_amazon_rufus(self, record: SkillRecord, force: bool = False) -> SkillUpgradeResult:
        """执行 ops-amazon-rufus 默认题库升级。"""
        response = self._get_rufus_default_question_templates()
        payload = self._parse_json_response(response, endpoint=self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise SkillRemoteError(
                "Rufus 默认题库接口返回格式异常",
                endpoint=self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT,
            )
        question_count = sum(len(item.get("questions", [])) for item in data["items"] if isinstance(item, dict))
        if question_count == 0:
            raise SkillRemoteError(
                "Rufus 默认题库为空，已取消本地题库更新",
                endpoint=self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT,
            )

        current_version = record.version
        remote_version = "v0.0.1"
        data_dir = record.root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # 仅写入合并题库与版本文件，不创建 runner_config / marketplaces / questions。
        with TemporaryDirectory(dir=data_dir) as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "question_templates.json").write_text(
                json.dumps({"items": data["items"]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (tmp_path / "VERSION.json").write_text(
                json.dumps({"name": record.name, "version": remote_version}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for filename in ["question_templates.json", "VERSION.json"]:
                (tmp_path / filename).replace(data_dir / filename)

        return SkillUpgradeResult(
            name=record.name,
            from_version=current_version,
            to_version=remote_version,
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
            field_count=question_count,
        )


    def _fetch_select_columns_csv(self) -> str:
        """拉取查询组件关联 CSV（dataset_select_columns.csv）。

        旧版后端可能尚未部署该接口；此时不阻断升级流程，
        而是返回仅含表头的空 CSV，保持向后兼容。
        """
        try:
            return self._get(self.SELECT_COLUMNS_ENDPOINT).text
        except SkillRemoteError as exc:
            if exc.status_code == 404:
                return "current_dataset_alias,column_name,verbose_name,component_dataset_alias\n"
            raise

    def _get_rufus_default_question_templates(self) -> httpx.Response:
        """请求 Rufus 默认题库接口；该本地接口不依赖 ops 登录态。"""
        try:
            response = httpx.get(
                self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT,
                timeout=20,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise SkillRemoteError(
                self._format_http_error(self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT, exc.response.status_code),
                endpoint=self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT,
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise SkillRemoteError(
                f"请求 Rufus 默认题库接口失败: {exc}",
                endpoint=self.RUFUS_DEFAULT_QUESTION_TEMPLATES_ENDPOINT,
            ) from exc

    def _extract_field_count(
        self,
        *,
        query_metadata: dict | None = None,
        manifest: dict | None = None,
    ) -> int:
        """优先从 query-metadata 中提取字段数，失败时回退到 manifest。"""
        if query_metadata:
            data = query_metadata.get("data")
            if isinstance(data, dict):
                fields = data.get("fields")
                if isinstance(fields, list):
                    return len(fields)

        if manifest and isinstance(manifest.get("field_count"), int):
            return int(manifest["field_count"])

        return 0

    def _get(self, endpoint: str) -> httpx.Response:
        """发送带认证的 GET 请求到运营系统后端。

        自动带上 ops 系统的统一认证参数用于鉴权。
        """
        from opscli.mcp.context import get_mcp_request_headers

        auth_client = AuthClient()
        try:
            headers, cookies = auth_client.build_request_auth("ops")
        except AuthError as exc:
            raise SkillRemoteError(
                "未登录 ops，请先执行 `opscli auth login`",
                endpoint=endpoint,
            ) from exc

        headers.update(get_mcp_request_headers())

        try:
            response = httpx.get(
                f"{OPS_URL}{endpoint}",
                headers=headers,
                cookies=cookies,
                timeout=20,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise SkillRemoteError(
                self._format_http_error(endpoint, exc.response.status_code),
                endpoint=endpoint,
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise SkillRemoteError(
                f"请求远端 Skill 服务失败: {exc}",
                endpoint=endpoint,
            ) from exc

    def _parse_json_response(self, response: httpx.Response, *, endpoint: str) -> dict:
        """解析 JSON 响应，并在格式错误时给出清晰提示。"""
        try:
            payload = response.json()
        except ValueError as exc:
            raise SkillRemoteError(
                f"远端接口返回了无法解析的 JSON: {endpoint}",
                endpoint=endpoint,
                status_code=response.status_code,
            ) from exc

        if not isinstance(payload, dict):
            raise SkillRemoteError(
                f"远端接口返回格式异常: {endpoint}",
                endpoint=endpoint,
                status_code=response.status_code,
            )

        business_code = payload.get("code")
        if business_code not in (None, 200):
            raise SkillRemoteError(
                self._format_business_error(endpoint, business_code, payload.get("msg")),
                endpoint=endpoint,
                status_code=int(business_code) if isinstance(business_code, int) else None,
            )

        return payload

    def _format_http_error(self, endpoint: str, status_code: int) -> str:
        """将常见 HTTP 状态码转换为更友好的错误信息。"""
        if status_code == 401:
            return f"远端 Skill 接口鉴权失败，请重新登录后重试: {endpoint}"
        if status_code == 403:
            return f"当前账号无权访问远端 Skill 接口: {endpoint}"
        if status_code == 404:
            return f"远端环境未部署该 Skill 接口: {OPS_URL}{endpoint}"
        if status_code >= 500:
            return f"远端 Skill 服务异常（HTTP {status_code}）: {OPS_URL}{endpoint}"
        return f"远端 Skill 接口请求失败（HTTP {status_code}）: {OPS_URL}{endpoint}"

    def _format_business_error(self, endpoint: str, code: int | str, message: str | None) -> str:
        """将业务层 code/msg 包装为更清晰的远端错误。"""
        if code == 404:
            return f"远端 Skill 数据尚未发布: {message or endpoint}"
        if code == 401:
            return f"远端 Skill 接口鉴权失败，请重新登录后重试: {message or endpoint}"
        if code == 403:
            return f"当前账号无权访问远端 Skill 接口: {message or endpoint}"
        if code == 422:
            return f"远端 Skill 接口参数校验失败: {message or endpoint}"
        return f"远端 Skill 接口返回业务错误（code={code}）: {message or endpoint}"




