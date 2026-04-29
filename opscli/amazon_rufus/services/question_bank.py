"""默认题库读取服务。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.amazon_rufus.domain.exceptions import QuestionBankNotReadyError
from opscli.amazon_rufus.domain.models import Question, QuestionTemplate


class QuestionBankService:
    """从已安装 Skill 中读取合并后的默认题目模板。"""

    def __init__(self, skills_dir: str | None = None) -> None:
        self.skills_dir = Path(skills_dir).expanduser() if skills_dir else None

    def load_templates(self) -> list[QuestionTemplate]:
        """读取并校验 question_templates.json。"""
        path = self._resolve_question_templates_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise self._not_ready() from exc
        except json.JSONDecodeError as exc:
            raise QuestionBankNotReadyError(f"题库 JSON 格式错误: {path}") from exc

        items = payload.get("items")
        if not isinstance(items, list):
            raise QuestionBankNotReadyError("题库格式错误：缺少 items 列表")
        templates = [self._parse_template(item) for item in items]
        question_count = sum(len(template.questions) for template in templates)
        if question_count == 0:
            raise QuestionBankNotReadyError("题库为空，请执行 `opscli skills upgrade ops-amazon-rufus` 同步默认题库")
        return templates

    def _resolve_question_templates_path(self) -> Path:
        """解析题库文件路径。"""
        if self.skills_dir:
            return self.skills_dir / "ops-amazon-rufus" / "data" / "question_templates.json"
        return Path.cwd() / ".agents" / "skills" / "ops-amazon-rufus" / "data" / "question_templates.json"

    def _parse_template(self, item: dict) -> QuestionTemplate:
        """解析单个模板。"""
        questions = [self._parse_question(q) for q in item.get("questions", []) if isinstance(q, dict)]
        questions.sort(key=lambda q: q.position)
        return QuestionTemplate(
            id=int(item.get("id", 0)),
            description=str(item.get("description", "")),
            preferred_version_index=int(item.get("preferred_version_index", 0)),
            questions=questions,
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
        )

    def _parse_question(self, item: dict) -> Question:
        """解析单个题目。"""
        return Question(
            id=int(item.get("id", 0)),
            text=str(item.get("text", "")),
            position=int(item.get("position", 0)),
        )

    def _not_ready(self) -> QuestionBankNotReadyError:
        """构造可操作的缺失题库错误。"""
        return QuestionBankNotReadyError(
            "题库未就绪，请先执行 `opscli skills install ops-amazon-rufus`，"
            "再执行 `opscli skills upgrade ops-amazon-rufus`"
        )
