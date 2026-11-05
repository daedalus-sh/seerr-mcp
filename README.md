# seerr-mcp

An [MCP](https://modelcontextprotocol.io) server that gives an AI assistant
your [Seerr](https://github.com/seerr-team/seerr): find a movie or a show,
see whether it is already in your library, on its way (and how far along),
or nowhere; request it; and report a problem with a file.

It talks to Seerr's REST API with Seerr's API key, which acts as Seerr's
first user, the admin: a request made here is approved at once and sent to
Radarr or Sonarr, as one made in Seerr's own page would be. It speaks MCP
over streamable HTTP behind a bearer token and keeps nothing on disk.

Written against Seerr v3.5.1.

## Tools

Read

| Tool | |
|---|---|
| `search` | Movies and shows by name, each with its state in the house: not requested, pending, processing, partially available, available. |
| `get_title` | One title: overview, genres, runtime or seasons (each season's state), what is downloading now (percent, ETA), its requests, Rotten Tomatoes and IMDb ratings, and where to stream, rent or buy it in one country. |
| `list_requests` | Requests by state (pending approval, approved, declined, failed, completed) or type, with titles. |
| `recently_added` | What arrived in the library most recently. |
| `list_issues` | Reported problems (video, audio, subtitles, other), open by default. |

Write

| Tool | |
|---|---|
| `request` | **Downloads.** A movie, or a show (every season unless seasons are named). Approved at once, as the admin: Radarr or Sonarr start downloading straight away. |
| `cancel_request` | Delete a request: anyone's, since the key is the admin's. Destructive; cannot be undone. |
| `report_issue` | A problem with a title's file, with a message, and a season and episode for a show. |

Annotations are honest: `readOnlyHint` on reads; `openWorldHint` on
`request`, whose effect leaves the house (an indexer search and a download);
`destructiveHint` on `cancel_request`.

## Configuration

| Variable | |
|---|---|
| `MCP_BEARER_TOKEN` | Required, 16+ characters. Every request but `GET /healthz` must carry `Authorization: Bearer <it>`. |
| `SEERR_URL` | Required. Seerr's base URL, e.g. `http://seerr:5055`. |
| `SEERR_API_KEY` | Required. Seerr › Settings › General › API Key. |
| `SEERR_WATCH_REGION` | A two-letter country code for `get_title`'s streaming, rent and buy lists. |
| `MCP_LISTEN` | Default `0.0.0.0:8080`. MCP is at `/mcp`. |

`GET /healthz` answers `ok` only while Seerr accepts the API key.

## Run

```
nix run github:santiagotoscanini/seerr-mcp
```

or install the package (`pip install .`, Python 3.12+) and run `seerr-mcp`.

## Develop

```
nix flake check      # the test suite (in the package's build) and ruff
```

## Licence

MIT.
