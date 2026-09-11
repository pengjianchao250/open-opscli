from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    manifest_path = ROOT / "app.yaml"
    assert manifest_path.is_file(), "missing AppHub manifest: app.yaml"

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict), "app.yaml must contain a YAML object"
    assert manifest.get("apiVersion") == "apps.aukeys/v1"
    assert manifest.get("name") == "test-keepa"
    assert manifest.get("title") == "test-keepa"
    for unsupported_key in ("runtime", "python", "entrypoint"):
        assert unsupported_key not in manifest, (
            f"AppHub schema rejects unsupported app.yaml field: {unsupported_key}"
        )
    assert manifest.get("database") == {"kind": "sqlite", "path": "/data/app.db"}
    assert manifest.get("opscli", {}).get("auth_mode") == "viewer"
    assert manifest.get("access", {}).get("visibility") == "members"

    assert (ROOT / "backend" / "app.py").is_file(), "missing FastAPI entrypoint"
    assert (ROOT / "Dockerfile").is_file(), "missing AppHub Dockerfile"
    compose_path = ROOT / "compose.apphub.yaml"
    assert compose_path.is_file(), "missing AppHub managed Compose contract"
    assert (ROOT / ".dockerignore").is_file(), "missing Docker build exclusions"
    assert (ROOT / "nixpacks.toml").is_file(), "missing Nixpacks build config"
    assert (ROOT / "requirements.txt").is_file(), "missing Python requirements"
    assert (ROOT / "requirements-app.txt").is_file(), "missing Docker business requirements"
    assert (ROOT / "AGENTS.md").is_file(), "missing repository guidance"
    assert (ROOT / "backend" / "CLAUDE.md").is_file(), "missing backend guidance"
    assert (ROOT / "docs" / "apphub-contract.md").is_file(), "missing AppHub contract"

    frontend = ROOT / "frontend"
    assert (frontend / "package.json").is_file(), "missing frontend package manifest"
    assert (frontend / "package-lock.json").is_file(), "missing frontend lock file"
    assert (frontend / "vite.config.js").is_file(), "missing frontend Vite config"
    assert (frontend / "index.html").is_file(), "missing frontend entrypoint"

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY frontend/package.json frontend/package-lock.json" in dockerfile
    assert "WORKDIR /app/frontend" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "/app/frontend/dist" in dockerfile
    assert "COPY requirements-app.txt" in dockerfile
    assert "-r requirements-app.txt" in dockerfile
    assert "opscli.keepa.api.scenarios" in dockerfile
    assert "uvicorn" in dockerfile
    assert "/__apphub_healthz" in dockerfile

    compose = compose_path.read_text(encoding="utf-8")
    for required in (
        "APPHUB_APP_ID",
        "APPHUB_SQLITE_PATH",
        "subpath: apphub-databases/${APPHUB_APP_ID:?}",
        "PathPrefix(`/ops-app/${APPHUB_APP_ID:?}/${APP_SLUG:?}/`)",
        "Path(`/ops-app/${APPHUB_APP_ID:?}/${APP_SLUG:?}/__apphub_healthz`)",
        "apphub.route_contract=root-v1",
    ):
        assert required in compose

    nixpacks = (ROOT / "nixpacks.toml").read_text(encoding="utf-8")
    assert "npm --prefix frontend ci" in nixpacks
    assert "npm --prefix frontend run build" in nixpacks
    assert "opscli.keepa.api.scenarios" in nixpacks
    assert "opscli.mcp.tools.keepa" in nixpacks


if __name__ == "__main__":
    main()
