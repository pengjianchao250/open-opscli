"""提供 AppHub 数据合同与数据层实现凭证的共享校验能力。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# 数据合同文档的当前稳定版本。
SCHEMA_VERSION = "1.1"
# OPS-only 合同继续兼容 1.0；第三方精确结构合同从 1.1 开始。
SUPPORTED_SCHEMA_VERSIONS = {"1.0", SCHEMA_VERSION}
# 需要精确响应结构与投影合同的第三方来源。
THIRD_PARTY_SOURCES = {"keepa", "seller_sprite"}
# 第三方响应记录允许的容器类型。
ALLOWED_RECORD_TYPES = {"object", "array"}
# 第三方字段投影允许的数据类型。
ALLOWED_FIELD_TYPES = {"string", "number", "integer", "boolean", "object", "array"}
# 支持的校验阶段，delivery 会额外检查项目实现工件。
VALIDATION_MODES = {"draft", "contract", "delivery"}
# 数据合同允许的生命周期状态。
ALLOWED_CONTRACT_STATUSES = {
    "candidate",
    "verifying",
    "verified",
    "degraded",
    "blocked",
    "deferred_attachment",
    "mock-only",
}
# 数据层实现允许的生命周期状态。
ALLOWED_IMPLEMENTATION_STATUSES = {
    "not_started",
    "in_progress",
    "implemented",
    "verified",
    "contract_verified_only",
    "layout_only",
    "blocked",
}
# 正式合同验证成功时允许的结果。
VERIFIED_OUTCOMES = {"success", "zero_rows"}
# 可以作为正式结构性阻塞的分类。
STRUCTURAL_BLOCKER_CATEGORIES = {
    "unsupported",
    "permission",
    "business_ambiguity",
    "runtime_prerequisite",
}
# 不允许伪装成结构性阻塞的临时状态和未执行状态。
NON_STRUCTURAL_BLOCKER_CODES = {
    "contract_not_verified",
    "not_attempted",
    "not_validated",
    "pending_validation",
    "service_error",
    "timeout",
    "upstream_unavailable",
}
# 最终交付必须覆盖的数据层实现工件类别。
REQUIRED_IMPLEMENTATION_ARTIFACTS = (
    "backend_api",
    "backend_service",
    "backend_schema",
    "frontend_consumer",
    "tests",
    "openapi",
)
# 前端文件中出现这些文字表示页面仍停留在布局或待接入阶段。
FRONTEND_PLACEHOLDER_MARKERS = (
    "等待真实数据合同",
    "仅用于布局验证",
    "contract_verified_only",
)
# 不能进入数据合同文件的敏感字段片段。
SENSITIVE_KEY_PARTS = {
    "api_key",
    "authorization",
    "cookie",
    "jwt",
    "password",
    "secret",
    "session_id",
    "token",
}
# 不能进入源码凭证文件的真实结果载荷字段。
FORBIDDEN_PAYLOAD_KEYS = {
    "download_url",
    "export_url",
    "raw_data",
    "raw_response",
    "result_rows",
    "rows",
    "sample_rows",
}


def _is_non_empty_text(value: Any) -> bool:
    """判断值是否为非空字符串。"""
    return isinstance(value, str) and bool(value.strip())


def _add_error(errors: list[str], location: str, message: str) -> None:
    """追加带位置的稳定校验错误。"""
    errors.append(f"{location}: {message}")


def _scan_forbidden_content(value: Any, location: str, errors: list[str]) -> None:
    """递归检查凭证字段和不应进入源码的业务载荷。"""
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = key.lower().replace("-", "_")
            child_location = f"{location}.{key}"
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                _add_error(errors, child_location, "不得保存凭证或敏感身份字段")
            if normalized_key in FORBIDDEN_PAYLOAD_KEYS:
                _add_error(errors, child_location, "不得保存真实结果载荷或临时下载地址")
            _scan_forbidden_content(child, child_location, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden_content(child, f"{location}[{index}]", errors)


def _validate_verification(
    product: dict[str, Any],
    location: str,
    status: str,
    errors: list[str],
) -> None:
    """校验真实调用证据与合同状态的对应关系。"""
    verification = product.get("verification")
    if not isinstance(verification, dict):
        _add_error(errors, location, "缺少 verification 对象")
        return

    attempted = verification.get("attempted")
    outcome = verification.get("outcome")
    attempted_at = verification.get("attempted_at")
    method = verification.get("method")

    if status in {"verified", "degraded"}:
        if attempted is not True:
            _add_error(
                errors,
                f"{location}.verification.attempted",
                f"{status} 必须有真实调用尝试",
            )
        if not _is_non_empty_text(attempted_at):
            _add_error(
                errors,
                f"{location}.verification.attempted_at",
                "必须记录验证时间",
            )
        if not _is_non_empty_text(method):
            _add_error(
                errors,
                f"{location}.verification.method",
                "必须记录正式验证方式",
            )

    if status == "verified" and outcome not in VERIFIED_OUTCOMES:
        _add_error(
            errors,
            f"{location}.verification.outcome",
            "verified 只接受 success 或 zero_rows",
        )

    if status == "degraded":
        if outcome != "failed":
            _add_error(
                errors,
                f"{location}.verification.outcome",
                "degraded 必须记录 failed",
            )
        failure = verification.get("failure")
        if not isinstance(failure, dict):
            _add_error(
                errors,
                f"{location}.verification.failure",
                "degraded 必须记录 failure",
            )
        else:
            if not _is_non_empty_text(failure.get("code")):
                _add_error(
                    errors,
                    f"{location}.verification.failure.code",
                    "必须记录稳定失败码",
                )
            if not isinstance(failure.get("retryable"), bool):
                _add_error(
                    errors,
                    f"{location}.verification.failure.retryable",
                    "必须明确是否可重试",
                )
            if failure.get("feedback_required") is True and not _is_non_empty_text(
                failure.get("feedback_uuid")
            ):
                _add_error(
                    errors,
                    f"{location}.verification.failure.feedback_uuid",
                    "需要远端反馈时必须记录 feedback_uuid",
                )


def _validate_technical_contract(
    product: dict[str, Any],
    location: str,
    status: str,
    source: str,
    schema_version: str,
    errors: list[str],
) -> None:
    """校验已验证数据产品的精确技术合同。"""
    if status != "verified":
        return

    if source in THIRD_PARTY_SOURCES and schema_version != SCHEMA_VERSION:
        _add_error(
            errors,
            "schema_version",
            "已验证第三方数据合同必须升级为 1.1",
        )
        return

    technical_contract = product.get("technical_contract")
    if not isinstance(technical_contract, dict) or not technical_contract:
        _add_error(
            errors,
            f"{location}.technical_contract",
            "verified 必须包含技术合同",
        )
        return

    if source in THIRD_PARTY_SOURCES:
        _validate_third_party_technical_contract(
            product,
            technical_contract,
            location,
            source,
            errors,
        )
        return

    if source != "ops":
        return

    for key in ("dataset_alias", "table_id"):
        if not _is_non_empty_text(technical_contract.get(key)):
            _add_error(
                errors,
                f"{location}.technical_contract.{key}",
                "OPS 合同必须提供精确值",
            )

    fields = technical_contract.get("fields")
    if not isinstance(fields, dict) or not fields:
        _add_error(
            errors,
            f"{location}.technical_contract.fields",
            "OPS 合同必须提供字段映射",
        )
        return

    required_business_roles = technical_contract.get("required_business_roles")
    if not isinstance(required_business_roles, list) or not required_business_roles:
        _add_error(
            errors,
            f"{location}.technical_contract.required_business_roles",
            "OPS 合同必须声明用户要求的业务角色",
        )
    else:
        for role in required_business_roles:
            if not _is_non_empty_text(role):
                _add_error(
                    errors,
                    f"{location}.technical_contract.required_business_roles",
                    "业务角色必须是非空字符串",
                )
                continue
            if role not in fields:
                _add_error(
                    errors,
                    f"{location}.technical_contract.fields.{role}",
                    "缺少用户要求的业务角色字段映射",
                )

    for business_role, field_contract in fields.items():
        field_location = f"{location}.technical_contract.fields.{business_role}"
        if not isinstance(field_contract, dict):
            _add_error(errors, field_location, "字段合同必须是对象")
            continue
        if not _is_non_empty_text(field_contract.get("field_name")):
            _add_error(
                errors,
                f"{field_location}.field_name",
                "必须提供精确 field_name",
            )
        if not _is_non_empty_text(field_contract.get("role")):
            _add_error(errors, f"{field_location}.role", "必须提供字段角色")
        if not _is_non_empty_text(field_contract.get("result_alias")):
            _add_error(
                errors,
                f"{field_location}.result_alias",
                "必须提供稳定结果别名",
            )


def _validate_third_party_shape(
    product: dict[str, Any],
    technical_contract: dict[str, Any],
    location: str,
    source: str,
    errors: list[str],
) -> set[str]:
    """校验第三方响应形状，并返回已观察字段集合。"""
    contract_location = f"{location}.technical_contract"
    response_shape = technical_contract.get("response_shape")
    records_path = None
    record_type = None
    if not isinstance(response_shape, dict):
        _add_error(
            errors,
            f"{contract_location}.response_shape",
            "第三方合同必须声明响应结构",
        )
    else:
        records_path = response_shape.get("records_path")
        record_type = response_shape.get("record_type")
        if not _is_non_empty_text(records_path):
            _add_error(
                errors,
                f"{contract_location}.response_shape.records_path",
                "必须提供精确记录路径",
            )
        if record_type not in ALLOWED_RECORD_TYPES:
            _add_error(
                errors,
                f"{contract_location}.response_shape.record_type",
                "记录类型必须为 object 或 array",
            )
        if source == "seller_sprite" and not _is_non_empty_text(
            response_shape.get("columns_path")
        ):
            _add_error(
                errors,
                f"{contract_location}.response_shape.columns_path",
                "SellerSprite columns + rows 合同必须提供 columns_path",
            )

    verification = product.get("verification")
    shape_evidence = (
        verification.get("shape_evidence") if isinstance(verification, dict) else None
    )
    observed_fields: set[str] = set()
    if not isinstance(shape_evidence, dict):
        _add_error(
            errors,
            f"{location}.verification.shape_evidence",
            "已验证第三方合同必须提供脱敏结构证据",
        )
        return observed_fields

    if shape_evidence.get("records_path") != records_path:
        _add_error(
            errors,
            f"{location}.verification.shape_evidence.records_path",
            "结构证据记录路径必须与技术合同一致",
        )
    if shape_evidence.get("record_type") != record_type:
        _add_error(
            errors,
            f"{location}.verification.shape_evidence.record_type",
            "结构证据记录类型必须与技术合同一致",
        )
    raw_observed_fields = shape_evidence.get("observed_fields")
    if not isinstance(raw_observed_fields, list) or not raw_observed_fields:
        _add_error(
            errors,
            f"{location}.verification.shape_evidence.observed_fields",
            "结构证据必须记录已观察字段名",
        )
        return observed_fields

    for observed_field in raw_observed_fields:
        if not _is_non_empty_text(observed_field):
            _add_error(
                errors,
                f"{location}.verification.shape_evidence.observed_fields",
                "已观察字段名必须是非空字符串",
            )
            continue
        observed_fields.add(str(observed_field).strip())
    return observed_fields


def _validate_third_party_technical_contract(
    product: dict[str, Any],
    technical_contract: dict[str, Any],
    location: str,
    source: str,
    errors: list[str],
) -> None:
    """校验 Keepa 与 SellerSprite 的精确响应结构和字段投影。"""
    contract_location = f"{location}.technical_contract"
    for key in ("scenario", "site"):
        if not _is_non_empty_text(technical_contract.get(key)):
            _add_error(
                errors,
                f"{contract_location}.{key}",
                "第三方合同必须提供精确值",
            )
    if technical_contract.get("result_format") != "json":
        _add_error(
            errors,
            f"{contract_location}.result_format",
            "第三方合同必须使用 json 结果",
        )

    observed_fields = _validate_third_party_shape(
        product,
        technical_contract,
        location,
        source,
        errors,
    )
    fields = technical_contract.get("fields")
    if not isinstance(fields, dict) or not fields:
        _add_error(
            errors,
            f"{contract_location}.fields",
            "第三方合同必须提供字段映射",
        )
        fields = {}

    required_business_roles = technical_contract.get("required_business_roles")
    if not isinstance(required_business_roles, list) or not required_business_roles:
        _add_error(
            errors,
            f"{contract_location}.required_business_roles",
            "第三方合同必须声明用户要求的业务角色",
        )
    else:
        for role in required_business_roles:
            if not _is_non_empty_text(role):
                _add_error(
                    errors,
                    f"{contract_location}.required_business_roles",
                    "业务角色必须是非空字符串",
                )
                continue
            if role not in fields:
                _add_error(
                    errors,
                    f"{contract_location}.fields.{role}",
                    "缺少用户要求的业务角色字段映射",
                )

    for business_role, field_contract in fields.items():
        field_location = f"{contract_location}.fields.{business_role}"
        if not isinstance(field_contract, dict):
            _add_error(errors, field_location, "字段合同必须是对象")
            continue
        for key in ("source_field", "source_path", "result_field"):
            if not _is_non_empty_text(field_contract.get(key)):
                _add_error(
                    errors,
                    f"{field_location}.{key}",
                    "必须提供精确第三方字段映射",
                )
        if field_contract.get("data_type") not in ALLOWED_FIELD_TYPES:
            _add_error(
                errors,
                f"{field_location}.data_type",
                "字段类型不受支持",
            )
        source_field = field_contract.get("source_field")
        if (
            _is_non_empty_text(source_field)
            and str(source_field).strip() not in observed_fields
        ):
            _add_error(
                errors,
                f"{field_location}.source_field",
                "字段未出现在 shape_evidence.observed_fields",
            )

    projection_policy = technical_contract.get("projection_policy")
    if not isinstance(projection_policy, dict):
        _add_error(
            errors,
            f"{contract_location}.projection_policy",
            "第三方合同必须声明投影校验策略",
        )
        return
    if projection_policy.get("validate_before_snapshot") is not True:
        _add_error(
            errors,
            f"{contract_location}.projection_policy.validate_before_snapshot",
            "保存快照前必须校验投影",
        )
    if projection_policy.get("on_schema_mismatch") != "degraded_preserve_snapshot":
        _add_error(
            errors,
            f"{contract_location}.projection_policy.on_schema_mismatch",
            "结构漂移必须降级并保留最后有效快照",
        )


def _validate_blockers(
    product: dict[str, Any],
    location: str,
    status: str,
    errors: list[str],
) -> None:
    """校验结构性阻塞证据，拒绝把未尝试或临时错误写成 blocked。"""
    if status != "blocked":
        return

    blockers = product.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        _add_error(errors, f"{location}.blockers", "blocked 必须记录结构化阻塞原因")
        return

    for index, blocker in enumerate(blockers):
        blocker_location = f"{location}.blockers[{index}]"
        if not isinstance(blocker, dict):
            _add_error(errors, blocker_location, "阻塞原因必须是对象")
            continue
        code = str(blocker.get("code") or "").strip().lower()
        category = str(blocker.get("category") or "").strip().lower()
        if not code:
            _add_error(errors, f"{blocker_location}.code", "必须记录稳定阻塞码")
        elif code in NON_STRUCTURAL_BLOCKER_CODES:
            _add_error(
                errors,
                f"{blocker_location}.code",
                "临时错误或未验证状态不能作为 blocked",
            )
        if category not in STRUCTURAL_BLOCKER_CATEGORIES:
            _add_error(
                errors,
                f"{blocker_location}.category",
                "必须使用结构性阻塞分类",
            )
        if not _is_non_empty_text(blocker.get("message")):
            _add_error(
                errors,
                f"{blocker_location}.message",
                "必须提供可理解的阻塞说明",
            )


def _validate_deferred_attachment(
    product: dict[str, Any],
    location: str,
    status: str,
    errors: list[str],
) -> None:
    """校验待附件产品的证据和解除条件。"""
    if status != "deferred_attachment":
        return
    if not _is_non_empty_text(product.get("deferred_reason")):
        _add_error(
            errors,
            f"{location}.deferred_reason",
            "deferred_attachment 必须记录待附件原因",
        )
    conditions = product.get("unblock_conditions")
    if not isinstance(conditions, list) or not conditions or not all(
        _is_non_empty_text(item) for item in conditions
    ):
        _add_error(
            errors,
            f"{location}.unblock_conditions",
            "deferred_attachment 必须记录解除条件",
        )


def _artifact_paths(
    artifacts: dict[str, Any],
    group: str,
    location: str,
    errors: list[str],
) -> list[str]:
    """读取并校验单个实现工件类别中的相对路径。"""
    values = artifacts.get(group)
    if not isinstance(values, list) or not values:
        _add_error(
            errors,
            f"{location}.implementation_artifacts.{group}",
            "交付实现必须提供至少一个项目内工件",
        )
        return []
    paths: list[str] = []
    for index, value in enumerate(values):
        if not _is_non_empty_text(value):
            _add_error(
                errors,
                f"{location}.implementation_artifacts.{group}[{index}]",
                "工件路径必须是非空字符串",
            )
            continue
        paths.append(str(value).strip())
    return paths


def _resolve_project_artifact(
    project_root: Path,
    relative_path: str,
    location: str,
    errors: list[str],
) -> Path | None:
    """解析项目内工件路径，并拒绝越出项目根目录的声明。"""
    artifact_path = (project_root / relative_path).resolve()
    if not artifact_path.is_relative_to(project_root):
        _add_error(errors, location, "工件路径不得越出项目根目录")
        return None
    if not artifact_path.is_file():
        _add_error(errors, location, f"项目工件不存在：{relative_path}")
        return None
    return artifact_path


def _validate_implementation(
    product: dict[str, Any],
    location: str,
    mode: str,
    project_root: Path | None,
    errors: list[str],
) -> None:
    """校验真实数据产品的数据层实现状态和项目工件。"""
    implementation_status = str(product.get("implementation_status") or "").strip().lower()
    if implementation_status not in ALLOWED_IMPLEMENTATION_STATUSES:
        _add_error(
            errors,
            f"{location}.implementation_status",
            "必须提供有效的数据层实现状态",
        )
        return
    if mode != "delivery":
        return
    if implementation_status != "verified":
        _add_error(
            errors,
            f"{location}.implementation_status",
            "交付时数据层实现状态必须为 verified",
        )
        return

    artifacts = product.get("implementation_artifacts")
    if not isinstance(artifacts, dict):
        _add_error(
            errors,
            f"{location}.implementation_artifacts",
            "交付时必须提供数据层实现工件",
        )
        return

    artifact_groups: dict[str, list[str]] = {}
    for group in REQUIRED_IMPLEMENTATION_ARTIFACTS:
        artifact_groups[group] = _artifact_paths(artifacts, group, location, errors)

    if project_root is None:
        _add_error(errors, location, "delivery 校验必须提供项目根目录")
        return

    normalized_root = project_root.expanduser().resolve()
    for group, paths in artifact_groups.items():
        for index, relative_path in enumerate(paths):
            artifact_location = f"{location}.implementation_artifacts.{group}[{index}]"
            artifact_path = _resolve_project_artifact(
                normalized_root,
                relative_path,
                artifact_location,
                errors,
            )
            if artifact_path is None or group != "frontend_consumer":
                continue
            try:
                frontend_content = artifact_path.read_text(encoding="utf-8")
            except OSError as exc:
                _add_error(errors, artifact_location, f"前端工件无法读取：{exc}")
                continue
            for marker in FRONTEND_PLACEHOLDER_MARKERS:
                if marker in frontend_content:
                    _add_error(
                        errors,
                        artifact_location,
                        f"前端仍包含未交付占位文本：{marker}",
                    )


def _validate_product(
    product: Any,
    index: int,
    schema_version: str,
    mode: str,
    project_root: Path | None,
    errors: list[str],
) -> None:
    """校验单个 AppHub 数据产品合同。"""
    location = f"products[{index}]"
    if not isinstance(product, dict):
        _add_error(errors, location, "数据产品必须是对象")
        return

    product_key = product.get("product_key")
    source = str(product.get("source") or "").strip().lower()
    status = str(product.get("contract_status") or "").strip().lower()
    requires_real_data = product.get("requires_real_data", True) is not False

    if not _is_non_empty_text(product_key):
        _add_error(errors, f"{location}.product_key", "必须提供数据产品标识")
    if not source:
        _add_error(errors, f"{location}.source", "必须提供数据来源")
    if status not in ALLOWED_CONTRACT_STATUSES:
        _add_error(errors, f"{location}.contract_status", "合同状态无效")
        return

    if mode == "delivery" and requires_real_data and status != "verified":
        _add_error(
            errors,
            f"{location}.contract_status",
            "交付时真实数据合同必须为 verified",
        )
    if mode == "delivery" and status == "mock-only" and requires_real_data:
        _add_error(
            errors,
            f"{location}.contract_status",
            "真实数据产品不能以 mock-only 交付",
        )

    _validate_verification(product, location, status, errors)
    _validate_technical_contract(
        product,
        location,
        status,
        source,
        schema_version,
        errors,
    )
    _validate_blockers(product, location, status, errors)
    _validate_deferred_attachment(product, location, status, errors)
    if requires_real_data and status == "verified":
        _validate_implementation(product, location, mode, project_root, errors)
    _scan_forbidden_content(product, location, errors)


def validate_document(
    document: Any,
    *,
    mode: str = "delivery",
    project_root: str | Path | None = None,
) -> list[str]:
    """返回数据合同文档中的全部稳定校验错误。"""
    errors: list[str] = []
    normalized_mode = mode.strip().lower()
    if normalized_mode not in VALIDATION_MODES:
        return [f"mode: 必须为 {', '.join(sorted(VALIDATION_MODES))}"]
    if not isinstance(document, dict):
        return ["root: 数据合同根节点必须是对象"]
    schema_version = str(document.get("schema_version") or "").strip()
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        _add_error(
            errors,
            "schema_version",
            f"必须为 {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}",
        )

    products = document.get("products")
    if not isinstance(products, list) or not products:
        _add_error(errors, "products", "必须包含至少一个数据产品")
        return errors

    normalized_root = Path(project_root) if project_root is not None else None
    seen_product_keys: set[str] = set()
    for index, product in enumerate(products):
        _validate_product(
            product,
            index,
            schema_version,
            normalized_mode,
            normalized_root,
            errors,
        )
        if isinstance(product, dict) and _is_non_empty_text(product.get("product_key")):
            product_key = str(product["product_key"]).strip()
            if product_key in seen_product_keys:
                _add_error(
                    errors,
                    f"products[{index}].product_key",
                    "数据产品标识重复",
                )
            seen_product_keys.add(product_key)
    return errors
