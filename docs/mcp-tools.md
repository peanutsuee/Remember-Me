<!-- SPDX-License-Identifier: CPAL-1.0 -->

# MCP Tools v1alpha1

The raw `tools/list` result contains exactly these nine names:

| Tool | Purpose |
| --- | --- |
| `rm_asset_upload_link` | Create a five-minute single-use upload URL. |
| `rm_asset_upload_status` | Read pending, processing, completed, failed, or expired status. |
| `rm_asset_get` | Read safe public asset metadata. |
| `rm_asset_update_metadata` | Replace selected title, description, or tags. |
| `rm_asset_reindex_embeddings` | Process a bounded optional embedding batch. |
| `rm_asset_search` | Run stable keyword search and filters. |
| `rm_asset_download_link` | Create a five-minute cleaned-image download URL. |
| `rm_asset_view` | Return an MCP App Viewer result with a text fallback. |
| `rm_asset_inspect` | Return a verified cleaned image as MCP ImageContent. |

No probe, diagnostic, delete, administrator, Ombre-Brain, or legacy
`asset_*` tools are registered.

## Upload link schema

```text
rm_asset_upload_link(
    expected_bytes: int,
    filename: str = "",
    mime_type: str = "application/octet-stream"
)
```

`expected_bytes` is required and limited to 10 MiB. MIME may be `image/png`,
`image/jpeg`, or `application/octet-stream`. The public schema does not
contain `expected_sha256` or any other client-supplied hash. The server
computes authoritative hashes only after receiving and decoding the bytes.

The returned URL accepts one multipart `file` field. It calls the existing
privacy sanitizer and Core ingest operation. No target path can be supplied.

## Search schema

`rm_asset_search` accepts `query`, `tags`, `kind`, `mime_type`,
`created_from`, `created_to`, `limit`, and `offset`. The default limit is 20
and the maximum is 50. The MCP adapter delegates once to the asynchronous Core
search operation; it does not embed queries, read vectors, calculate cosine, or
rank results itself. With an enabled host-injected provider, current same-model
and same-dimension embeddings may contribute semantic matches through the
existing result contract. The `NullVectorProvider` keeps the default Standalone
runtime keyword-only and network-free.
Core's default semantic minimum is `0.42`, configurable through its Python
constructor or factory. The MCP search input and output schemas are unchanged;
low-score pure semantic candidates are absent, and no match returns an empty
`items` list with `total=0`.

## Metadata and embeddings

`rm_asset_update_metadata` accepts `asset_id` and at least one of `title`,
`description`, or `tags`. It never changes image bytes or the asset ID.

`rm_asset_reindex_embeddings` accepts optional `asset_id` and a batch `limit`
from 1 through 500. It delegates once to the Core `reindex_embeddings`
operation; the MCP adapter does not build index text, hash content, call the
provider, write the repository, or implement counters. With the default Null
provider it reports `enabled=false`; it does not treat the lack of a vector
service as an error. Its existing `selected`, `indexed`, and `failed` output
shape remains unchanged, and Core-only `scanned` and `skipped` are not exposed.
The `failed` value reflects Core failures even when `enabled=false`; it is not
forced to zero. Reindex preserves an old vector during provider failure or
cancellation and replaces it only after a validated result is ready.
Stage 7G-B search consumes current embeddings in Core without changing the
nine MCP tool names, input schemas, output envelope, or error envelope.
Provider and per-record vector failures do not become new public MCP errors.

## Cleaned image outputs

`rm_asset_download_link` serves only the stored privacy-cleaned image.
`rm_asset_inspect` places base64 only in MCP ImageContent.
`rm_asset_view` places Viewer image base64 only in a dedicated
`_meta.remember_me.image` namespace. TextContent and structuredContent never
contain image base64, complete hashes, blob keys, SQLite paths, data roots, or
filesystem paths.

The Viewer resource is:

```text
ui://remember-me/asset-viewer.html
```

Its MIME type is `text/html;profile=mcp-app`. The authoritative tool metadata
is the nested `ui.resourceUri` field. The Viewer is an original CPAL-1.0
implementation and loads no external resources. It initializes the standard
MCP Apps Host-to-View JSON-RPC channel before accepting
`ui/notifications/tool-result`. `window.openai.toolOutput` remains an optional
host compatibility fallback; it is not required by the standard protocol and
the Viewer does not depend on it.

## About resource

`remember-me://about` returns canonical project and protocol metadata,
including:

```text
Remember-Me was originally created by Ting.
Ting (peanutsuee)
```

It contains no Host name, Token, data path, or deployment information.
