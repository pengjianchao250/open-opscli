"""ops-dataset-query Skill 的查询转发脚本。

该脚本不直接访问后端接口，只负责把查询动作转交给 `opscli query`。
适合在 Skill 目录内直接运行：

- `python query.py metadata --dataset ds_xxx`
- `python query.py catalog --pretty`
- `python query.py simple --table-id 1 --json '{"dimensions":[]}' --run`
- `python query.py chart --uuid <chart_uuid> --run`
- `python query.py chart-doc --uuid <chart_uuid> --output /tmp/chart.md`
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys


def build_opscli_prefix() -> list[str]:
    """解析 opscli 调用前缀。

    优先级：
    1. 环境变量 OPSCLI_BIN
    2. PATH 中的 opscli 可执行文件
    3. 当前 Python 环境可导入 opscli.cli 时使用 `python -m opscli.cli`
    """
    env_bin = os.getenv("OPSCLI_BIN")
    if env_bin:
        return [env_bin]

    cli_bin = shutil.which("opscli")
    if cli_bin:
        return [cli_bin]

    if importlib.util.find_spec("opscli.cli") is not None:
        return [sys.executable, "-m", "opscli.cli"]

    raise RuntimeError("未找到 opscli，请先安装 opscli，或通过 OPSCLI_BIN 指定可执行路径")


def build_command(args: argparse.Namespace) -> list[str]:
    """根据脚本参数构造最终的 opscli query 命令。"""
    command = [*build_opscli_prefix(), "query", args.command]

    if args.command == "catalog":
        if args.source:
            command.extend(["--source", args.source])
        if not args.fallback_local:
            command.append("--no-fallback-local")
        if args.skills_dir:
            command.extend(["--skills-dir", args.skills_dir])
    elif args.command == "metadata":
        if args.dataset:
            command.extend(["--dataset", args.dataset])
        if args.table_id is not None:
            command.extend(["--table-id", str(args.table_id)])
        if args.skills_dir:
            command.extend(["--skills-dir", args.skills_dir])
    elif args.command == "simple":
        command.extend(["--table-id", str(args.table_id)])
        if args.payload:
            command.extend(["--payload", args.payload])
        if args.payload_json:
            command.extend(["--json", args.payload_json])
        if args.output:
            command.extend(["--output", args.output])
        if args.run:
            command.append("--run")
    elif args.command == "chart":
        command.extend(["--uuid", args.uuid])
        if args.run:
            command.append("--run")
        if args.dry_run:
            command.append("--dry-run")
    elif args.command == "chart-doc":
        command.extend(["--uuid", args.uuid])
        if args.output:
            command.extend(["--output", args.output])

    if args.pretty:
        command.append("--pretty")
    return command


def _emit_error(message: str) -> None:
    """以 JSON 形式输出本地错误，保持脚本行为稳定。"""
    print(
        json.dumps(
            {
                "success": False,
                "command": "ops-dataset-query query",
                "data": None,
                "error": message,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    """运行查询转发脚本。"""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    metadata = subparsers.add_parser("metadata")
    metadata.add_argument("--dataset", help="dataset_alias")
    metadata.add_argument("--table-id", type=int, help="table_id")
    metadata.add_argument("--skills-dir", help="指定 Skill 目录")
    metadata.add_argument("--pretty", action="store_true", help="格式化输出")

    catalog = subparsers.add_parser("catalog")
    catalog.add_argument("--source", default="remote", choices=["remote", "local"], help="数据来源")
    catalog.add_argument("--no-fallback-local", dest="fallback_local", action="store_false", help="远端失败时不回退本地缓存")
    catalog.set_defaults(fallback_local=True)
    catalog.add_argument("--skills-dir", help="指定 Skill 目录")
    catalog.add_argument("--pretty", action="store_true", help="格式化输出")

    simple = subparsers.add_parser("simple")
    simple.add_argument("--table-id", required=True, type=int, help="数据集 ID")
    simple.add_argument("--payload", help="简化查询 JSON 文件路径（与 --json 二选一）")
    simple.add_argument("--json", dest="payload_json", help="简化查询 JSON 字符串（与 --payload 二选一）")
    simple.add_argument("--output", help="将 payload 写入指定文件")
    simple.add_argument("--run", action="store_true", help="构造后立即执行查询")
    simple.add_argument("--pretty", action="store_true", help="格式化输出")

    chart = subparsers.add_parser("chart")
    chart.add_argument("--uuid", required=True, help="图表 UUID（chart_uuid）")
    chart.add_argument("--run", action="store_true", help="获取后立即执行所有查询并合并输出")
    chart.add_argument("--dry-run", action="store_true", help="仅生成 SQL，不执行查询")
    chart.add_argument("--pretty", action="store_true", help="格式化输出")

    chart_doc = subparsers.add_parser("chart-doc")
    chart_doc.add_argument("--uuid", required=True, help="图表 UUID（chart_uuid）")
    chart_doc.add_argument("--output", help="将 Markdown 文档写入指定文件路径")
    chart_doc.add_argument("--pretty", action="store_true", help="格式化输出")

    args = parser.parse_args()

    if args.command == "simple" and args.payload and args.payload_json:
        _emit_error("--payload 和 --json 只能使用一种")
        raise SystemExit(1)

    try:
        command = build_command(args)
    except Exception as exc:
        _emit_error(str(exc))
        raise SystemExit(1) from exc

    result = subprocess.run(command, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
