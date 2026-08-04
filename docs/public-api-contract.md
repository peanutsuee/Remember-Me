# Public API Contract

## Core operations

The host-independent `RememberMeService` implements these operations:

- `ingest_image`
- `import_asset`
- `get_asset`
- `update_metadata`
- `delete_asset`
- `search_assets`
- `reindex_embeddings`
- `resolve_asset`
- `begin_asset_verification`
- `list_asset_verification_page`
- `verify_asset_blob`
- `complete_asset_verification`

Requests and results are immutable dataclasses. Expected domain failures cross
the boundary as public `RememberMeError` subclasses. Host exceptions,
authentication objects, framework requests, and deployment configuration do
not enter the core.

The implementation receives `AssetRepository`, `BlobStore`,
`ImageSanitizer`, `VectorProvider`, and `Clock` dependencies. It must not
hard-code a host object.

## Asset verification

Package version `0.1.0.dev7` adds four synchronous, read-only Core operations
for bounded verification of one local asset target. They are generic Core
capabilities and are not part of Search, Reindex, HTTP, MCP, or any
host-specific workflow. The immutable release commit and archive digest will
be determined by the later release stage; this development tree does not
declare either value.

`begin_asset_verification` creates a short-lived generation-guarded session.
The result contains an unpredictable opaque snapshot token, a persistent
opaque target identity, the current non-negative asset mutation generation,
the selected kind filter, and the inventory count observed at that
generation. Neither identity contains a path, database filename, hostname, or
storage locator.

The snapshot is not a long-running physical SQLite transaction. The repository
persists one target identity and a monotonic asset generation. Successful
asset ingest, import, metadata change, and delete increment that generation in
the same SQLite transaction as the asset mutation. Idempotent imports,
metadata no-ops, unsuccessful deletes, reads, Search, Reindex, and verification
do not increment it. Every verification operation checks target identity and
generation before and after its read. Concurrent asset mutation invalidates
the session and fails closed with `verification_snapshot_changed`.

`list_asset_verification_page` uses bounded keyset pagination in strict
ascending asset-ID order. Limits are exact integers from 1 through 500.
Cursors are unpredictable, single-use, session-bound tokens rather than
offsets. A cursor cannot be replayed, reordered, modified, or used with another
snapshot. A page must have every listed blob successfully verified before the
session can advance, keeping session memory bounded by the page limit.

`AssetVerificationRecord` includes asset identity, source and stored hashes,
filename, MIME, kind, decoded and stored byte counts, dimensions, asset
timestamps, title, description, and timestamped `AssetVerificationTag`
entries. It intentionally excludes stored relative paths, blob keys, data
roots, database identifiers, and absolute paths.

`verify_asset_blob` accepts an expected SHA-256, size, and optional exact
`bytes`. Expected bytes are excluded from dataclass representations and never
enter errors or results. Core obtains the internal blob locator from the
current asset record, reads the actual stored bytes through the injected blob
store, recomputes actual length and SHA-256, compares them with both the
verification record and caller expectations, and optionally performs exact
byte equality. The result contains only verification facts and never returns
the actual bytes or locator. Blob verification performs no embedding or
network call.

`complete_asset_verification` succeeds only after the cursor chain reaches its
end, scanned count equals the begin count, every scanned asset has one
successful blob verification, and a fresh bounded keyset rescan has reread
every current blob and matched it to its current verification record. The
rescan is limited to 500 records per repository page and does not use Search.
Current target identity and generation must still match, and the repository
must report no duplicate asset or stored-SHA ownership. Completion closes the
session. Further page, blob, or completion calls use the stable
`verification_snapshot_closed` error. A successful verification request never
serves a cached result in place of rereading the actual blob.

Verification sessions are process-local and belong to the exact `RememberMeService`
instance that created them. Begin, page, blob verification,
and completion must be routed to that same service/process. They are bounded to
32 active sessions per service, expire after 15 minutes of inactivity, and
leave only bounded short-lived closed tombstones. A service restart invalidates
old tokens; a token routed to another worker returns
`verification_snapshot_invalid`. Multi-worker deployments therefore need
sticky routing, or verification should run in an offline single-process
maintenance tool. Another process sharing the database can mutate assets
safely because the persistent SQLite generation invalidates sessions in every
process.

