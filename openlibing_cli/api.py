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
    def __init__(self, base_url, session_id, environment="prod", refresh_token=None, on_tokens=None):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.environment = environment
        self.refresh_token = refresh_token
        self.on_tokens = on_tokens
        self._refresh_attempt_in_progress = False

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
        self._set_session_cookie(session_id)

    # -- low level --------------------------------------------------------

    def _url(self, path):
        return f"{self.base_url}{GATEWAY_PATH}{path}"

    def _set_session_cookie(self, session_id):
        self.session_id = session_id
        self.s.cookies.set("sessionId", session_id, domain="")

    def _persist_tokens(self):
        if self.on_tokens:
            self.on_tokens(self.session_id, self.refresh_token)

    def _request(self, method, url, *, retry_on_401=True, **kwargs):
        resp = self.s.request(method, url, **kwargs)
        if retry_on_401 and self._business_code(resp) == 401:
            if self._try_refresh_session():
                headers = dict(kwargs.get("headers") or {})
                if "Cookie" not in headers:
                    headers["Cookie"] = f"sessionId={self.session_id}"
                kwargs["headers"] = headers
                resp = self.s.request(method, url, **kwargs)
        return resp

    def _business_code(self, resp):
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError):
            return None
        if isinstance(data, dict):
            return data.get("code")
        return None

    def _try_refresh_session(self):
        if self._refresh_attempt_in_progress:
            return False
        self._refresh_attempt_in_progress = True
        try:
            if not self.refresh_token:
                refresh_data = self.get_refresh_token(retry_on_401=False)
                refresh_token = refresh_data.get("data")
                if not refresh_token:
                    return False
                self.refresh_token = refresh_token
                self._persist_tokens()
            new_session = self.refresh_access_token(self.refresh_token, retry_on_401=False)
            self._set_session_cookie(new_session)
            self._persist_tokens()
            return True
        except APIError:
            return False
        finally:
            self._refresh_attempt_in_progress = False

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
        return self._check(self._request("POST", url, json=body))

    def check_status(self, dev_env_id):
        """GET /localIde/checkStatus/{id} — returns full status + SSH info.

        Used both for polling and for `info` / `ssh-config` when you don't
        want the side effect of re-uploading the public key.
        """
        url = self._url(f"{API_CHECK_STATUS}/{dev_env_id}")
        log.info("GET %s", url)
        return self._check(self._request("GET", url))

    def stop(self, dev_env_id):
        url = self._url(f"{API_STOP}/{dev_env_id}")
        log.info("POST %s", url)
        return self._check(self._request("POST", url, json={}))

    def delete(self, dev_env_id):
        url = self._url(f"{API_DELETE}/{dev_env_id}")
        log.info("DELETE %s", url)
        return self._check(self._request("DELETE", url))

    def get_status(self, dev_env_id):
        url = self._url(f"{API_GET_STATUS}/{dev_env_id}")
        log.info("GET %s", url)
        return self._check(self._request("GET", url))

    def list_env(self):
        url = self._url(API_LIST)
        log.info("GET %s", url)
        return self._check(self._request("GET", url))

    def get_refresh_token(self, retry_on_401=True):
        url = self._url(API_REFRESH_TOKEN)
        log.info("GET %s", url)
        data = self._check(self._request("GET", url, retry_on_401=retry_on_401))
        refresh_token = data.get("data") if isinstance(data, dict) else None
        if refresh_token:
            self.refresh_token = refresh_token
            self._persist_tokens()
        return data

    def refresh_access_token(self, refresh_token, retry_on_401=True):
        """GET /hwaccount/accessToken, pass refresh token as sessionId cookie.

        The new sessionId is in the Set-Cookie response header.
        """
        url = self._url(API_ACCESS_TOKEN)
        log.info("GET %s (refresh)", url)
        resp = self._request(
            "GET",
            url,
            retry_on_401=retry_on_401,
            headers={"Cookie": f"sessionId={refresh_token}"},
        )
        self._check(resp)
        # The extension parses Set-Cookie to find sessionId=...
        set_cookie = resp.headers.get("set-cookie", "")
        for chunk in set_cookie.split(","):
            for part in chunk.split(";"):
                part = part.strip()
                if part.startswith("sessionId="):
                    return part.split("=", 1)[1]
        raise APIError("No sessionId in Set-Cookie header", body=resp.headers)
