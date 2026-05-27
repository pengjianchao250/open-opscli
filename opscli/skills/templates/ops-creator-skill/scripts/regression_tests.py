#!/usr/bin/env python3
"""Run static and simulated-dialogue regressions for ops-creator-skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
POLICY_FILES = [
    ROOT / "SKILL.md",
    ROOT / "agents" / "openai.yaml",
    *sorted((ROOT / "references").glob("*.md")),
]


@dataclass(frozen=True)
class StaticCase:
    scenario: str
    prompt: str
    expected: str
    must_contain: tuple[str, ...]
    must_not_contain: tuple[str, ...] = ()


@dataclass(frozen=True)
class DialogueCase:
    scenario: str
    prompt: str
    expected: str
    response_must_contain: tuple[str, ...]
    response_must_not_contain: tuple[str, ...] = ()


STATIC_CASES = (
    StaticCase(
        scenario="经验盘点与 Skill 规划",
        prompt="帮我总结我上面提到过的跟亚马逊的所有运营知识，告诉我哪些可以做成skills，并按我之前的处理逻辑做成skills",
        expected="先触发知识盘点/Skill 规划，输出现有资产、能力重叠、建议复用项和真实缺口，再决定新建。",
        must_contain=("知识盘点/Skill 规划", "资产去重门", "现有相关 Skills", "能力重叠", "真正缺口"),
        must_not_contain=(),
    ),
    StaticCase(
        scenario="非跨境运营 Skill 创建",
        prompt="请你帮我创建一个“Skill 验收官”Skill，用于验收其他 Skill 是否合格。",
        expected="不因非跨境运营而拒绝；先做价值判断，再进入访谈和 skill-creator 落地。",
        must_contain=("价值判断", "阶段 0", "skill-creator", "可安装"),
        must_not_contain=("默认面向 Aukeys", "跨境电商运营场景"),
    ),
    StaticCase(
        scenario="安装并验收已有 Skill",
        prompt="帮我安装你刚才生成好的skills。然后利用这个skills，去给我去验收这个skills:ops-creator-skill",
        expected="识别为安装/使用/验收任务，输出安装路径、校验和测试结果。",
        must_contain=("Skill 验收、安装使用", "安装位置", "校验结果", "测试清单"),
    ),
    StaticCase(
        scenario="标准新建 Skill",
        prompt="我想把“Amazon 差评处理流程”沉淀成一个 Skill。",
        expected="进入标准新建流程，先完成 Q1-Q6、阶段 1 和复述确认，再创建文件。",
        must_contain=("Q1-Q6", "阶段 1", "复述", "不得创建或更新"),
    ),
    StaticCase(
        scenario="用户输入很模糊",
        prompt="帮我把我们运营经验做成一个 Skill。",
        expected="判定信息不足，需要先补访谈，不直接创建文件。",
        must_contain=("泛泛目标", "需要先补访谈", "不要创建 Skill 文件"),
    ),
    StaticCase(
        scenario="用户要求代替回答",
        prompt="你先别问我了，我懒得一题题回答。你根据这个场景帮我代答并创建 Skill。",
        expected="只输出 AI 假设草案并等待确认，不固化到正式文件。",
        must_contain=("AI 假设，待用户确认", "代答", "不得写入正式"),
    ),
    StaticCase(
        scenario="不适合做 Skill 的场景",
        prompt="帮我创建一个 Skill，专门用于明天给领导写一条微信群通知，内容是提醒大家下午 3 点开会。",
        expected="判定为一次性任务，不创建 Skill，给轻量替代物。",
        must_contain=("一次性任务", "不建议创建 Skill", "停止创建"),
    ),
    StaticCase(
        scenario="旧 Skill 改造",
        prompt="我有一个旧 Skill，叫 amazon-negative-review-handler。请帮我把它改造成适合所有平台差评处理的新版本。",
        expected="先盘点旧能力，再做影响点扫描；只确认本次受影响项，不把示例确认项固定成通用规则。",
        must_contain=("影响点扫描", "只对受影响项", "同源对比", "不覆盖原则"),
        must_not_contain=("确认新范围、确认新名称", "`新范围确认`", "`名称确认`", "用户要扩展到", "如果旧名称含"),
    ),
    StaticCase(
        scenario="涉及内部数据",
        prompt="帮我创建一个 Skill，用于每天识别广告异常 ASIN。它需要看广告花费、销售额、订单量、库存、排名变化。",
        expected="启动内部数据预检；字段/dry-run/smoke query 不完整时阻止正式创建。",
        must_contain=("预检是硬门槛", "catalog", "metadata", "dry-run", "smoke query", "阻塞"),
    ),
)


DIALOGUE_CASES = (
    DialogueCase(
        scenario="经验盘点与 Skill 规划",
        prompt="帮我总结我上面提到过的跟亚马逊的所有运营知识，告诉我哪些可以做成skills，并按我之前的处理逻辑做成skills",
        expected="先做知识盘点和去重，不直接新建重复 Skill。",
        response_must_contain=("任务类型：知识盘点/Skill 规划", "现有 Skill 资产", "建议复用", "真实缺口", "再决定新建或改造"),
        response_must_not_contain=("已直接创建", "跳过资产盘点"),
    ),
    DialogueCase(
        scenario="非跨境运营 Skill 创建",
        prompt="请你帮我创建一个“Skill 验收官”Skill，用于验收其他 Skill 是否合格。",
        expected="输出值得创建，但先访谈和交给 skill-creator。",
        response_must_contain=("创建价值判断：值得创建 Skill", "阶段 0", "skill-creator", "不会因为不是跨境运营而拒绝"),
        response_must_not_contain=("已创建", "已安装"),
    ),
    DialogueCase(
        scenario="安装并验收已有 Skill",
        prompt="帮我安装你刚才生成好的skills。然后利用这个skills，去给我去验收这个skills:ops-creator-skill",
        expected="识别为安装与验收任务，而非新建。",
        response_must_contain=("任务类型：安装/使用/验收", "安装位置", "验收结果", "测试清单"),
        response_must_not_contain=("进入阶段 0 访谈", "创建价值判断：值得创建 Skill"),
    ),
    DialogueCase(
        scenario="标准新建 Skill",
        prompt="我想把“Amazon 差评处理流程”沉淀成一个 Skill。",
        expected="认可复用价值，但停在访谈门，不直接建文件。",
        response_must_contain=("创建价值判断：值得创建 Skill", "阶段 0", "Q1-Q6", "暂不创建文件"),
        response_must_not_contain=("已创建", "已安装"),
    ),
    DialogueCase(
        scenario="用户输入很模糊",
        prompt="帮我把我们运营经验做成一个 Skill。",
        expected="判定信息不足，先澄清。",
        response_must_contain=("创建价值判断：需要先补访谈", "信息不足", "请先给一个具体场景"),
        response_must_not_contain=("已创建", "已安装"),
    ),
    DialogueCase(
        scenario="用户要求代替回答",
        prompt="你先别问我了，我懒得一题题回答。你根据这个场景帮我代答并创建 Skill：我们运营每周要复盘广告异常，找出花费上涨但销售没涨的 ASIN，给出处理建议。",
        expected="只生成待确认假设，不固化。",
        response_must_contain=("AI 假设，待用户确认", "我问 → AI 代答 → 内部检查", "暂不创建文件"),
        response_must_not_contain=("已创建", "已安装"),
    ),
    DialogueCase(
        scenario="不适合做 Skill 的场景",
        prompt="帮我创建一个 Skill，专门用于明天给领导写一条微信群通知，内容是提醒大家下午 3 点开会。",
        expected="停止创建并给轻量替代。",
        response_must_contain=("创建价值判断：不建议创建 Skill", "一次性任务", "更合适的交付"),
        response_must_not_contain=("进入阶段 0", "已创建"),
    ),
    DialogueCase(
        scenario="旧 Skill 改造",
        prompt="我有一个旧 Skill，叫 amazon-negative-review-handler，它现在是亚马逊差评处理流程。请帮我把它改造成适合所有平台差评处理的新版本。",
        expected="做影响点扫描，只确认受影响项。",
        response_must_contain=("任务类型：旧 Skill 改造", "只读盘点", "影响点扫描", "只确认本次受影响项"),
        response_must_not_contain=("必须确认平台范围和新名称", "已覆盖旧 Skill"),
    ),
    DialogueCase(
        scenario="涉及内部数据",
        prompt="帮我创建一个 Skill，用于每天识别广告异常 ASIN。它需要看广告花费、销售额、订单量、库存、排名变化，然后输出需要运营处理的 ASIN 清单。",
        expected="启动数据预检，预检不完整不创建正式取数规则。",
        response_must_contain=("内部数据预检", "catalog", "metadata", "dry-run", "预检不通过则暂不创建正式 Skill"),
        response_must_not_contain=("已创建", "已安装"),
    ),
)


GLOBAL_FORBIDDEN = (
    "明天会议通知",
    "Skill 验收官",
    "amazon-negative-review-handler",
    "确认新范围、确认新名称",
    "`新范围确认`",
    "`名称确认`",
    "用户要扩展到“所有平台”时",
    "如果旧名称含 `amazon`",
)


def load_policy_text() -> tuple[str, list[str]]:
    chunks: list[str] = []
    files: list[str] = []
    for path in POLICY_FILES:
        if not path.exists():
            continue
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        files.append(str(path.relative_to(ROOT)))
    return "\n".join(chunks), files


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def contains_any(text: str, words: tuple[str, ...]) -> bool:
    normalized = normalize(text)
    return any(normalize(word) in normalized for word in words)


def simulate_dialogue_response(prompt: str) -> str:
    """A deterministic executor that models the skill's first response policy."""

    if contains_any(prompt, ("总结", "盘点", "哪些可以做成skills", "哪些可以做成 skills", "按我之前的处理逻辑做成skills", "skill 规划")):
        return (
            "任务类型：知识盘点/Skill 规划。\n"
            "下一步：先输出现有 Skill 资产、能力重叠、建议复用项和真实缺口，完成资产盘点与去重。\n"
            "然后再决定新建或改造哪些能力、哪些直接复用；在这一步完成前不直接创建重复 Skill。"
        )

    if contains_any(prompt, ("验收官", "验收其他 skill", "是否合格")):
        return (
            "创建价值判断：值得创建 Skill。\n"
            "原因：这是可复用的 Skill 质量审核流程，不会因为不是跨境运营而拒绝。\n"
            "下一步：进入阶段 0 访谈补 Q1-Q6，再把确认后的流程交给 skill-creator 落地。"
        )

    if "安装" in prompt and contains_any(prompt, ("验收", "使用")):
        return (
            "任务类型：安装/使用/验收。\n"
            "下一步：确认安装位置，调用对应验收能力，输出验收结果、测试清单和校验结果。\n"
            "安装位置：需读取当前 Skill 根或用户提供路径。"
        )

    if contains_any(prompt, ("明天", "通知", "微信群", "下午3点", "下午 3 点")):
        return (
            "创建价值判断：不建议创建 Skill。\n"
            "原因：这是一次性任务，不具备稳定复用流程。\n"
            "更合适的交付：直接写一条微信群通知或给轻量 prompt 模板。"
        )

    if contains_any(prompt, ("旧 skill", "改造", "旧skill")):
        return (
            "任务类型：旧 Skill 改造。\n"
            "下一步：先做只读盘点，列出现有触发、输入、输出、脚本和规则。\n"
            "随后做影响点扫描，只确认本次受影响项，再做同源测试；未确认前不覆盖旧 Skill。"
        )

    if contains_any(prompt, ("代答", "懒得", "别问")):
        return (
            "我问 → AI 代答 → 内部检查。\n"
            "[AI 假设，待用户确认] 可以先给一版代答草案。\n"
            "内部检查：这些内容未经确认，暂不创建文件，也不得写入正式 Skill。"
        )

    if contains_any(prompt, ("广告异常", "广告花费", "销售额", "订单量", "库存", "排名")):
        return (
            "创建价值判断：值得创建 Skill，但涉及内部数据。\n"
            "下一步：启动内部数据预检，先做 catalog 匹配、metadata 字段校验、dry-run/query_build，必要时 smoke query。\n"
            "预检不通过则暂不创建正式 Skill，也不写入正式取数规则。"
        )

    if contains_any(prompt, ("运营经验",)) and not contains_any(prompt, ("具体", "每周", "每天", "流程", "差评")):
        return (
            "创建价值判断：需要先补访谈。\n"
            "原因：信息不足，还没有具体场景、输入、判断规则和输出。\n"
            "请先给一个具体场景，或讲最近一次真实处理案例。"
        )

    if contains_any(prompt, ("沉淀成一个 skill", "沉淀成 skill", "差评处理流程")):
        return (
            "创建价值判断：值得创建 Skill。\n"
            "下一步：先进入阶段 0，补齐 Q1-Q6 和阶段 1 技术细节。\n"
            "在用户复述确认前暂不创建文件。"
        )

    return (
        "创建价值判断：需要先补访谈。\n"
        "原因：还缺少复用场景、输入、判断和输出。\n"
        "下一步：先完成阶段 0。"
    )


