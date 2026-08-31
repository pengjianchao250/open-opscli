"""AppHub 发布链使用的冻结常量。"""

from __future__ import annotations

import re

APPHUB_URL_DEFAULT = "https://ops.xenkee.com"
APPHUB_URL_ENV = "OPSCLI_APPHUB_URL"
APP_YAML_FILENAME = "app.yaml"
GIT_MIN_VERSION = (2, 30, 0)
GIT_DEFAULT_BRANCH = "main"
MESSAGE_MAX_LENGTH = 512
RUNTIMES_MVP = ("streamlit", "fastapi", "gradio")
RUNTIMES_PHASE2 = ("dash", "flask", "static")
RESERVED_SLUGS = frozenset({
    "login",
    "api",
    "static",
    "internal",
    "admin",
    "assets",
    "authz",
    "apphub",
    "healthz",
    "well-known",
    "apps",
    "ui",
    "datasette",
})
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")
DATASET_PATTERN = re.compile(r"^ds_[0-9a-f]{6,32}$")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
TERMINAL_STATUSES = frozenset({"healthy", "failed", "cancelled"})
CODEX_SITE_MARKERS = ("package.json", ".openai/hosting.json", "site.config.json")

