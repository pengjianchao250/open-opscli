"""Bug 12136：Rufus 报告正文保真校验、正文与商品链接分开渲染、CLI 与 MCP 结果一致。

fixture `fixtures/b0fl2b5hzs_6q.json` 是 QA 会话中 Rufus 实际返回的 6 题正文（合计 10879 字符），
商品链接取自同一会话的报告。线上症状：报告只剩商品链接和大量「无」，CLI 却提示「已保存」。
"""

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from opscli.amazon_rufus.cli import app
from opscli.amazon_rufus.domain.exceptions import RufusReportContentError
from opscli.amazon_rufus.services import answer_report_publisher as publisher_module
from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter
from opscli.amazon_rufus.services.answer_report_publisher import AnswerReportPublisher, report_warning_fields
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.mcp_manager import RufusMcpManager
from opscli.amazon_rufus.services.question_bank import QuestionBankService
from opscli.amazon_rufus.services.report_validator import RufusDiagnosisReportValidator, skeleton_report_data
from opscli.mcp.tools import amazon_rufus as amazon_rufus_tools
from opscli.shared.file_uploads import FileUploadResult

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "b0fl2b5hzs_6q.json").read_text(encoding="utf-8"))
TEXTS: list[str] = FIXTURE["texts"]
MAIN_LINK: str = FIXTURE["main_link"]
RENDER_LOSS = "RUFUS_REPORT_RENDER_LOSS"
EMPTY_CONTENT = "RUFUS_REPORT_EMPTY_CONTENT"
runner = CliRunner()


def _links(count: int) -> list[list[str]]:
    """第 3 题带 5 条真实链接，其余题各 1 条，与线上报告一致。"""
    return [list(FIXTURE["q3_links"]) if index == 2 else [MAIN_LINK] for index in range(count)]


def _blocks(text: str) -> list[dict]:
    """按空行把正文拆成结构化段落 block，模拟只有 blocks、没有 text 的回答。"""
    return [{"type": "paragraph", "text": part} for part in text.split("\n\n") if part.strip()]


def _questions(template: str) -> list[str]:
    """自定义题用 fixture 原题；诊断题用内置默认题库（7 题，命中诊断模板）。"""
    if template == "custom":
        return list(FIXTURE["questions"])
    templates_dir = Path(__file__).resolve().parents[2] / "opscli" / "skills" / "templates"
    templates = QuestionBankService(skills_dir=str(templates_dir)).load_templates()
    return [question.text for item in templates for question in item.questions]


def _texts(count: int) -> list[str]:
    """诊断模板需要 7 题，循环复用真实正文补齐题数。"""
    return [TEXTS[index % len(TEXTS)] for index in range(count)]


BODY_SOURCES = {
    "text": lambda text: {"text": text, "isSuccess": True},
    "blocks": lambda text: {"text": "", "blocks": _blocks(text), "isSuccess": True},
    "answer+blocks": lambda text: {"answer": text, "blocks": _blocks(text)},
    "summaryText": lambda text: {"text": "", "summaryText": text, "isSuccess": True},
    "text+summaryText+recommendedAsins": lambda text: {
        "text": text, "summaryText": text, "recommendedAsins": ["B0FL2B5HZS"], "isSuccess": True,
    },
}


def _data(template: str, source: str | None = None, *, with_links: bool = True, links_only: tuple[int, ...] = ()) -> dict:
    """构造 manager.get_backend 形态的数据；links_only 中的题号只有商品链接、没有正文。"""
    questions = _questions(template)
    answers = []
    for index, (text, links) in enumerate(zip(_texts(len(questions)), _links(len(questions))), start=1):
        if source is None or index in links_only:
            answer = {"text": "", "isSuccess": True}
        else:
            answer = BODY_SOURCES[source](text)
        if with_links:
            answer["productLinks"] = links
        answers.append(answer)
    return {"asin": "B0FL2B5HZS", "country": "US", "question_count": len(questions), "questions": questions, "answers": answers}


