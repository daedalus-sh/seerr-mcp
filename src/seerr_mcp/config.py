"""Settings from the environment. Anything ambiguous refuses to start."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

MIN_TOKEN = 16
DEFAULT_LISTEN = "0.0.0.0:8080"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    listen_host: str
    listen_port: int
    url: str
    api_key: str = field(repr=False)
    # ISO 3166 country whose streaming, rent and buy options a title lists;
    # None = Seerr's own region setting, then every country.
    watch_region: str | None = None


def _port(name: str, value: str) -> int:
    if not value.strip().isdigit() or not 0 < int(value) < 65536:
        raise ConfigError(f"{name} must be a TCP port")
    return int(value)


def _listen(value: str) -> tuple[str, int]:
    host, sep, port = value.rpartition(":")
    if not sep or not host:
        raise ConfigError("MCP_LISTEN must be host:port")
    return host.strip("[]"), _port("MCP_LISTEN", port)


def _url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ConfigError("SEERR_URL must be set, e.g. http://seerr:5055")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("SEERR_URL must be an http:// or https:// URL")
    if parts.username or parts.password:
        raise ConfigError("SEERR_URL must not carry credentials; use SEERR_API_KEY")
    if parts.query or parts.fragment:
        raise ConfigError("SEERR_URL must not have a query or fragment")
    return value.rstrip("/")


def _region(value: str) -> str | None:
    value = value.strip().upper()
    if not value:
        return None
    if len(value) != 2 or not value.isalpha():
        raise ConfigError("SEERR_WATCH_REGION must be a two-letter country code, e.g. AR")
    return value


def load(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    token = env.get("MCP_BEARER_TOKEN", "")
    if len(token) < MIN_TOKEN:
        raise ConfigError(f"MCP_BEARER_TOKEN must be set (at least {MIN_TOKEN} characters)")
    api_key = env.get("SEERR_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("SEERR_API_KEY must be set: Seerr › Settings › General › API Key")
    if any(c in api_key for c in " \t\r\n\0"):
        raise ConfigError("SEERR_API_KEY must be a single token with no spaces")
    host, port = _listen(env.get("MCP_LISTEN", DEFAULT_LISTEN))
    return Settings(
        token=token,
        listen_host=host,
        listen_port=port,
        url=_url(env.get("SEERR_URL", "")),
        api_key=api_key,
        watch_region=_region(env.get("SEERR_WATCH_REGION", "")),
    )