The snapshot is generation-guarded rather than a physical filesystem freeze.
The API detects direct blob damage that exists before or during a verification
read and during the completion rescan. Operators must prevent direct data-root
writes with a single-writer or maintenance window while verification runs.
Completion proves the database inventory was unchanged and every blob matched
its record during the fresh rescan; it cannot promise that a future external
filesystem write after completion will not change the target.

Stable verification errors include:

- `verification_snapshot_invalid`
- `verification_snapshot_expired`
- `verification_snapshot_changed`
- `verification_snapshot_closed`
- `invalid_verification_cursor`
- `invalid_verification_limit`
- `verification_page_out_of_order`
- `verification_asset_not_scanned`
- `verification_asset_missing`
- `verification_blob_missing`
- `verification_blob_unreadable`
- `verification_blob_checksum_mismatch`
- `verification_blob_size_mismatch`
- `verification_blob_bytes_mismatch`
- `verification_record_invalid`
- `verification_incomplete`
- `verification_unavailable`
- `verification_internal_error`

Errors use fixed public codes and do not include SQLite messages, paths,
session tokens, blob bytes, expected bytes, or user metadata. Ordinary
repository and storage exceptions are mapped to that safe boundary.
`BaseException` subclasses such as cancellation, `KeyboardInterrupt`, and
`SystemExit` are not caught by ordinary verification error handling.

The local implementation receives those dependencies through its constructor.
`create_local_runtime(data_root, vector_provider=None)` is the explicit assembly
used by the Standalone Host and does not read host configuration. The optional
provider is host-injected; the default remains `NullVectorProvider`.

## Upload contract

The public upload request accepts only:

- `expected_bytes`
- `filename`
- `mime_type`

It does not accept `expected_sha256`. The server computes the authoritative
`source_sha256` from the complete received bytes. A client or model must not
supply, infer, guess, or invent the hash. Client execution code may compare a
local digest with the server result internally, but a complete digest must not
be printed to chat text or standard output.

The server remains responsible for actual byte-count verification,
completeness, format and MIME validation, the pixel limit, privacy cleaning,
content hashing, and deduplication. `application/octet-stream` is a transport
declaration only. A formal asset must decode as PNG or JPEG; non-image content
must not be persisted as a formal asset.

Historical diagnostic probes that accepted or compared a hash are not part of
the public upload design.

Stage 7C exposes this behavior at `POST /api/v1/assets` with multipart fields
`file`, `expected_bytes`, optional `filename`, `mime_type`, `title`,
`description`, and repeated `tag`. It rejects client hash fields and arbitrary
paths. The service computes both source and cleaned-content digests internally.
Duplicate cleaned content returns HTTP 200 with `deduplicated=true` and does
not overwrite metadata; a new asset returns HTTP 201.

## HTTP boundary

The development HTTP API identifier is `v1alpha1`, while routes currently use
the `/api/v1` prefix. Package and HTTP versions evolve independently.

Public asset responses contain identifiers, user-facing metadata, MIME, kind,
byte counts, dimensions, timestamps, and tags. They do not contain source
hashes, stored hashes, stored relative paths, blob keys, data roots, or
absolute paths. All asset routes use one `asset_to_public_response` conversion.

Bearer authentication applies to every asset route when configured. Health,
readiness, and project information remain unauthenticated. The Host accepts the
Token only through the `Authorization` Header, never query parameters or
Cookies.

## Vectors

`VectorProvider` exposes `enabled`, a stable non-empty `model_id`, and async
`embed(text)`. The built-in `NullVectorProvider` is network-free and keeps
keyword-only operation valid. Core does not nest event loops, create thread
bridges, or ship a network provider.

