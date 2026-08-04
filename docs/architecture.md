# Architecture

## One core

`peanutsuee/Remember-Me` is the only long-term core code source for image
validation, privacy cleaning, content addressing, blob storage, SQLite
metadata, title/description/tag handling, deduplication, search, optional vector
indexing, shared Dashboard image behavior, and the public upload contract.

The durable dependency direction is:

```text
Remember-Me public core
        ^
Ombre Brain thin plugin or adapter
        ^
Ombre Brain host
```

Feature branches are temporary construction and review tools. They are not
separate Standalone and Ombre Brain product branches. The project must not keep
copied AssetStore, sanitizer, search, or vector-core implementations.

## Boundaries

The core owns domain models, errors, protocols, validation policy, persistence
semantics, and search behavior. `RememberMeService` receives
`AssetRepository`, `BlobStore`, `ImageSanitizer`, `VectorProvider`, and `Clock`
dependencies by injection.

The core does not know web frameworks, authentication state, cookies, CSRF,
deployment platforms, host sessions, host configuration objects, production
domains, or API keys.

Stage 7F expands the tested Pillow runtime range to 10.4 through 12.x without
changing the sanitizer algorithm or dependency direction. Fixed synthetic
fixtures validate privacy semantics and same-version determinism. Those
fixtures produced identical encoded bytes on Pillow 10.4.0, 11.3.0, and
12.3.0, and RM matched the current Ombre-Brain sanitizer byte-for-byte under
Pillow 12.3.0. A production host should still pin its accepted Pillow version
because future encoder byte streams or other inputs can vary while remaining
semantically compatible.

The Standalone Host provides configuration, process lifecycle, HTTP and MCP
transport, Bearer authentication, signed transfer Tickets, and package wiring.
A future Ombre Brain plugin may
provide host configuration, data-root injection, session/cookie/CSRF handling,
Dashboard shell mounting, MCP registration, logging, feature flags, and package
version locking. A host may inject an asynchronous `VectorProvider`, but Core
owns canonical index text, its content hash, model/current checks, per-asset
reindex counters, embedding persistence, and metadata-concurrency protection.
Neither host may copy the core implementation.

Stage 7G-A makes reindexing a formal asynchronous `RememberMeService`
operation. The SQLite repository owns embedding read, delete, and transactional
conditional-store capabilities using the existing compatible table. The
Standalone MCP adapter delegates to that operation and only translates the
Core result into its established public envelope.

Stage 7G-B makes semantic search consumption a Core responsibility. When an
enabled asynchronous provider is injected, Core embeds the query once, derives
the active dimension from that validated query vector, reads only records for
the active model, and accepts only current canonical-content hashes with the
same dimension. The model identity must remain unchanged across the query
embedding await. Core computes dependency-free cosine similarity and delegates
final filtering and stable ranking over the same immutable asset snapshot to
the existing keyword search contract.
Invalid queries, provider failures, corrupt individual vectors, dimension
mismatches, and zero-norm vectors safely degrade to keyword-only behavior;
cancellation and whole-repository failures still propagate. Search never
repairs or deletes stale records. The default null provider remains network-free
and keyword-only. Remember-Me ships no network vector provider.

The Stage 7D Dashboard belongs to Remember-Me and calls only the public
Standalone HTTP API. Its HTML, CSS, JavaScript, visual system, and state are
independent from Ombre Brain. Host-specific shells remain in their hosts.
The Standalone Host serves `index.html` only from `/dashboard` and
`/dashboard/`. The `/dashboard/static` boundary uses an explicit CSS/JavaScript
allowlist rather than exposing the complete packaged Dashboard directory.
The Stage 7E MCP adapter and resources belong to Remember-Me. FastMCP is a thin
protocol layer over the same `LocalRuntime` used by `/api/v1` and the
Dashboard. It does not create another repository, blob store, sanitizer, or
SQLite writer. The exact `/mcp` Route is composed into the existing ASGI app,
and the MCP session manager participates in the Host lifespan.

Stage 7C provides `create_local_runtime(data_root)` and
`create_local_service(data_root)` as explicit local assembly factories. They
accept an optional injected async vector provider, read no host configuration,
and otherwise wire the compatible SQLite repository, local content store,
Pillow sanitizer, system clock, and network-free null vector provider. The
Standalone layer calls those factories; Core never imports FastAPI, Starlette,
Uvicorn, Pydantic, or Standalone modules.

HTTP request objects and schemas remain in `remember_me.standalone`. They are
converted to immutable public Core requests, and internal `AssetRecord` hash
and path fields are converted through one safe public response function.

The Dashboard remains a local single-user browser surface. It is not an Ombre
Brain plugin, multi-tenant service, account system, or deployment
configuration. The browser layer never imports Core or accesses SQLite and
blob paths directly. It continues to use only `/api/v1`; it does not bypass
the HTTP API through MCP.

Deletion coordination requires a minimal BlobStore extension: quarantine a
blob before database deletion, restore it if the transaction fails, and
finalize the quarantined file after commit. This keeps filesystem and metadata
state recoverable without exposing absolute paths through the public API.
