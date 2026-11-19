"""Provider auth & fingerprint adapters.

Different model providers behind the harness require different *client identities*:
  - OpenCode Go: rewards a stable x-opencode-session (session affinity) and rejects requests without one.
  - GitHub Copilot: no static API key. A GitHub OAuth token must be exchanged for a short-lived
    Copilot token; requests must carry a VS Code Chat client fingerprint (User-Agent / Editor-Version /
    Copilot-Integration-Id) plus X-Initiator + Openai-Intent dynamic headers.
  - Google AI: OpenAI-compatible endpoint; Bearer key or x-goog-api-key.

Everything is resolved at request time so tokens can refresh without restarting the gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any

import httpx

# Fingerprint taken from the reference client (VS Code Chat). Providers gate on these.
COPILOT_FINGERPRINT: dict[str, str] = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
    "Accept": "application/json",
}

COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_DEFAULT_BASE = "https://api.githubcopilot.com"

GOOGLE_UA = "harness-router/0.3 (google-generative-language)"


def secrets_dir() -> Path:
    return Path(os.getenv("HARNESS_SECRETS_DIR", "/app/.secrets"))


def _strip(v: str | None) -> str | None:
    return v.strip().strip('"').strip("'") if v else v


def copilot_credentials_path() -> Path:
    return secrets_dir() / "github-copilot.json"


def load_copilot_credentials() -> dict[str, Any] | None:
    """Credentials are written by start_harness.ps1 / `python -m proxy_gateway.provider_auth login`."""
    path = copilot_credentials_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if data.get("github") or data.get("refresh") else None


def save_copilot_credentials(github_token: str) -> Path:
    path = copilot_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"github": github_token}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


@dataclass
class CopilotToken:
    token: str
    expires_at: datetime
    base_url: str


class CopilotAuth:
    """Exchanges a GitHub token for a Copilot token, caching until expiry."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._cache: CopilotToken | None = None
        self._transport = transport

    def _github_token(self) -> str | None:
        for var in ("HARNESS_COPILOT_GITHUB_TOKEN", "GITHUB_COPILOT_TOKEN", "GITHUB_TOKEN"):
            val = _strip(os.getenv(var))
            if val:
                return val
        creds = load_copilot_credentials()
        if creds:
            return _strip(creds.get("github") or creds.get("refresh"))
        return None

    def token(self) -> CopilotToken | None:
        now = datetime.now(timezone.utc)
        if self._cache and now < self._cache.expires_at - timedelta(seconds=60):
            return self._cache
        gh = self._github_token()
        if not gh:
            return None
        try:
            with httpx.Client(transport=self._transport, timeout=20) as client:
                resp = client.get(COPILOT_TOKEN_URL, headers={**COPILOT_FINGERPRINT, "Authorization": f"Bearer {gh}"})
            if resp.status_code != 200:
                return None
            data = resp.json()
            raw_token = str(data.get("token") or "")
            expires = int(data.get("expires_at") or 0)
            if not raw_token or not expires:
                return None
        except (httpx.HTTPError, ValueError):
            return None
        self._cache = CopilotToken(
            token=raw_token,
            expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
            base_url=_base_url_from_token(raw_token),
        )
        return self._cache

    def headers(self, body: dict[str, Any] | None = None) -> dict[str, str]:
        tok = self.token()
        hdrs = dict(COPILOT_FINGERPRINT)
        if tok:
            hdrs["Authorization"] = f"Bearer {tok.token}"
        hdrs.update(copilot_dynamic_headers(body or {}))
        return hdrs

    def base_url(self) -> str | None:
        tok = self.token()
        return tok.base_url if tok else None


def _base_url_from_token(token: str) -> str:
    """Copilot tokens embed `proxy-ep=proxy.<host>`; the API host is the same with `api.` prefix."""
    for part in token.split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "proxy-ep" and value:
            host = value.strip().replace("proxy.", "api.", 1)
            return f"https://{host}"
    return COPILOT_DEFAULT_BASE


def _last_role(messages: list[dict[str, Any]]) -> str:
    return str(messages[-1].get("role", "user")) if messages else "user"


def copilot_dynamic_headers(body: dict[str, Any]) -> dict[str, str]:
    messages = body.get("messages") or []
    headers = {
        "X-Initiator": "user" if _last_role(messages) == "user" else "agent",
        "Openai-Intent": "conversation-edits",
    }
    has_image = any(
        isinstance(m.get("content"), list)
        and any(isinstance(p, dict) and p.get("type") in ("image_url", "input_image") for p in m["content"])
        for m in messages
        if isinstance(m, dict)
    )
    if has_image:
        headers["Copilot-Vision-Request"] = "true"
    return headers


def google_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "x-goog-api-key": api_key,
        "User-Agent": GOOGLE_UA,
    }


_COPILOT = CopilotAuth()


def copilot_auth() -> CopilotAuth:
    return _COPILOT


# --------------------------------------------------------------------------------------
# Device-flow login (same flow Pi uses): github.com/login/device/code -> poll access_token
# --------------------------------------------------------------------------------------
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"  # VS Code Chat / GitHub Copilot public client id
GITHUB_SCOPE = "read:user"


def device_login(poll_interval: int = 5, timeout_sec: int = 900, out=None) -> str:
    """Interactive device flow; prints the verification URL, returns and stores the GitHub token."""
    import time
    import sys

    out = out or sys.stdout
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            GITHUB_DEVICE_CODE_URL,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": COPILOT_FINGERPRINT["User-Agent"]},
            data={"client_id": GITHUB_CLIENT_ID, "scope": GITHUB_SCOPE},
        )
        resp.raise_for_status()
        data = resp.json()
        device_code = data["device_code"]
        interval = max(1, int(data.get("interval", poll_interval)))
        print(f"Open: {data['verification_uri']}\nCode: {data['user_code']}", file=out, flush=True)

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(interval)
            poll = client.post(
                GITHUB_ACCESS_TOKEN_URL,
                headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": COPILOT_FINGERPRINT["User-Agent"]},
                data={"client_id": GITHUB_CLIENT_ID, "device_code": device_code,
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
            )
            payload = poll.json()
            token = payload.get("access_token")
            if token:
                save_copilot_credentials(token)
                print("Stored credentials for GitHub Copilot.", file=out, flush=True)
                return token
            if payload.get("error") not in ("authorization_pending", "slow_down"):
                raise RuntimeError(f"device flow failed: {payload}")
    raise TimeoutError("device flow timed out")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "login":
        device_login()
    elif len(sys.argv) > 1 and sys.argv[1] == "check":
        tok = copilot_auth().token()
        print("copilot token:", "ok" if tok else "unavailable",
              "| base:", tok.base_url if tok else "-",
              "| expires:", tok.expires_at.isoformat() if tok else "-")
    else:
        print("usage: python -m proxy_gateway.provider_auth [login|check]")
