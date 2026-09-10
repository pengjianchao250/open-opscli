"""站点本地绑定文件读写。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from opscli.app.domain.constants import BINDING_RELATIVE_PATH
from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding


class BindingStore:
    def prepare_root(self, path: str | Path) -> Path:
        root = Path(path).expanduser().resolve()
        if root.exists() and not root.is_dir():
            raise AppProjectError("APP-PATH-INVALID", f"绑定路径不是目录：{root}")
        return root

    def save(self, path: str | Path, binding: SiteBinding) -> Path:
        """原子保存当前 schema 的绑定，不覆盖损坏或不同应用的历史文件。"""
        binding = SiteBinding.from_dict(binding.to_dict())
        root = self.prepare_root(path)
        root.mkdir(parents=True, exist_ok=True)
        target = root / BINDING_RELATIVE_PATH
        if target.exists():
            current = self.load(root)
            if current.app_id != binding.app_id:
                raise AppProjectError(
                    "APP-ALREADY-BOUND",
                    f"目录已绑定其他应用：{current.app_name} ({current.app_id})",
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"app-{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(binding.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(target)
        return target

    def load(self, path: str | Path) -> SiteBinding:
        root = self.prepare_root(path)
        target = root / BINDING_RELATIVE_PATH
        if not target.is_file():
            raise AppProjectError(
                "APP-NOT-BOUND",
                f"未找到应用绑定文件：{target}",
                fix_hint="执行 opscli app init --app-id <app_id> 恢复绑定，或 app create 创建新应用。",
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppProjectError("APP-BINDING-INVALID", f"应用绑定文件读取失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise AppProjectError("APP-BINDING-INVALID", "应用绑定文件顶层必须是 JSON 对象。")
        return SiteBinding.from_dict(payload)

    def is_bound(self, path: str | Path) -> bool:
        root = self.prepare_root(path)
        return (root / BINDING_RELATIVE_PATH).is_file()

    def has_source_files(self, path: str | Path) -> bool:
        root = self.prepare_root(path)
        if not root.exists():
            return False
        return any(item.name not in {".git", ".opscli"} for item in root.iterdir())

    def prepare_creation(self, root: Path, payload: dict, *, scope: str) -> dict:
        """发送请求前持久化唯一创建意图；同目录重试必须保持账号、环境和声明一致。"""
        target = root / ".opscli" / "creation.json"
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        state = {"key": str(uuid4()), "request_hash": digest, "scope": scope, "completed": False}
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # 排他创建防止两个进程为同一目录发送不同键；部分写入会拒绝重试。
            with target.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            try:
                state = json.loads(target.read_text(encoding="utf-8"))
                UUID(state["key"])
                if not isinstance(state["completed"], bool):
                    raise ValueError("invalid completed")
            except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise AppProjectError("APP-CREATE-INVALID", "创建记录损坏，请核对原应用 ID 后显式恢复。") from exc
            if state.get("scope") != scope or state.get("request_hash") != digest:
                raise AppProjectError(
                    "APP-CREATE-CONFLICT", "此目录已有不同账号、环境或内容的创建请求。",
                    fix_hint="重试时使用原账号、环境和名称；创建另一应用请使用独立目录。",
                )
            if state["completed"]:
                raise AppProjectError(
                    "APP-NOT-BOUND", f"此目录已完成创建：{state.get('app_id')}。",
                    fix_hint="使用 opscli app init --app-id <app_id> 恢复，不能再次创建。",
                )
        return state

    def complete_creation(self, root: Path, state: dict, app_id: str) -> None:
        """绑定落盘后标记创建完成，保留 ID 供丢失绑定时恢复。"""
        target = root / ".opscli" / "creation.json"
        temporary = target.with_name(f"creation-{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(
            {**state, "completed": True, "app_id": app_id}, ensure_ascii=False, indent=2,
        ) + "\n", encoding="utf-8")
        temporary.replace(target)
