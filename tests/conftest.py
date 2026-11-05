"""A fake Seerr: the /api/v1 routes this server calls, shaped like v3.5.1's
answers, checking the API key on every request."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from seerr_mcp.client import Seerr
from seerr_mcp.config import Settings
from seerr_mcp.service import Requests

BASE = "http://seerr.test:5055"
TOKEN = "test-bearer-token-0123456789"
KEY = "seerr-api-key"


def settings(region: str | None = "AR") -> Settings:
    return Settings(token=TOKEN, listen_host="127.0.0.1", listen_port=8080, url=BASE, api_key=KEY, watch_region=region)


def movie(tmdb: int, title: str, status: int | None = None, **extra: Any) -> dict[str, Any]:
    doc = {
        "id": tmdb,
        "title": title,
        "releaseDate": "2001-07-20",
        "runtime": 125,
        "overview": f"{title}, a film.",
        "genres": [{"id": 16, "name": "Animation"}],
        "watchProviders": [
            {"iso_3166_1": "AR", "flatrate": [{"name": "Netflix"}], "buy": [{"name": "Apple TV Store"}], "rent": []},
            {"iso_3166_1": "FR", "flatrate": [{"name": "Arte"}]},
        ],
        "mediaInfo": None
        if status is None
        else {"id": tmdb * 10, "tmdbId": tmdb, "mediaType": "movie", "status": status, "requests": [], "downloadStatus": []},
    }
    doc.update(extra)
    return doc


def show(
    tmdb: int, name: str, seasons: dict[int, int], status: int | None = None, season_status: dict[int, int] | None = None
) -> dict[str, Any]:
    info = None
    if status is not None:
        info = {
            "id": tmdb * 10,
            "tmdbId": tmdb,
            "mediaType": "tv",
            "status": status,
            "requests": [],
            "downloadStatus": [],
            "seasons": [{"seasonNumber": s, "status": st} for s, st in (season_status or {}).items()],
        }
    return {
        "id": tmdb,
        "name": name,
        "firstAirDate": "2022-02-17",
        "overview": f"{name}, a show.",
        "genres": [{"id": 18, "name": "Drama"}],
        "inProduction": True,
        "seasons": [{"seasonNumber": s, "episodeCount": n, "airDate": f"{2021 + s}-01-01"} for s, n in seasons.items()],
        "watchProviders": [{"iso_3166_1": "AR", "flatrate": [{"name": "Apple TV"}]}],
        "mediaInfo": info,
    }


@dataclass
class FakeSeerr:
    movies: dict[int, dict[str, Any]] = field(default_factory=dict)
    shows: dict[int, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    media: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, str, dict[str, Any], Any]] = field(default_factory=list)
    down: bool = False
    duplicate: bool = False

    def posted(self, path: str) -> list[Any]:
        return [b for m, p, _, b in self.calls if m == "POST" and p == path]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path.removeprefix("/api/v1")
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, params, copy.deepcopy(body)))
        if request.headers.get("x-api-key") != KEY:
            return httpx.Response(401, json={"message": "You do not have permission to access this endpoint"})
        route = (request.method, path)
        if route == ("GET", "/auth/me"):
            return httpx.Response(200, json={"id": 1, "displayName": "santi"})
        if route == ("GET", "/search"):
            return httpx.Response(200, json={"page": 1, "totalPages": 2, "totalResults": 30, "results": self.search_results})
        if m := re.fullmatch(r"/movie/(\d+)/ratingscombined", path):
            return httpx.Response(200, json={"rt": {"criticsScore": 96, "audienceScore": 96}, "imdb": {"criticsScore": 8.6}})
        if m := re.fullmatch(r"/tv/(\d+)/ratings", path):
            return httpx.Response(200, json={"criticsScore": 97, "audienceScore": 89})
        if m := re.fullmatch(r"/(movie|tv)/(\d+)", path):
            store = self.movies if m.group(1) == "movie" else self.shows
            doc = store.get(int(m.group(2)))
            return httpx.Response(200, json=doc) if doc else httpx.Response(404, json={"message": "Unable to retrieve"})
        if route == ("GET", "/request"):
            take, skip = int(params["take"]), int(params["skip"])
            page = self.requests[skip : skip + take]
            return httpx.Response(
                200,
                json={
                    "pageInfo": {
                        "pages": -(-len(self.requests) // take),
                        "page": skip // take + 1,
                        "results": len(self.requests),
                    },
                    "results": page,
                },
            )
        if route == ("POST", "/request"):
            if self.duplicate:
                return httpx.Response(409, json={"message": "Request for this media already exists."})
            created = {
                "id": 99,
                "status": 2,
                "is4k": False,
                "requestedBy": {"displayName": "santi"},
                "createdAt": "2026-11-05T03:00:00.000Z",
                "media": {"id": 7, "tmdbId": body["mediaId"], "mediaType": body["mediaType"], "status": 3},
                "seasons": [],
            }
            return httpx.Response(201, json=created)
        if m := re.fullmatch(r"/request/(\d+)", path):
            return httpx.Response(204)
        if route == ("GET", "/media"):
            return httpx.Response(
                200, json={"pageInfo": {"pages": 1, "page": 1, "results": len(self.media)}, "results": self.media}
            )
        if route == ("GET", "/issue"):
            return httpx.Response(200, json={"pageInfo": {"pages": 1}, "results": self.issues})
        if route == ("POST", "/issue"):
            return httpx.Response(200, json={"id": 5})
        return httpx.Response(404, json={"message": f"no route {route}"})


@pytest.fixture()
def fake() -> FakeSeerr:
    return FakeSeerr()


def make(fake: FakeSeerr, region: str | None = "AR") -> tuple[Seerr, Requests]:
    seerr = Seerr(settings(region), transport=httpx.MockTransport(fake.handler))
    return seerr, Requests(seerr, watch_region=region)
