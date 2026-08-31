from __future__ import annotations

import json

import opscli.telemetry.mysql_writer as writer


class FakeCursor:
    def __init__(self):
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((" ".join(sql.split()), params))


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def test_write_event_persists_normalized_dimensions(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setenv("OPSCLI_MCP_TELEMETRY_MYSQL_ENABLED", "true")
    monkeypatch.setenv("OPSCLI_COLLECTION_MYSQL_HOST", "mysql.internal")
    monkeypatch.setenv("OPSCLI_COLLECTION_MYSQL_DATABASE", "polaris_ops_mcp")
    monkeypatch.setenv("OPSCLI_COLLECTION_MYSQL_USER", "writer")
    monkeypatch.setenv("OPSCLI_COLLECTION_MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("OPSCLI_MCP_TELEMETRY_MYSQL_AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setattr(writer, "_connect", lambda settings: connection)
    writer._schema_ready.clear()

    assert writer.write_event(
        {
            "event_type": "mcp_tool",
            "module": "seller_sprite",
            "command": "seller_sprite_run",
            "status": "error",
            "error_type": "QUOTA_EXCEEDED",
            "duration_ms": 123,
            "user_email": "user@example.com",
            "timestamp": "2026-08-21T00:00:00Z",
            "dimensions": {
                "schema_version": 1,
                "service": "seller_sprite",
                "operation": "seller_sprite_run",
                "endpoint": "/v1/keyword-reverse",
                "scenario": "keyword-reverse",
                "runtime_role": "executor",
                "site": "US",
            },
            "raw_payload": None,
        }
    )

    assert connection.committed is True
    assert connection.closed is True
    insert = next(
        params
        for sql, params in connection.cursor_obj.executions
        if sql.startswith("INSERT INTO mcp_call_events")
    )
    assert insert[2:15] == (
        "user@example.com",
        "seller_sprite",
        "seller_sprite_run",
        "/v1/keyword-reverse",
        "keyword-reverse",
        "executor",
        "US",
        None,
        None,
        "called",
        None,
        123,
        None,
    )
    assert json.loads(insert[15])['scenario'] == "keyword-reverse"


def test_write_event_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPSCLI_MCP_TELEMETRY_MYSQL_ENABLED", raising=False)
    monkeypatch.delenv("OPSCLI_COLLECTION_STORAGE_ENABLED", raising=False)
    monkeypatch.setattr(
        writer,
        "_connect",
        lambda settings: (_ for _ in ()).throw(AssertionError("must not connect")),
    )
    assert writer.write_event({"event_type": "mcp_tool"}) is False
