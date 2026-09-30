[简体中文](README.md) | English

# Remember-Me

**Remember-Me — originally created by Ting (peanutsuee)**

Remember-Me is an independent image memory, storage, retrieval, and management
project. Original concept, product design, and independent project initiated by
Ting (peanutsuee).

Official repository: https://github.com/peanutsuee/Remember-Me

Stage 7E requires Python 3.10 or newer because the stable official MCP Python
SDK v1 requires Python 3.10+.

## Stage 7H-A status

The current package version is `0.1.0.dev8`. The privacy-safe image core,
Standalone HTTP Host, original local Dashboard, and public Standalone MCP
server are implemented for local development.

- The Dashboard is available for local preview and real asset operations at
  `/dashboard`.
- PNG/JPEG upload, cleaning, browsing, search, filtering, metadata editing,
  cleaned-image preview, and safe deletion are connected through `/api/v1`.
- The Dashboard is an independent Dusk Archive design and does not copy or
  reuse the Ombre-Brain Dashboard.
- The Dashboard has not been integrated into Ombre Brain.
- The MCP address is `/mcp` and uses Streamable HTTP.
- MCP, the HTTP API, and the Dashboard share one Core runtime, repository,
  content store, and SQLite database.
- The MCP server exposes exactly nine public `rm_asset_*` tools and no
  diagnostic tools.
- The Core supports Pillow 10.4 through 12.x. The accepted Pillow 12 target
  for current Ombre-Brain compatibility is Pillow 12.3.0.
- The Stage 7F fixed fixtures produced identical cleaned bytes under Pillow
  10.4.0, 11.3.0, and 12.3.0. Encoder output can still change in a future
  Pillow release or for other inputs, so production environments should pin
  the exact Pillow version they have tested.
- Claude one-click attachment saving has not been implemented.
- This remains an early development version, is not deployable as a complete
  production product, and has not been deployed.

Remember-Me is the single long-term image-core source. Ombre Brain may consume
it later through a thin plugin or adapter rather than maintain a copied core.
The current design is single-user and does not promise multi-tenant behavior.
Two independent processes must not write the same SQLite database.

## Local Dashboard preview

No deployment or account registration is required.

Windows PowerShell:

From the Remember-Me repository root:

```powershell
py -m venv .venv

.\.venv\Scripts\python.exe -m pip install -e ".[standalone,test]"

.\.venv\Scripts\python.exe -m remember_me serve `
  --data-root ".\.dashboard-preview"
```

Open:

```text
http://127.0.0.1:8787/dashboard
```

Stop the Host with `Ctrl+C`.

`.dashboard-preview` is local test data. It does not connect to Ombre Brain,
Render, or production data and can be deleted after the preview. The default
loopback mode does not require a Token. Do not let two processes write the same
data directory.

macOS or Linux:

From the Remember-Me repository root:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[standalone,test]"
./.venv/bin/python -m remember_me serve \
  --data-root "./.dashboard-preview"
```

Then open `http://127.0.0.1:8787/dashboard` and stop with `Ctrl+C`.

See `docs/dashboard.md`, `docs/design-system.md`,
`docs/standalone-host.md`, `docs/http-api.md`, `docs/mcp.md`,
`docs/mcp-tools.md`, and `docs/security.md`.

## Local MCP

The same `remember-me serve` process exposes MCP at:

```text
http://127.0.0.1:8787/mcp
```

The formal tool names are:

- `rm_asset_upload_link`
- `rm_asset_upload_status`
- `rm_asset_get`
- `rm_asset_update_metadata`
- `rm_asset_reindex_embeddings`
- `rm_asset_search`
- `rm_asset_download_link`
- `rm_asset_view`
- `rm_asset_inspect`

When a Standalone Bearer Token is configured, MCP clients must send it in the
`Authorization` Header. The Token is never accepted in a URL or Cookie.
Signed upload and download URLs use separate short-lived Ticket credentials.

`REMEMBER_ME_PUBLIC_BASE_URL` controls the absolute base used for signed URLs.
It must be an absolute URL without credentials, query, or fragment.
Non-loopback network use requires HTTPS. If it is omitted in loopback mode,
Remember-Me uses `http://127.0.0.1:<port>`. The Host never derives signed URLs
from untrusted Host or forwarded headers.

## Dashboard security

The Dashboard page and static files are public to load, but asset APIs retain
the existing Bearer authentication policy. In Token mode, the user unlocks the
archive in the current tab. The Token is stored only in `sessionStorage`, never
in localStorage, a Cookie, a URL, or page content.

Images are fetched with an Authorization Header, converted to Blob Object URLs,
loaded lazily with bounded concurrency, and revoked when no longer needed.
User metadata is rendered with safe DOM text APIs rather than executable HTML.

The Dashboard uses a restrictive CSP, no external fonts or scripts, no
third-party requests, no wildcard CORS, no analytics, and no telemetry. The
Standalone Host does not provide TLS and is not a deployment package.
Any non-loopback bind still requires `REMEMBER_ME_ALLOW_NETWORK=true` and a
valid Bearer Token.

## Local Python core

```python
from remember_me import create_local_service

service = create_local_service("./remember-me-data")
```

The caller owns process lifecycle, access control, and backup policy.

## Version dimensions

- Python package: `0.1.0.dev8`
- HTTP API: `v1alpha1`, routes under `/api/v1`
- Dashboard: `v1alpha1`
- MCP API: `v1alpha1`, Streamable HTTP at `/mcp`
- Data compatibility: `ombre-brain-assets-v1`

