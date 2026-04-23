"""ops-dataset-query Skill 的查询转发脚本。

该脚本不直接访问后端接口，只负责把查询动作转交给 `opscli query`。
适合在 Skill 目录内直接运行：

- `python query.py metadata --dataset ds_xxx`
- `python query.py run --payload payload.json`
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

    if args.command == "metadata":
        if args.dataset:
            command.extend(["--dataset", args.dataset])
        if args.table_id is not None:
            command.extend(["--table-id", str(args.table_id)])
        if args.skills_dir:
            command.extend(["--skills-dir", args.skills_dir])
    elif args.command == "run":
        command.extend(["--payload", args.payload])
    elif args.command == "build":
        if args.dataset:
            command.extend(["--dataset", args.dataset])
        if args.table_id is not None:
            command.extend(["--table-id", str(args.table_id)])
        for item in args.dimension or []:
            command.extend(["--dimension", item])
        for item in args.metric or []:
            command.extend(["--metric", item])
        for item in args.where or []:
            command.extend(["--where", item])
        for item in args.order_by or []:
            command.extend(["--order-by", item])
        if args.where_json:
            command.extend(["--where-json", args.where_json])
        if args.where_file:
            command.extend(["--where-file", args.where_file])
        if args.skills_dir:
            command.extend(["--skills-dir", args.skills_dir])
        if args.output:
            command.extend(["--output", args.output])
        command.extend(["--limit", str(args.limit), "--offset", str(args.offset)])
        if args.run:
            command.append("--run")

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

    run = subparsers.add_parser("run")
    run.add_argument("--payload", required=True, help="查询 payload JSON 文件")
    run.add_argument("--pretty", action="store_true", help="格式化输出")

    build = subparsers.add_parser("build")
    build.add_argument("--dataset", help="dataset_alias")
    build.add_argument("--table-id", type=int, help="table_id")
    build.add_argument("--dimension", action="append", help="维度定义：field_name[:alias]")
    build.add_argument("--metric", action="append", help="指标定义：field_name:aggregation[:alias]")
    build.add_argument("--where", action="append", help="筛选条件：field|operator|value_json，可重复")
    build.add_argument("--where-json", help="where JSON 字符串")
    build.add_argument("--where-file", help="where JSON 文件路径")
    build.add_argument("--order-by", action="append", help="排序定义：expr[:asc|desc]")
    build.add_argument("--limit", type=int, default=20, help="limit，默认 20")
    build.add_argument("--offset", type=int, default=0, help="offset，默认 0")
    build.add_argument("--skills-dir", help="指定 Skill 目录")
    build.add_argument("--output", help="将 payload 写入指定文件")
    build.add_argument("--run", action="store_true", help="构造后立即执行查询")
    build.add_argument("--pretty", action="store_true", help="格式化输出")

    args = parser.parse_args()

    try:
        command = build_command(args)
    except Exception as exc:
        _emit_error(str(exc))
        raise SystemExit(1) from exc

    result = subprocess.run(command, check=False)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
