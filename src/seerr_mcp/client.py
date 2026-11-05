"""Seerr's REST API (/api/v1), authenticated with its API key.

The key acts as Seerr's first user, the admin, so a request made here is
theirs and is approved (and sent to Radarr or Sonarr) at once, as one made
in Seerr's own page would be."""

from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .errors import AlreadyRequested, AuthFailed, NotFound, Unavailable, UpstreamError

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class Seerr:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"{settings.url}/api/v1",
            timeout=TIMEOUT,
            transport=transport,
            headers={"X-Api-Key": settings.api_key, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, path: str, **kw: Any) -> Any:
        try:
            resp = await self._http.request(method, path, **kw)
        except httpx.TimeoutException:
            raise Unavailable("Seerr did not answer in time") from None
        except httpx.TransportError as exc:
            raise Unavailable(f"Seerr could not be reached: {type(exc).__name__}") from None
        message = self._message(resp)
        if resp.status_code in (401, 403):
            raise AuthFailed(f"Seerr refused the API key ({resp.status_code})")
        if resp.status_code == 404:
            raise NotFound(message or "Seerr has no such thing")
        if resp.status_code == 409:
            raise AlreadyRequested(message or "Seerr already has this request")
        if resp.status_code >= 500:
            raise Unavailable(f"Seerr answered HTTP {resp.status_code}" + (f": {message}" if message else ""))
        if resp.status_code >= 400:
            raise UpstreamError(message or f"Seerr answered HTTP {resp.status_code}")
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            raise UpstreamError("Seerr answered something that is not JSON") from None

    @staticmethod
    def _message(resp: httpx.Response) -> str | None:
        if resp.status_code < 400:
            return None
        try:
            doc = resp.json()
        except ValueError:
            return None
        if isinstance(doc, dict) and doc.get("message"):
            return str(doc["message"])[:300]
        return None

    async def get(self, path: str, **params: Any) -> Any:
        return await self._send("GET", path, params={k: v for k, v in params.items() if v is not None})

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        return await self._send("POST", path, json=body)

    async def delete(self, path: str) -> Any:
        return await self._send("DELETE", path)
