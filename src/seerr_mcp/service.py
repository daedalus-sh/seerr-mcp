"""What each tool does, in Seerr's terms.

A title is its TMDB id plus its type (movie or show): the id Seerr's own
pages use. Seerr keeps two states: the TITLE's (is it in the library, on its
way, or nowhere), and each REQUEST's (waiting for approval, approved,
declined, failed, done). The tools name both in words."""

from __future__ import annotations

import asyncio
from typing import Any

from .client import Seerr
from .errors import InvalidArgument, NotInSeerr, SeerrError

# server/constants/media.ts
MEDIA_STATUS = {
    1: "not_requested",
    2: "pending",
    3: "processing",
    4: "partially_available",
    5: "available",
    6: "blocklisted",
    7: "deleted",
}
REQUEST_STATUS = {1: "pending_approval", 2: "approved", 3: "declined", 4: "failed", 5: "completed"}
# server/constants/issue.ts
ISSUE_TYPES = {"video": 1, "audio": 2, "subtitles": 3, "other": 4}
ISSUE_TYPE_NAMES = {v: k for k, v in ISSUE_TYPES.items()}
ISSUE_STATUS = {1: "open", 2: "resolved"}

TYPES = {"movie": "movie", "show": "tv"}
TYPE_NAMES = {"movie": "movie", "tv": "show"}
REQUEST_FILTERS = ("all", "pending", "approved", "processing", "available", "unavailable", "failed", "completed")


def _media_status(info: dict[str, Any] | None) -> str:
    if not info:
        return "not_requested"
    return MEDIA_STATUS.get(info.get("status"), f"status_{info.get('status')}")


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def _tmdb_id(args: dict[str, Any]) -> int:
    value = args.get("tmdb_id")
    if not isinstance(value, int) or value < 1:
        raise InvalidArgument("tmdb_id must be a TMDB id returned by search")
    return value


def _type(args: dict[str, Any]) -> str:
    value = args.get("type")
    if value not in TYPES:
        raise InvalidArgument("type must be movie or show")
    return TYPES[value]


def _downloads(info: dict[str, Any] | None) -> list[dict[str, Any]]:
    out = []
    for d in (info or {}).get("downloadStatus") or []:
        size, left = d.get("size") or 0, d.get("sizeLeft") or 0
        row = {
            "release": d.get("title"),
            "percent": round(100 * (size - left) / size, 1) if size else None,
            "eta": d.get("estimatedCompletionTime"),
            "state": d.get("status"),
        }
        episode = d.get("episode")
        if isinstance(episode, dict):
            row["season"], row["episode"] = episode.get("seasonNumber"), episode.get("episodeNumber")
        out.append({k: v for k, v in row.items() if v is not None})
    return out


def _request(r: dict[str, Any]) -> dict[str, Any]:
    out = {
        "request_id": r.get("id"),
        "status": REQUEST_STATUS.get(r.get("status"), f"status_{r.get('status')}"),
        "requested_by": (r.get("requestedBy") or {}).get("displayName"),
        "requested_on": r.get("createdAt"),
        "4k": r.get("is4k") or None,
        "seasons": [s["seasonNumber"] for s in r.get("seasons") or []] or None,
    }
    return {k: v for k, v in out.items() if v is not None}


