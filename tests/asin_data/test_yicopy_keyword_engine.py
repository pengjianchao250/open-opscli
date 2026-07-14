"""校验 asin-data yicopy 销词引擎的本地解析与输出契约。"""

from __future__ import annotations

import asyncio

from opscli.asin_data.services.yicopy_keyword_engine import (
    YicopyKeywordEngine,
    YicopyRunOptions,
    _build_completion_params,
    _site_config,
    build_yicopy_ai_ready_response,
    dedupe_preserve_order,
    extract_asins_from_inputs,
    format_keyword_reverse_export,
    generate_title_prefixes,
    parse_product_detail_html,
)


def test_extract_asins_from_urls_and_plain_text() -> None:
    """从 Amazon URL 和普通 ASIN 文本中提取并去重。"""

    result = extract_asins_from_inputs(
        [
            "https://amazon.com/dp/B0D41JFYRR?th=1",
            "B08N5WRWNW",
            "duplicate https://www.amazon.com/gp/product/B0D41JFYRR/ref=x",
        ]
    )

    assert result == ["B0D41JFYRR", "B08N5WRWNW"]


def test_parse_product_detail_html_extracts_title_and_first_five_bullets() -> None:
    """从商品详情 HTML 中解析标题和前 5 条五点。"""

    html = """
    <html>
      <span id="productTitle"> Wireless Mouse Bluetooth </span>
      <div id="feature-bullets">
        <ul>
          <li><span class="a-list-item">Ergonomic design</span></li>
          <li><span class="a-list-item">Silent click</span></li>
          <li><span class="a-list-item">USB-C charging</span></li>
          <li><span class="a-list-item">For laptop</span></li>
          <li><span class="a-list-item">Portable size</span></li>
          <li><span class="a-list-item">Ignored sixth bullet</span></li>
        </ul>
      </div>
    </html>
    """

    product = parse_product_detail_html("B08N5WRWNW", html)

    assert product.asin == "B08N5WRWNW"
    assert product.title == "Wireless Mouse Bluetooth"
    assert product.bullet_points == [
        "Ergonomic design",
        "Silent click",
        "USB-C charging",
        "For laptop",
        "Portable size",
    ]


def test_generate_title_prefixes_uses_two_word_sliding_window() -> None:
    """按 2 个词滑动窗口生成标题前缀。"""

    prefixes = generate_title_prefixes('HP Stream 14" HD BrightView Laptop, Intel Processor N150')

    assert prefixes[:5] == [
        "HP Stream",
        "Stream 14",
        "14 HD",
        "HD BrightView",
        "BrightView Laptop",
    ]


def test_dedupe_preserve_order_is_case_insensitive() -> None:
    """关键词去重保留首次出现顺序，并忽略大小写重复。"""

    assert dedupe_preserve_order(["Wireless Mouse", "wireless mouse", "Mouse Pad", ""]) == [
        "Wireless Mouse",
        "Mouse Pad",
    ]


def test_default_completion_params_match_frontend_runner() -> None:
    """默认补全请求参数应对齐参考前端销词引擎。"""

    params = _build_completion_params(
        "Wireless Mouse",
        YicopyRunOptions(),
        _site_config("US"),
    )
    param_map = dict(params)
    suggestion_types = [value for key, value in params if key == "suggestion-type"]

    assert suggestion_types == ["KEYWORD"]
    assert param_map["wc"] == ""
    assert param_map["avg-ks-time"] == "500"
    assert param_map["fb"] == "1"
    assert "session-id" not in param_map
    assert "request-id" not in param_map


def test_engine_run_returns_required_output_shape_without_network() -> None:
    """默认模式应对齐前端销词引擎导出：补全词去重后频次全 0。"""

    class FakeYicopyKeywordEngine(YicopyKeywordEngine):
        """提供固定 HTML 和补全词，验证主流程输出契约。"""

        async def _fetch_product_html(
            self,
            client: object,
            asin: str,
            options: YicopyRunOptions,
        ) -> str:
            """返回固定商品 HTML。"""

            _ = client, asin, options
            return """
            <span id="productTitle">Wireless Mouse Bluetooth</span>
            <div id="feature-bullets">
              <span class="a-list-item">Wireless mouse for laptop</span>
            </div>
            """

        async def _fetch_completion_keywords(
            self,
            client: object,
            prefix: str,
            options: YicopyRunOptions,
        ) -> list[str]:
            """返回固定自动补全关键词。"""

            _ = client, prefix, options
            return ["wireless mouse", "Wireless Mouse", "mouse pad"]

    result = asyncio.run(
        FakeYicopyKeywordEngine().run(
            ["https://amazon.com/dp/B08N5WRWNW"],
            YicopyRunOptions(max_prefixes_per_asin=1),
        )
    )

    assert result["status"] == "succeeded"
    assert result["asins"] == ["B08N5WRWNW"]
    assert result["productList"][0]["asin"] == "B08N5WRWNW"
    assert result["allKeywords"][0]["prefix"] == "Wireless Mouse"
    assert result["completionKeywords"] == ["wireless mouse", "mouse pad"]
    assert result["summary"]["analysisMode"] == "frontend"
    assert format_keyword_reverse_export(result)[0] == {
        "keyword": "wireless mouse",
        "titleFrequency": 0,
        "bulletsFrequency": 0,
        "totalFrequency": 0,
    }


def test_build_yicopy_ai_ready_response_indexes_keyword_reverse_dataset(tmp_path) -> None:
    """yicopy 返回结构应对齐 asin-data AI Ready 协议。"""

    output_file = tmp_path / "yicopy.json"
    output_file.write_text("[]", encoding="utf-8")
    rendered = [
        {
            "keyword": "wireless mouse",
            "titleFrequency": 0,
            "bulletsFrequency": 0,
            "totalFrequency": 0,
        }
    ]
    result = {
        "status": "succeeded",
        "asins": ["B08N5WRWNW"],
        "errors": [],
        "summary": {
            "asinCount": 1,
            "prefixCount": 1,
            "keywordReverseCount": 1,
            "errorCount": 0,
        },
    }

    response = build_yicopy_ai_ready_response(
        tool_name="asin_data_yicopy_keyword_engine",
        request={"asin": "B08N5WRWNW", "site": "US", "result_format": "keyword-reverse"},
        result=result,
        rendered_result=rendered,
        result_format="keyword-reverse",
        site="US",
        output_file=str(output_file),
    )

    assert response["metadata"]["protocol"] == "asin_data_ai_response"
    assert response["metadata"]["tool"] == "asin_data_yicopy_keyword_engine"
    assert response["metadata"]["data_scope"] == "yicopy_keyword_reverse"
    assert response["status"] == "succeeded"
    assert response["row_count"] == 1
    item = response["items"][0]
    assert item["asin"] == "B08N5WRWNW"
    assert item["artifacts"][0]["file_key"] == "yicopy_keyword_reverse"
    assert item["artifacts"][0]["type"] == "json"
    assert item["artifacts"][0]["complete"] is True
    dataset = item["datasets"][0]
    assert dataset["source_key"] == "yicopy_keyword_reverse"
    assert dataset["row_count"] == 1
    assert dataset["columns"] == ["keyword", "titleFrequency", "bulletsFrequency", "totalFrequency"]
    assert dataset["preview_rows"] == rendered
    assert response["diagnostics"] == []
