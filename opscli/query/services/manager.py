"""query 模块业务编排层。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from opscli.query.domain.exceptions import DatasetNotFoundError, InvalidPayloadError, QueryMetadataNotReadyError
from opscli.query.domain.models import QueryMetadataResult
from opscli.query.transport.client import QueryClient
from opscli.skills.discovery.detector import SkillDetector


@dataclass
class _FieldSpec:
    field_name: str
    alias: str | None
    aggregation: str | None = None


SELECT_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class QueryManager:
    """协调本地 metadata 与远端 query 执行。"""

    def __init__(self) -> None:
        self.detector = SkillDetector()
        self.client = QueryClient()
        self.template_dir = Path(__file__).resolve().parent.parent.parent / "skills" / "templates" / "ops-dataset-query" / "data"

    def metadata(
        self,
        *,
        dataset_alias: str | None = None,
        table_id: int | None = None,
        skills_dir: str | None = None,
        cwd: Path | None = None,
    ) -> QueryMetadataResult:
        """按数据集别名或 table_id 查询本地 query metadata。"""
        if not dataset_alias and table_id is None:
            raise InvalidPayloadError("必须提供 --dataset 或 --table-id")

        payload = self._load_query_metadata(skills_dir=skills_dir, cwd=cwd)
        datasets = payload.get("datasets") or []
        fields = payload.get("fields") or []

        matched = None
        if dataset_alias:
            matched = next((item for item in datasets if item.get("dataset_alias") == dataset_alias), None)
        elif table_id is not None:
            matched = next((item for item in datasets if int(item.get("table_id", -1)) == int(table_id)), None)

        if matched is None:
            needle = dataset_alias if dataset_alias else str(table_id)
            raise DatasetNotFoundError(f"未找到目标数据集: {needle}")

        matched_fields = [
            item for item in fields
            if int(item.get("table_id", -1)) == int(matched.get("table_id", -1))
        ]
        return QueryMetadataResult(dataset=matched, fields=matched_fields, source="local")

    def run(self, *, payload_path: str) -> dict:
        """读取本地 payload 文件并转发执行查询。"""
        payload_file = Path(payload_path).expanduser()
        if not payload_file.exists():
            raise InvalidPayloadError(f"payload 文件不存在: {payload_file}")

        try:
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise InvalidPayloadError(f"payload 不是合法 JSON: {payload_file}") from exc

        self._validate_payload(payload)
        return self.client.cli_query(payload)

    def build(
        self,
        *,
        dataset_alias: str | None = None,
        table_id: int | None = None,
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
        where_conditions: list[str] | None = None,
        where_json: str | None = None,
        where_file: str | None = None,
        having_conditions: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        dry_run: bool = False,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        output_path: str | None = None,
        data_comparison: str | None = None,
    ) -> dict:
        """基于简化参数构造标准 query payload。"""
        if not dimensions and not metrics:
            raise InvalidPayloadError("至少需要提供一个 --dimension 或 --metric")
        where_source_count = sum(1 for item in (where_conditions, where_json, where_file) if item)
        if where_source_count > 1:
            raise InvalidPayloadError("--where、--where-json 和 --where-file 只能使用一种")

        metadata = self.metadata(
            dataset_alias=dataset_alias,
            table_id=table_id,
            skills_dir=skills_dir,
            cwd=cwd,
        )
        dataset = metadata.dataset

        select_items: list[dict] = []
        group_by: list[str] = []

        for spec in dimensions or []:
            item = self._parse_dimension_spec(spec)
            resolved = self._resolve_field(metadata.fields, item.field_name, field_type="dimension")
            output_alias = self._resolve_output_alias(item.alias, resolved)
            select_items.append(
                {
                    "expr": f"{dataset['dataset_alias']}.{resolved['field_name']}",
                    "alias": output_alias,
                }
            )
            group_by.append(output_alias)

        for spec in metrics or []:
            item = self._parse_metric_spec(spec)
            resolved = self._resolve_field(metadata.fields, item.field_name, field_type="metric")
            output_alias = self._resolve_output_alias(item.alias, resolved)
            select_row = {
                "expr": self._resolve_metric_expr(str(dataset["dataset_alias"]), resolved),
                "alias": output_alias,
            }
            if item.aggregation and select_row["expr"] == f"{dataset['dataset_alias']}.{resolved['field_name']}":
                select_row["aggregation"] = item.aggregation
            select_items.append(select_row)

        payload = {
            "tableId": int(dataset["table_id"]),
            "query": {
                "select": select_items,
                "groupBy": group_by,
                "orderBy": self._build_order_by(order_by or []),
                "limit": limit,
                "offset": offset,
            },
        }
        if dry_run:
            payload["dryRun"] = True

        where_payload = self._load_where_clause(
            where_conditions=where_conditions or [],
            where_json=where_json,
            where_file=where_file,
            dataset_alias=str(dataset["dataset_alias"]),
        )
        if where_payload is not None:
            payload["query"]["where"] = where_payload

        having_payload = self._build_having_clause(having_conditions or [])
        if having_payload:
            payload["query"]["having"] = having_payload

        # 构造 dataComparison（数据对比）
        if data_comparison:
            payload["dataComparison"] = self._build_data_comparison(
                data_comparison, dataset_alias=str(dataset["dataset_alias"]),
            )

        self._validate_payload(payload)
        if output_path:
            output_file = Path(output_path).expanduser()
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "dataset": dataset,
            "payload": payload,
            "output": str(Path(output_path).expanduser()) if output_path else None,
        }

    def build_and_run(self, **kwargs) -> dict:
        """先构造 payload，再立即执行查询。"""
        build_result = self.build(**kwargs)
        query_result = self.client.cli_query(build_result["payload"])
        return {
            **build_result,
            "result": query_result,
        }

    def _build_data_comparison(self, raw: str, *, dataset_alias: str) -> dict:
        """解析 dataComparison 定义：field,start_date,end_date。

        格式示例：date_id,2026-03-01,2026-03-22
        field 可以是纯字段名（自动加前缀）或含前缀的全名。
        """
        parts = [item.strip() for item in raw.split(",")]
        if len(parts) != 3 or not all(parts):
            raise InvalidPayloadError(
                "--data-comparison 格式: field,start_date,end_date"
                "（例: date_id,2026-03-01,2026-03-22）"
            )
        field, start_date, end_date = parts
        # 自动补全数据集别名前缀
        if "." not in field:
            field = f"{dataset_alias}.{field}"
        return {
            "switch": True,
            "field": field,
            "startDate": start_date,
            "endDate": end_date,
        }

    def _validate_payload(self, payload: dict) -> None:
        """校验最小请求结构。"""
        if not isinstance(payload, dict):
            raise InvalidPayloadError("payload 顶层必须是 JSON 对象")
        if "tableId" not in payload:
            raise InvalidPayloadError("payload 缺少 tableId")
        if "query" not in payload or not isinstance(payload["query"], dict):
            raise InvalidPayloadError("payload 缺少 query 对象")

    def _load_query_metadata(self, *, skills_dir: str | None, cwd: Path | None) -> dict:
        """从已安装 Skill 或内置模板中读取 query_metadata.json。"""
        metadata_file = self._resolve_metadata_file(skills_dir=skills_dir, cwd=cwd)
        try:
            payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise QueryMetadataNotReadyError(f"query metadata 读取失败: {metadata_file}") from exc

        if not isinstance(payload, dict):
            raise QueryMetadataNotReadyError(f"query metadata 结构非法: {metadata_file}")
        return payload

    def _resolve_metadata_file(self, *, skills_dir: str | None, cwd: Path | None) -> Path:
        """优先使用已安装 Skill 的 metadata 文件，否则回退到内置模板。"""
        records = self.detector.discover(skills_dir=skills_dir, cwd=cwd)
        for record in records:
            if record.name != "ops-dataset-query":
                continue
            metadata_file = record.root / "data" / "query_metadata.json"
            if metadata_file.exists():
                return metadata_file

        fallback = self.template_dir / "query_metadata.json"
        if fallback.exists():
            return fallback
        raise QueryMetadataNotReadyError("本地未找到 query_metadata.json，请先安装并升级 ops-dataset-query")

    def _parse_dimension_spec(self, raw: str) -> _FieldSpec:
        """解析维度定义：field_name[:alias]。"""
        parts = [item.strip() for item in raw.split(":")]
        if len(parts) == 1 and parts[0]:
            return _FieldSpec(field_name=parts[0], alias=None)
        if len(parts) == 2 and parts[0] and parts[1]:
            return _FieldSpec(field_name=parts[0], alias=parts[1])
        raise InvalidPayloadError(f"无效的 --dimension 定义: {raw}")

    def _parse_metric_spec(self, raw: str) -> _FieldSpec:
        """解析指标定义：field_name:aggregation[:alias]。"""
        parts = [item.strip() for item in raw.split(":")]
        if len(parts) == 2 and parts[0] and parts[1]:
            return _FieldSpec(field_name=parts[0], aggregation=parts[1].upper(), alias=None)
        if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
            return _FieldSpec(field_name=parts[0], aggregation=parts[1].upper(), alias=parts[2])
        raise InvalidPayloadError(f"无效的 --metric 定义: {raw}")

    def _build_order_by(self, items: list[str]) -> list[dict]:
        """解析排序定义：expr[:asc|desc]。"""
        result: list[dict] = []
        for raw in items:
            parts = [item.strip() for item in raw.split(":")]
            if len(parts) == 1 and parts[0]:
                result.append({"expr": parts[0], "desc": False})
                continue
            if len(parts) == 2 and parts[0] and parts[1]:
                direction = parts[1].lower()
                if direction not in ("asc", "desc"):
                    raise InvalidPayloadError(f"无效的 --order-by 排序方向: {raw}")
                result.append({"expr": parts[0], "desc": direction == "desc"})
                continue
            raise InvalidPayloadError(f"无效的 --order-by 定义: {raw}")
        return result

    def _load_where_clause(
        self,
        *,
        where_conditions: list[str],
        where_json: str | None,
        where_file: str | None,
        dataset_alias: str,
    ) -> dict | None:
        """从 JSON 字符串或文件中读取 where 结构。"""
        if where_conditions:
            payload = {
                "operator": "AND",
                "conditions": [self._parse_where_condition(item, dataset_alias=dataset_alias) for item in where_conditions],
            }
        elif where_json:
            try:
                payload = json.loads(where_json)
            except Exception as exc:
                raise InvalidPayloadError("--where-json 不是合法 JSON") from exc
        elif where_file:
            file_path = Path(where_file).expanduser()
            if not file_path.exists():
                raise InvalidPayloadError(f"where 文件不存在: {file_path}")
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise InvalidPayloadError(f"where 文件不是合法 JSON: {file_path}") from exc
        else:
            return None

        if not isinstance(payload, dict):
            raise InvalidPayloadError("where 必须是 JSON 对象")
        return payload

    def _parse_where_condition(self, raw: str, *, dataset_alias: str) -> dict:
        """解析 where 简写条件：field|operator|value_json。"""
        parts = raw.split("|", 2)
        if len(parts) != 3:
            raise InvalidPayloadError(f"无效的 --where 定义: {raw}")

        field, operator, value_raw = (item.strip() for item in parts)
        if not field or not operator or not value_raw:
            raise InvalidPayloadError(f"无效的 --where 定义: {raw}")

        expr = field if "." in field else f"{dataset_alias}.{field}"
        try:
            value = json.loads(value_raw)
        except Exception:
            value = value_raw

        return {
            "field": expr,
            "operator": operator,
            "value": value,
        }

    def _build_having_clause(self, items: list[str]) -> list[dict]:
        """解析 having 简写条件：expr|operator|value_json。"""
        result: list[dict] = []
        for raw in items:
            parts = raw.split("|", 2)
            if len(parts) != 3:
                raise InvalidPayloadError(f"无效的 --having 定义: {raw}")

            expr, operator, value_raw = (item.strip() for item in parts)
            if not expr or not operator or not value_raw:
                raise InvalidPayloadError(f"无效的 --having 定义: {raw}")

            try:
                value = json.loads(value_raw)
            except Exception:
                value = value_raw

            result.append(
                {
                    "field": expr,
                    "operator": operator,
                    "value": value,
                }
            )
        return result

    def _resolve_field(self, fields: list[dict], identifier: str, *, field_type: str) -> dict:
        """按 global_alias > field_name > verbose_name 解析字段。"""
        normalized = identifier.strip().lower()
        if not normalized:
            raise InvalidPayloadError("字段标识不能为空")

        global_alias_matches: list[dict] = []
        field_name_matches: list[dict] = []
        verbose_name_matches: list[dict] = []

        for item in fields:
            current_type = str(item.get("field_type") or "").strip().lower()
            if current_type and current_type != field_type:
                continue

            global_alias = str(item.get("global_alias") or "").strip().lower()
            field_name = str(item.get("field_name") or "").strip().lower()
            verbose_name = str(item.get("verbose_name") or "").strip().lower()

            if global_alias and global_alias == normalized:
                global_alias_matches.append(item)
            if field_name and field_name == normalized:
                field_name_matches.append(item)
            if verbose_name and verbose_name == normalized:
                verbose_name_matches.append(item)

        for key, matches in (
            ("global_alias", global_alias_matches),
            ("field_name", field_name_matches),
            ("verbose_name", verbose_name_matches),
        ):
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise InvalidPayloadError(
                    f"字段标识存在歧义（{key} 命中多条）: {identifier}，请改用 global_alias 或 field_name"
                )

        raise InvalidPayloadError(f"字段不存在于当前数据集 metadata 中: {identifier}")

    def _resolve_output_alias(self, alias: str | None, field: dict) -> str:
        """校验显式 alias，或默认回退到 global_alias。"""
        if alias:
            if not SELECT_ALIAS_PATTERN.match(alias):
                raise InvalidPayloadError(
                    "select alias 仅支持英文、数字和下划线，且不能以数字开头；"
                    "建议省略 alias 自动使用 global_alias"
                )
            return alias

        fallback = str(field.get("global_alias") or "").strip() or str(field.get("field_name") or "").strip()
        if not fallback:
            raise InvalidPayloadError("字段缺少可用 alias，请检查 query metadata")
        return fallback

    def _resolve_metric_expr(self, dataset_alias: str, field: dict) -> str:
        """指标字段优先使用汇总公式，否则回退到原始字段。"""
        summary_expression = str(field.get("summary_expression") or "").strip()
        if summary_expression:
            return summary_expression
        return f"{dataset_alias}.{field['field_name']}"
