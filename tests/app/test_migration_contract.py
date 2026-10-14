"""源码复制迁移发布合同测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from opscli.app.services.migration_contract import (
    inspect_migration_public_paths,
    inspect_migration_release_assets,
)


def _write_base_project(root: Path, *, dockerfile: str, server: str) -> None:
    (root / "app.yaml").write_text(
        "apiVersion: apps.aukeys/v1\napp_id: Ab123\ntitle: 通用迁移项目\n",
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (root / "server.js").write_text(server, encoding="utf-8")
    (root / ".gitignore").write_text(".opscli/\n.env\n", encoding="utf-8")
    (root / ".dockerignore").write_text(".git\n.opscli\n.env\n", encoding="utf-8")


def test_generic_node_project_matches_apphub_release_gate(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is True
    assert result["detail"]["missing"] == []
    assert result["detail"]["violations"] == []


def test_release_gate_rejects_ignored_static_build_config_input(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )
    hosting = tmp_path / ".openai" / "hosting.json"
    hosting.parent.mkdir()
    hosting.write_text('{"d1": null}\n', encoding="utf-8")
    (tmp_path / "vite.config.ts").write_text(
        'import hostingConfig from "./.openai/hosting.json";\n'
        "export default hostingConfig;\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".opscli/\n.env\n.openai/\n", encoding="utf-8")

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is False
    assert result["detail"]["violations"] == [
        {
            "file": "vite.config.ts",
            "line": 1,
            "kind": "build_input_not_releasable",
            "value": ".openai/hosting.json",
            "reason": (
                "file is ignored by .gitignore and is not tracked; it will be absent "
                "from remote source"
            ),
        }
    ]


def test_release_gate_allows_present_static_build_config_input(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )
    (tmp_path / "hosting.json").write_text('{"d1": null}\n', encoding="utf-8")
    (tmp_path / "vite.config.ts").write_text(
        'import hostingConfig from "./hosting.json";\nexport default hostingConfig;\n',
        encoding="utf-8",
    )

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is True
    assert result["detail"]["violations"] == []


def test_release_gate_allows_optional_runtime_config_read(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )
    (tmp_path / "vite.config.ts").write_text(
        'import { readFileSync } from "node:fs";\n'
        "try { readFileSync(new URL(\"./.openai/hosting.json\", import.meta.url)); } "
        "catch {}\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(".opscli/\n.env\n.openai/\n", encoding="utf-8")

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is True
    assert result["detail"]["violations"] == []


def test_release_gate_rejects_untracked_static_build_config_input(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )
    (tmp_path / "hosting.json").write_text('{"d1": null}\n', encoding="utf-8")
    (tmp_path / "vite.config.ts").write_text(
        'import hostingConfig from "./hosting.json";\nexport default hostingConfig;\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "add",
            "app.yaml",
            "Dockerfile",
            ".dockerignore",
            ".gitignore",
            "server.js",
            "vite.config.ts",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is False
    assert result["detail"]["violations"] == [
        {
            "file": "vite.config.ts",
            "line": 1,
            "kind": "build_input_not_releasable",
            "value": "hosting.json",
            "reason": "file is not tracked by Git and will be absent from remote source",
        }
    ]


def test_release_gate_requires_docker_start_command(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile="FROM node:22-alpine\nWORKDIR /app\nCOPY . .\nEXPOSE 8000\n",
        server='const healthPath = "/__apphub_healthz";\n',
    )

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is False
    assert {item["kind"] for item in result["detail"]["violations"]} >= {
        "docker_start_command_missing"
    }


def test_release_gate_requires_apphub_health_route(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            'CMD ["node", "server.js"]\n'
        ),
        server='const port = Number(process.env.PORT || "8000");\n',
    )

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is False
    assert {item["kind"] for item in result["detail"]["violations"]} >= {
        "health_route_missing"
    }


def test_release_gate_rejects_unknown_app_yaml_field(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )
    with (tmp_path / "app.yaml").open("a", encoding="utf-8") as handle:
        handle.write("runtime: node\n")

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is False
    assert {item["kind"] for item in result["detail"]["violations"]} >= {
        "unknown_app_yaml_field"
    }


def test_sqlite_release_gate_requires_compose_file(tmp_path: Path) -> None:
    _write_base_project(
        tmp_path,
        dockerfile=(
            "FROM node:22-alpine\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            'CMD ["node", "server.js"]\n'
        ),
        server=(
            'const port = Number(process.env.PORT || "8000");\n'
            'const healthPath = "/__apphub_healthz";\n'
        ),
    )
    with (tmp_path / "app.yaml").open("a", encoding="utf-8") as handle:
        handle.write("database:\n  kind: sqlite\n  path: /data/app.db\n")

    result = inspect_migration_release_assets(tmp_path, expected_app_id="Ab123")

    assert result["ready"] is False
    assert "compose.apphub.yaml" in result["detail"]["missing"]


def test_vinext_generated_root_assets_fail_public_path_contract(tmp_path: Path) -> None:
    manifest = tmp_path / "dist" / "server" / "__vite_rsc_assets_manifest.js"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        'export default {bootstrapScriptContent: "import(\\"/_next/static/chunks/app.js\\")"};\n',
        encoding="utf-8",
    )

    result = inspect_migration_public_paths(tmp_path)

    assert result["ready"] is False
    assert result["reason"] == "root_relative_public_url"
    assert result["detail"]["generated_files"] == [
        "dist/server/__vite_rsc_assets_manifest.js"
    ]
    assert result["detail"]["violations"] == [
        {
            "file": "dist/server/__vite_rsc_assets_manifest.js",
            "line": 1,
            "kind": "generated_script_url",
            "value": "/_next/",
        }
    ]


def test_vinext_generated_dot_root_assets_fail_public_path_contract(tmp_path: Path) -> None:
    manifest = tmp_path / "dist" / "server" / "vinext-client-assets.js"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        'export default {appBootstrapPreinitModules: ["/./_next/static/chunks/app.js"]};\n',
        encoding="utf-8",
    )

    result = inspect_migration_public_paths(tmp_path)

    assert result["ready"] is False
    assert result["detail"]["violations"][0]["value"] == "/./_next/"


def test_vinext_generated_relative_assets_pass_public_path_contract(tmp_path: Path) -> None:
    manifest = tmp_path / "dist" / "server" / "__vite_rsc_assets_manifest.js"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        'export default {bootstrapScriptContent: "import(\\"./_next/static/chunks/app.js\\")"};\n',
        encoding="utf-8",
    )

    result = inspect_migration_public_paths(tmp_path)

    assert result["ready"] is True
    assert result["reason"] == "ready"
