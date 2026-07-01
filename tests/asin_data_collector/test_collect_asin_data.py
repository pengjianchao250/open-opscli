import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-asin-data-collector"
    / "scripts"
    / "collect_asin_data.py"
)


def load_collector_module():
    spec = importlib.util.spec_from_file_location("collect_asin_data", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_input_parser_accepts_chinese_keyword_column_and_merges_duplicate_asins(tmp_path: Path):
    collector = load_collector_module()
    input_path = tmp_path / "asins.csv"
    input_path.write_text(
        "ASIN,站点,关键词\n"
        "B0TEST0001,US,\"bed frame; storage bed\"\n"
        "B0TEST0001,US,charging bed\n",
        encoding="utf-8",
    )

    records, errors = collector.load_asin_records(input_path)

    assert errors == []
    assert len(records) == 1
    assert records[0]["keyword"] == "bed frame"
    assert records[0]["keywords"] == ["bed frame", "storage bed", "charging bed"]


def test_listing_analysis_content_is_loaded_from_export_path(tmp_path: Path):
    collector = load_collector_module()
    content = {
        "moduleName": "LA",
        "reportDetails": {
            "subTitle": "多功能储物充电软包床架",
            "overallSummary": "完整报告内容",
        },
    }
    export_path = tmp_path / "listing-analysis.json"
    export_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "taskId": "task-1",
                        "taskStatus": "COMPLETED",
                        "content": json.dumps(content, ensure_ascii=False),
                        "completedTime": "2026-06-08 12:08:13",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = {
        "status": "success",
        "command": ["opscli", "seller-sprite", "run", "listing-analysis"],
        "json": {
            "job_id": "job-1",
            "row_count": 1,
            "export": {"path": str(export_path), "url": None},
            "data": [],
        },
    }

    compact = collector.compact_listing_analysis_result(result)

    assert compact["job_id"] == "job-1"
    assert compact["task_id"] == "task-1"
    assert compact["task_status"] == "COMPLETED"
    assert compact["content"] == content


def test_frontend_record_has_four_chinese_sections_and_full_ai_content():
    collector = load_collector_module()
    ai_content = {"moduleName": "LA", "reportDetails": {"subTitle": "标题"}}
    record = {
        "asin": "B0TEST0001",
        "site": "US",
        "input": {
            "keyword": "bed frame",
            "keywords": ["bed frame", "storage bed"],
            "keyword_count": 2,
            "keyword_source": "input",
            "row_index": 1,
            "source_file": "asins.csv",
        },
        "seller_sprite": {
            "keyword_reverse": {"status": "success", "job_id": "reverse-1", "row_count": 10},
            "keyword_miner": {
                "status": "success",
                "seed_keywords": ["bed frame"],
                "jobs": [{"status": "success", "job_id": "miner-1", "row_count": 20}],
            },
            "listing_analysis": {
                "status": "success",
                "job_id": "listing-1",
                "task_id": "task-1",
                "task_status": "COMPLETED",
                "content": ai_content,
            },
        },
        "amazon": {"scrape": {"status": "success", "product_name": "Bed Frame", "price_amount": 99.99}},
        "query": {
            "sales": {
                "status": "success",
                "row_count": 1,
                "rows": [{"f_asin": "B0TEST0001", "f_product_name": "床架", "f_order_qty": 3}],
            },
            "crawler_listing": {
                "status": "success",
                "row_count": 1,
                "rows": [
                    {
                        "f_asin": "B0TEST0001",
                        "f_product_name": "Listing标题",
                        "f_a_image": "a-image.jpg",
                        "f_a_description": "A+文案",
                        "f_product_details": "产品详情",
                        "f_five_point_description": "五点描述",
                        "f_qa": "QA内容",
                        "f_rating": "4.5",
                        "f_original_price": "129.99",
                        "f_price": "99.99",
                        "f_reduction": "23%",
                        "f_review_list": "评论内容",
                        "f_review_count": 123,
                    }
                ],
            },
        },
        "rufus": {
            "status": "success",
            "country": "US",
            "questions": ["这是什么商品", "这个商品评价如何？"],
            "question_count": 2,
            "answer_count": 1,
            "report_path": "output/amazon-rufus/B0TEST0001.md",
            "answers": [
                {
                    "index": 1,
                    "question": "这是什么商品",
                    "related_products": ["https://www.amazon.com/dp/B0TEST0001"],
                    "answer": "这是一款床架。",
                    "recommended_asins": ["B0TEST0001"],
                    "summary": "床架总结。",
                }
            ],
        },
        "errors": [],
    }

    frontend = collector.build_frontend_record(record)

    assert list(frontend.keys()) == [
        "基础数据",
        "卖家精灵关键词数据",
        "卖家精灵AI全景分析数据",
        "Alexa优化建议数据",
    ]
    assert frontend["基础数据"]["关键词来源"] == "输入文件"
    assert frontend["基础数据"]["输入关键词列表"] == ["bed frame", "storage bed"]
    assert frontend["卖家精灵关键词数据"]["关键词输入"] == {
        "状态": "成功",
        "原始状态": "success",
        "关键词来源": "输入文件",
        "关键词列表": ["bed frame", "storage bed"],
        "关键词数量": 2,
    }
    assert frontend["基础数据"]["BI销售数据"]["明细"][0]["产品名称"] == "床架"
    crawler = frontend["基础数据"]["爬虫Listing数据"]["明细"][0]
    assert crawler["产品名称"] == "Listing标题"
    assert crawler["A+图片"] == "a-image.jpg"
    assert crawler["A+文案"] == "A+文案"
    assert crawler["产品详情"] == "产品详情"
    assert crawler["五点描述"] == "五点描述"
    assert crawler["QA"] == "QA内容"
    assert crawler["星级"] == "4.5"
    assert crawler["划线价"] == "129.99"
    assert crawler["售价"] == "99.99"
    assert crawler["折扣百分比"] == "23%"
    assert crawler["评论"] == "评论内容"
    assert crawler["评论数"] == 123
    assert frontend["卖家精灵AI全景分析数据"]["content"] == ai_content
    assert frontend["Alexa优化建议数据"]["状态"] == "成功"
    assert frontend["Alexa优化建议数据"]["接入状态"] == "已接入"
    assert frontend["Alexa优化建议数据"]["报告路径"] == "output/amazon-rufus/B0TEST0001.md"
    assert frontend["Alexa优化建议数据"]["数据"][0]["答案"] == "这是一款床架。"


def test_seller_sprite_job_outputs_rows_without_paths(tmp_path: Path):
    collector = load_collector_module()
    export_path = tmp_path / "seller-sprite.json"
    rows = [{"关键词": "bed frame", "排名": 1}]
    export_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")

    localized = collector.localize_seller_sprite_job(
        {
            "status": "success",
            "job_id": "job-1",
            "row_count": 1,
            "export_path": str(export_path),
            "export_url": "file:///seller-sprite.json",
            "command": ["opscli", "seller-sprite"],
        }
    )

    assert localized["结果数据"] == rows
    assert "导出路径" not in localized
    assert "导出URL" not in localized
    assert "命令" not in localized


def test_seller_sprite_spreadsheet_job_outputs_export_reference_only():
    collector = load_collector_module()

    compact = collector.compact_seller_sprite_result(
        {
            "status": "success",
            "command": ["opscli", "seller-sprite", "run", "keyword-reverse"],
            "json": {
                "job_id": "job-1",
                "row_count": 100,
                "data": [{"keyword": "bed frame"}],
                "export": {
                    "path": "keyword-reverse.xlsx",
                    "url": "https://example.test/keyword-reverse.xlsx",
                    "format": "xlsx",
                },
            },
        },
        inline_rows=False,
    )
    localized = collector.localize_seller_sprite_job(compact)

    assert compact["rows"] == []
    assert compact["rows_inlined"] is False
    assert localized["\u7ed3\u679c\u6570\u636e"] == []
    assert localized["\u5bfc\u51fa\u683c\u5f0f"] == "xlsx"
    assert localized["\u5bfc\u51faURL"] == "https://example.test/keyword-reverse.xlsx"


def test_keyword_miner_runs_input_keywords_up_to_limit(tmp_path: Path, monkeypatch):
    collector = load_collector_module()
    commands = []

    def fake_run_or_plan(**kwargs):
        commands.append(kwargs["command"])
        return {
            "status": "success",
            "command": kwargs["command"],
            "json": {"data": {"job_id": "job-1", "row_count": 0, "data": []}},
        }

    monkeypatch.setattr(collector, "run_or_plan", fake_run_or_plan)
    args = argparse.Namespace(
        skip_seller_sprite=False,
        skip_keyword_miner=False,
        skip_listing_analysis=True,
        skip_amazon=True,
        keyword_source="input_only",
        seller_sprite_period="30d",
        seller_sprite_page_size=100,
        max_miner_keywords=2,
        dry_run=False,
        opscli_bin="opscli",
    )

    result = collector.collect_one_asin(
        args=args,
        record={
            "asin": "B0TEST0001",
            "site": "US",
            "keyword": "bed frame",
            "keywords": ["bed frame", "storage bed", "charging bed"],
            "row_index": 1,
            "source_file": "asins.csv",
        },
        output_root=tmp_path,
        command_log=None,
        error_log=None,
        query_bundle={},
    )

    miner_commands = [command for command in commands if "keyword-miner" in command]
    miner_params = [
        json.loads(command[command.index("--params") + 1])["keyword"]
        for command in miner_commands
    ]
    assert miner_params == ["bed frame", "storage bed"]
    assert all(command[command.index("--export-format") + 1] == "xlsx" for command in miner_commands)
    reverse_command = next(command for command in commands if "keyword-reverse" in command)
    assert reverse_command[reverse_command.index("--export-format") + 1] == "xlsx"
    assert result["input"]["keywords"] == ["bed frame", "storage bed", "charging bed"]
    assert result["seller_sprite"]["keyword_miner"]["seed_keywords"] == ["bed frame", "storage bed"]


def test_rufus_report_is_compacted_from_cli_stdout(tmp_path: Path):
    collector = load_collector_module()
    report_path = tmp_path / "rufus.md"
    report_path.write_text(
        """## 第 1 题：这是什么商品

### 相关产品

- https://www.amazon.com/dp/B0TEST0001

### 答案

这是一款温控鹅颈电热水壶。

### 推荐 ASIN

- B0TEST0001

### 总结

水壶总结。
""",
        encoding="utf-8",
    )

    compact = collector.compact_rufus_result(
        {
            "status": "success",
            "stdout": f"Rufus 答案报告已保存：{report_path}\n",
            "command": ["opscli", "amazon-rufus", "get-backend"],
        },
        asin="B0TEST0001",
        country="US",
        questions=["这是什么商品"],
    )

    assert compact["report_path"] == str(report_path)
    assert compact["answer_count"] == 1
    assert compact["answers"][0] == {
        "index": 1,
        "question": "这是什么商品",
        "related_products": ["https://www.amazon.com/dp/B0TEST0001"],
        "answer": "这是一款温控鹅颈电热水壶。",
        "recommended_asins": ["B0TEST0001"],
        "summary": "水壶总结。",
    }


def test_rufus_report_parser_supports_official_markdown(tmp_path: Path):
    collector = load_collector_module()
    report_path = tmp_path / "rufus-official.md"
    report_path.write_text(
        """# Rufus 数据 - B0TEST0001

- ASIN: B0TEST0001
- 站点: US
- 状态: success
- 问题数量: 1
- 商品URL: https://www.amazon.com/dp/B0TEST0001
- 原始报告: output/amazon-rufus/B0TEST0001.md

## 第 1 题

问题:
这是什么商品

#### Rufus 展示内容

这是一款温控鹅颈电热水壶。
""",
        encoding="utf-8",
    )

    compact = collector.compact_rufus_result(
        {
            "status": "success",
            "stdout": f"Rufus 答案报告已保存：{report_path}\n",
            "command": ["opscli", "amazon-rufus", "get-backend"],
        },
        asin="B0TEST0001",
        country="US",
        questions=["这是什么商品"],
    )

    assert compact["answer_count"] == 1
    assert compact["answers"][0] == {
        "index": 1,
        "question": "这是什么商品",
        "related_products": [],
        "answer": "这是一款温控鹅颈电热水壶。",
        "recommended_asins": [],
        "summary": "",
    }


def test_split_package_renders_rufus_diagnosis_instead_of_copying_report_path(tmp_path: Path):
    from opscli.asin_data.services.split_package_builder import FILE_RUFUS, build_split_package

    old_report = tmp_path / "old-rufus.md"
    old_report.write_text("## 第 1 题：旧格式\n\n### 答案\n\n旧内容\n", encoding="utf-8")
    asin_result = {
        "asin": "B0TEST0001",
        "site": "US",
        "seller_sprite": {},
        "query": {},
        "bi_report_data": {},
        "rufus": {
            "status": "success",
            "country": "US",
            "report_path": str(old_report),
            "answers": [
                {
                    "index": 1,
                    "answer": "\n".join(
                        [
                            "当前标题：",
                            "ANCTOR Full Corner Bed Frame with Storage Drawers",
                            "分析结果",
                            "问题类型",
                            "具体问题",
                            "问题依据",
                            "建议修改",
                            "核心属性缺失",
                            "尺寸未写在标题中",
                            "产品有多个尺寸变体",
                            "加入 Full Size",
                            "综合建议标题（参考）",
                            "ANCTOR Full Size L-Shaped Daybed Frame",
                        ]
                    ),
                }
            ],
        },
        "frontend_data": {"基础数据": {}},
    }

    package = build_split_package(
        output_root=tmp_path,
        asin_results=[asin_result],
        summary={"summary": {"asin_count": 1}},
    )
    rufus_path = Path(package["package_dir"]) / "B0TEST0001" / FILE_RUFUS
    markdown = rufus_path.read_text(encoding="utf-8")

    assert markdown.startswith("# ASIN B0TEST0001 Listing 优化诊断报告")
    assert "### 1、当前标题内容" in markdown
    assert "| 核心属性缺失 | 尺寸未写在标题中 | 产品有多个尺寸变体 | 加入 Full Size |" in markdown
    assert "旧内容" not in markdown


def test_collect_one_asin_runs_rufus_backend_and_attaches_answers(tmp_path: Path, monkeypatch):
    collector = load_collector_module()
    report_path = tmp_path / "rufus.md"
    report_path.write_text(
        """## 第 1 题：这个商品评价如何？

### 答案

评价总体较好，但需要关注耐用性。
""",
        encoding="utf-8",
    )
    commands = []

    def fake_run_or_plan(**kwargs):
        command = kwargs["command"]
        commands.append(command)
        if "remote-consent" in command:
            return {"status": "success", "command": command, "json": {"success": True, "data": {"status": "allowed"}}}
        if "login-status" in command:
            return {
                "status": "success",
                "command": command,
                "json": {"success": True, "data": {"can_get_backend": True}},
            }
        if "get-backend" in command:
            return {"status": "success", "command": command, "stdout": f"Rufus 答案报告已保存：{report_path}\n"}
        return {"status": "skipped", "command": command}

    monkeypatch.setattr(collector, "run_or_plan", fake_run_or_plan)
    args = argparse.Namespace(
        skip_seller_sprite=True,
        skip_keyword_miner=True,
        skip_listing_analysis=True,
        skip_amazon=True,
        skip_rufus=False,
        skip_rufus_login_recovery=False,
        rufus_country=None,
        rufus_questions=["这个商品评价如何？"],
        rufus_skills_dir=".agents/skills",
        rufus_timeout_seconds=180,
        rufus_login_timeout_seconds=180,
        rufus_parallel=False,
        rufus_concurrency=3,
        rufus_retry=0,
        rufus_strict_answer=False,
        keyword_source="input",
        dry_run=False,
        opscli_bin="opscli",
    )

    result = collector.collect_one_asin(
        args=args,
        record={"asin": "B0TEST0001", "site": "US", "row_index": 1, "source_file": "asins.csv"},
        output_root=tmp_path,
        command_log=None,
        error_log=None,
        query_bundle={},
    )

    assert any("get-backend" in command for command in commands)
    assert result["rufus"]["status"] == "success"
    assert result["rufus"]["answers"][0]["answer"] == "评价总体较好，但需要关注耐用性。"
    assert result["frontend_data"]["Alexa优化建议数据"]["数据"][0]["答案"] == "评价总体较好，但需要关注耐用性。"


def test_rufus_default_questions_are_listing_diagnosis_and_render_asin():
    collector = load_collector_module()
    args = argparse.Namespace(rufus_questions=None)

    questions = collector.rufus_questions(args, asin="b0test0001")

    assert len(questions) == 6
    assert questions[0] == (
        "分析这个ASIN B0TEST0001的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：\n"
        "1、当前标题内容\n"
        "2、问题逐项分析\n"
        "问题类型｜具体问题 ｜ 问题依据｜建议修改\n"
        "3、建议优化标题\n"
        "4、优化核心逻辑总结"
    )
    assert questions[-1] == (
        "从标题、五点、图片、A+、评论中，找出这个 ASIN B0TEST0001 最优先修改的一处。按这个格式输出：\n"
        "1、核心问题定位\n"
        "2、最优先修改原因\n"
        "问题维度｜影响范围｜具体分析｜建议方案\n"
        "3、总体执行修改方案\n"
        "4、优化核心逻辑总结"
    )
    assert "每张图序号｜目标｜具体问题 ｜ 核心依据｜优化方案" in questions[2]
    assert "每个模块｜目标｜具体问题 ｜ 核心依据｜优化方案" in questions[3]
    assert all("{{asin}}" not in question for question in questions)


def test_rufus_collect_command_passes_collector_default_questions_explicitly():
    collector = load_collector_module()
    args = argparse.Namespace(
        opscli_bin="opscli",
        rufus_skills_dir=".agents/skills",
        rufus_timeout_seconds=180,
        rufus_questions=None,
        rufus_parallel=True,
        rufus_concurrency=2,
        rufus_retry=1,
        rufus_strict_answer=True,
    )
    questions = collector.rufus_questions(args, asin="B0TEST0001")

    command = collector.build_rufus_get_backend_command(args, "B0TEST0001", "US", questions)

    assert command.count("-q") == 6
    assert any(item.startswith("分析这个ASIN B0TEST0001的标题是否清楚") for item in command)
    assert "--skills-dir" in command
    assert "--parallel" in command
    assert command[command.index("--concurrency") + 1] == "2"
    assert command[command.index("--retry") + 1] == "1"
    assert "--strict-answer" in command


def test_rufus_explicit_questions_render_asin_placeholder():
    collector = load_collector_module()
    args = argparse.Namespace(rufus_questions=["这个产品ASIN {{asin}}评价里大家最常夸什么？"])

    assert collector.rufus_questions(args, asin="b0test0001") == [
        "这个产品ASIN B0TEST0001评价里大家最常夸什么？"
    ]


def test_sales_payload_uses_realtime_comprehensive_metrics():
    collector = load_collector_module()
    args = argparse.Namespace(
        sales_dataset_alias="ds_d35ac6f3910c",
        sales_field_mode="full",
        sales_start=None,
        sales_end=None,
        query_chunk_size=100,
    )

    payload = collector.build_sales_payload(args, ["B0TEST0001"])

    dimension_fields = [item["field"].split(".", 1)[1] for item in payload["dimensions"]]
    metric_fields = [
        item["field"].split(".", 1)[1]
        for item in payload["metrics"]
        if "field" in item
    ]
    metric_expr_aliases = [
        item["alias"]
        for item in payload["metrics"]
        if "expr" in item
    ]
    filter_fields = [item["field"].split(".", 1)[1] for item in payload["filters"]]
    assert dimension_fields == [
        "asin",
        "product_name",
    ]
    assert metric_fields == [
        "order_qty",
        "orders",
        "sessions",
        "page_views",
        "original_price",
        "price",
        "advertising_fee",
        "ads_sales_cny",
        "ads_clicks",
        "ads_impressions",
        "refund",
        "refund_qty",
    ]
    assert metric_expr_aliases == []
    assert filter_fields == [
        "asin",
    ]


def test_sales_payload_metadata_filter_drops_unregistered_refund_qty():
    collector = load_collector_module()
    args = argparse.Namespace(
        sales_dataset_alias="ds_d35ac6f3910c",
        sales_field_mode="full",
        sales_start=None,
        sales_end=None,
        query_chunk_size=100,
    )

    payload = collector.build_sales_payload(args, ["B0TEST0001"])
    filtered, dropped = collector.filter_query_payload_by_metadata(
        payload,
        "ds_d35ac6f3910c",
        {
            "dimension": {"asin", "product_name"},
            "metric": {
                "order_qty",
                "orders",
                "sessions",
                "page_views",
                "convert_percent",
                "original_price",
                "price",
                "avg_price",
                "advertising_fee",
                "ads_sales_cny",
                "ads_acos",
                "ads_clicks",
                "ads_impressions",
                "refund",
                "refund_percent",
            },
        },
    )

    metric_fields = [
        item["field"].split(".", 1)[1]
        for item in filtered["metrics"]
        if "field" in item
    ]
    assert "refund_qty" not in metric_fields
    assert "refund" in metric_fields
    assert "metric:refund_qty" in dropped


def test_sales_compatible_payload_uses_supported_minimal_metrics():
    collector = load_collector_module()
    args = argparse.Namespace(
        sales_dataset_alias="ds_d35ac6f3910c",
        sales_field_mode="compatible",
        sales_start=None,
        sales_end=None,
        query_chunk_size=100,
    )

    payload = collector.build_sales_payload(args, ["B0TEST0001"])

    metric_fields = [
        item["field"].split(".", 1)[1]
        for item in payload["metrics"]
        if "field" in item
    ]
    assert metric_fields == ["order_qty", "orders", "price"]
    assert all("expr" not in item for item in payload["metrics"])


def test_crawler_payload_orders_latest_snapshot_first():
    collector = load_collector_module()
    args = argparse.Namespace(
        crawler_dataset_alias="ds_crawler",
        crawler_field_mode="full",
        query_chunk_size=100,
    )

    payload = collector.build_crawler_payload(args, ["B0TEST0001"])

    assert payload["orderBy"] == [{"field": "f_date_id", "desc": True}]
    crawler_dimensions = {item["field"].split(".", 1)[1] for item in payload["dimensions"]}
    assert {
        "asin",
        "a_image",
        "a_description",
        "product_details",
        "five_point_description",
        "qa",
        "review_list",
    }.issubset(crawler_dimensions)


def test_crawler_payload_metadata_filter_drops_unregistered_detail_fields():
    collector = load_collector_module()
    args = argparse.Namespace(
        crawler_dataset_alias="ds_icw50TLOFu4F",
        crawler_field_mode="full",
        query_chunk_size=100,
    )

    payload = collector.build_crawler_payload(args, ["B0TEST0001"])
    filtered, dropped = collector.filter_query_payload_by_metadata(
        payload,
        "ds_icw50TLOFu4F",
        {
            "dimension": {
                "asin",
                "date_id",
                "country",
                "currency",
                "listing",
                "link",
                "image",
                "description",
                "brand",
                "seller_id",
                "price_scribe",
                "original_price",
                "unit_price",
                "reduction",
                "coupon",
                "promo_code_value",
                "promo_code",
                "deal",
                "major_name",
                "major_rank",
                "subclass_name",
                "subclass_rank",
                "deal_type",
            },
            "metric": {
                "price",
                "rating",
                "rating_count",
                "review_count",
                "stock_qty",
                "sales_status",
                "in_stock",
                "subplot_count",
                "video_count",
                "five_point_description_count",
                "a_image_count",
                "variant_count",
                "cs_count",
                "qa_count",
                "timestamp",
            },
        },
    )

    crawler_dimensions = {item["field"].split(".", 1)[1] for item in filtered["dimensions"]}
    crawler_metrics = {item["field"].split(".", 1)[1] for item in filtered["metrics"] if "field" in item}
    assert {
        "a_image",
        "a_description",
        "product_details",
        "five_point_description",
        "qa",
        "review_list",
    }.isdisjoint(crawler_dimensions)
    assert "a_image_count" in crawler_metrics
    assert "dimension:a_image" in dropped


def test_crawler_compatible_payload_excludes_unavailable_detail_fields():
    collector = load_collector_module()
    args = argparse.Namespace(
        crawler_dataset_alias="ds_crawler",
        crawler_field_mode="compatible",
        query_chunk_size=100,
    )

    payload = collector.build_crawler_payload(args, ["B0TEST0001"])

    crawler_dimensions = {item["field"].split(".", 1)[1] for item in payload["dimensions"]}
    assert {
        "asin",
        "date_id",
        "listing",
        "link",
        "image",
        "description",
        "original_price",
        "reduction",
    }.issubset(crawler_dimensions)
    assert {
        "a_image",
        "a_description",
        "product_details",
        "five_point_description",
        "qa",
        "review_list",
    }.isdisjoint(crawler_dimensions)


def test_crawler_payload_filters_requested_sites():
    collector = load_collector_module()
    args = argparse.Namespace(
        crawler_dataset_alias="ds_crawler",
        crawler_field_mode="compatible",
        crawler_sites=["US"],
        query_chunk_size=100,
    )

    payload = collector.build_crawler_payload(args, ["B0TEST0001"])

    assert {"field": "ds_crawler.country", "operator": "in", "value": ["US"]} in payload["filters"]


def test_crawler_rows_keep_only_latest_date_per_asin():
    collector = load_collector_module()
    result = {
        "status": "success",
        "row_count": 4,
        "rows": [
            {"f_asin": "B0TEST0001", "f_date_id": "2026-06-06", "f_product_name": "旧标题"},
            {"f_asin": "B0TEST0001", "f_date_id": "2026-06-08", "f_product_name": "新标题"},
            {"f_asin": "B0TEST0002", "f_date_id": "2026-06-07", "f_product_name": "第二个旧标题"},
            {"f_asin": "B0TEST0002", "f_date_id": "2026-06-08", "f_product_name": "第二个新标题"},
        ],
    }

    latest = collector.keep_latest_date_per_asin(result)

    assert latest["latest_date_only"] is True
    assert latest["row_count"] == 2
    assert latest["latest_dates_by_asin"] == {
        "B0TEST0001": "2026-06-08",
        "B0TEST0002": "2026-06-08",
    }
    assert [row["f_product_name"] for row in latest["rows"]] == ["新标题", "第二个新标题"]


def test_sales_row_maps_dataset_aliases_to_chinese_labels():
    collector = load_collector_module()

    localized = collector.localize_sales_row(
        {
            "channel_uuid": "amazon#US",
            "f_listing_uuid": "1#2#US#SKU",
            "f_order_qty": 3,
            "orders": 2,
            "f_sessions": 100,
            "f_convert_percent": 0.03,
            "f_advertising_fee": -12.3,
            "f_ads_acos": 0.25,
            "f_refund": -2,
            "f_refund_percent": 0.02,
            "ads_sp_percent": 0.12,
            "f_sales_amount": 99.99,
        }
    )

    assert localized == {
        "渠道UUID": "amazon#US",
        "Listing UUID": "1#2#US#SKU",
        "订单量": 2,
        "销量": 3,
        "流量": 100,
        "转化率": 0.03,
        "退款金额": -2,
        "广告费": -12.3,
        "ACOS": 0.25,
        "退款率": 0.02,
        "SP广告费占比": 0.12,
        "销售额": 99.99,
    }


def test_amazon_scrape_failure_is_not_reported_as_frontend_error(tmp_path: Path, monkeypatch):
    collector = load_collector_module()

    def fake_run_or_plan(**kwargs):
        assert kwargs["source"] == "amazon.scrape"
        return {"status": "failed", "reason": "amazon scrape failed"}

    monkeypatch.setattr(collector, "run_or_plan", fake_run_or_plan)
    args = argparse.Namespace(
        skip_seller_sprite=True,
        skip_keyword_miner=True,
        skip_listing_analysis=True,
        skip_amazon=False,
        keyword_source="input",
        dry_run=False,
        opscli_bin="opscli",
    )

    result = collector.collect_one_asin(
        args=args,
        record={"asin": "B0TEST0001", "site": "US", "row_index": 1, "source_file": "asins.csv"},
        output_root=tmp_path,
        command_log=None,
        error_log=None,
        query_bundle={},
    )

    assert result["amazon"]["scrape"]["status"] == "failed"
    assert result["errors"] == []


def test_dry_run_writes_frontend_files_and_plans_listing_analysis(tmp_path: Path):
    input_path = tmp_path / "asins.csv"
    input_path.write_text("asin,site,keyword\nB0TEST0001,US,bed frame\n", encoding="utf-8")
    output_dir = tmp_path / "output"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "dry-run-front-end",
            "--skip-query",
            "--skip-amazon",
            "--skip-keyword-miner",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    stdout = json.loads(completed.stdout)
    run_dir = Path(stdout["output_dir"])
    frontend_json = json.loads((run_dir / "frontend-data.json").read_text(encoding="utf-8"))
    frontend_md_path = run_dir / "frontend-data.md"
    assert frontend_md_path.read_bytes().startswith(b"\xef\xbb\xbf")
    frontend_md = frontend_md_path.read_text(encoding="utf-8-sig")
    commands = [
        json.loads(line)
        for line in (run_dir / "commands.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert frontend_json["数据"][0]["卖家精灵AI全景分析数据"]["状态"] == "计划中"
    assert "SellerSprite AI 全景分析" in frontend_md
    assert any("listing-analysis" in command["command"] for command in commands)
