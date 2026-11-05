from __future__ import annotations

import pytest

from seerr_mcp import config

OK = {"MCP_BEARER_TOKEN": "x" * 16, "SEERR_URL": "http://seerr:5055/", "SEERR_API_KEY": "k" * 20}


def test_minimal() -> None:
    s = config.load(OK)
    assert (s.url, s.listen_port, s.watch_region) == ("http://seerr:5055", 8080, None)
    assert "k" * 20 not in repr(s) and "x" * 16 not in repr(s)


def test_region() -> None:
    assert config.load({**OK, "SEERR_WATCH_REGION": "ar"}).watch_region == "AR"


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        ({"MCP_BEARER_TOKEN": "short"}, "MCP_BEARER_TOKEN"),
        ({"SEERR_API_KEY": ""}, "SEERR_API_KEY must be set"),
        ({"SEERR_API_KEY": "two words"}, "single token"),
        ({"SEERR_URL": ""}, "SEERR_URL must be set"),
        ({"SEERR_URL": "ftp://seerr"}, "http://"),
        ({"SEERR_URL": "http://u:p@seerr"}, "credentials"),
        ({"MCP_LISTEN": "8080"}, "host:port"),
        ({"SEERR_WATCH_REGION": "ARG"}, "two-letter"),
    ],
)
def test_refuses(extra: dict[str, str], needle: str) -> None:
    with pytest.raises(config.ConfigError, match=needle):
        config.load({**OK, **extra})
