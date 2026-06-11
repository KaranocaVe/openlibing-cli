"""Endpoint paths and base URLs for the CLI.

The repository only stores sanitized placeholder endpoints. Inject real
values through environment variables in local use.
"""

import os
from pathlib import Path

from .vscode_uri import populate_env_from_vscode_uri


def _parse_dotenv_line(line):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        return None
    name, value = line.split("=", 1)
    name = name.strip()
    value = value.strip()
    if not name:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return name, value


def _dotenv_candidates():
    seen = set()
    roots = [Path.cwd().resolve(), Path(__file__).resolve().parent.parent]
    for root in roots:
        for parent in (root, *root.parents):
            candidate = parent / ".env"
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


def load_dotenv():
    override = os.environ.get("OPENLIBING_DOTENV")
    candidates = [Path(override).expanduser()] if override else _dotenv_candidates()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            parsed = _parse_dotenv_line(raw_line)
            if not parsed:
                continue
            name, value = parsed
            os.environ.setdefault(name, value)
        return str(candidate)
    return None


load_dotenv()
populate_env_from_vscode_uri()


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
