import json
import re
from pathlib import Path

from opscli.calculator.draft import validate_draft_data


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "opscli" / "skills" / "templates" / "ops-new-product-calculator" / "SKILL.md"
VERSION = ROOT / "opscli" / "skills" / "templates" / "ops-new-product-calculator" / "data" / "VERSION.json"
MANIFEST = ROOT / "opscli" / "skills" / "templates" / "manifest.json"


def _skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    return text.split("---", 2)[1]


def _first_json_example(text: str) -> dict:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


def test_new_product_calculator_skill_guides_dropdown_workflow():
    text = _skill_text()

    assert "opscli calculator" in text
    assert "search-category" in text
    assert "opscli calculator dropdown-list --json" in text
    assert "只向用户展示" in text
    assert "draft" in text
    assert "validate" in text
    assert "submit" in text
    assert "不得直接调用 Polaris" in text
    assert "试算平台默认同时选择亚马逊和沃尔玛" in text
    assert "--platform 1 --platform 7" in text
    assert "submit 会创建真实试算任务" in text


def test_new_product_calculator_skill_guides_second_stage_draft_completion():
    text = _skill_text()

    assert "第二阶段草稿补全" in text
    assert "pick_up_province" in text
    assert "pick_up_city" in text
    assert "pick_up_province_code" in text
    assert "填写表格.csv" in text
    assert "请填写" in text
    assert "https://bi.xenkee.com/#/newProductCalculator" in text
    assert "pick_up_city_code" in text
    assert "130000" in text
    assert "130200" in text
    assert "two_zone_combine" in text
    assert "zone_1_3" in text
    assert "checkbox_stock" in text
    assert "GROSS_PROFIT" in text
    assert "product_price" in text
    assert "PRICING" in text
    assert "gross_profit_percent" in text
    assert "不要把中文省市名写入 draft.json" in text
    assert "河北省" in text
    assert "唐山市" in text
    assert "算毛利" in text
    assert "1区全部、指定分区" in text
    assert "美东+美中" in text
    assert ".dropdown-cache.json" in text
    assert "自动转换成后端 key/code" in text
    assert "validate 通过后才允许进入 submit" in text


def test_new_product_calculator_skill_json_example_passes_real_validation():
    draft = _first_json_example(_skill_text())

    assert validate_draft_data(draft) == []


def test_new_product_calculator_skill_prevents_draft_overwrite():
    text = _skill_text()

    assert "输出目录必须是新的空目录" in text
    assert "不得覆盖已有 draft.json" in text
    assert "普通用户不建议手动替换整个 JSON" in text
    assert "calculator-draft-usb-cable-20260703" in text


def test_new_product_calculator_skill_routes_failures_to_ops_feedback():
    text = _skill_text()

    assert "REQUIRED SUB-SKILL" in text
    assert "ops-feedback" in text
    assert "非认证类" in text
    assert "立即提交结构化反馈" in text
    assert "反馈完成后再继续原任务" in text


def test_new_product_calculator_skill_requires_polaris_auth_preflight():
    text = _skill_text()

    assert "需要北极星 Polaris 权限" in text
    assert "opscli auth token status" in text
    assert "未登录" in text
    assert "opscli auth login" in text
    assert "已登录但 Polaris Token 状态为无效/未获取" in text
    assert "申请 BI/Polaris 权限" in text


def test_new_product_calculator_skill_guides_result_query_workflow():
    text = _skill_text()

    assert "查询最终试算结果" in text
    assert "calculator detail --task-code" in text
    assert "--sudo" in text
    assert "--json" in text
    assert "trial-result-teble" in text
    assert "费用" in text
    assert "自发货(币种)" in text
    assert "FBA(币种)" in text
    assert "Web详情页" in text
    assert "unexpected extra argument" in text
    assert "不要在回复中泄露完整 JWT/Cookie" in text


def test_new_product_calculator_skill_has_version_and_manifest_entry():
    version = json.loads(VERSION.read_text(encoding="utf-8"))
    assert version["version"] == "v0.0.1"

    frontmatter_keys = {
        line.split(":", 1)[0].strip()
        for line in _frontmatter(_skill_text()).splitlines()
        if ":" in line
    }
    assert frontmatter_keys == {"name", "description"}

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["skills"]["ops-new-product-calculator"]
    assert entry["tier"] == "experimental"
    assert all(entry[target] for target in ("source", "wheel", "binary", "binary_full"))
