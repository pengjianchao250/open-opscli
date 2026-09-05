"""组件授权枚举失败的归因分流回归测试。

背景（生产会话 5384，2026-09-05）：远端 MCP 上的登录 Session 失效后，opscli 拿它去
`POST /api/v1/auth/cli-token` 换 JWT 恒 401，抛 TokenFetchError。规划器的 enum_failed
分支对异常只做 `except Exception` 不分类型，一律按「通常是该筛选组件的元数据配置异常，
重试无效，请提交反馈由平台侧核查」归因——把一个"重新登录就能恢复"的问题误导成平台缺陷。
生产实测 2026-08-04 起 59 个会话 / 17 个用户被这条文案误导。

本文件钉住：认证类失败必须单独归因为 auth_required/reauthenticate，
且非认证类失败的原有归因不得被带偏。
"""

from __future__ import annotations

import pytest

from opscli.auth.exceptions import NotAuthenticatedError, TokenFetchError
from opscli.query.services.planner import query_plan


def _contract() -> dict:
    """构造一个待解析部门筛选的 planned 合同骨架。"""
    return {
        "status": "planned",
        "query_mode": "dataset_query",
        "model_view": {"clarification_messages_zh": [], "next_action": "construct_query"},
        "execution_ref": {
            "dataset_alias": "ds_instant",
            "filter_components": [
                {
                    "field_name": "dept_name",
                    "label_zh": "部门",
                    "component_dataset_alias": "ds_dept",
                    "component_table_id": 40,
                }
            ],
            "query_template": {"tableId": 1, "dimensions": [], "metrics": [], "filters": []},
        },
    }


def _resolve(query: str, raised: Exception) -> dict:
    """让枚举回调抛出指定异常，返回处理后的合同。"""

    def enum_fn(_table_id, _field_name, *, limit):
        raise raised

    return query_plan._resolve_component_filters(_contract(), query, enum_fn, auto_enum=True)


# ── 分类判定 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "summary, expected",
    [
        ("TokenFetchError: 获取 ops JWT 失败: 401", True),
        ("NotAuthenticatedError: 未登录，请运行: opscli auth login", True),
        ("RemoteBusinessError: 字段不存在", False),
        ("RuntimeError: boom", False),
        ("", False),
        ("没有冒号的裸文本", False),
    ],
)
def test_auth_error_classification(summary, expected):
    """只有 auth 子模块的两个异常类名算认证类，其余一律不算。"""
    assert query_plan._is_auth_enum_error(summary) is expected


def test_auth_error_type_names_track_real_classes():
    """类名集合取自类对象本身，异常类改名时判定自动跟随，不会静默失效。"""
    names = query_plan._auth_error_type_names()

    assert TokenFetchError.__name__ in names
    assert NotAuthenticatedError.__name__ in names


# ── 合同归因 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [TokenFetchError("获取 ops JWT 失败: 401"), NotAuthenticatedError("登录已过期")],
    ids=["TokenFetchError", "NotAuthenticatedError"],
)
def test_auth_failure_is_attributed_to_login_state(exc):
    """认证类失败归因为 auth_required/reauthenticate，并明说不是数据集/权限问题。"""
    contract = _resolve("查部门是九部的销售额", exc)

    model_view = contract["model_view"]
    assert contract["status"] == "blocked"
    assert model_view["component_filter_state"] == "auth_required"
    assert model_view["next_action"] == "reauthenticate"

    message = model_view["clarification_messages_zh"][0]
    assert "登录态失效" in message
    assert "重新登录" in message
    assert "不是数据集或数据权限问题" in message
    # 仍要透出原始错误，便于排查
    assert type(exc).__name__ in message


@pytest.mark.parametrize(
    "exc",
    [TokenFetchError("获取 ops JWT 失败: 401"), NotAuthenticatedError("登录已过期")],
    ids=["TokenFetchError", "NotAuthenticatedError"],
)
def test_auth_failure_message_drops_misleading_wording(exc):
    """认证类文案禁止再出现把用户引向"提反馈干等"的三处措辞。"""
    message = _resolve("查部门是九部的销售额", exc)["model_view"]["clarification_messages_zh"][0]

    assert "元数据配置异常" not in message
    assert "重试无效" not in message
    assert "提交反馈" not in message


def test_non_auth_failure_keeps_original_attribution():
    """非认证类失败的既有归因与文案不得被本次改动带偏。"""
    contract = _resolve("查部门是九部的销售额", RuntimeError("字段不存在"))

    model_view = contract["model_view"]
    assert contract["status"] == "blocked"
    assert model_view["component_filter_state"] == "enum_failed"
    assert model_view["next_action"] == "report_component_enum_defect"
    assert "元数据配置异常" in model_view["clarification_messages_zh"][0]


@pytest.mark.parametrize(
    "exc",
    [TokenFetchError("获取 ops JWT 失败: 401"), RuntimeError("字段不存在")],
    ids=["认证类", "非认证类"],
)
def test_template_is_withdrawn_on_any_enum_failure(exc):
    """无论哪类失败都必须 fail-closed 撤下模板，绝不放行成全范围查询。"""
    contract = _resolve("查部门是九部的销售额", exc)

    assert "query_template" not in contract["execution_ref"]
    assert "query_template_fill_rules_zh" not in contract["execution_ref"]
