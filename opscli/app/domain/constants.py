"""`opscli app` 使用的稳定常量。"""

APPHUB_API_PREFIX = "/api/v1"

MCP_REST_API_BASE_URL_ENV_KEY = "OPSCLI_MCP_REST_API_BASE_URL"
MCP_REST_API_BASE_URL_BY_APPHUB_ORIGIN = {
    "https://apphub.qa.aukeyit.com": "https://mcp.ops.aukeyit.com",
    "https://apphub.xenkee.com": "https://ops.mcp.xenkee.com",
}

BINDING_SCHEMA_VERSION = 4
BINDING_RELATIVE_PATH = ".opscli/app.json"
GIT_DEFAULT_BRANCH = "master"
GIT_MIN_VERSION = (2, 30, 0)
MESSAGE_MAX_LENGTH = 512
