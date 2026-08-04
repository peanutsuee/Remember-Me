<!-- SPDX-License-Identifier: CPAL-1.0 -->

# Standalone Security

Stage 7E is local-first and single-user. It does not implement accounts,
registration, roles, tenant isolation, Cookie sessions, or deployment.

## Exposure boundary

The default listener is `127.0.0.1`. A non-loopback address requires both
`allow_network=True` and a valid Bearer Token. The Host provides no TLS and
must not be exposed as plaintext HTTP to the public internet. Trusted HTTPS
reverse proxy deployment is outside this stage.

Bearer authentication is Header-only and uses constant-time comparison. Tokens
are not accepted in URLs or Cookies and are not logged. Token files are
recommended because command-line Tokens can appear in shell history and process
listings.

The `/mcp` endpoint uses the same Bearer policy. The official SDK's Origin and
DNS-rebinding checks remain enabled. Normal non-browser MCP clients may omit
Origin, but an invalid Host or Origin is rejected. MCP does not accept Tokens
from query parameters or Cookies.

Signed upload and download URLs contain separate high-entropy Ticket
credentials. The server stores only their SHA-256 digests in bounded process
memory. Upload Tickets expire after five minutes and are single-use; a failed
upload cannot be replayed. Download Tickets expire after five minutes, HEAD
does not consume a use, and at most three successful GET attempts are allowed.
Restarting the Host invalidates all Tickets.

## Browser boundary

The Dashboard does not use a Cookie session. The Host does not implement CSRF,
does not enable wildcard CORS, and does not accept cross-origin credentials.
If a future release adds Cookie sessions, it must design CSRF separately; the
current Bearer scheme is not a complete account security model.

In Token mode, the Dashboard stores the Token only in `sessionStorage` for the
current tab. It does not use localStorage, Cookies, URLs, service workers, or
IndexedDB. Asset fetches use `credentials: "omit"` and `cache: "no-store"`.

Dashboard HTML uses a restrictive CSP allowing only same-origin scripts,
styles, connections, and fonts, plus Blob/data image sources. It excludes
unsafe inline script, unsafe evaluation, objects, base URLs, framing, and
external domains. No third-party JavaScript or analytics are loaded.

The packaged `index.html` is served only from `/dashboard` and `/dashboard/`,
where the Host attaches the Dashboard CSP. `/dashboard/static` exposes only the
explicitly allowlisted CSS and JavaScript module names; it does not expose
`index.html` or arbitrary files from the package directory.

## Request and response protection

Image bytes remain limited to 10 MiB. The complete multipart request is limited
to 11 MiB, including overhead. Content-Length is checked early, and the ASGI
receive stream is counted when the header is missing or inaccurate. Structured
request bodies are limited to 64 KiB. Signed multipart uploads use the same
10 MiB image and 11 MiB total request boundaries.

Responses set `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`X-Frame-Options: DENY`, `Cache-Control: no-store`, and `X-Request-ID`. Cleaned
image responses use `Cache-Control: private, no-store`. HSTS is not set because
the Host itself does not provide TLS.

Responses also set `Permissions-Policy: camera=(), microphone=(),
geolocation=()`.

Public asset schemas omit hashes, blob keys, data roots, and filesystem paths.
Content reads use only the Core-resolved confined blob key.

The image sanitizer supports Pillow 10.4 through 12.x and is tested with fixed
synthetic metadata-bearing fixtures. Supported versions preserve the same
decode, orientation, metadata-removal, size-limit, and format rules. The Stage
7F fixtures encoded identically on Pillow 10.4.0, 11.3.0, and 12.3.0, but
encoded bytes remain runtime output and may vary for future releases or other
inputs. A production environment must pin the exact Pillow version it has
accepted. The current Ombre-Brain target is Pillow 12.3.0. Pillow upgrades
require compatibility testing before they are used with persistent asset data.

MCP TextContent and structuredContent follow the same privacy boundary.
Cleaned image base64 appears only in MCP ImageContent or the Viewer-specific
tool-result `_meta`, never in model-visible text or structuredContent.

## Logging

Uvicorn access logs are disabled. Controlled logs contain request ID, method,
route, status, duration, authentication success, and safe error code. They do
not contain Authorization Headers, Tokens, query strings, multipart or JSON
bodies, titles, descriptions, tags, image bytes, complete hashes, blob keys,
data-root paths, or temporary file paths.

API docs are disabled by default. Enabling docs is intended for loopback
development and is not evidence of a secure deployment.