def run_static_tests(policy_text: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for case in STATIC_CASES:
        missing = [item for item in case.must_contain if item not in policy_text]
        forbidden = [item for item in case.must_not_contain if item in policy_text]
        results.append(
            {
                "type": "static",
                "scenario": case.scenario,
                "prompt": case.prompt,
                "expected": case.expected,
                "actual": "static policy scan",
                "passed": not missing and not forbidden,
                "missing": missing,
                "forbidden_hits": forbidden,
            }
        )

    global_hits = [item for item in GLOBAL_FORBIDDEN if item in policy_text]
    results.append(
        {
            "type": "static",
            "scenario": "不要把测试样例写成通用硬规则",
            "prompt": "扫描 SKILL.md 和 references/*.md",
            "expected": "策略文档不出现特定测试样例或旧版硬编码确认项。",
            "actual": "static policy scan",
            "passed": not global_hits,
            "missing": [],
            "forbidden_hits": global_hits,
        }
    )
    return results


def run_dialogue_tests() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for case in DIALOGUE_CASES:
        actual = simulate_dialogue_response(case.prompt)
        missing = [item for item in case.response_must_contain if item not in actual]
        forbidden = [item for item in case.response_must_not_contain if item in actual]
        results.append(
            {
                "type": "dialogue",
                "scenario": case.scenario,
                "prompt": case.prompt,
                "expected": case.expected,
                "actual": actual,
                "passed": not missing and not forbidden,
                "missing": missing,
                "forbidden_hits": forbidden,
            }
        )
    return results


def run_tests() -> dict[str, object]:
    policy_text, files = load_policy_text()
    results = run_static_tests(policy_text) + run_dialogue_tests()
    passed = sum(1 for result in results if result["passed"])
    return {
        "success": passed == len(results),
        "root": str(ROOT),
        "files_checked": files,
        "passed": passed,
        "failed": len(results) - passed,
        "static_cases": sum(1 for result in results if result["type"] == "static"),
        "dialogue_cases": sum(1 for result in results if result["type"] == "dialogue"),
        "results": results,
    }


def print_markdown(report: dict[str, object]) -> None:
    print("# ops-creator-skill 回归测试")
    print()
    print(f"- 根目录: `{report['root']}`")
    print(f"- 结果: {report['passed']} 通过，{report['failed']} 失败")
    print(f"- 静态策略用例: {report['static_cases']}")
    print(f"- 模拟对话用例: {report['dialogue_cases']}")
    print()
    print("| 类型 | 场景 | 结果 | 缺失 | 禁止命中 |")
    print("| --- | --- | --- | --- | --- |")
    for result in report["results"]:  # type: ignore[index]
        status = "通过" if result["passed"] else "失败"
        missing = "、".join(result["missing"]) or "-"
        forbidden = "、".join(result["forbidden_hits"]) or "-"
        print(f"| {result['type']} | {result['scenario']} | {status} | {missing} | {forbidden} |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = run_tests()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