class Requests:
    def __init__(self, seerr: Seerr, *, watch_region: str | None = None, concurrency: int = 4) -> None:
        self.seerr = seerr
        self.watch_region = watch_region
        self._sem = asyncio.Semaphore(concurrency)
        self._titles: dict[tuple[str, int], tuple[str | None, int | None]] = {}

    async def health(self) -> tuple[bool, str]:
        try:
            me = await self.seerr.get("/auth/me")
        except SeerrError as err:
            return False, err.kind
        return True, f"signed in as {me.get('displayName')}"

    async def _details(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        async with self._sem:
            details = await self.seerr.get(f"/{media_type}/{tmdb_id}")
        self._titles[(media_type, tmdb_id)] = (
            details.get("title") or details.get("name"),
            _year(details.get("releaseDate") or details.get("firstAirDate")),
        )
        return details

    async def _title(self, media_type: str, tmdb_id: int) -> tuple[str | None, int | None]:
        if (media_type, tmdb_id) not in self._titles:
            try:
                await self._details(media_type, tmdb_id)
            except SeerrError:
                return None, None
        return self._titles[(media_type, tmdb_id)]

    def _where(self, details: dict[str, Any], region: Any) -> dict[str, Any] | None:
        wanted = str(region).upper() if region else self.watch_region
        if not wanted:
            return None
        for entry in details.get("watchProviders") or []:
            if entry.get("iso_3166_1") == wanted:
                out = {
                    "region": wanted,
                    "stream": [p["name"] for p in entry.get("flatrate") or []],
                    "rent": [p["name"] for p in entry.get("rent") or []],
                    "buy": [p["name"] for p in entry.get("buy") or []],
                }
                return {k: v for k, v in out.items() if v}
        return {"region": wanted}

    # ── read tools ─────────────────────────────────────────────────────

    async def search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            raise InvalidArgument("query must not be empty")
        data = await self.seerr.get("/search", query=query, page=int(args.get("page") or 1))
        results = []
        for r in data.get("results") or []:
            if r.get("mediaType") not in TYPE_NAMES:
                continue
            results.append(
                {
                    k: v
                    for k, v in {
                        "tmdb_id": r.get("id"),
                        "type": TYPE_NAMES[r["mediaType"]],
                        "title": r.get("title") or r.get("name"),
                        "year": _year(r.get("releaseDate") or r.get("firstAirDate")),
                        "status": _media_status(r.get("mediaInfo")),
                    }.items()
                    if v is not None
                }
            )
        page, pages = data.get("page"), data.get("totalPages")
        return {"results": results, "next_page": page + 1 if page and pages and page < pages else None}

    async def _ratings(self, media_type: str, tmdb_id: int) -> dict[str, Any] | None:
        path = f"/movie/{tmdb_id}/ratingscombined" if media_type == "movie" else f"/tv/{tmdb_id}/ratings"
        try:
            async with self._sem:
                data = await self.seerr.get(path)
        except SeerrError:
            return None
        rt = data.get("rt") if media_type == "movie" else data
        imdb = data.get("imdb") if media_type == "movie" else None
        out: dict[str, Any] = {}
        if rt and rt.get("criticsScore") is not None:
            out["rotten_tomatoes_critics"] = rt["criticsScore"]
        if rt and rt.get("audienceScore") is not None:
            out["rotten_tomatoes_audience"] = rt["audienceScore"]
        if imdb and imdb.get("criticsScore") is not None:
            out["imdb"] = imdb["criticsScore"]
        return out or None

    async def get_title(self, args: dict[str, Any]) -> dict[str, Any]:
        media_type, tmdb_id = _type(args), _tmdb_id(args)
        details, ratings = await asyncio.gather(self._details(media_type, tmdb_id), self._ratings(media_type, tmdb_id))
        info = details.get("mediaInfo")
        limit = int(args.get("max_overview_chars", 800))
        overview = details.get("overview") or ""
        out: dict[str, Any] = {
            "tmdb_id": tmdb_id,
            "type": TYPE_NAMES[media_type],
            "title": details.get("title") or details.get("name"),
            "year": _year(details.get("releaseDate") or details.get("firstAirDate")),
            "status": _media_status(info),
            "genres": [g["name"] for g in details.get("genres") or []],
            "overview": overview[:limit] if limit else None,
            "ratings": ratings,
            "where_to_watch": self._where(details, args.get("region")),
            "downloading": _downloads(info),
            "requests": [_request(r) for r in (info or {}).get("requests") or []],
        }
        if media_type == "movie":
            out["runtime_minutes"] = details.get("runtime")
        else:
            by_number = {s["seasonNumber"]: s for s in (info or {}).get("seasons") or []}
            out["seasons"] = [
                {
                    "season": s["seasonNumber"],
                    "episodes": s.get("episodeCount"),
                    "aired": s.get("airDate"),
                    "status": MEDIA_STATUS.get((by_number.get(s["seasonNumber"]) or {}).get("status"), "not_requested"),
                }
                for s in details.get("seasons") or []
            ]
            out["in_production"] = details.get("inProduction")
        return {k: v for k, v in out.items() if v not in (None, [], "")}

    async def _with_titles(self, rows: list[dict[str, Any]], media_of: Any) -> list[dict[str, Any]]:
        async def one(row: dict[str, Any]) -> dict[str, Any]:
            media = media_of(row) or {}
            media_type, tmdb_id = media.get("mediaType"), media.get("tmdbId")
            title, year = await self._title(media_type, tmdb_id) if media_type and tmdb_id else (None, None)
            head = {"tmdb_id": tmdb_id, "type": TYPE_NAMES.get(media_type, media_type), "title": title, "year": year}
            return {k: v for k, v in head.items() if v is not None}

        heads = await asyncio.gather(*(one(r) for r in rows))
        return list(heads)

    async def list_requests(self, args: dict[str, Any]) -> dict[str, Any]:
        state = args.get("filter") or "all"
        if state not in REQUEST_FILTERS:
            raise InvalidArgument(f"filter must be one of {', '.join(REQUEST_FILTERS)}")
        kind = args.get("type")
        if kind is not None and kind not in TYPES:
            raise InvalidArgument("type must be movie or show")
        limit, page = int(args.get("limit") or 10), int(args.get("page") or 1)
        data = await self.seerr.get(
            "/request",
            take=limit,
            skip=(page - 1) * limit,
            filter=state,
            sort=args.get("sort") or "added",
            mediaType=TYPES[kind] if kind else "all",
        )
        rows = data.get("results") or []
        heads = await self._with_titles(rows, lambda r: r.get("media"))
        items = [
            {**head, **_request(r), "title_status": _media_status(r.get("media"))} for head, r in zip(heads, rows, strict=True)
        ]
        info = data.get("pageInfo") or {}
        pages = info.get("pages") or 0
        return {"requests": items, "total": info.get("results"), "next_page": page + 1 if page < pages else None}

    async def recently_added(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit") or 10)
        data = await self.seerr.get("/media", take=limit, skip=0, filter="allavailable", sort="mediaAdded")
        rows = data.get("results") or []
        heads = await self._with_titles(rows, lambda m: m)
        items = [
            {**head, "status": _media_status(m), "added_on": m.get("mediaAddedAt")} for head, m in zip(heads, rows, strict=True)
        ]
        return {"added": [{k: v for k, v in i.items() if v is not None} for i in items]}

    async def list_issues(self, args: dict[str, Any]) -> dict[str, Any]:
        state = args.get("filter") or "open"
        if state not in ("open", "resolved", "all"):
            raise InvalidArgument("filter must be open, resolved or all")
        limit = int(args.get("limit") or 10)
        data = await self.seerr.get("/issue", take=limit, skip=0, filter=state, sort="added")
        rows = data.get("results") or []
        heads = await self._with_titles(rows, lambda i: i.get("media"))
        items = []
        for head, i in zip(heads, rows, strict=True):
            comments = i.get("comments") or []
            row = {
                **head,
                "issue_id": i.get("id"),
                "problem": ISSUE_TYPE_NAMES.get(i.get("issueType"), "other"),
                "status": ISSUE_STATUS.get(i.get("status"), "open"),
                "season": i.get("problemSeason") or None,
                "episode": i.get("problemEpisode") or None,
                "message": comments[0].get("message") if comments else None,
                "reported_by": (i.get("createdBy") or {}).get("displayName"),
                "reported_on": i.get("createdAt"),
            }
            items.append({k: v for k, v in row.items() if v is not None})
        return {"issues": items}

    # ── write tools ────────────────────────────────────────────────────

    async def request(self, args: dict[str, Any]) -> dict[str, Any]:
        media_type, tmdb_id = _type(args), _tmdb_id(args)
        body: dict[str, Any] = {"mediaType": media_type, "mediaId": tmdb_id, "is4k": False}
        seasons = args.get("seasons")
        if media_type == "tv":
            if seasons is None or seasons == "all":
                body["seasons"] = "all"
            elif isinstance(seasons, list) and seasons and all(isinstance(s, int) and s >= 0 for s in seasons):
                body["seasons"] = sorted(set(seasons))
            else:
                raise InvalidArgument('seasons must be "all" or a list of season numbers')
        elif seasons is not None:
            raise InvalidArgument("seasons are for shows")
        created = await self.seerr.post("/request", body)
        title, year = await self._title(media_type, tmdb_id)
        return {
            "tmdb_id": tmdb_id,
            "type": TYPE_NAMES[media_type],
            "title": title,
            "year": year,
            **_request(created or {}),
            "title_status": _media_status((created or {}).get("media")),
        }

    async def cancel_request(self, args: dict[str, Any]) -> dict[str, Any]:
        request_id = args.get("request_id")
        if not isinstance(request_id, int) or request_id < 1:
            raise InvalidArgument("request_id must be a request id from list_requests or get_title")
        await self.seerr.delete(f"/request/{request_id}")
        return {"cancelled": request_id}

    async def report_issue(self, args: dict[str, Any]) -> dict[str, Any]:
        media_type, tmdb_id = _type(args), _tmdb_id(args)
        problem = args.get("problem")
        if problem not in ISSUE_TYPES:
            raise InvalidArgument(f"problem must be one of {', '.join(ISSUE_TYPES)}")
        message = str(args.get("message") or "").strip()
        if not message:
            raise InvalidArgument("message must say what is wrong")
        details = await self._details(media_type, tmdb_id)
        info = details.get("mediaInfo")
        if not info or not info.get("id"):
            raise NotInSeerr(
                f"{details.get('title') or details.get('name')} has never been requested or added, so it has no file to report"
            )
        body: dict[str, Any] = {"issueType": ISSUE_TYPES[problem], "message": message, "mediaId": info["id"]}
        if media_type == "tv":
            body["problemSeason"] = int(args.get("season") or 0)
            body["problemEpisode"] = int(args.get("episode") or 0)
        elif args.get("season") is not None or args.get("episode") is not None:
            raise InvalidArgument("season and episode are for shows")
        created = await self.seerr.post("/issue", body)
        return {"issue_id": (created or {}).get("id"), "title": details.get("title") or details.get("name"), "problem": problem}
