"""Each tool against the fake Seerr: what it sends, and what it answers."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import BASE, TOKEN, FakeSeerr, make, movie, show

from seerr_mcp.client import Seerr
from seerr_mcp.config import Settings
from seerr_mcp.errors import AlreadyRequested, AuthFailed, InvalidArgument, NotFound, NotInSeerr, Unavailable
from seerr_mcp.service import Requests


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


def test_search_names_each_title_s_state(fake: FakeSeerr) -> None:
    fake.search_results = [
        {"id": 95396, "mediaType": "tv", "name": "Severance", "firstAirDate": "2022-02-17", "mediaInfo": None},
        {"id": 129, "mediaType": "movie", "title": "Spirited Away", "releaseDate": "2001-07-20", "mediaInfo": {"status": 5}},
        {"id": 1, "mediaType": "person", "name": "Someone"},
    ]
    _, s = make(fake)
    out = run(s.search({"query": "x"}))
    assert out == {
        "results": [
            {"tmdb_id": 95396, "type": "show", "title": "Severance", "year": 2022, "status": "not_requested"},
            {"tmdb_id": 129, "type": "movie", "title": "Spirited Away", "year": 2001, "status": "available"},
        ],
        "next_page": 2,
    }


def test_get_title_movie(fake: FakeSeerr) -> None:
    fake.movies[129] = movie(129, "Spirited Away", status=3)
    fake.movies[129]["mediaInfo"]["downloadStatus"] = [
        {
            "title": "Spirited.Away.2001.2160p",
            "size": 1000,
            "sizeLeft": 250,
            "estimatedCompletionTime": "2026-11-05T04:00:00Z",
            "status": "downloading",
        }
    ]
    fake.movies[129]["mediaInfo"]["requests"] = [
        {
            "id": 3,
            "status": 2,
            "requestedBy": {"displayName": "santi"},
            "createdAt": "2026-11-01T00:00:00Z",
            "is4k": False,
            "seasons": [],
        }
    ]
    _, s = make(fake)
    out = run(s.get_title({"type": "movie", "tmdb_id": 129}))
    assert out["status"] == "processing"
    assert out["runtime_minutes"] == 125
    assert out["ratings"] == {"rotten_tomatoes_critics": 96, "rotten_tomatoes_audience": 96, "imdb": 8.6}
    assert out["where_to_watch"] == {"region": "AR", "stream": ["Netflix"], "buy": ["Apple TV Store"]}
    assert out["downloading"] == [
        {"release": "Spirited.Away.2001.2160p", "percent": 75.0, "eta": "2026-11-05T04:00:00Z", "state": "downloading"}
    ]
    assert out["requests"] == [
        {"request_id": 3, "status": "approved", "requested_by": "santi", "requested_on": "2026-11-01T00:00:00Z"}
    ]


def test_get_title_show_has_each_season_s_state(fake: FakeSeerr) -> None:
    fake.shows[95396] = show(95396, "Severance", {0: 1, 1: 9, 2: 10}, status=4, season_status={1: 5})
    _, s = make(fake)
    out = run(s.get_title({"type": "show", "tmdb_id": 95396, "region": "fr"}))
    assert out["status"] == "partially_available"
    assert [(x["season"], x["status"]) for x in out["seasons"]] == [(0, "not_requested"), (1, "available"), (2, "not_requested")]
    assert out["ratings"] == {"rotten_tomatoes_critics": 97, "rotten_tomatoes_audience": 89}
    assert out["where_to_watch"] == {"region": "FR"}


def test_unknown_title(fake: FakeSeerr) -> None:
    _, s = make(fake)
    with pytest.raises(NotFound):
        run(s.get_title({"type": "movie", "tmdb_id": 404}))


def test_list_requests_names_titles_once(fake: FakeSeerr) -> None:
    fake.movies[129] = movie(129, "Spirited Away")
    fake.requests = [
        {
            "id": 2,
            "status": 5,
            "media": {"tmdbId": 129, "mediaType": "movie", "status": 5},
            "requestedBy": {"displayName": "santi"},
            "createdAt": "t2",
            "seasons": [],
        },
        {
            "id": 1,
            "status": 1,
            "media": {"tmdbId": 129, "mediaType": "movie", "status": 2},
            "requestedBy": {"displayName": "sofi"},
            "createdAt": "t1",
            "seasons": [],
        },
    ]
    _, s = make(fake)
    out = run(s.list_requests({"filter": "all", "limit": 10}))
    assert [(r["request_id"], r["title"], r["status"], r["title_status"]) for r in out["requests"]] == [
        (2, "Spirited Away", "completed", "available"),
        (1, "Spirited Away", "pending_approval", "pending"),
    ]
    assert len([c for c in fake.calls if c[1] == "/movie/129"]) == 1
    sent = next(p for m, path, p, _ in fake.calls if path == "/request")
    assert (sent["take"], sent["skip"], sent["filter"], sent["mediaType"]) == ("10", "0", "all", "all")


def test_request_a_show_s_seasons(fake: FakeSeerr) -> None:
    fake.shows[95396] = show(95396, "Severance", {1: 9, 2: 10})
    _, s = make(fake)
    out = run(s.request({"type": "show", "tmdb_id": 95396, "seasons": [2, 1, 2]}))
    assert fake.posted("/request") == [{"mediaType": "tv", "mediaId": 95396, "is4k": False, "seasons": [1, 2]}]
    assert (out["request_id"], out["status"], out["title"], out["title_status"]) == (99, "approved", "Severance", "processing")
    run(s.request({"type": "show", "tmdb_id": 95396}))
    assert fake.posted("/request")[1]["seasons"] == "all"


def test_request_refusals(fake: FakeSeerr) -> None:
    fake.movies[129] = movie(129, "Spirited Away")
    _, s = make(fake)
    with pytest.raises(InvalidArgument, match="seasons are for shows"):
        run(s.request({"type": "movie", "tmdb_id": 129, "seasons": [1]}))
    fake.duplicate = True
    with pytest.raises(AlreadyRequested):
        run(s.request({"type": "movie", "tmdb_id": 129}))


def test_report_issue_needs_a_title_in_seerr(fake: FakeSeerr) -> None:
    fake.shows[95396] = show(95396, "Severance", {1: 9}, status=5)
    fake.movies[1] = movie(1, "Never Requested")
    _, s = make(fake)
    out = run(
        s.report_issue(
            {"type": "show", "tmdb_id": 95396, "problem": "subtitles", "message": "Out of sync", "season": 1, "episode": 3}
        )
    )
    assert out == {"issue_id": 5, "title": "Severance", "problem": "subtitles"}
    assert fake.posted("/issue") == [
        {"issueType": 3, "message": "Out of sync", "mediaId": 953960, "problemSeason": 1, "problemEpisode": 3}
    ]
    with pytest.raises(NotInSeerr):
        run(s.report_issue({"type": "movie", "tmdb_id": 1, "problem": "video", "message": "x"}))


def test_cancel_and_issue_and_recent(fake: FakeSeerr) -> None:
    fake.movies[129] = movie(129, "Spirited Away")
    fake.media = [{"id": 1, "tmdbId": 129, "mediaType": "movie", "status": 5, "mediaAddedAt": "2026-11-04T00:00:00Z"}]
    fake.issues = [
        {
            "id": 4,
            "issueType": 2,
            "status": 1,
            "problemSeason": 0,
            "problemEpisode": 0,
            "media": {"tmdbId": 129, "mediaType": "movie"},
            "createdBy": {"displayName": "sofi"},
            "createdAt": "t",
            "comments": [{"message": "No sound after 20 min"}],
        }
    ]
    _, s = make(fake)
    assert run(s.cancel_request({"request_id": 3})) == {"cancelled": 3}
    assert run(s.recently_added({}))["added"] == [
        {
            "tmdb_id": 129,
            "type": "movie",
            "title": "Spirited Away",
            "year": 2001,
            "status": "available",
            "added_on": "2026-11-04T00:00:00Z",
        }
    ]
    issue = run(s.list_issues({}))["issues"][0]
    assert (issue["problem"], issue["status"], issue["message"], "season" in issue) == (
        "audio",
        "open",
        "No sound after 20 min",
        False,
    )


def test_errors_are_typed(fake: FakeSeerr) -> None:
    _, s = make(fake)
    fake.down = True
    with pytest.raises(Unavailable):
        run(s.search({"query": "x"}))
    fake.down = False
    wrong = Seerr(
        Settings(token=TOKEN, listen_host="h", listen_port=1, url=BASE, api_key="wrong"),
        transport=httpx.MockTransport(fake.handler),
    )
    with pytest.raises(AuthFailed):
        run(Requests(wrong).search({"query": "x"}))
