"""系统注册表模块。

管理三类系统来源：
- builtin：内置系统（ops/polaris），代码硬编码，不可删除（铁律9）
- local：用户手动添加的系统，持久化到 systems.json
- ops_sync：从运营系统后端同步的系统列表

系统合并优先级：local/ops_sync > builtin（同别名时用户配置覆盖内置）。
"""
import json
import stat
from pathlib import Path
from opscli.auth.exceptions import SystemNotFoundError


class SystemRegistry:
    """系统注册表，管理内置、本地和远端同步的系统实例。"""

    def __init__(self, base_dir: Path | None = None, builtin_systems: list | None = None):
        """
        Args:
            base_dir: 配置存储目录，默认使用 CONFIG_DIR（~/.config/opscli/）
            builtin_systems: 内置系统列表（由 auth/config.py 的 get_builtin_systems() 提供）
        """
        from opscli.config import CONFIG_DIR
        base = Path(base_dir or CONFIG_DIR)
        base.mkdir(parents=True, exist_ok=True)
        if base_dir is not None:
            base.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self._path = base / "systems.json"
        # 内置系统以 alias 为 key 构建字典，方便快速查找和去重
        self._builtin = {s["alias"]: s for s in (builtin_systems or [])}

    def _load(self) -> list:
        """从 systems.json 加载用户自定义和远端同步的系统列表。"""
        return json.loads(self._path.read_text()) if self._path.exists() else []

    def _save(self, systems: list):
        """将系统列表持久化到 systems.json。"""
        self._path.write_text(json.dumps(systems, ensure_ascii=False, indent=2))
        self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def list_all(self) -> list:
        """返回所有系统（内置 + 用户配置），同别名时用户配置覆盖内置。"""
        stored = {s["alias"]: s for s in self._load()}
        # 合并策略：先 builtin 再 stored，stored 的同名项会覆盖 builtin
        return list({**self._builtin, **stored}.values())

    def get(self, alias: str) -> dict:
        """按别名查找系统，找不到则抛出 SystemNotFoundError。"""
        for s in self.list_all():
            if s["alias"] == alias:
                return s
        raise SystemNotFoundError(f"系统 '{alias}' 未注册")

    def add_local(self, alias: str, system_key: str, url: str,
                  token_endpoint: str = "/api/auth/cli-token"):
        """添加或更新用户自定义系统（source=local）。

        如果同别名已存在，执行替换（upsert 语义）。
        """
        # 先移除同别名旧记录，再追加新记录
        systems = [s for s in self._load() if s["alias"] != alias]
        systems.append({
            "alias": alias,
            "system_key": system_key,
            "url": url,
            "token_endpoint": token_endpoint,
            "source": "local",
        })
        self._save(systems)

    def remove(self, alias: str):
        """移除系统（仅限 local 类型，内置系统受保护不可删除）。"""
        if alias in self._builtin:
            raise SystemNotFoundError(f"内置系统 '{alias}' 不可删除")
        self._save([s for s in self._load() if s["alias"] != alias])

    def sync_from_ops(self, ops_systems: list):
        """从运营系统后端同步系统列表。

        合并策略：
        - 保留所有非 ops_sync 来源的系统（builtin/local 不受影响）
        - ops_sync 来源的系统以远端最新数据全量替换
        """
        existing = {s["alias"]: s for s in self._load()}
        # 保留所有非 ops_sync 的条目
        kept = {a: s for a, s in existing.items() if s.get("source") != "ops_sync"}
        # 用远端数据填充（不覆盖 local/builtin 的同名条目）
        for s in ops_systems:
            if s["alias"] not in kept:
                kept[s["alias"]] = {**s, "source": "ops_sync"}
        self._save(list(kept.values()))
