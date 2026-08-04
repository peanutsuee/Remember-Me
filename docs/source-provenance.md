# Stage 7B Source Provenance

This file records the source and license classification for files created or
materially changed while implementing the Stage 7B local image core.

Remember-Me project identity remains:

Original concept, product design, and independent project initiated by
Ting (peanutsuee).

That project-origin statement does not replace upstream code authorship.

## Independent Stage 7B core reimplementation

The following six core modules were independently reimplemented from a frozen
behavioral specification, public contracts, sanitized tests, and data
compatibility requirements through a documented clean-room engineering
process. They use `SPDX-License-Identifier: CPAL-1.0`.

This engineering process and its similarity reviews do not by themselves
determine copyright ownership, legal independence, or license obligations.

| Remember-Me file | Engineering input | License | Responsibility |
| --- | --- | --- | --- |
| `src/remember_me/imaging/pillow_sanitizer.py` | Frozen behavior, public contracts, sanitized tests, compatibility requirements | CPAL-1.0 | Privacy-safe image probing, orientation handling, clean re-encoding, limits, and validation. |
| `src/remember_me/storage/content_store.py` | Frozen behavior, public contracts, sanitized tests, compatibility requirements | CPAL-1.0 | Content-addressed storage, path confinement, atomic writes, and quarantine operations. |
| `src/remember_me/core/normalization.py` | Frozen behavior, public contracts, sanitized tests, compatibility requirements | CPAL-1.0 | Filename, text, tag, timestamp, and identifier normalization. |
| `src/remember_me/search/keyword.py` | Frozen behavior, public contracts, sanitized tests, compatibility requirements | CPAL-1.0 | Search filtering, match reasons, ranking, sorting, and pagination. |
| `src/remember_me/storage/sqlite_repository.py` | Frozen behavior, public contracts, sanitized tests, compatibility requirements | CPAL-1.0 | SQLite compatibility, metadata operations, tags, verification, and embeddings. |
| `src/remember_me/core/service.py` | Frozen behavior, public contracts, sanitized tests, compatibility requirements | CPAL-1.0 | Host-independent orchestration of public core operations. |

## Preserved upstream notice

The repository separately retains the complete applicable upstream MIT text at
`LICENSES/MIT-Ombre-Brain.txt`, including
`Copyright (c) 2026 P0lar1zzZ`, for content and historical distributions that
remain covered. This preserved notice is not file-level provenance for the six
independently reimplemented core modules listed above.

## Independently written Stage 7B files

These files were independently written for the public package and use
`SPDX-License-Identifier: CPAL-1.0` where a source header is applicable.

| File | Classification | License | Purpose |
| --- | --- | --- | --- |
| `src/remember_me/core/clock.py` | Independent | CPAL-1.0 | Injectable system clock and UTC second-precision formatting. |
| `src/remember_me/factory.py` | Independent | CPAL-1.0 | Explicit local service assembly without host configuration. |
| `tests/test_pillow_sanitizer.py` | Independent tests | CPAL-1.0 | Sanitizer, metadata removal, format, MIME, and pixel-limit behavior. |
| `tests/test_content_store.py` | Independent tests | CPAL-1.0 | Blob confinement, conflict, atomic storage, and quarantine behavior. |
| `tests/test_sqlite_repository.py` | Independent tests | CPAL-1.0 | Schema compatibility, metadata, cascade, timeout, and threads. |
| `tests/test_keyword_search.py` | Independent tests | CPAL-1.0 | Ranking, filters, dates, pagination, and stable ordering. |
| `tests/test_service.py` | Independent tests | CPAL-1.0 | Public operations, hashing, deduplication, resolve, and deletion. |
| `tests/test_stage7b_contract.py` | Independent tests | CPAL-1.0 | Cross-component compatibility, provenance, and privacy contracts. |

## Existing CPAL files changed in Stage 7B

The following pre-existing CPAL files received independently written package,
protocol, metadata, test, or documentation changes:

- `pyproject.toml`
- `src/remember_me/__init__.py`
- `src/remember_me/metadata.py`
- `src/remember_me/core/__init__.py`
- `src/remember_me/core/contracts.py`
- `src/remember_me/core/errors.py`
- `src/remember_me/imaging/__init__.py`
- `src/remember_me/search/__init__.py`
- `src/remember_me/storage/__init__.py`
- `tests/test_attribution_contract.py`
- `tests/test_package_metadata.py`
- `README.md`
- `AUTHORS.md`
- `NOTICE`
- `ORIGIN.md`
- `CITATION.cff`
- `docs/architecture.md`
- `docs/claude-web.md`
- `docs/data-compatibility.md`
- `docs/public-api-contract.md`
- `docs/versioning.md`
- `docs/licensing-and-origin.md`

No production database, image, hash inventory, private path, credential, or
host configuration was used to create these files.

## Independently written Stage 7C files

Stage 7C does not use or copy Ombre-Brain `server.py`. The following Host files
are independent CPAL-1.0 implementations that call public Remember-Me Core
interfaces:

| File | Classification | License | Purpose |
| --- | --- | --- | --- |
| `src/remember_me/__main__.py` | Independent | CPAL-1.0 | Module CLI entry point. |
| `src/remember_me/standalone/__init__.py` | Independent | CPAL-1.0 | Optional Host package boundary. |
| `src/remember_me/standalone/config.py` | Independent | CPAL-1.0 | Immutable defaults, environment/CLI precedence, Token files, and network gates. |
| `src/remember_me/standalone/cli.py` | Independent | CPAL-1.0 | Version, about, and serve commands. |
| `src/remember_me/standalone/auth.py` | Independent | CPAL-1.0 | Header-only Bearer authentication. |
| `src/remember_me/standalone/middleware.py` | Independent | CPAL-1.0 | Request limits, request IDs, security headers, and metadata-only logs. |
| `src/remember_me/standalone/schemas.py` | Independent | CPAL-1.0 | Public HTTP models and safe asset conversion. |
| `src/remember_me/standalone/app.py` | Independent | CPAL-1.0 | Minimal FastAPI application and route adapters. |
| `src/remember_me/standalone/errors.py` | Independent | CPAL-1.0 | Host configuration and request-limit errors. |
| `docs/standalone-host.md` | Independent documentation | CPAL-1.0 | Local installation and configuration. |
| `docs/http-api.md` | Independent documentation | CPAL-1.0 | Development HTTP contract. |
| `docs/security.md` | Independent documentation | CPAL-1.0 | Host threat boundaries and safe defaults. |
| `tests/test_standalone_config.py` | Independent tests | CPAL-1.0 | Configuration and network gates. |
| `tests/test_standalone_cli.py` | Independent tests | CPAL-1.0 | CLI identity and Token argument exclusion. |
| `tests/test_standalone_api.py` | Independent tests | CPAL-1.0 | HTTP, auth, limits, privacy, and lifecycle behavior. |
| `tests/test_stage7c_contract.py` | Independent tests | CPAL-1.0 | Version, dependency, provenance, and documentation contracts. |

Stage 7C makes small CPAL updates to project metadata, package exports, and the
local assembly factory. It adds readiness probes to the Stage 7B SQLite and
blob implementations without changing the independent rewrite record or the
separately preserved upstream MIT notice.

## Independently written Stage 7D Dashboard

Stage 7D did not read, copy, migrate, or imitate Ombre-Brain Dashboard HTML,
CSS, JavaScript, layout, navigation, visual styling, upload UI, authentication,
Cookie, or CSRF code. The Dashboard is an original Dusk Archive implementation
that calls only the public Remember-Me HTTP API.

| File | Classification | License | Purpose |
| --- | --- | --- | --- |
| `src/remember_me/standalone/dashboard/index.html` | Independent | CPAL-1.0 | Accessible Dashboard structure and dialogs. |
| `src/remember_me/standalone/dashboard/styles.css` | Independent | CPAL-1.0 | Dusk Archive responsive visual system. |
| `src/remember_me/standalone/dashboard/api.js` | Independent | CPAL-1.0 | Unified public HTTP API client and session Token handling. |
| `src/remember_me/standalone/dashboard/ui.js` | Independent | CPAL-1.0 | Safe DOM construction and formatting. |
| `src/remember_me/standalone/dashboard/app.js` | Independent | CPAL-1.0 | Dashboard state and asset workflows. |
| `docs/dashboard.md` | Independent documentation | CPAL-1.0 | Local preview and workflow contract. |
| `docs/design-system.md` | Independent documentation | CPAL-1.0 | Dusk Archive design tokens and rules. |
| `tests/test_dashboard.py` | Independent tests | CPAL-1.0 | Routes, CSP, XSS, accessibility, and package-data contracts. |

Stage 7B independently reimplemented core files and their CPAL-1.0 headers
remain unchanged.

## Independently written Stage 7E MCP

Stage 7E did not read, copy, rewrite, or migrate Ombre-Brain MCP, upload,
download, Viewer, or tool-registration code. The public adapter is an original
CPAL-1.0 implementation over the public Remember-Me runtime.

| File | Classification | License | Purpose |
| --- | --- | --- | --- |
| `src/remember_me/mcp/__init__.py` | Independent | CPAL-1.0 | Public MCP package boundary. |
| `src/remember_me/mcp/server.py` | Independent | CPAL-1.0 | FastMCP Streamable HTTP assembly, auth, and resources. |
| `src/remember_me/mcp/tools.py` | Independent | CPAL-1.0 | Nine public Core-backed asset tools. |
| `src/remember_me/mcp/transfers.py` | Independent | CPAL-1.0 | Bounded in-memory signed transfer Tickets. |
| `src/remember_me/mcp/schemas.py` | Independent | CPAL-1.0 | Safe structured MCP output conversion. |
| `src/remember_me/mcp/viewer.py` | Independent | CPAL-1.0 | Viewer metadata and packaged-resource loader. |
| `src/remember_me/mcp/asset-viewer.html` | Independent | CPAL-1.0 | Original single-image MCP App Viewer. |
| `docs/mcp.md` | Independent documentation | CPAL-1.0 | Transport, auth, transfer, and client guidance. |
| `docs/mcp-tools.md` | Independent documentation | CPAL-1.0 | Stable tool schemas and semantics. |
| `tests/test_stage7e_mcp.py` | Independent tests | CPAL-1.0 | Official-client protocol and workflow acceptance. |

The small `AssetRepository.store_embedding` extension is independently written
support for the public vector-provider abstraction. It does not alter the six
public Core operation names or the Stage 7B independent rewrite record.
