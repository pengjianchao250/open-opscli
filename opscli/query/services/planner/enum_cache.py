"""组件枚举值本地磁盘缓存：TTL 24 小时，供网络枚举超时/失败时降级兜底（内核版）。

背景：规划器的组件权限枚举经注入的 enum_fn 发起一次同步 HTTP 调用，网络抖动
或服务端短暂不可用时若无兜底，会直接 fail-closed 阻断所有依赖枚举的查询。
引入本地缓存后，失败时优先尝试用近 24 小时内的历史枚举值兜底，只有缓存也
未命中时才维持现行的 fail-closed 行为——不改变"无兜底"场景下的安全性，
只是新增一条恢复路径；调用方命中缓存后必须在披露文案里如实标注"来自缓存"，
不得当作实时结果静默使用。

缓存文件与 Skill 版 ~/.config/opscli/enum_cache/ 同址：内核侧可以合法依赖
opscli.config（铁律2允许的依赖方向），直接复用 CONFIG_DIR 拼路径。除
`_cache_dir()` 的实现方式外与 Skill 版
（opscli/skills/templates/ops-dataset-query/scripts/enum_cache.py）完全
一致（双份同步铁律）。

base_dir 参数用于测试隔离（照搬 metadata_cache.py 的约定）：CLI/MCP 生产路径
不传，默认落在 CONFIG_DIR；测试传入 tmp_path，避免读写真实
~/.config/opscli/（铁律8：测试不依赖真实网络/系统 Keychain/真实用户目录）。

任何文件 IO/JSON 异常都必须静默返回 None / 放弃写入——缓存是可选的
可用性优化，绝不能因为缓存自身故障而拖累或阻断主查询流程。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from opscli.config import CONFIG_DIR

# TTL 24 小时：总纲已确定的默认值，过期缓存一律视为不存在
_TTL_SECONDS = 24 * 60 * 60

# 文件名安全化：table_id / field_name 理论上可能含路径分隔符等特殊字符，
# 只保留字母数字、下划线、连字符与中文，其余一律替换为下划线，避免路径穿越。
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_\-一-鿿]")


def _cache_dir(base_dir: Path | None = None) -> Path:
    """缓存根目录：base_dir 未传时用 CONFIG_DIR（与 Skill 版落地同一路径）。"""
    base = Path(base_dir) if base_dir else CONFIG_DIR
    return base / "enum_cache"


def _safe_key_part(value: object) -> str:
    """把 table_id / field_name 中的非常规字符替换成下划线，避免路径穿越或非法文件名。"""
    text = str(value).strip()
    return _UNSAFE_CHARS_RE.sub("_", text) or "_"


def _cache_path(table_id: object, field_name: str, base_dir: Path | None = None) -> Path:
    """按 (table_id, field_name) 拼出缓存文件路径。"""
    filename = f"{_safe_key_part(table_id)}_{_safe_key_part(field_name)}.json"
    return _cache_dir(base_dir) / filename


def _read_entry(table_id: object, field_name: str, base_dir: Path | None = None) -> dict | None:
    """读取未过期的缓存条目；任何异常（不存在/损坏/字段缺失/已过期）都返回 None。"""
    path = _cache_path(table_id, field_name, base_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(payload["fetched_at"])
        values = payload["values"]
        if not isinstance(values, list):
            return None
        if time.time() - fetched_at > _TTL_SECONDS:
            return None  # 过期视为不存在，交由调用方走现行失败路径
        return {"values": [str(item) for item in values], "fetched_at": fetched_at}
    except Exception:  # noqa: BLE001 缓存故障绝不能阻断主查询流程
        return None


def get(table_id: object, field_name: str, *, base_dir: Path | None = None) -> list[str] | None:
    """读取 TTL 24h 内的枚举缓存值；未命中/已过期/损坏均返回 None。"""
    entry = _read_entry(table_id, field_name, base_dir)
    return entry["values"] if entry else None


def get_age_hours(
    table_id: object, field_name: str, *, base_dir: Path | None = None
) -> float | None:
    """返回缓存距今的小时数，供降级披露文案标注"来自 N 小时前缓存"；未命中返回 None。"""
    entry = _read_entry(table_id, field_name, base_dir)
    if entry is None:
        return None
    return (time.time() - entry["fetched_at"]) / 3600


def put(
    table_id: object, field_name: str, values: list, *, base_dir: Path | None = None
) -> None:
    """原子写入枚举缓存（tempfile + os.replace）。空值不写入；任何 IO 异常静默吞掉。"""
    if not values:
        return
    try:
        cache_dir = _cache_dir(base_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(table_id, field_name, base_dir)
        payload = {"values": [str(item) for item in values], "fetched_at": time.time()}
        fd, tmp_name = tempfile.mkstemp(dir=cache_dir, prefix=".enum_cache_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp_name, path)
        except Exception:  # noqa: BLE001 写入失败不阻断主流程，清理临时文件即可
            try:
                os.remove(tmp_name)
            except OSError:
                pass
    except Exception:  # noqa: BLE001 目录创建等失败同样静默吞掉
        pass
