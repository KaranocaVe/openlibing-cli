"""Endpoint paths and base URLs for the CLI.

The repository only stores sanitized placeholder endpoints. Inject real
values through environment variables in local use.
"""

import os


def _env(name, default):
    return os.environ.get(name, default)

# Sanitized placeholder gateway path. Override locally with
# OPENLIBING_GATEWAY_PATH when you need the real upstream route.
GATEWAY_PATH = _env(
    "OPENLIBING_GATEWAY_PATH",
    "/resource-manager-gateway/vendor.resource:service/resource-manager",
)

# Base URL per environment. The checked-in defaults are safe placeholders.
ENVIRONMENTS = {
    "prod": _env("OPENLIBING_BASE_URL_PROD", "https://rm.example.com"),
    "beta": _env("OPENLIBING_BASE_URL_BETA", "https://rm-beta.example.com/api/beta"),
    "alpha": _env("OPENLIBING_BASE_URL_ALPHA", "https://rm-alpha.example.com/api/alpha"),
    "alpha_yellow": _env("OPENLIBING_BASE_URL_ALPHA_YELLOW", "https://rm-alpha-yellow.example.com"),
}

# Referer header per environment. The backend may validate this.
REFERERS = {
    "prod": _env("OPENLIBING_REFERER_PROD", "https://portal.example.com/"),
    "beta": _env("OPENLIBING_REFERER_BETA", "https://portal-beta.example.com/"),
    "alpha": _env("OPENLIBING_REFERER_ALPHA", "https://portal-alpha.example.com/"),
    "alpha_yellow": _env("OPENLIBING_REFERER_ALPHA_YELLOW", "https://portal-alpha-yellow.example.com/"),
}

# localIde API paths (suffix to GATEWAY_PATH).
API_CONNECT = "/localIde/connect"            # POST — uploads sshPublicKey, returns SSH info
API_CHECK_STATUS = "/localIde/checkStatus"   # GET  /{envId}
API_STOP = "/localIde/stop"                  # POST /{envId}
API_DELETE = "/localIde/delete"              # DELETE /{envId}
API_GET_STATUS = "/localIde/getStatus"       # GET  /{envId}  — for stop/delete polling
API_LIST = "/localIde/listDevEnv"            # GET
API_HAS_PERMISSION = "/localIde/hasPermission"  # GET

# Token endpoints.
API_REFRESH_TOKEN = "/hwaccount/refreshToken"   # GET  — exchange sessionId for refreshToken
API_ACCESS_TOKEN = "/hwaccount/accessToken"     # GET  — exchange refreshToken for new sessionId

# Default SSH key paths.
DEFAULT_SSH_DIR = "~/.ssh"
DEFAULT_KEY_NAME = "id_rsa"
DEFAULT_KEY_COMMENT = "resource-manager-cli"