Stage 7G-A makes `reindex_embeddings` a Core operation. Core owns canonical
index text and SHA-256 content identity, current/stale checks, empty-metadata
cleanup, per-asset counters, vector validation, and conditional persistence.
The repository exposes embedding read, delete, and transactionally guarded
store operations using the existing compatible schema. A host may inject an
async provider, while the default factory continues to use the null provider.

Stage 7G-B makes `search_assets` asynchronous and Core-owned for semantic
orchestration. Direct Python callers must now use
`await service.search_assets(request)`. This is a deliberate breaking change to
the pre-alpha Python call shape; the HTTP and MCP schemas and envelopes remain
unchanged. No synchronous event-loop wrapper is provided.

With an enabled provider and non-blank query, Core validates one
query vector and treats its length as the dynamic search dimension. Only
same-model stored vectors with that exact dimension, a current canonical
content hash, an existing asset, non-empty canonical text, finite values, and a
non-zero norm can contribute cosine similarity. Cosine is dependency-free,
finite, and clamped to `[-1.0, 1.0]`. No database dimension column or fixed
provider dimension is introduced. The provider `model_id` is read before and
after query embedding; a change causes exact keyword fallback before any stored
vector read.

The baseline keyword ranking remains authoritative: keyword ranks precede pure
semantic rank 6, and only a strictly positive cosine creates a semantic match.
Zero or negative cosine values do not create pure semantic candidates. Current
hash checks and final ranking use one immutable asset snapshot. This is a
per-search read snapshot, not a cross-table serializable transaction; metadata
committed after the snapshot appears on the next search.

Ordinary provider failures, invalid or zero-norm query vectors, corrupt
individual stored vectors, stale records, and incompatible dimensions degrade
to the exact keyword-only result. Cancellation and whole-repository failures
are not hidden. Search performs no embedding writes or cleanup. The existing
keyword filter, ranking, pagination, result fields, MCP schema, and error
envelope remain authoritative. The default Standalone factory still injects
`NullVectorProvider`, so it remains keyword-only and performs no network
access. Hosts may inject an async provider; Remember-Me includes no real network
provider.

## Trusted import contract

`ImportAssetRequest` is a synchronous, single-asset contract for a trusted Host
to import one trusted, already-cleaned PNG or JPEG through Core. Core still
validates image structure and metadata. The Host supplies a valid legacy asset
ID, historical metadata and timestamps, tag display values with creation times,
cleaned bytes, source/stored hashes, byte counts, MIME type, and dimensions. The
request does not accept an embedding, model identity, Ticket, URL, absolute
path, relative CAS path, or alias. It rejects `kind=file` and every format
other than PNG or JPEG.

Remember-Me recomputes `stored_sha256` from the cleaned bytes, validates the
actual image format, MIME, dimensions, byte length, pixel and upload limits,
and derives the content-addressed path. It does not rotate, compress, sanitize,
or otherwise re-encode the bytes. `source_sha256` and `decoded_bytes` describe
the unavailable original upload and therefore receive format/range validation,
not a false recomputation from cleaned bytes.

Asset and tag timestamps must be valid ISO 8601 values with explicit time-zone
offsets. The original strings are stored unchanged. Tags use Remember-Me
normalization for identity; duplicate normalized tags are rejected so no
history is silently discarded. The asset creation time must not follow its
update time, and tag creation times must fall within that history interval.

Dry-run performs the same validation, existing-record comparison, CAS integrity
read, and ownership checks without writing a temporary file, blob, SQLite row,
tag, or embedding. A complete repeat is idempotent only when every persistent
field, tag timestamp, and CAS byte matches. Conflicting asset IDs or stored-hash
ownership are never overwritten or remapped. Import is a single-asset contract;
batching, checkpointing, migration orchestration, runtime enablement, and
reindexing belong to later Host stages.

Import does not migrate embeddings, enable a runtime, migrate production, or
execute Reindex. A later explicitly authorized Reindex must rebuild vectors.
The Host depends only on the public `remember_me.core` contract and must not
call internal repository or storage modules directly.
