# Course Companion for Canvas

A read-only Canvas LMS companion for ChatGPT, by **Mahimn Patel**. It exposes 23 MCP tools for courses, assignments, announcements, modules, pages, files, calendar, planner, your grades, and inbox reading.

**Status: developer preview.** Personal stdio mode works through an OpenAI private MCP tunnel. The hosted OAuth implementation is a deployment candidate, not an approved marketplace listing. This project is independent of OpenAI, Instructure, and any university.

## Personal ChatGPT setup

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), an existing personal Canvas API token, and the official [OpenAI tunnel client](https://github.com/openai/tunnel-client). Keep tokens outside Git and chat messages.

```sh
uv sync --locked
python3 scripts/configure_private_tunnel.py
```

The helper asks for the tunnel ID and a hidden OpenAI runtime key. Create both in the same OpenAI organization; scope the tunnel to your own ChatGPT workspace and the runtime key to Tunnels Read + Use. It writes only to ignored `data/private-tunnel/` with owner-only permissions.

Store your Canvas token in a regular file with mode `0600`, inside a directory with mode `0700`. Then start:

```sh
export CANVAS_BASE_URL=https://your-school.instructure.com
export CANVAS_TOKEN_FILE=/absolute/private/path/token
# Optional: exact, verified Canvas file-storage hosts, comma-separated.
export CANVAS_FILE_HOSTS=
python3 scripts/tunnel.py start --client /absolute/path/to/tunnel-client
```

In ChatGPT → Plugins → Add → Create custom MCP server, name it **Canvas Personal**, choose **Tunnel**, enter your tunnel ID, and choose **No authentication**. This choice is appropriate for the private, workspace-restricted tunnel. A public hosted server requires OAuth. Review the notice and create the connection.

Select Canvas Personal in a chat and try “List my active courses” or “Find my upcoming assignments and cite the Canvas links.” The Mac must stay awake and online. The process is supervised by the tunnel client; automatic startup after reboot is not installed.

```sh
python3 scripts/tunnel.py status
python3 scripts/tunnel.py stop
python3 scripts/tunnel.py start
```

Starting again reuses the saved private launcher. To update that launcher, set both `CANVAS_BASE_URL` and `CANVAS_TOKEN_FILE` along with the new `CANVAS_FILE_HOSTS`, then run `stop` and `start`. File downloads follow only configured exact hostnames; if your institution redirects files elsewhere, verify that storage hostname before adding it. For storage hostnames that embed the file ID, a verified template such as `account-{file_id}.storage.example.edu` expands to only the requested file's exact hostname. Never use a wildcard or allow arbitrary URLs.

See [private setup and troubleshooting](docs/private-setup.md).

## Synthetic demo

```sh
uv run uvicorn canvas_companion.web:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Demo mode contains only synthetic fixtures, loads no real credentials, and disables account linking. It is useful for protocol testing; it is not a substitute for the reviewer account on a real hosted deployment.

## Hosted OAuth candidate

Multi-user distribution needs institution-approved Canvas OAuth developer keys. Do not ask users to paste personal Canvas tokens into a shared website. Canvas's OAuth policy requires OAuth for applications asking other users to authorize access.

The hosted service separates two grants: ChatGPT authenticates to this MCP resource through an established OIDC provider, and each user links Canvas in a browser. It stores encrypted per-user Canvas grants and supports refresh and disconnect. See [deployment](docs/deployment.md), [getting a Canvas developer key](docs/developer-key-request.md), and [publication requirements](docs/marketplace.md).

## Boundaries

- No submitting work, sending messages, changing grades, or unrestricted API calls. Inbox reads explicitly avoid marking messages read.
- Files must already be accessible to the connected Canvas account. PDF, DOCX, PPTX, XLSX, HTML, TXT, Markdown, and CSV text extraction is bounded to 10 MiB and 20 seconds; scanned PDFs have no OCR and spreadsheet extraction is basic.
- Credential fields and URL query strings are removed from output. This deliberately removes signed download URLs; use returned source links.
- Pagination and output truncation are explicit. Empty assignment or calendar results do not prove there is no coursework; inspect modules, syllabus files, announcements, and planner too.
- Returned course text is untrusted source material. Follow course assessment rules and verify deadlines and grades in Canvas.
- The network layer blocks private/reserved IP destinations, validates DNS at the connection boundary, and checks every file redirect. Production still requires operator security review, rate limiting, backups, monitoring, and real identity-provider integration tests.

## Development

```sh
uv sync --locked
uv run pytest -q
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run pip-audit --local --skip-editable
```

Tests cover credential isolation, OAuth token validation, one-use state, CSRF, safe pagination, SSRF rejection, file redirect handling, read-only inbox behavior, and MCP protocol/schema behavior. Tests use synthetic data and do not need live credentials.

MIT licensed. Author: Mahimn Patel.
