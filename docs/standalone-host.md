<!-- SPDX-License-Identifier: CPAL-1.0 -->

# Standalone Host

The Standalone Host provides a single-user local HTTP API, the Dashboard at
`/dashboard`, and Streamable HTTP MCP at `/mcp`. It is not an account system,
multi-tenant service, or production deployment package.

## Install

```text
pip install "remember-me[standalone]"
```

The tested Stage 7F stack is MCP SDK 1.28.1, FastAPI 0.115.14, Starlette
0.46.2, Uvicorn 0.33.0, Pydantic 2.12.5, python-multipart 0.0.32, and HTTPX
0.28.1. Python 3.10 or newer is required. Pillow 10.4 through 12.x is
supported; production installations should pin an exact tested Pillow
version. The current Ombre-Brain compatibility target is Pillow 12.3.0.

## Local start

Windows PowerShell:

```powershell
remember-me serve
remember-me serve --data-root "$HOME\.remember-me"
```

macOS or Linux:

```sh
remember-me serve
remember-me serve --data-root "$HOME/.remember-me"
```

Stop the foreground process with the terminal interrupt command. Uvicorn
performs normal ASGI shutdown; the current SQLite implementation does not keep
a global connection open.

## Configuration

Precedence is command line, then `REMEMBER_ME_` environment variables, then
safe defaults.

| Setting | Environment variable | Default |
| --- | --- | --- |
| Data root | `REMEMBER_ME_DATA_ROOT` | `~/.remember-me` |
| Host | `REMEMBER_ME_HOST` | `127.0.0.1` |
| Port | `REMEMBER_ME_PORT` | `8787` |
| Token | `REMEMBER_ME_AUTH_TOKEN` | unset |
| Token file | `REMEMBER_ME_AUTH_TOKEN_FILE` | unset |
| Network gate | `REMEMBER_ME_ALLOW_NETWORK` | `False` |
| API docs | `REMEMBER_ME_ENABLE_DOCS` | `False` |
| Log level | `REMEMBER_ME_LOG_LEVEL` | `INFO` |
| Signed-link base | `REMEMBER_ME_PUBLIC_BASE_URL` | loopback URL |

Boolean values accept trimmed, case-insensitive `1`, `true`, `yes`, and `on`
as true; `0`, `false`, `no`, `off`, and an empty value are false. Other values
are configuration errors.

The CLI supports `--data-root`, `--host`, `--port`, `--auth-token-file`,
`--allow-network`, `--enable-docs`, `--log-level`, and
`--public-base-url`. It deliberately has no `--auth-token` option.

`REMEMBER_ME_PUBLIC_BASE_URL` must be an absolute HTTP or HTTPS URL without
credentials, query, or fragment. Loopback may use HTTP. A non-loopback
deployment must use HTTPS. When omitted outside loopback, the Host can still
start safely, but signed link creation is unavailable rather than being
derived from an untrusted request Host.

## Token file

Use a regular text file containing one Token of at least 32 characters:

```powershell
$env:REMEMBER_ME_AUTH_TOKEN_FILE="$HOME\.remember-me-token"
remember-me serve
```

```sh
export REMEMBER_ME_AUTH_TOKEN_FILE="$HOME/.remember-me-token"
remember-me serve
```

Do not place `<YOUR_TOKEN>` in a URL or command argument. Configuring both the
Token environment variable and a Token file is rejected.

## Network mode

`localhost`, `127.0.0.1`, and `::1` are loopback. Any other bind address
requires both an explicit network gate and a valid Token:

```powershell
$env:REMEMBER_ME_ALLOW_NETWORK="true"
$env:REMEMBER_ME_AUTH_TOKEN_FILE="$HOME\.remember-me-token"
remember-me serve --host 0.0.0.0
```

The Host does not provide TLS, trusted-proxy handling, or automatic proxy
headers. Do not expose plaintext HTTP directly to the public internet. A
network deployment must use a trusted HTTPS reverse proxy and is outside the
Stage 7E deployment acceptance scope.

The data root contains `assets.sqlite3`, content-addressed `assets/`, and the
controlled `assets/.tmp/` directory. Do not run two independent writers against
the same data root.

Dashboard preview instructions are in `docs/dashboard.md`. The Dashboard and
static files require no Token to load. Asset requests continue to use the
configured Bearer policy. MCP uses the same policy: loopback without a Token
is available locally; once a Token is configured, every `/mcp` request must
send `Authorization: Bearer <token>`.
