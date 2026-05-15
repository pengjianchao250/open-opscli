"""ops-dataset-query Skill 的搜索脚本。

提供命令行关键词搜索功能，支持：
- 关键词搜索
- 指定数据集过滤
- 限制返回数量
"""

from __future__ import annotations

import argparse
import json

from core import discover_data_dir, filter_rows_by_dataset, load_csv_rows, search_rows


def main() -> None:
    """读取 CSV 数据并按关键词搜索，输出匹配结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("keyword")
    parser.add_argument("--dataset", help="按 dataset_alias 过滤")
    parser.add_argument("-n", "--limit", type=int, default=10, help="限制返回条数，默认 10")
    args = parser.parse_args()

    # 通过 discover_data_dir 自动发现数据目录（支持环境变量和多路径扫描）
    data_dir = discover_data_dir()
    if data_dir is None:
        print(json.dumps(
            {"error": "未找到本地数据目录，请先执行 opscli skills upgrade ops-dataset-query"},
            ensure_ascii=False,
        ))
        raise SystemExit(1)
    rows = load_csv_rows(data_dir / "dataset_fields.csv")
    filtered_rows = filter_rows_by_dataset(rows, args.dataset)
    matched_rows = search_rows(filtered_rows, args.keyword, limit=args.limit)

    print(json.dumps(matched_rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
