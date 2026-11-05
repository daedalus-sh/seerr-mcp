"""Typed errors. Every failure a tool reports has a `kind` the model can act on."""

from __future__ import annotations

from typing import Any


class SeerrError(Exception):
    """Base of every error a tool returns to the model."""

    kind = "error"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.kind, "message": self.message}
        out.update(self.detail)
        return out


class Unavailable(SeerrError):
    """Seerr refused the connection, timed out, or answered 5xx."""

    kind = "seerr_unavailable"


class AuthFailed(SeerrError):
    """Seerr did not accept the API key."""

    kind = "auth_failed"


class NotFound(SeerrError):
    kind = "not_found"


class InvalidArgument(SeerrError):
    kind = "invalid_argument"


class UpstreamError(SeerrError):
    """Seerr answered with an error of its own, or something this server does not understand."""

    kind = "upstream_error"


class AlreadyRequested(SeerrError):
    """Seerr already has a request for this title (or these seasons)."""

    kind = "already_requested"


class NotInSeerr(SeerrError):
    """The title has never been requested or added, so Seerr has no record to attach an issue to."""

    kind = "not_in_seerr"