class RecordingUploadClient:
    """记录上传路径的假上传客户端，不发起真实网络请求。"""

    def __init__(self, *args, **kwargs) -> None:
        self.uploaded: list[Path] = []

    def upload(self, path: Path, **kwargs) -> FileUploadResult:
        self.uploaded.append(Path(path))
        return FileUploadResult(url=f"https://files.example/{Path(path).name}", raw={})


class V0132LikeFormatter(AnswerReportFormatter):
    """复刻 v0.0.132 的缺陷：商品链接抢先当作正文，且自定义题也强套诊断模板。"""

    def format_data(self, data: dict) -> str:
        return self._format_official_report(data, data["answers"], self._extract_questions(data))

    def _answer_text(self, index, answer):
        links = self._format_product_links((answer or {}).get("productLinks"))
        return "\n".join(links) if links else super()._answer_text(index, answer)


class DropThirdAnswerFormatter(AnswerReportFormatter):
    """模拟只丢第 3 题正文的渲染回归。"""

    def format_data(self, data: dict) -> str:
        answers = [dict(answer) for answer in data["answers"]]
        answers[2]["text"] = ""
        return super().format_data({**data, "answers": answers})


class DropAllBodiesFormatter(AnswerReportFormatter):
    """模拟任意渲染回归：所有正文字段都没进报告，题目、链接和模板文字照常输出。"""

    def format_data(self, data: dict) -> str:
        answers = [
            {**answer, "text": "", "answer": "", "summaryText": "", "blocks": []} if isinstance(answer, dict) else answer
            for answer in data["answers"]
        ]
        return super().format_data({**data, "answers": answers})


def _publisher(upload_client: RecordingUploadClient, formatter: AnswerReportFormatter | None = None) -> AnswerReportPublisher:
    """按线上默认参数（唯一文件名 + BOM）构造 publisher，可替换 formatter 模拟渲染回归。"""
    writer = AnswerReportWriter(formatter=formatter, unique_filenames=True, encoding="utf-8-sig")
    return AnswerReportPublisher(writer=writer, file_upload_client=upload_client)


