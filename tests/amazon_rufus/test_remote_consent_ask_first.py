"""Rufus 远程授权偏好「先询问后修改」运行时提示测试（QA 第三轮 E2E 问题 N7）。

G4 中 Agent 没有加载 Rufus Skill，它看到的只有 CLI 帮助、MCP 工具描述和报错文案：
`get-backend` 返回 `RUFUS_SECRET_NOT_READY`「请先完成 Rufus 授权状态初始化」后 4 秒，
Agent 就执行了 `remote-consent set US --allow`。所以只改 Skill 文档不够，
Agent 在决策点能看到的这些文本也必须写清「设为允许须经用户明确同意」，
并切断「缺登录态 → 改授权偏好」的误联想。本测试只校验文本，不改变任何命令行为。
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest
import typer.main

from opscli.amazon_rufus.cli import app
from opscli.amazon_rufus.domain.exceptions import InvalidRufusCurlError, RufusSecretNotReadyError
from opscli.amazon_rufus.services.backend_secret import RufusBackendSecretProvider
from opscli.mcp.tools import amazon_rufus as amazon_rufus_tools

COLLECTOR_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-asin-data-collector"
    / "scripts"
    / "collect_asin_data.py"
)


def test_mcp_remote_consent_set_description_requires_explicit_user_reply():
    """MCP 工具描述对所有连接的 Agent 可见（无论是否加载 Skill），必须写明 allowed=true 的前提。"""
    doc = amazon_rufus_tools.amazon_rufus_remote_consent_set.__doc__ or ""

    assert "改状态操作" in doc
    assert "allowed=true 只能在用户对“是否允许保存并复用该站点的亚马逊 Rufus 登录状态”明确回复“允许”之后调用" in doc
    assert "用户暂不继续、未回复或回复不明确时不得调用" in doc
    assert "RUFUS_SECRET_NOT_READY" in doc


def _remote_consent_set_command():
    """取出 `remote-consent set` 的 click 命令对象，直接读参数帮助，避免终端换行影响断言。"""
    root = typer.main.get_command(app)
    return root.commands["remote-consent"].commands["set"]


def test_cli_remote_consent_set_help_requires_explicit_user_reply():
    """CLI 帮助是 G4 中 Agent 实际读过的文本，`--allow` 与命令短说明都要写明须经用户明确同意。"""
    command = _remote_consent_set_command()
    allow_option = next(param for param in command.params if "--allow" in param.opts)

    assert "仅在用户明确回复同意后使用" in allow_option.help
    assert "状态未知时先询问用户" in allow_option.help
    assert "--allow 须经用户明确同意" in (command.help or "")
    # 终端输出须 GBK 兼容（铁律23）
    allow_option.help.encode("gbk")
    (command.help or "").encode("gbk")


class _FakeStore:
    """只返回预置记录的登录态存储桩，不访问网络与 Keychain。"""

    def __init__(self, record):
        self._record = record

    def load(self, country: str):
        return self._record


class _RaisingParser:
    """模拟 cURL 解析失败的解析器桩。"""

    def parse(self, raw_curl: str):
        raise InvalidRufusCurlError("bad curl")


@pytest.mark.parametrize(
    ("record", "parser"),
    [
        (None, None),
        ({"curl": ""}, None),
        ({"curl": "wget https://www.amazon.com"}, None),
        ({"curl": "curl https://www.amazon.com/rufus/cl/streaming"}, _RaisingParser()),
    ],
    ids=["missing", "empty_curl", "not_curl", "unparsable_curl"],
)
def test_secret_not_ready_message_points_to_login_state_not_consent(record, parser):
    """`RUFUS_SECRET_NOT_READY` 是缺登录态：四处文案都要给出具体登录入口，并说明与远程授权偏好无关。

    G4 中 Agent 没加载 Skill，只看到「请先完成 Rufus 授权状态初始化」就去改授权偏好；
    报错文案本身必须能把 Agent 引到正确的恢复入口。
    """
    provider = RufusBackendSecretProvider(browser_state_store=_FakeStore(record), curl_parser=parser)

    with pytest.raises(RufusSecretNotReadyError) as exc_info:
        provider.load(country="US")

    message = str(exc_info.value)
    assert "授权状态初始化" not in message
    # 具体恢复入口：CLI 用法与 docs/guide 一致（watch-login 需要 ASIN 和国家），并给出 MCP 工具名
    assert "opscli amazon-rufus watch-login <ASIN> <COUNTRY> --close-browser" in message
    assert "amazon_rufus_watch_login" in message
    # Linux AI 助手环境（G4 所在环境）没有本机浏览器，要提示由用户在自己电脑上执行
    assert "Linux AI 助手环境请让用户在自己的 Windows/Mac 电脑上执行" in message
    assert "重新采集亚马逊 Rufus 登录态" in message
    assert "与远程授权偏好（remote-consent）无关" in message
    # 报错会经 CLI JSON 输出到终端，须 GBK 兼容（铁律23）
    message.encode("gbk")


def _load_collector_module():
    """按文件路径加载 ops-asin-data-collector 采集脚本。"""
    spec = importlib.util.spec_from_file_location("collect_asin_data_n7", COLLECTOR_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_collector_unknown_consent_reason_asks_user_first(tmp_path: Path, monkeypatch):
    """采集脚本遇到授权未设置时，提示语不得直接指挥 Agent 去执行 set，必须先问用户。"""
    collector = _load_collector_module()

    def fake_run_or_plan(**kwargs):
        command = kwargs["command"]
        if "remote-consent" in command:
            return {"status": "success", "command": command, "json": {"success": True, "data": {"status": "unknown"}}}
        return {"status": "success", "command": command, "json": {"success": True, "data": {"can_get_backend": True}}}

    monkeypatch.setattr(collector, "run_or_plan", fake_run_or_plan)
    args = argparse.Namespace(
        skip_rufus=False,
        rufus_country=None,
        rufus_questions=["这个商品评价如何？"],
        dry_run=False,
        opscli_bin="opscli",
    )

    result = collector.collect_rufus_data(args, "B0TEST0001", "US", tmp_path, None, None)

    assert result["status"] == "failed"
    assert "run opscli amazon-rufus remote-consent set first" not in result["reason"]
    assert "ask the user" in result["reason"]
    assert "only after the user explicitly agrees" in result["reason"]
