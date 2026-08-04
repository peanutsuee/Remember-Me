# Data Compatibility

Stage 7B implements a read/write-compatible local repository for existing
Ombre Brain image data. It creates missing tables and indexes, incrementally
adds missing `title`, `description`, and `updated_at` columns, and backfills an
empty `updated_at` from `created_at`. It does not copy images, bulk migrate a
database, rewrite existing files, or recompute existing hashes.

Stage 7C's Standalone Host uses the same explicit local assembly and data-root
contract. It does not auto-discover Ombre Brain, connect to a production data
directory, rewrite existing images, or recompute existing hashes. Operators
must explicitly select a data root and must not run a second writer against an
Ombre Brain data root.

## Layout and identity

- Database: `assets.sqlite3` under the injected data root.
- Blob directory: `assets/`.
- Asset ID: 32 lowercase hexadecimal characters.
- Cleaned image path:
  `assets/<first-two-stored-hash-characters>/<stored-hash>.png` or `.jpg`.
- `source_sha256`: SHA-256 of the complete uploaded source bytes as received by
  the server.
- `stored_sha256`: SHA-256 of the privacy-cleaned, orientation-normalized,
  re-encoded bytes. This digest controls content addressing and deduplication.

Supported formal assets are PNG and JPEG. `application/octet-stream` is only an
accepted transport declaration; it does not make non-image bytes a formal image
asset. The source upload limit is 10 MiB and the decoded pixel limit is
20,000,000.

The cleaning-byte contract is identified as `remember-me-pillow-v1`.
Stage 7F supports `Pillow>=10.4,<13` and validates Pillow 10.4.0, 11.3.0, and
12.3.0 with fixed synthetic PNG/JPEG fixtures. Privacy cleaning, orientation,
format, dimensions, metadata removal, and same-version determinism must remain
consistent throughout that range.

The fixed Stage 7F fixtures produced identical bytes and `stored_sha256` values
under all three tested versions. This is a recorded test result, not a promise
that every future Pillow release or every possible input will encode
identically. Production environments should pin an exact tested Pillow version
because a changed stored byte stream changes `stored_sha256`, content
addressing, and deduplication identity for new uploads. The current Ombre-Brain
compatibility target uses Pillow 12.3.0. Every Pillow upgrade requires the
compatibility matrix and byte comparison to run before rollout.

Under Pillow 12.3.0, the fixed RM and Ombre-Brain inputs produced identical
cleaned bytes, MIME types, dimensions, stored hashes, extensions, and relative
blob paths. The temporary bidirectional data smoke confirmed that RM could
open and update OB-created data and the old OB code could read the result.
RM initialization added only the bounded embedding table and its two indexes;
it did not alter asset columns or backfill `updated_at` in the current schema.

This expanded runtime range does not change `ombre-brain-assets-v1`, existing
stored files, database schema, blob paths, hash algorithms, or the
`remember-me-pillow-v1` cleaning algorithm.

## Schema

The compatibility contract records these tables:

- `assets`: asset ID, source/stored hashes, relative path, original filename,
  MIME, kind, byte counts, dimensions, creation time, title, description, and
  update time.
- `asset_tags`: asset ID, normalized tag, display tag, and creation time.
- `asset_embeddings`: asset ID, serialized vector, model identifier, indexed
  content hash, and update time.

Timestamps are UTC ISO 8601 strings with explicit offsets, stored to whole
seconds. `created_at` is asset creation time. `updated_at` begins at creation
time and changes when editable metadata changes.

Title and description are user-facing metadata, limited to 200 and 4,000
characters after NFKC/control cleanup. Tags receive NFKC cleanup, whitespace
collapse, case-folded identity, first-display preservation, empty removal, and
case-insensitive deduplication. A tag is limited to 64 characters and an asset
to 30 tags.

## Search and consistency

Keyword match priority is exact asset ID, exact tag, exact/prefix title,
filename, then other substring matches. Within equal rank, newer creation time
sorts first and asset ID is the stable final tie-breaker. Semantic-only results
sort by descending score, then creation time and asset ID. Filters require all
requested normalized tags.

Deduplication is based on `stored_sha256`, so different source files that clean
to identical stored bytes resolve to the same asset.

Deletion must preserve database/file consistency. The compatible behavior
quarantines the blob, deletes the database row transactionally, restores the
blob on database failure, and reports deferred cleanup if final unlinking fails.
Foreign-key cascades remove tags and embeddings.

The goal is zero-copy, in-place reading of an existing compatible data root.
Two independent processes must not write the same SQLite database
simultaneously. Any later migration must snapshot `assets.sqlite3` and the
`assets/` tree as a pair. The first compatibility phase must not rewrite
existing files or recalculate existing hashes.

Connections enable foreign keys, use a 30-second SQLite connection timeout and
30,000 ms busy timeout, and do not enable WAL by default. The
`asset_embeddings` table remains intact even though Stage 7B does not generate
or write real vectors.
