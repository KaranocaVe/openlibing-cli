"""Helpers for parsing and deriving values from VS Code deep links."""

import os
from urllib.parse import parse_qs, unquote, urlparse


VSCODE_URI_ENV_MAP = {
    "OPENLIBING_SESSION_ID": "authTicket",
    "OPENLIBING_USER_ID": "userId",
    "OPENLIBING_DEFAULT_ENV_ID": "envId",
    "OPENLIBING_AUTH_TYPE": "authType",
}


def parse_vscode_uri(uri):
    """Parse a `vscode://.../connect?...` deep link.

    Tolerates URIs where the whole query string has been percent-encoded
    (e.g. `?authTicket%3DABC%26userId%3DXYZ` — common when the URL is
    captured from a redirected address bar).
    """
    parsed = urlparse(uri.strip())
    qs = parse_qs(parsed.query, keep_blank_values=True)
    result = {
        "authTicket": (qs.get("authTicket") or [None])[0],
        "userId": (qs.get("userId") or [None])[0],
        "envId": (qs.get("envId") or [None])[0],
        "authType": (qs.get("authType") or [None])[0],
    }
    if not any(result.values()) and parsed.query:
        decoded = unquote(parsed.query)
        if decoded != parsed.query:
            qs2 = parse_qs(decoded, keep_blank_values=True)
            result = {
                "authTicket": (qs2.get("authTicket") or [None])[0],
                "userId": (qs2.get("userId") or [None])[0],
                "envId": (qs2.get("envId") or [None])[0],
                "authType": (qs2.get("authType") or [None])[0],
            }
    return result


def populate_env_from_vscode_uri():
    """Derive env vars from OPENLIBING_VSCODE_URI when present."""
    uri = os.environ.get("OPENLIBING_VSCODE_URI")
    if not uri:
        return {}
    parsed = parse_vscode_uri(uri)
    derived = {}
    for env_name, key in VSCODE_URI_ENV_MAP.items():
        value = parsed.get(key)
        if not value:
            continue
        # When a deep link is present, treat it as the source of truth so
        # stale shell exports do not override the fresh callback values.
        os.environ[env_name] = value
        derived[env_name] = value
    return derived
