"""HTTP client for the upstream resource-manager backend."""

import json
import logging
import urllib3
import requests

from .constants import (
    GATEWAY_PATH,
    REFERERS,
    API_CONNECT,
    API_CHECK_STATUS,
    API_STOP,
    API_DELETE,
    API_GET_STATUS,
    API_LIST,
    API_REFRESH_TOKEN,
    API_ACCESS_TOKEN,
)

# Suppress the InsecureRequestWarning — the extension disables cert checks too.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)


class APIError(Exception):
    """A non-200 / business-code-non-200 response from the backend."""

    def __init__(self, message, *, code=None, body=None, status=None):
        super().__init__(message)
        self.code = code
        self.body = body
        self.status = status


class ResourceManagerAPI:
    def __init__(self, base_url, session_id, environment="prod"):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.environment = environment

        self.s = requests.Session()
        # The extension does process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0'.
        # Keep parity with the reverse-engineered client behavior. Users can
        # re-enable TLS verification in their own fork if their deployment
        # presents a trusted certificate chain.
        self.s.verify = False
        self.s.headers.update({
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",  # extension forces identity
            "Referer": REFERERS.get(environment, REFERERS["prod"]),
        })
        # The whole auth model is: Cookie: sessionId=<ticket>
        self.s.cookies.set("sessionId", session_id, domain="")

    # -- low level --------------------------------------------------------

    def _url(self, path):
        return f"{self.base_url}{GATEWAY_PATH}{path}"

    def _check(self, resp, allow_code=None):
        if resp.status_code != 200:
            raise APIError(
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
                body=resp.text,
            )
        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise APIError(
                f"Non-JSON response: {resp.text[:200]}",
                status=resp.status_code,
                body=resp.text,
            )
        # Business envelope: { code: 200, msg: "...", data: ... }
        if isinstance(data, dict) and "code" in data:
            if allow_code is not None:
                codes = allow_code if isinstance(allow_code, (list, tuple, set)) else {allow_code}
            else:
                codes = {200}
            if data["code"] not in codes:
                raise APIError(
                    f"{data.get('msg', 'unknown error')} (code: {data['code']})",
                    code=data["code"],
                    body=data,
                )
        return data

    # -- endpoints --------------------------------------------------------

    def connect(self, dev_env_id, ssh_public_key):
        """POST /localIde/connect — uploads pub key, returns SSH info.

        Mirrors `connectToEnvironment` in the extension. The backend will
        write the public key into the target's authorized_keys.
        """
        url = self._url(API_CONNECT)
        body = {"devEnvId": dev_env_id, "sshPublicKey": ssh_public_key}
        log.info("POST %s devEnvId=%s", url, dev_env_id)
        return self._check(self.s.post(url, json=body))

    def check_status(self, dev_env_id):
        """GET /localIde/checkStatus/{id} — returns full status + SSH info.

        Used both for polling and for `info` / `ssh-config` when you don't
        want the side effect of re-uploading the public key.
        """
        url = self._url(f"{API_CHECK_STATUS}/{dev_env_id}")
        log.info("GET %s", url)
        return self._check(self.s.get(url))

    def stop(self, dev_env_id):
        url = self._url(f"{API_STOP}/{dev_env_id}")
        log.info("POST %s", url)
        return self._check(self.s.post(url, json={}))

    def delete(self, dev_env_id):
        url = self._url(f"{API_DELETE}/{dev_env_id}")
        log.info("DELETE %s", url)
        return self._check(self.s.delete(url))

    def get_status(self, dev_env_id):
        url = self._url(f"{API_GET_STATUS}/{dev_env_id}")
        log.info("GET %s", url)
        return self._check(self.s.get(url))

    def list_env(self):
        url = self._url(API_LIST)
        log.info("GET %s", url)
        return self._check(self.s.get(url))

    def get_refresh_token(self):
        url = self._url(API_REFRESH_TOKEN)
        log.info("GET %s", url)
        return self._check(self.s.get(url))

    def refresh_access_token(self, refresh_token):
        """GET /hwaccount/accessToken, pass refresh token as sessionId cookie.

        The new sessionId is in the Set-Cookie response header.
        """
        url = self._url(API_ACCESS_TOKEN)
        log.info("GET %s (refresh)", url)
        resp = self.s.get(url, cookies={"sessionId": refresh_token})
        self._check(resp)
        # The extension parses Set-Cookie to find sessionId=...
        set_cookie = resp.headers.get("set-cookie", "")
        for chunk in set_cookie.split(","):
            for part in chunk.split(";"):
                part = part.strip()
                if part.startswith("sessionId="):
                    return part.split("=", 1)[1]
        raise APIError("No sessionId in Set-Cookie header", body=resp.headers)
