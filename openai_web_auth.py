import base64
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import threading
import time
from typing import Any, Dict, Optional

import requests

from config import OPENAI_WEB_AUTH_FILE, OPENAI_WEB_CALLBACK_PORT, OPENAI_WEB_CLIENT_ID, OPENAI_WEB_ISSUER, PROVIDER_REQUEST_TIMEOUT


class OpenAIWebAuthError(Exception):
    pass


class OpenAIWebAuthStore:
    CODEX_API_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

    def __init__(self):
        self.file_path = OPENAI_WEB_AUTH_FILE
        self._callback_server: Optional[socketserver.TCPServer] = None
        self._callback_thread: Optional[threading.Thread] = None
        self._ensure_storage()

    def _success_html(self) -> bytes:
        return b"""<!doctype html><html><head><title>OpenAI login complete</title><style>body{font-family:Arial,sans-serif;background:#0f172a;color:#e5e7eb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}.card{max-width:520px;padding:28px;border-radius:18px;border:1px solid #243041;background:#111827;text-align:center}h1{color:#10a37f}</style></head><body><div class='card'><h1>Login complete</h1><p>You can close this window and return to ia Profesor.</p></div><script>setTimeout(function(){window.close()},1200)</script></body></html>"""

    def _error_html(self, message: str) -> bytes:
        safe = (message or "Authentication failed").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<!doctype html><html><head><title>OpenAI login failed</title><style>body{{font-family:Arial,sans-serif;background:#0f172a;color:#e5e7eb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}.card{{max-width:520px;padding:28px;border-radius:18px;border:1px solid #243041;background:#111827;text-align:center}}h1{{color:#ef4444}}</style></head><body><div class='card'><h1>Login failed</h1><p>{safe}</p></div></body></html>".encode("utf-8")

    def _ensure_storage(self) -> None:
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            return {"version": 1, "pending": None, "token": None}
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, dict):
                payload.setdefault("version", 1)
                payload.setdefault("pending", None)
                payload.setdefault("token", None)
                return payload
        except Exception:
            pass
        return {"version": 1, "pending": None, "token": None}

    def _save(self, payload: Dict[str, Any]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)

    def _base64_url_encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")

    def _generate_pkce(self) -> Dict[str, str]:
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = self._base64_url_encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        return {"verifier": verifier, "challenge": challenge}

    def _generate_state(self) -> str:
        return self._base64_url_encode(secrets.token_bytes(32))

    def parse_jwt_claims(self, token: str) -> Optional[Dict[str, Any]]:
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None
        try:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
            payload = json.loads(decoded)
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def extract_account_id_from_claims(self, claims: Dict[str, Any]) -> Optional[str]:
        api_claims = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else None
        organizations = claims.get("organizations") if isinstance(claims, dict) else None
        if claims.get("chatgpt_account_id"):
            return claims["chatgpt_account_id"]
        if isinstance(api_claims, dict) and api_claims.get("chatgpt_account_id"):
            return api_claims["chatgpt_account_id"]
        if isinstance(organizations, list) and organizations:
            first = organizations[0]
            if isinstance(first, dict) and first.get("id"):
                return first["id"]
        return None

    def extract_account_id(self, token_payload: Dict[str, Any]) -> Optional[str]:
        for key in ("id_token", "access_token"):
            claims = self.parse_jwt_claims(token_payload.get(key, ""))
            if not claims:
                continue
            account_id = self.extract_account_id_from_claims(claims)
            if account_id:
                return account_id
        return None

    def extract_email(self, token_payload: Dict[str, Any]) -> str:
        for key in ("id_token", "access_token"):
            claims = self.parse_jwt_claims(token_payload.get(key, ""))
            if isinstance(claims, dict) and isinstance(claims.get("email"), str):
                return claims["email"]
        return ""

    def build_authorize_url(self, redirect_uri: str, challenge: str, state: str) -> str:
        params = requests.models.PreparedRequest()
        params.prepare_url(
            f"{OPENAI_WEB_ISSUER}/oauth/authorize",
            {
                "response_type": "code",
                "client_id": OPENAI_WEB_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "scope": "openid profile email offline_access",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
                "state": state,
                "originator": "opencode",
            },
        )
        return params.url or ""

    def _start_callback_server(self) -> str:
        if self._callback_server:
            return f"http://localhost:{OPENAI_WEB_CALLBACK_PORT}/auth/callback"

        store = self

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import parse_qs, urlparse

                parsed = urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not found")
                    return

                params = parse_qs(parsed.query)
                error = (params.get("error", [""])[0] or "").strip()
                error_description = (params.get("error_description", [""])[0] or error).strip()
                code = (params.get("code", [""])[0] or "").strip()
                state = (params.get("state", [""])[0] or "").strip()

                try:
                    if error:
                        raise OpenAIWebAuthError(error_description or error)
                    if not code or not state:
                        raise OpenAIWebAuthError("Missing authorization code or state")
                    store.complete_browser_login(code, state)
                    body = store._success_html()
                    self.send_response(200)
                except Exception as exc:
                    body = store._error_html(str(exc))
                    self.send_response(400)

                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        self._callback_server = ReusableTCPServer(("127.0.0.1", OPENAI_WEB_CALLBACK_PORT), CallbackHandler)
        self._callback_thread = threading.Thread(target=self._callback_server.serve_forever, daemon=True)
        self._callback_thread.start()
        return f"http://localhost:{OPENAI_WEB_CALLBACK_PORT}/auth/callback"

    def start_browser_login(self) -> Dict[str, str]:
        redirect_uri = self._start_callback_server()
        pkce = self._generate_pkce()
        state = self._generate_state()
        payload = self._load()
        payload["pending"] = {
            "state": state,
            "verifier": pkce["verifier"],
            "redirect_uri": redirect_uri,
            "created_at": int(time.time()),
        }
        self._save(payload)
        return {
            "authorize_url": self.build_authorize_url(redirect_uri, pkce["challenge"], state),
            "state": state,
            "redirect_uri": redirect_uri,
        }

    def _exchange_code_for_tokens(self, code: str, redirect_uri: str, verifier: str) -> Dict[str, Any]:
        response = requests.post(
            f"{OPENAI_WEB_ISSUER}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": OPENAI_WEB_CLIENT_ID,
                "code_verifier": verifier,
            },
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        if not response.ok:
            raise OpenAIWebAuthError(f"Token exchange failed: {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise OpenAIWebAuthError("OpenAI returned an invalid token response.")
        return payload

    def _refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        response = requests.post(
            f"{OPENAI_WEB_ISSUER}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OPENAI_WEB_CLIENT_ID,
            },
            timeout=PROVIDER_REQUEST_TIMEOUT,
        )
        if not response.ok:
            raise OpenAIWebAuthError(f"Token refresh failed: {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise OpenAIWebAuthError("OpenAI returned an invalid refresh response.")
        return payload

    def complete_browser_login(self, code: str, state: str) -> Dict[str, Any]:
        payload = self._load()
        pending = payload.get("pending") or {}
        if not pending:
            raise OpenAIWebAuthError("No login attempt is pending.")
        if pending.get("state") != state:
            raise OpenAIWebAuthError("OAuth state mismatch.")

        tokens = self._exchange_code_for_tokens(code, pending.get("redirect_uri", ""), pending.get("verifier", ""))
        account_id = self.extract_account_id(tokens)
        email = self.extract_email(tokens)
        expires_at = int(time.time() * 1000) + int(tokens.get("expires_in") or 3600) * 1000

        payload["pending"] = None
        payload["token"] = {
            "type": "oauth",
            "refresh_token": tokens.get("refresh_token", ""),
            "access_token": tokens.get("access_token", ""),
            "id_token": tokens.get("id_token", ""),
            "expires_at": expires_at,
            "account_id": account_id or "",
            "email": email,
            "connected_at": int(time.time()),
        }
        self._save(payload)
        return payload["token"]

    def clear(self) -> None:
        payload = self._load()
        payload["pending"] = None
        payload["token"] = None
        self._save(payload)

    def get_token(self) -> Optional[Dict[str, Any]]:
        payload = self._load()
        token = payload.get("token")
        return token if isinstance(token, dict) else None

    def is_connected(self) -> bool:
        token = self.get_token() or {}
        return bool(token.get("refresh_token") and (token.get("access_token") or token.get("id_token")))

    def ensure_fresh_token(self, force_refresh: bool = False) -> Dict[str, Any]:
        token = self.get_token()
        if not token:
            raise OpenAIWebAuthError("OpenAI browser login is not connected.")

        expires_at = int(token.get("expires_at") or 0)
        now = int(time.time() * 1000)
        if not force_refresh and token.get("access_token") and expires_at > now + 60_000:
            return token

        refresh_token = (token.get("refresh_token") or "").strip()
        if not refresh_token:
            raise OpenAIWebAuthError("Missing refresh token for OpenAI browser login.")

        refreshed = self._refresh_access_token(refresh_token)
        new_access = refreshed.get("access_token") or token.get("access_token") or ""
        new_refresh = refreshed.get("refresh_token") or refresh_token
        new_id_token = refreshed.get("id_token") or token.get("id_token") or ""
        expires_at = int(time.time() * 1000) + int(refreshed.get("expires_in") or 3600) * 1000
        account_id = self.extract_account_id(refreshed) or token.get("account_id") or ""
        email = self.extract_email(refreshed) or token.get("email") or ""

        payload = self._load()
        payload["token"] = {
            **token,
            "refresh_token": new_refresh,
            "access_token": new_access,
            "id_token": new_id_token,
            "expires_at": expires_at,
            "account_id": account_id,
            "email": email,
        }
        self._save(payload)
        return payload["token"]

    def get_request_headers(self) -> Dict[str, str]:
        token = self.ensure_fresh_token()
        access_token = (token.get("access_token") or "").strip()
        if not access_token:
            raise OpenAIWebAuthError("OpenAI browser login is missing an access token.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Originator": "opencode",
            "User-Agent": "ollama-voice-assistant/1.0",
        }
        account_id = (token.get("account_id") or "").strip()
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id
        return headers

    def get_public_state(self) -> Dict[str, Any]:
        token = self.get_token() or {}
        return {
            "connected": self.is_connected(),
            "email": token.get("email", ""),
            "account_id": token.get("account_id", ""),
            "expires_at": token.get("expires_at", 0),
        }