def _markers(text: str) -> list[str]:
    """每题取首、中、尾三条长行的前 40 字符作为正文标记（与 Bug 复现脚本口径一致）。"""
    lines = [line.strip(" •\t") for line in text.splitlines() if len(line.strip(" •\t")) >= 30]
    return [line[:40] for line in (lines[0], lines[len(lines) // 2], lines[-1])]


@pytest.mark.parametrize("with_links", [True, False], ids=["with_links", "no_links"])
@pytest.mark.parametrize("source", list(BODY_SOURCES))
@pytest.mark.parametrize("template", ["custom", "diagnosis"])
def test_publish_keeps_body_and_links_matrix(monkeypatch, tmp_path, template, source, with_links):
    """各种正文来源与商品链接组合下，报告保留每题正文和每条链接，链接不进诊断表格，校验通过后才上传。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    data = _data(template, source, with_links=with_links)

    report = _publisher(upload_client).publish(data)
    text = report.path.read_text(encoding="utf-8-sig")

    assert upload_client.uploaded == [report.path]
    assert report.empty_question_indexes == ()
    assert "| - http" not in text
    if with_links:
        for links in _links(len(data["answers"])):
            assert all(link in text for link in links)
        assert "### 相关产品" in text
    if template == "custom":
        assert "Listing 优化诊断报告" not in text
        assert all(marker in text for body in TEXTS for marker in _markers(body))
    else:
        assert text.startswith("# ASIN B0FL2B5HZS Listing 优化诊断报告")
        assert all(body.splitlines()[0][:40] in text for body in TEXTS)


def test_summary_same_as_text_is_rendered_once():
    """summaryText 与正文相同（Rufus 常见）时不再重复输出「总结」，不同时保留。"""
    formatter = AnswerReportFormatter()
    same = formatter.format_data(_data("custom", "text+summaryText+recommendedAsins", with_links=True))
    marker = _markers(TEXTS[0])[0]

    assert same.count(marker) == 1
    assert "### 总结" not in same

    different = formatter.format_data({
        "questions": ["这个商品适合送礼吗？"],
        "answers": [{"text": TEXTS[0], "summaryText": "适合作为乔迁礼物，注意尺寸与重量。"}],
    })
    assert "### 总结\n\n适合作为乔迁礼物，注意尺寸与重量。" in different

    # 总结只是正文中的一句时不算重复，仍单独输出
    fragment = formatter.format_data({
        "questions": ["q"],
        "answers": [{"text": "Overall it is good value. Customers praise the sturdy build.", "summaryText": "good value"}],
    })
    assert "### 总结\n\ngood value" in fragment

    # 与正文只差连字符（2-4 与 24）语义不同，不能当作重复
    hyphen = formatter.format_data({"questions": ["q"], "answers": [{"text": "Fits 2-4 people", "summaryText": "Fits 24 people"}]})
    assert "### 总结\n\nFits 24 people" in hyphen


def test_diagnosis_links_render_in_related_products_without_masking_subsections():
    """诊断模板把链接放进独立「相关产品」小节：不进表格、不补「无」，也不掩盖批量校验器的空小节判断。"""
    formatter = AnswerReportFormatter()
    with_links = formatter.format_data(_data("diagnosis", "text", with_links=True))
    without_links = formatter.format_data(_data("diagnosis", "text", with_links=False))
    links_only = formatter.format_data(_data("diagnosis", with_links=True))

    assert with_links.index("### 相关产品") < with_links.index("### 1、")
    validator = RufusDiagnosisReportValidator()
    assert validator.validate_text(with_links, expected_section_count=7).to_dict() == \
        validator.validate_text(without_links, expected_section_count=7).to_dict()
    assert "| - http" not in links_only
    assert "第 1 题未获取到答案" in links_only
    assert MAIN_LINK in links_only


@pytest.mark.parametrize("template", ["custom", "diagnosis"])
def test_publish_rejects_links_only_report_without_upload(monkeypatch, tmp_path, template):
    """所有题只有商品链接：判 EMPTY_CONTENT，保留本地文件但不上传。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    data = _data(template, with_links=True)

    with pytest.raises(RufusReportContentError) as caught:
        _publisher(upload_client).publish(data)

    error = caught.value.to_dict()
    assert error["code"] == EMPTY_CONTENT
    assert error["empty_question_indexes"] == list(range(1, len(data["answers"]) + 1))
    assert error["lost_question_indexes"] == []
    assert error["answer_error_reasons"][0] == {"question_index": 1, "error_reason": ""}
    assert caught.value.report_path.exists()
    assert upload_client.uploaded == []


@pytest.mark.parametrize("answer", [
    {"text": "适合送礼", "isSuccess": True},
    {"text": "Yes, it is dishwasher safe.", "isSuccess": True},
    # 单题拒答：有正文，由 Agent 读报告后按 Skill 规则判拒答并改写重试，发布层不拦截
    {"text": "I can't complete your request. I can help with shopping questions.",
     "isSuccess": False, "errorReason": "shopping_scope_refusal"},
], ids=["中文短答", "英文一句短答", "单题拒答"])
def test_publish_accepts_short_or_refused_single_answer(monkeypatch, tmp_path, answer):
    """不设报告级字数下限：短答、拒答只要正文在报告里就照常上传。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    report = _publisher(upload_client).publish({"asin": "B0FL2B5HZS", "questions": ["q"], "answers": [answer]})

    assert upload_client.uploaded == [report.path]
    assert answer["text"] in report.path.read_text(encoding="utf-8-sig")


def test_publish_rejects_all_empty_answers_with_error_reasons(monkeypatch, tmp_path):
    """所有题 Rufus 都空答（isSuccess=false 且无 text）：判 EMPTY_CONTENT，并带回每题 errorReason 供 Agent 判断重试。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    answers = [
        {"text": "", "isSuccess": False, "errorReason": "empty_answer", "summaryText": ""},
        {"text": "", "isSuccess": False, "errorReason": "thinking_placeholder",
         "blocks": [{"type": "table_row", "cells": "not-a-list"}]},
    ]

    with pytest.raises(RufusReportContentError) as caught:
        _publisher(upload_client).publish({"asin": "B0FL2B5HZS", "questions": ["q1", "q2"], "answers": answers})

    error = caught.value.to_dict()
    assert error["code"] == EMPTY_CONTENT
    assert error["empty_question_indexes"] == [1, 2]
    assert error["answer_error_reasons"] == [
        {"question_index": 1, "error_reason": "empty_answer"},
        {"question_index": 2, "error_reason": "thinking_placeholder"},
    ]
    assert "不要改写问题重试" not in error["message"]
    assert upload_client.uploaded == []


DIAGNOSIS_ZH = json.loads((Path(__file__).parent / "fixtures" / "diagnosis_zh_7q.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("variant", ["numbered", "inferred"])
def test_publish_accepts_chinese_diagnosis_formats(monkeypatch, tmp_path, variant):
    """中文诊断回答：「1、」编号小节与同行标签、键值表格等推断格式，模板剥标签前缀或丢表格键列时不能误判丢失。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    data = {
        "asin": "B0FL2B5HZS",
        "questions": _questions("diagnosis"),
        "answers": [{"text": text, "productLinks": [MAIN_LINK]} for text in DIAGNOSIS_ZH[variant]],
    }

    report = _publisher(upload_client).publish(data)

    assert report.path.read_text(encoding="utf-8-sig").startswith("# ASIN B0FL2B5HZS Listing 优化诊断报告")
    assert upload_client.uploaded == [report.path]


def test_partial_render_loss_publishes_with_warning(monkeypatch, tmp_path):
    """只有部分题正文疑似丢失（内容条目用「1、」编号被诊断模板当作小节标记吞掉，formatter 既有缺陷）：
    照常上传，并返回疑似丢失题号供告警；启发式误判时也不会让用户拿不到报告。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    texts = list(DIAGNOSIS_ZH["numbered"])
    texts[2] = DIAGNOSIS_ZH["swallowed_q3"]

    report = _publisher(upload_client).publish({
        "asin": "B0FL2B5HZS", "questions": _questions("diagnosis"), "answers": [{"text": text} for text in texts],
    })

    assert report.render_loss_question_indexes == (3,)
    assert report.empty_question_indexes == ()
    assert upload_client.uploaded == [report.path]
    assert report_warning_fields(report) == {
        "render_loss_question_indexes": [3],
        "warning": "第 3 题答案正文疑似在报告渲染中丢失",
    }


def test_publish_reports_render_loss_for_chinese_numbered_diagnosis_with_v0132_formatter(monkeypatch, tmp_path):
    """默认题库「1、…4、」编号作答 + 链接覆盖正文：模板小节标题、表头与回答里的编号标题相同，
    剔除模板行后仍要识别出 7 题正文全部丢失。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    data = {
        "asin": "B0FL2B5HZS",
        "questions": _questions("diagnosis"),
        "answers": [{"text": text, "productLinks": [MAIN_LINK]} for text in DIAGNOSIS_ZH["numbered"]],
    }

    with pytest.raises(RufusReportContentError) as caught:
        _publisher(upload_client, V0132LikeFormatter()).publish(data)

    assert caught.value.to_dict()["code"] == RENDER_LOSS
    assert caught.value.to_dict()["lost_question_indexes"] == [1, 2, 3, 4, 5, 6, 7]
    assert upload_client.uploaded == []


@pytest.mark.parametrize("question,answer", [
    ("这个是什么颜色？", {"text": "是"}),
    ("这个商品适合送礼吗？", {"text": "适合"}),
    ("q", {"text": "答案"}),
    ("Is this table sturdy enough for daily family dining?",
     {"text": "Is this table sturdy enough for daily family dining?\nYes, customers say the marble top is thick."}),
    ("q", {"text": "Built-in power outlets and USB ports make charging easy for the whole family.",
           "recommendedAsins": [{"asin": "B0FL2B5HZS", "title": "ONBRILL",
                                 "description": "Built-in power outlets and USB ports make charging easy"}]}),
], ids=["一字短答且问题含该字", "短答且问题含该词", "短答与兜底文案重字", "正文首行复述问题", "推荐ASIN描述与正文同句"])
def test_publish_reports_render_loss_when_body_only_overlaps_template_text(monkeypatch, tmp_path, question, answer):
    """正文丢失时，题目、「未获取到答案」、推荐 ASIN 描述等模板文字与正文重字也不能掩盖丢失。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    with pytest.raises(RufusReportContentError) as caught:
        _publisher(upload_client, DropAllBodiesFormatter()).publish({"questions": [question], "answers": [answer]})

    assert caught.value.to_dict()["lost_question_indexes"] == [1]
    assert upload_client.uploaded == []
    # 同样的数据用正常渲染器可以通过：短答本身是有效回答
    _publisher(upload_client).publish({"questions": [question], "answers": [answer]})
    assert len(upload_client.uploaded) == 1


@pytest.mark.parametrize("answers,expected_empty", [
    ([], [1, 2]),
    ([{"text": "Thinking...", "isSuccess": False, "errorReason": "thinking_placeholder"},
      {"text": "Sorry, something went wrong", "isSuccess": False, "errorReason": "official_error_placeholder"}], [1, 2]),
    ([{"text": "无"}, {"text": "无"}], [1, 2]),
    ([{"text": "", "blocks": [{"type": "table_row", "cells": [None, None]}]}], [1, 2]),
], ids=["零个答案", "全是占位回答", "每题只答无", "表格单元格为None"])
def test_publish_rejects_when_no_question_has_body(monkeypatch, tmp_path, answers, expected_empty):
    """所有题都没有正文时判 EMPTY_CONTENT；无正文题号按题目数填全（缺答案的题也算），不上传。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    with pytest.raises(RufusReportContentError) as caught:
        _publisher(upload_client).publish({"asin": "B0FL2B5HZS", "questions": ["q1", "q2"], "answers": answers})

    assert caught.value.to_dict()["code"] == EMPTY_CONTENT
    assert caught.value.to_dict()["empty_question_indexes"] == expected_empty
    assert upload_client.uploaded == []


def _format_echo(question: str) -> str:
    """Rufus 原样回显题目里「按这个格式输出：」之后的格式模板。"""
    return question.split("按这个格式输出：", 1)[1].strip()


def _headings_only(question: str) -> str:
    """只保留格式模板中的「N、标题」行。"""
    return "\n".join(line for line in _format_echo(question).splitlines() if re.match(r"^\d、", line.strip()))


@pytest.mark.parametrize("form,expected", [
    ("第2题回显格式模板", ("ok", [])),
    ("第2题只写小节标题", ("ok", [2])),
    ("7题全部回显格式模板", ("ok", [])),
    ("7题全部只写小节标题", (EMPTY_CONTENT, list(range(1, 8)))),
    ("7题小节标题加无", (EMPTY_CONTENT, list(range(1, 8)))),
    ("自定义单题回显格式模板", (EMPTY_CONTENT, [1])),
])
def test_echoed_template_lines_are_not_counted_as_body(monkeypatch, tmp_path, form, expected):
    """Rufus 回显格式模板或只写小节标题时，与骨架相同的标题行、「标题：无」不算正文：
    部分题如此按无正文告警，全部题如此判 EMPTY_CONTENT（可改写重试），都不误判为渲染丢失。"""
    monkeypatch.chdir(tmp_path)
    questions = _questions("diagnosis")
    numbered = DIAGNOSIS_ZH["numbered"]
    answers = {
        "第2题回显格式模板": [_format_echo(questions[1]) if i == 1 else text for i, text in enumerate(numbered)],
        "第2题只写小节标题": [_headings_only(questions[1]) if i == 1 else text for i, text in enumerate(numbered)],
        "7题全部回显格式模板": [_format_echo(question) for question in questions],
        "7题全部只写小节标题": [_headings_only(question) for question in questions],
        "7题小节标题加无": [
            "\n".join(f"{line}\n无" for line in _headings_only(question).splitlines()) for question in questions
        ],
        "自定义单题回显格式模板": [_format_echo(questions[2])],
    }[form]
    data = {
        "asin": "B0FL2B5HZS",
        "questions": questions[2:3] if form.startswith("自定义") else questions,
        "answers": [{"text": text} for text in answers],
    }
    upload_client = RecordingUploadClient()
    code, empty = expected

    if code == "ok":
        report = _publisher(upload_client).publish(data)
        assert report.empty_question_indexes == tuple(empty)
        assert report.render_loss_question_indexes == ()
        assert upload_client.uploaded == [report.path]
    else:
        with pytest.raises(RufusReportContentError) as caught:
            _publisher(upload_client).publish(data)
        assert caught.value.to_dict()["code"] == code
        assert caught.value.to_dict()["empty_question_indexes"] == empty
        assert upload_client.uploaded == []


def test_skeleton_render_failure_falls_back_without_failing_publish(monkeypatch, tmp_path, caplog):
    """骨架渲染异常时记 warning（带 report_path），退化为不剔除模板行的校验，发布照常成功。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    class SkeletonFailingFormatter(AnswerReportFormatter):
        def format_data(self, data: dict) -> str:
            if not any(answer.get("text") for answer in data["answers"]):
                raise RuntimeError("骨架渲染失败")
            return super().format_data(data)

    with caplog.at_level("WARNING", logger=publisher_module.__name__):
        report = _publisher(upload_client, SkeletonFailingFormatter()).publish(_data("custom", "text"))

    assert upload_client.uploaded == [report.path]
    assert report.path.as_posix() in caplog.text
    assert "RuntimeError" in caplog.text


def test_skeleton_report_data_clears_structured_report_fields():
    """骨架数据清空每题正文字段，同时去掉结构化诊断报告字段，只保留题目、链接等非正文字段。"""
    data = {
        "questions": ["q"],
        "diagnosis_report": {"sections": [{"title": "正文"}]},
        "listingOptimizationReport": {"sections": []},
        "answers": [{"text": "正文", "blocks": [{"type": "paragraph", "text": "正文"}], "productLinks": [MAIN_LINK]}],
    }

    skeleton = skeleton_report_data(data)

    assert "diagnosis_report" not in skeleton and "listingOptimizationReport" not in skeleton
    assert skeleton["answers"] == [{"text": "", "blocks": [], "productLinks": [MAIN_LINK]}]
    assert data["answers"][0]["text"] == "正文"


@pytest.mark.parametrize("answer", [
    # 渲染器优先用可渲染的 blocks，text 不出现在报告里；任一来源命中即算正文在
    {"text": TEXTS[2], "blocks": [{"type": "paragraph", "text": "买家普遍认为做工扎实、外观大气，台面厚实，性价比高。"}]},
    {"text": "I recommend https://www.amazon.com/dp/B0FL2B5HZS because it is sturdy and has built-in outlets."},
    {"text": "See [ONBRILL Table](https://www.amazon.com/dp/B0FL2B5HZS) for details about outlets and LED lights."},
    # 链接后直接连写中文：只按 ASCII 识别链接，后面的中文仍算正文
    {"text": "https://www.amazon.com/dp/B0FL2B5HZS，这款桌子桌面厚实做工扎实，适合四口之家日常用餐。"},
], ids=["text与blocks不一致", "行内链接", "Markdown链接", "链接后连写中文"])
def test_fidelity_matches_any_source_and_ignores_links(monkeypatch, tmp_path, answer):
    """多来源任一命中、两侧都剔除链接后比对，不误判丢失。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    _publisher(upload_client).publish({"asin": "B0FL2B5HZS", "questions": ["q"], "answers": [answer]})

    assert len(upload_client.uploaded) == 1


@pytest.mark.parametrize("source", ["text", "blocks"])
def test_publish_reports_render_loss_for_v0132_like_formatter(monkeypatch, tmp_path, source):
    """复刻 v0.0.132「链接覆盖正文」：每题都有正文却全部丢失，判 RENDER_LOSS 并列出 1~6 题，不上传。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    with pytest.raises(RufusReportContentError) as caught:
        _publisher(upload_client, V0132LikeFormatter()).publish(_data("custom", source, with_links=True))

    error = caught.value.to_dict()
    assert error["code"] == RENDER_LOSS
    assert error["lost_question_indexes"] == [1, 2, 3, 4, 5, 6]
    assert "1、2、3、4、5、6" in error["message"]
    assert caught.value.report_path.exists()
    assert upload_client.uploaded == []


def test_publish_warns_when_only_one_question_loses_body(monkeypatch, tmp_path):
    """6 题中只有第 3 题正文在渲染时丢失：不阻断，照常上传并精确给出疑似丢失题号。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    report = _publisher(upload_client, DropThirdAnswerFormatter()).publish(_data("custom", "text", with_links=True))

    assert report.render_loss_question_indexes == (3,)
    assert upload_client.uploaded == [report.path]


def test_publish_partial_body_succeeds_with_warning(monkeypatch, tmp_path):
    """部分题只有链接：仍算成功并上传，但返回无正文题号。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()

    report = _publisher(upload_client).publish(_data("custom", "text", with_links=True, links_only=(2,)))

    assert report.empty_question_indexes == (2,)
    assert upload_client.uploaded == [report.path]


def test_fidelity_tolerates_renderer_rewrites_of_first_line(monkeypatch, tmp_path):
    """渲染器合法改写首行（有序编号转「-」、诊断模板剥掉「当前标题：」前缀）时不能误判丢失。"""
    monkeypatch.chdir(tmp_path)
    upload_client = RecordingUploadClient()
    ordered = {
        "questions": ["这款适合送礼吗？"],
        "answers": [{"text": "1. 适合送给搬新家的朋友，柔软且可机洗，送礼前请确认房间尺寸和颜色偏好。\n"
                             "2. 包装精美，带礼盒可以直接送出，不需要额外购买包装纸。"}],
    }
    diagnosis = {
        "questions": ["分析标题：1、当前标题内容 2、问题逐项分析 3、建议优化标题 4、优化核心逻辑总结"],
        "answers": [{"text": "当前标题：ONBRILL Kitchen Island Table with Power Outlet and LED Lights\n"
                             "分析结果\n维度 问题 依据 建议改为\n关键词 缺少核心词 搜索量高 增加 dining table\n"
                             "优化点说明\n- 前置核心词：提升搜索相关性"}],
    }

    for data in (ordered, diagnosis):
        _publisher(upload_client).publish(data)

    assert len(upload_client.uploaded) == 2


def _run_cli(data: dict) -> tuple[int, str]:
    """经 typer CLI 执行 get-backend，返回退出码与标准输出。"""

    class DummyManager:
        def get_backend(self, **kwargs):
            return data

    with patch("opscli.amazon_rufus.commands.cli.RufusManager", lambda: DummyManager()):
        result = runner.invoke(app, ["get-backend", "B0FL2B5HZS", "US", "-q", "占位问题", "--no-upload-payload"])
    return result.exit_code, result.stdout


def _run_mcp(data: dict) -> dict:
    """经 MCP 工具 amazon_rufus_get 执行（含通用异常到错误响应的映射），返回工具响应。"""

    class DummyRufusManager:
        def get_backend(self, **kwargs):
            return data

    manager = RufusMcpManager(
        rufus_manager=DummyRufusManager(),
        remote_consent_store=object(),
        report_publisher=AnswerReportPublisher(),
    )
    with patch.object(amazon_rufus_tools, "_rufus_mcp_manager_for_current_request", lambda **kwargs: manager):
        return asyncio.run(amazon_rufus_tools.amazon_rufus_get("B0FL2B5HZS", "US", question="占位问题"))


@pytest.mark.parametrize("case", ["ok", "partial", "partial_render_loss", "links_only", "render_loss"])
def test_cli_and_mcp_share_fidelity_outcome(monkeypatch, tmp_path, case):
    """同一 fixture 分别走 CLI 与 MCP：报告字节一致、成功/失败一致、错误码一致；失败时 CLI 不输出「已保存」。"""
    monkeypatch.chdir(tmp_path)
    uploads: list[Path] = []

    class SharedUploadClient(RecordingUploadClient):
        def __init__(self, *args, **kwargs) -> None:
            self.uploaded = uploads

    monkeypatch.setattr(publisher_module, "FileUploadClient", SharedUploadClient)
    if case in {"render_loss", "partial_render_loss"}:
        # CLI 与 MCP 都在内部构造默认 publisher，替换其写入器以注入渲染缺陷（全部丢失 / 只丢第 3 题）。
        formatter_class = V0132LikeFormatter if case == "render_loss" else DropThirdAnswerFormatter
        monkeypatch.setattr(
            publisher_module,
            "AnswerReportWriter",
            lambda **kwargs: AnswerReportWriter(formatter=formatter_class(), **kwargs),
        )
    data = {
        "ok": lambda: _data("custom", "text+summaryText+recommendedAsins"),
        "partial": lambda: _data("custom", "text", links_only=(2,)),
        "links_only": lambda: _data("custom"),
        "render_loss": lambda: _data("custom", "text"),
        "partial_render_loss": lambda: _data("custom", "text"),
    }[case]()

    exit_code, stdout = _run_cli(data)
    mcp_result = _run_mcp(data)
    reports = sorted((tmp_path / "output" / "amazon-rufus").glob("*.md"))

    assert len(reports) == 2
    assert reports[0].read_bytes() == reports[1].read_bytes()
    if case in {"ok", "partial", "partial_render_loss"}:
        assert exit_code == 0
        assert "Rufus 答案报告已保存：" in stdout
        assert mcp_result["success"] is True
        assert len(uploads) == 2
        if case == "partial":
            assert "Rufus 答案报告告警：第 2 题未获取到答案正文" in stdout
            assert mcp_result["data"]["empty_question_indexes"] == [2]
            assert mcp_result["data"]["warning"] == "第 2 题未获取到答案正文"
        elif case == "partial_render_loss":
            assert "Rufus 答案报告告警：第 3 题答案正文疑似在报告渲染中丢失" in stdout
            assert mcp_result["data"]["render_loss_question_indexes"] == [3]
            assert mcp_result["data"]["warning"] == "第 3 题答案正文疑似在报告渲染中丢失"
        else:
            assert "告警" not in stdout
            assert "empty_question_indexes" not in mcp_result["data"]
        return

    cli_error = json.loads(stdout)["error"]
    mcp_error = mcp_result["error"]
    assert exit_code == 1
    assert "已保存" not in stdout
    assert mcp_result["success"] is False
    assert uploads == []
    assert cli_error["code"] == mcp_error["code"] == (EMPTY_CONTENT if case == "links_only" else RENDER_LOSS)
    assert {**cli_error, "report_path": None} == {**mcp_error, "report_path": None}
