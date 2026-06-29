"""HTTP client for the Milesight LoRaWAN gateway HTTP API.

Handles AES password encryption (required on firmware 60.0.0.42-r5 / 56.0.0.4 and
later), JWT bearer-token auth with automatic re-login, and a thin async request
wrapper over httpx. The gateway serves HTTPS on port 8080 with a self-signed
certificate, so TLS verification is disabled by default.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# AES settings are fixed by the Milesight firmware (see HTTP API spec, section 1.1).
_AES_KEY = b"1111111111111111"
_AES_IV = b"2222222222222222"


class MilesightError(RuntimeError):
    """Raised when the gateway returns an error response."""

    def __init__(self, message: str, *, status: int | None = None, code: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code


def encrypt_password(plaintext: str) -> str:
    """AES-128-CBC encrypt a password and return Base64, per the gateway spec."""
    cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_IV)
    encrypted = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("ascii")


class MilesightClient:
    """Async client for a single Milesight gateway."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 8080,
        verify: bool = False,
        timeout: float = 20.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.base_url = f"https://{host}:{port}"
        self._jwt: str | None = None
        self._jwt_acquired_at: float = 0.0
        # Token is valid 24h; refresh proactively a little early.
        self._jwt_ttl = 23 * 60 * 60
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            verify=verify,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "MilesightClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- auth ---------------------------------------------------------------

    async def login(self) -> str:
        """Authenticate and cache a JWT. Returns the token."""
        payload = {
            "username": self.username,
            "password": encrypt_password(self.password),
        }
        resp = await self._client.post("/api/internal/login", json=payload)
        if resp.status_code != 200:
            raise MilesightError(
                f"Login failed: HTTP {resp.status_code} {resp.text[:200]}",
                status=resp.status_code,
            )
        data = resp.json()
        jwt = data.get("jwt")
        if not jwt:
            raise MilesightError(f"Login response had no jwt: {data}")
        self._jwt = jwt
        self._jwt_acquired_at = time.monotonic()
        return jwt

    async def _ensure_token(self) -> str:
        if (
            self._jwt is None
            or time.monotonic() - self._jwt_acquired_at > self._jwt_ttl
        ):
            await self.login()
        assert self._jwt is not None
        return self._jwt

    # -- requests -----------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Perform an authenticated request, retrying once after re-login on 401.

        Returns parsed JSON (or ``{}`` for empty bodies). Raises ``MilesightError``
        on non-2xx responses.
        """
        token = await self._ensure_token()
        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )

        async def _do(tok: str) -> httpx.Response:
            return await self._client.request(
                method,
                path,
                params=clean_params,
                json=json,
                headers={"Authorization": f"Bearer {tok}"},
            )

        resp = await _do(token)
        if resp.status_code == 401:
            token = await self.login()
            resp = await _do(token)

        if resp.status_code < 200 or resp.status_code >= 300:
            raise MilesightError(
                f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}",
                status=resp.status_code,
            )

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    # Convenience verbs ------------------------------------------------------

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> Any:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw: Any) -> Any:
        return await self.request("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> Any:
        return await self.request("DELETE", path, **kw)
