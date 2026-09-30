# Versioning

Remember-Me tracks separate version dimensions because code, storage, and
transport contracts evolve at different rates.

## Python package version

The installable package uses PEP 440. The current public preview is
`0.1.0.dev8`; the previous public preview was `0.1.0.dev7`. Package versions
describe released code, not the age of pre-existing integrated prototypes.

Stage 7F validates `Pillow>=10.4,<13` with Pillow 10.4.0, 11.3.0, and 12.3.0.
This is a package-runtime compatibility change only. HTTP API, Dashboard, MCP
API, and data compatibility versions do not change. Production deployments
should pin the exact Pillow version accepted by their compatibility run. The
fixed Stage 7F fixtures produced identical cleaned bytes in all three tested
versions, but that result does not guarantee identical encoder output for
future Pillow releases or all possible images.

## Data schema version

The schema version describes SQLite tables, columns, constraints, and
content-addressed path semantics. A schema change requires explicit
compatibility and migration notes. Stage 7B implements the
`ombre-brain-assets-v1` compatibility target with incremental schema creation
and legacy metadata-column extension. It does not bulk migrate production data.

## Public Python API version

The Python API version covers public models, errors, and protocols. Until a
stable API is declared, package release notes must identify breaking contract
changes. Stage 7B implements the initial local API but does not assign a
separate stable number.

## HTTP API version

Stage 7C defines the development HTTP API identifier `v1alpha1` and the route
prefix `/api/v1`. The identifier describes wire behavior independently from
the Python package version. This alpha contract does not promise long-term
stability; incompatible wire changes require explicit API version notes.

## Dashboard version

Stage 7D defines Dashboard version `v1alpha1`. It describes the browser UI,
static-resource contract, and connected workflows independently from the
Python package and HTTP API versions.

## MCP contract version

Stage 7E defines MCP API version `v1alpha1`. It covers the exact tool names,
schemas, annotations, resources, Viewer metadata, and Streamable HTTP behavior
at `/mcp`. It evolves independently from the Python package, HTTP API,
Dashboard, and data compatibility versions.

Stage 7E requires Python 3.10 or newer because the stable official MCP Python
SDK v1 requires that minimum. The project does not use an environment marker
that silently omits MCP on Python 3.8 or 3.9.

## Ombre Brain compatibility matrix

Each Remember-Me release that claims Ombre Brain compatibility must record:

- Remember-Me package version;
- supported Ombre Brain version or commit range;
- data schema compatibility version;
- adapter/plugin version;
- read/write support and migration requirements.

Historical private integration labels are not independent Remember-Me package
versions and must not be used as public release identifiers.

## Current metadata, search and reindex policy

The current package separates storage/display spelling from NFKC comparison
keys, applies a configurable Core semantic minimum of `0.42` by default, and
preserves old embeddings until validated replacements are ready. It keeps
`ombre-brain-assets-v1` and the HTTP and MCP schemas unchanged. There is no
historical spelling restoration or data migration. See
[data compatibility](data-compatibility.md) for import and downgrade boundaries.

Build a release source archive from the exact final commit with a fixed archive
prefix and `gzip -n`. Record the commit, tree, package version, archive SHA-256,
and provenance in the release manifest.
