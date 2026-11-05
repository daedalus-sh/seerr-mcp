"""The MCP layer end to end: a real HTTP server, the SDK's own client, the fake Seerr."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import anyio
import httpx
import pytest
import uvicorn
from conftest import TOKEN, FakeSeerr, movie, settings
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from seerr_mcp.client import Seerr
from seerr_mcp.server import INSTRUCTIONS, build_app
from seerr_mcp.service import Requests

EXPECTED = {
    # name: (readOnly, destructive, idempotent, openWorld)
    "search": (True, False, True, False),
    "get_title": (True, False, True, False),
    "list_requests": (True, False, True, False),
    "recently_added": (True, False, True, False),
    "list_issues": (True, False, True, False),
    "request": (False, False, False, True),
    "cancel_request": (False, True, True, False),
    "report_issue": (False, False, False, False),
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    def __init__(self, port: int, fake: FakeSeerr) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.fake = fake


@pytest.fixture()
def server(fake: FakeSeerr) -> Iterator[Running]:
    seerr = Seerr(settings(), transport=httpx.MockTransport(fake.handler))
    port = free_port()
    config = uvicorn.Config(
        build_app(TOKEN, seerr, Requests(seerr, watch_region="AR")), host="127.0.0.1", port=port, log_level="error", lifespan="on"
    )
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(250):
        if srv.started:
            break
        time.sleep(0.02)
    yield Running(port, fake)
    srv.should_exit = True
    t.join(5)


def call(base: str, fn: Any) -> Any:
    async def go() -> Any:
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30) as http:
            async with streamable_http_client(f"{base}/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    return await fn(session, init)

    return anyio.run(go)


def test_tools_and_annotations(server: Running) -> None:
    async def fn(session: ClientSession, init: types.InitializeResult) -> Any:
        return init, await session.list_tools()

    init, listed = call(server.base, fn)
    assert init.serverInfo.name == "seerr-mcp"
    assert init.instructions == INSTRUCTIONS
    assert "untrusted" in INSTRUCTIONS
    got = {t.name: t for t in listed.tools}
    assert set(got) == set(EXPECTED)
    for name, (ro, destructive, idem, open_world) in EXPECTED.items():
        a = got[name].annotations
        assert (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint) == (ro, destructive, idem, open_world), name
        assert got[name].inputSchema["additionalProperties"] is False


def test_bearer_auth_and_health(server: Running) -> None:
    with httpx.Client() as http:
        assert http.post(f"{server.base}/mcp", json={}).status_code == 401
        r = http.get(f"{server.base}/healthz")
        assert (r.status_code, r.text) == (200, "ok")
        server.fake.down = True
        r = http.get(f"{server.base}/healthz")
        assert (r.status_code, r.text) == (503, "unavailable: seerr_unavailable")


def test_a_call_round_trip(server: Running) -> None:
    server.fake.movies[129] = movie(129, "Spirited Away", status=5)

    async def fn(session: ClientSession, _: Any) -> tuple[types.CallToolResult, types.CallToolResult]:
        ok = await session.call_tool("get_title", {"type": "movie", "tmdb_id": 129})
        missing = await session.call_tool("get_title", {"type": "movie", "tmdb_id": 404})
        return ok, missing

    ok, missing = call(server.base, fn)
    assert not ok.isError
    assert ok.structuredContent == json.loads(ok.content[0].text)
    assert ok.structuredContent["status"] == "available"
    assert missing.isError and missing.structuredContent["error"] == "not_found"
