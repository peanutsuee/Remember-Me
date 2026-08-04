<!-- SPDX-License-Identifier: CPAL-1.0 -->

# HTTP API

The development API identifier is `v1alpha1`; routes use `/api/v1`. This alpha
contract can change independently from the Python package version.

## Authentication

When configured, every asset route requires:

```text
Authorization: Bearer $REMEMBER_ME_TOKEN
```

The Token is not accepted in query parameters or Cookies. `/healthz`,
`/readyz`, `/api/v1/about`, `/dashboard`, and Dashboard static files are public.

Stage 7E also adds signed transfer routes used only with short-lived Tickets
created by MCP tools. They are not a second asset backend and are omitted from
OpenAPI. Signed uploads call the same `RememberMeService`; signed downloads
return only the privacy-cleaned stored copy.

## Routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/healthz` | Minimal liveness. |
| GET | `/readyz` | Read-only database and assets-root readiness. |
| GET | `/api/v1/about` | Canonical project and version identity. |
| POST | `/api/v1/assets` | Upload and sanitize a PNG or JPEG. |
| GET | `/api/v1/assets` | Search and filter assets. |
| GET | `/api/v1/assets/{asset_id}` | Read public metadata. |
| PATCH | `/api/v1/assets/{asset_id}` | Edit title, description, or tags. |
| GET | `/api/v1/assets/{asset_id}/content` | Read cleaned image bytes. |
| DELETE | `/api/v1/assets/{asset_id}` | Coordinated metadata/blob deletion. |

Upload is `multipart/form-data` with required `file` and `expected_bytes`,
optional `filename`, `mime_type`, `title`, `description`, and repeated `tag`.
It does not accept `expected_sha256`, other hashes, blob keys, or target paths.
A new asset returns 201; cleaned-content deduplication returns 200 and does not
overwrite existing metadata.

```sh
curl -H "Authorization: Bearer $REMEMBER_ME_TOKEN" \
  -F "file=@photo.png;type=image/png" \
  -F "expected_bytes=<BYTE_COUNT>" \
  -F "title=Example" \
  -F "tag=local" \
  http://127.0.0.1:8787/api/v1/assets
```

Search accepts `query`, repeated `tag`, `kind`, `mime_type`, `created_from`,
`created_to`, `limit`, and `offset`. The default `limit` is 20 and the HTTP
maximum is 50.

PATCH accepts only `title`, `description`, and `tags`. Missing fields are
unchanged; empty strings clear text and an empty list clears tags. Explicit
null, unknown fields, and an empty object are rejected.

Public asset responses include `asset_id`, original filename, MIME, kind,
decoded/stored byte counts, dimensions, timestamps, title, description, and
tags. They never include source hashes, stored hashes, stored relative paths,
blob keys, data roots, or absolute paths.

Errors use:

```json
{
  "error": {
    "code": "asset_unavailable",
    "message": "Asset is unavailable.",
    "request_id": "<REQUEST_ID>"
  }
}
```

Expected statuses include 400 invalid input, 401 authentication failure, 404
unavailable assets, 409 conflicts, 413 size limits, 422 structured validation,
500 internal failures, and 503 readiness failure. Every response includes
`X-Request-ID`.

The Dashboard does not add a second asset backend. It consumes these same
routes for upload, search, metadata, content, and deletion.
