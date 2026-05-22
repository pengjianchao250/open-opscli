"""Skill 使用次数异步上报模块。

CLI 每次调用一个 Skill 后调用 UsageReporter.record()，将记录追加到本地
队列文件（~/.opscli/usage_queue.jsonl），满足以下任一条件时在后台线程
批量上报至服务端，对 CLI 主流程完全无感知：

- 队列积累 >= BATCH_SIZE 条
- 距上次上报 >= FLUSH_INTERVAL_SECONDS 秒
- atexit 钩子（CLI 正常退出时）
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_logger = logging.getLogger("opscli.skills.marketplace.usage_reporter")

QUEUE_FILE = Path.home() / ".opscli" / "usage_queue.jsonl"
STATE_FILE  = Path.home() / ".opscli" / "usage_reporter_state.json"

BATCH_SIZE = 10
FLUSH_INTERVAL_SECONDS = 300   # 5 分钟
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_flush_at": 0}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception as exc:
        _logger.debug("保存 reporter 状态失败: %s", exc)


def _queue_size() -> int:
    try:
        if not QUEUE_FILE.exists():
            return 0
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _pop_all_records() -> list[dict]:
    """原子读取并清空队列文件，返回所有记录。"""
    records: list[dict] = []
    with _LOCK:
        if not QUEUE_FILE.exists():
            return records
        try:
            lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
            QUEUE_FILE.write_text("", encoding="utf-8")  # 清空
        except Exception as exc:
            _logger.debug("读取队列失败: %s", exc)
            return records
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def _do_flush() -> None:
    """实际执行上报，供后台线程和 atexit 共同调用。"""
    records = _pop_all_records()
    if not records:
        return

    try:
        from opscli.skills.marketplace.client import MarketplaceClient
        client = MarketplaceClient()
        result = client.batch_usage(records)
        _logger.debug("使用上报完成: %s", result)
    except Exception as exc:
        # 上报失败：把记录写回队列末尾，下次再试
        _logger.debug("使用上报失败，记录回写: %s", exc)
        try:
            with _LOCK:
                QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(QUEUE_FILE, "a", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return

    _save_state({"last_flush_at": time.time()})


def _flush_background() -> None:
    """在守护线程中执行上报，不阻塞 CLI 主流程。"""
    t = threading.Thread(target=_do_flush, daemon=True, name="usage-reporter")
    t.start()


def _should_flush() -> bool:
    size = _queue_size()
    if size >= BATCH_SIZE:
        return True
    if size > 0:
        state = _load_state()
        elapsed = time.time() - state.get("last_flush_at", 0)
        if elapsed >= FLUSH_INTERVAL_SECONDS:
            return True
    return False


# atexit：CLI 正常退出时同步上报（守护线程可能来不及执行）
atexit.register(_do_flush)


class UsageReporter:
    """Skill 使用次数上报器（单例安全，线程安全写入）。"""

    def record(self, identifier: str, client_id: str | None = None) -> None:
        """记录一次技能调用，写入本地队列，满足条件时后台上报。

        Args:
            identifier: Skill 标识符，如 pengjianchao@ops-auth
            client_id:  客户端机器 ID，可选
        """
        entry = {
            "identifier": identifier,
            "used_at":    _now_iso(),
            "client_id":  client_id or _get_client_id(),
        }
        try:
            with _LOCK:
                QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(QUEUE_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            _logger.debug("写入使用队列失败: %s", exc)
            return

        if _should_flush():
            _flush_background()


def _get_client_id() -> str:
    """获取或生成本机唯一客户端 ID，持久化到 ~/.opscli/client_id。"""
    id_file = Path.home() / ".opscli" / "client_id"
    try:
        if id_file.exists():
            return id_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    import hashlib
    import socket
    raw = f"{socket.gethostname()}-{os.getpid()}-{time.time()}"
    client_id = hashlib.sha1(raw.encode()).hexdigest()[:16]
    try:
        id_file.parent.mkdir(parents=True, exist_ok=True)
        id_file.write_text(client_id, encoding="utf-8")
    except Exception:
        pass
    return client_id


# 全局单例
_reporter = UsageReporter()


def get_reporter() -> UsageReporter:
    return _reporter
