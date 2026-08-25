"""执行器读取 plan/payload/query 文件必须容忍 Windows 常见编码的回归测试。

事故形态：PowerShell 的 `>` 重定向与 `Tee-Object` 默认把文件写成 UTF-16 LE
with BOM，而执行器固定按 UTF-8 读取，直接抛
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff`。
线上取数反馈实测：`query_plan.py ... > plan.json` 落盘后
`run_query.py --plan-file plan.json` 读取即崩（0.0.147 上 3 条独立反馈）。

修复策略：只做 BOM 探测（UTF-16 LE/BE、UTF-8 BOM），无 BOM 一律按 UTF-8，
保证既有文件的行为完全不变。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli" / "skills" / "templates" / "ops-dataset-query" / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import core  # noqa: E402

SAMPLE = '{"查询": "近7天销售额", "limit": 10}'


@pytest.mark.parametrize(
    "label,encoder",
    [
        ("utf-8", lambda s: s.encode("utf-8")),
        ("utf-8-sig", lambda s: s.encode("utf-8-sig")),
        # PowerShell `>` / Tee-Object 的默认输出形态
        ("utf-16-le-bom", lambda s: b"\xff\xfe" + s.encode("utf-16-le")),
        ("utf-16-be-bom", lambda s: b"\xfe\xff" + s.encode("utf-16-be")),
    ],
)
def test_read_text_auto_handles_windows_encodings(tmp_path: Path, label: str, encoder):
    target = tmp_path / f"plan_{label}.json"
    target.write_bytes(encoder(SAMPLE))
    assert core.read_text_auto(target) == SAMPLE, f"{label} 读取结果与原文不一致"


def test_plain_utf8_content_is_byte_identical(tmp_path: Path):
    """无 BOM 的普通 UTF-8 必须原样返回——不得引入任何启发式改写。"""
    target = tmp_path / "plain.json"
    payload = '{"a": "值", "b": [1, 2, 3]}'
    target.write_text(payload, encoding="utf-8")
    assert core.read_text_auto(target) == payload


def test_invalid_utf8_still_raises(tmp_path: Path):
    """真正的坏字节仍然要报错，不能静默吞掉产生错数据。"""
    target = tmp_path / "bad.bin"
    target.write_bytes(b"\xa6\xb7\xc8 not utf8")
    with pytest.raises(UnicodeDecodeError):
        core.read_text_auto(target)