These versions evolve independently. The HTTP API, Dashboard, and MCP API
remain development contracts without a long-term stability promise.

The Pillow range does not change `ombre-brain-assets-v1`, sanitizer behavior,
hash algorithms, content-addressed paths, or public API contracts. Revalidate
image output before upgrading a pinned production Pillow version.

## Trusted single-asset import

`RememberMeCore.import_asset()` is the synchronous public boundary for a trusted
Host to import one trusted, already-cleaned legacy PNG or JPEG. Core still
validates image structure and metadata. Import preserves a valid 32-character
lowercase hexadecimal asset ID, asset timestamps, metadata, and each tag's
creation time.
It accepts cleaned bytes, never a filesystem path, CAS key, Ticket, URL,
embedding, vector, or model identity. Remember-Me derives the CAS path from the
actual stored SHA-256 and MIME type.

`stored_sha256` is recomputed from the supplied cleaned bytes and must match
exactly. `source_sha256` is historical provenance for original upload bytes
that may no longer exist; Import validates its lowercase SHA-256 format and
preserves it without claiming to recompute it from cleaned bytes. The compatible
`decoded_bytes` field likewise records the original received byte length, so it
is range-validated but cannot be reconstructed from cleaned bytes.

Import validates the existing PNG/JPEG byte stream without re-encoding it.
`dry_run=True` performs validation, blob integrity checks, and conflict checks
without creating files or database rows. Repeating a completely identical
record is an idempotent skip. A changed persistent field for the same asset ID,
or ownership of the same stored SHA by another ID, is a stable conflict. Import
does not create embeddings, Tickets, links, aliases, migrations, or batch jobs.
It rejects `kind=file`; Stage 7H-A supports only PNG and JPEG images. Import
does not enable a runtime, migrate production, or execute Reindex. Embeddings
are not migrated and must be rebuilt later through an explicitly authorized
Reindex. Hosts must call the public Core contract and must not depend on internal
storage or repository modules.

## Public upload rule

The public upload interface does not accept `expected_sha256`. The server
computes authoritative hashes after receiving bytes. Clients and models must
not guess or supply a hash. Public responses and the Dashboard do not expose
source hashes, stored hashes, blob keys, data roots, or filesystem paths.

## Claude network settings

Claude chat attachments are not automatically injected into standard MCP tool
calls. One-click saving requires a code-execution environment to send the
original bytes to a short-lived URL returned by `rm_asset_upload_link`, and
will require enabling `Allow network egress`.

Under `Additional allowed domains`, enter only the hostname of your own
Remember-Me deployment:

- enter a hostname only;
- do not include `https://`;
- do not include a path;
- do not include a Token;
- do not include a signed URL;
- keep restricted-domain mode enabled;
- do not enable `All domains`.

Manual uploads through the Dashboard do not require Claude network access.
Use only the precise hostname of your own Remember-Me Host. Do not enable
`All domains`. Stage 7E provides signed transfer URLs but does not deploy a
Host or automatically obtain current-chat attachment bytes.

## Origin and licensing

Independently written Remember-Me code and documentation are licensed under the
Common Public Attribution License Version 1.0 (`CPAL-1.0`) as identified per
file and in `LICENSE`.

The six Stage 7B core modules were independently reimplemented from a frozen
behavioral specification, public contracts, sanitized tests, and data
compatibility requirements through a documented clean-room engineering
process.

This engineering process and its similarity reviews do not by themselves
determine copyright ownership, legal independence, or license obligations.

The repository also preserves applicable upstream MIT notices for content and
historical distributions that remain covered, including:

`Copyright (c) 2026 P0lar1zzZ`

The Stage 7D Dashboard and Stage 7E MCP adapter are original CPAL
implementations. No Ombre-Brain
Dashboard HTML, CSS, JavaScript, layout, visual system, authentication, Cookie,
CSRF, MCP, transfer, Viewer, or tool-registration code was read or copied.
See `NOTICE`,
`LICENSES/MIT-Ombre-Brain.txt`, and `docs/source-provenance.md`.

## Unicode metadata and semantic search

`0.1.0.dev8` preserves safely cleaned metadata spelling without NFC or
NFKC storage/display rewriting. Comparison, tag identity, search and filtering
use separate NFKC canonical keys. Schema and blob/hash identity are unchanged;
there is no historical spelling restoration or migration. Import preserves
spelling and timestamps but rejects canonical tag collisions. Older import and
search implementations may not support new spelling. See
[data compatibility](docs/data-compatibility.md).

With an injected vector provider, pure semantic matches require a cosine score
of at least `0.42` by default. Keyword matches remain; a score below the
threshold adds neither a `semantic` reason nor `semantic_score`. Core callers
may set `semantic_min_score` in `create_local_runtime(...)` or
`create_local_service(...)` to a finite value in `[0, 1]`. Explicit `0` keeps
the former positive-score behavior. No match succeeds with `total=0` and
`results=[]`. The default `NullVectorProvider` remains keyword-only.

Reindex validates a new vector and checks the asset and provider state before
atomically replacing the old record. Generation failure or cancellation keeps
the old record. Explicit no-text and disabled-provider cleanup remains
synchronous. Batches process each asset independently and retries skip records
already current. See the [Core contract](docs/public-api-contract.md).
