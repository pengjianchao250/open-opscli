"""Rufus 原始回答到报告的正文保留回归测试。"""

import json
from pathlib import Path

import pytest

from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter
from opscli.amazon_rufus.services.parser import RufusParserService
from opscli.amazon_rufus.services.question_bank import QuestionBankService


@pytest.mark.parametrize("question_count", [1, 6, 7])
def test_custom_question_keeps_streamed_answer_with_product_link(question_count):
    """真实流形状同时携带正文和商品链接，报告必须保留送礼回答。"""
    question = "这个商品适合送礼吗？"
    answer_text = "适合送给搬新家的朋友，柔软且可机洗；送礼前请确认房间尺寸。"
    product_url = "https://www.amazon.com/dp/B0CSN6FR1W"
    event = {
        "type": "JSONPatches",
        "patches": [{
            "groupId": "markdown_processor_gift_0",
            "op": "add",
            "path": "/",
            "value": {
                "type": "container",
                "children": [
                    {"type": "text", "children": answer_text},
                    {"type": "text", "children": "查看商品", "onPress": {"url": product_url}},
                ],
            },
        }],
    }
    answer = RufusParserService().parse(f"data: {json.dumps(event)}\n\ndata: [DONE]\n")
    report = AnswerReportFormatter().format_data({
        "asin": "B0CSN6FR1W",
        "questions": [question] * question_count,
        "answers": [answer.to_dict()] * question_count,
    })

    assert answer.is_success
    assert answer.product_links == [product_url]
    assert f"## 第 1 题：{question}" in report
    assert f"## 第 {question_count} 题：{question}" in report
    assert answer_text in report
    assert product_url in report
    assert "标题清晰度与点击意愿分析" not in report
    assert "未获取到答案" not in report


@pytest.mark.parametrize("body", [
    {"text": "建议注明可机洗，帮助买家判断清洁难度。"},
    {"blocks": [{"type": "paragraph", "text": "建议注明可机洗，帮助买家判断清洁难度。"}]},
    {"summaryText": "建议注明可机洗，帮助买家判断清洁难度。"},
])
def test_diagnosis_report_uses_body_before_product_links(body):
    """默认诊断题继续使用固定章节，但链接不能覆盖任何有效正文来源。"""
    report = AnswerReportFormatter().format_data({
        "asin": "B0CSN6FR1W",
        "questions": [
            "分析这个 ASIN B0CSN6FR1W 的标题，按这个格式输出：\n"
            "1、当前标题内容\n2、问题逐项分析\n3、建议优化标题\n4、优化核心逻辑总结"
        ],
        "answers": [{**body, "productLinks": ["https://www.amazon.com/dp/B0CSN6FR1W"]}],
    })

    assert report.startswith("# ASIN B0CSN6FR1W Listing 优化诊断报告")
    assert "建议注明可机洗，帮助买家判断清洁难度。" in report


def test_bundled_diagnosis_questions_keep_all_report_sections():
    """使用真实内置题库确认默认诊断报告仍按七个主题排版。"""
    templates_dir = Path(__file__).resolve().parents[2] / "opscli" / "skills" / "templates"
    templates = QuestionBankService(skills_dir=str(templates_dir)).load_templates()
    questions = [question.text for template in templates for question in template.questions]
    report = AnswerReportFormatter().format_data({
        "asin": "B0CSN6FR1W",
        "questions": questions,
        "answers": [{"text": "已取得商品信息。"} for _ in questions],
    })

    assert report.startswith("# ASIN B0CSN6FR1W Listing 优化诊断报告")
    assert "## 1. 标题清晰度与点击意愿分析" in report
    assert "## 6. 最高评分竞品完整对比分析" in report
    assert "## 7. 最优先修改项综合判断" in report
