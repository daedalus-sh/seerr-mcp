"""Tool definitions: names, descriptions, input schemas, annotations.

Annotations are honest so a client can ask before the ones that matter:
reads are readOnly; a request reaches outside the house (Radarr or Sonarr
search the indexers and download), so it is openWorld; cancelling a request
is destructive; an issue report adds an entry every call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp import types

from .service import ISSUE_TYPES, REQUEST_FILTERS, Requests

TMDB_ID = {"type": "integer", "minimum": 1, "description": "The title's TMDB id, from search."}
TYPE = {"type": "string", "enum": ["movie", "show"]}
REGION = {
    "type": "string",
    "pattern": "^[A-Za-z]{2}$",
    "description": "A two-letter country code for where_to_watch, e.g. when travelling.",
}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def _ann(title: str, read_only: bool, destructive: bool, idempotent: bool, open_world: bool = False) -> types.ToolAnnotations:
    return types.ToolAnnotations(
        title=title,
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


READ = dict(read_only=True, destructive=False, idempotent=True)


@dataclass(frozen=True)
class ToolSpec:
    tool: types.Tool
    call: Callable[[Requests, dict[str, Any]], Awaitable[dict[str, Any]]]


def _tool(
    name: str,
    description: str,
    schema: dict[str, Any],
    annotations: types.ToolAnnotations,
    call: Callable[[Requests, dict[str, Any]], Awaitable[dict[str, Any]]],
) -> ToolSpec:
    return ToolSpec(types.Tool(name=name, description=description, inputSchema=schema, annotations=annotations), call)


TOOLS: list[ToolSpec] = [
    # ── read ────────────────────────────────────────────────────────────
    _tool(
        "search",
        "Find movies and shows by name. Each result has its TMDB id, type, title, year and status in the house: "
        "not_requested, pending (requested, waiting for approval), processing (approved; downloading or waiting "
        "for a release), partially_available (some seasons), available (in the library), blocklisted or deleted. "
        "Paged: pass next_page as page for more.",
        _schema(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "page": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ["query"],
        ),
        _ann("Search movies and shows", **READ),
        lambda s, a: s.search(a),
    ),
    _tool(
        "get_title",
        "One movie or show: year, genres, overview, runtime (movies), seasons with episode counts and each "
        "season's status (shows), its status in the house, what is downloading for it now (percent and ETA), "
        "its requests (each with request_id and status), Rotten Tomatoes and IMDb ratings, and where it can be "
        "streamed, rented or bought in this server's country (or region's).",
        _schema(
            {
                "type": TYPE,
                "tmdb_id": TMDB_ID,
                "region": REGION,
                "max_overview_chars": {"type": "integer", "minimum": 0, "maximum": 5000, "description": "Default 800."},
            },
            ["type", "tmdb_id"],
        ),
        _ann("Look up a movie or show", **READ),
        lambda s, a: s.get_title(a),
    ),
    _tool(
        "list_requests",
        "Requests, newest first: each with its title, request_id, status (pending_approval, approved, declined, "
        "failed, completed), who asked, when, the seasons asked for, and the title's status in the house. "
        "Optionally one state or one type. Paged.",
        _schema(
            {
                "filter": {"type": "string", "enum": list(REQUEST_FILTERS), "description": "Default 'all'."},
                "type": TYPE,
                "sort": {"type": "string", "enum": ["added", "modified"], "description": "Default 'added'."},
                "page": {"type": "integer", "minimum": 1, "maximum": 1000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Default 10."},
            }
        ),
        _ann("List requests", **READ),
        lambda s, a: s.list_requests(a),
    ),
    _tool(
        "recently_added",
        "What arrived in the library most recently, newest first, with when it was added.",
        _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Default 10."}}),
        _ann("Recently added", **READ),
        lambda s, a: s.recently_added(a),
    ),
    _tool(
        "list_issues",
        "Problems reported with files in the library (video, audio, subtitles, other), open ones unless filter "
        "says otherwise: each with its title, season and episode, what was said, who reported it and when.",
        _schema(
            {
                "filter": {"type": "string", "enum": ["open", "resolved", "all"], "description": "Default 'open'."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Default 10."},
            }
        ),
        _ann("List issues", **READ),
        lambda s, a: s.list_issues(a),
    ),
    # ── write ───────────────────────────────────────────────────────────
    _tool(
        "request",
        "DOWNLOADS. Request a movie or a show for the library. This server acts as Seerr's admin, so the request "
        "is approved immediately, with no one reviewing it, and Radarr or Sonarr start searching the indexers "
        "and downloading straight away. For a show, leaving out seasons requests EVERY season; pass seasons to "
        "ask for fewer. Call it only when the person asked for this title to be downloaded. Refused with "
        "already_requested when Seerr has it (or those seasons) already; get_title shows what exists.",
        _schema(
            {
                "type": TYPE,
                "tmdb_id": TMDB_ID,
                "seasons": {
                    "oneOf": [
                        {"type": "string", "enum": ["all"]},
                        {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                            "minItems": 1,
                            "maxItems": 100,
                        },
                    ],
                    "description": 'Shows only: "all" (the default) or season numbers.',
                },
            },
            ["type", "tmdb_id"],
        ),
        _ann("Request a title", read_only=False, destructive=False, idempotent=False, open_world=True),
        lambda s, a: s.request(a),
    ),
    _tool(
        "cancel_request",
        "Permanently delete a request (a request_id from list_requests or get_title). This server acts as "
        "Seerr's admin, so it can cancel ANYONE's request, not only this person's: check requested_by and "
        "cancel only what the person asked to cancel. What was already downloaded stays; nothing more is "
        "fetched for it. It cannot be undone, only requested again.",
        _schema({"request_id": {"type": "integer", "minimum": 1}}, ["request_id"]),
        _ann("Cancel a request", read_only=False, destructive=True, idempotent=True),
        lambda s, a: s.cancel_request(a),
    ),
    _tool(
        "report_issue",
        "Report a problem with a title's file in the library: video, audio, subtitles or other, with a message "
        "saying what is wrong, and for a show the season and episode. The house's admins see it in Seerr. The "
        "title must have been requested or added (not_in_seerr otherwise).",
        _schema(
            {
                "type": TYPE,
                "tmdb_id": TMDB_ID,
                "problem": {"type": "string", "enum": list(ISSUE_TYPES)},
                "message": {"type": "string", "minLength": 1, "maxLength": 2000},
                "season": {"type": "integer", "minimum": 0, "maximum": 1000},
                "episode": {"type": "integer", "minimum": 0, "maximum": 100000},
            },
            ["type", "tmdb_id", "problem", "message"],
        ),
        _ann("Report a problem", read_only=False, destructive=False, idempotent=False),
        lambda s, a: s.report_issue(a),
    ),
]

BY_NAME = {t.tool.name: t for t in TOOLS}
