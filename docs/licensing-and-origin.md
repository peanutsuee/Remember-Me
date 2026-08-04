# Licensing and Origin

Remember-Me's original concept, product design, and independent project were
initiated by Ting (peanutsuee). This project-origin statement is distinct from
authorship of every line of code.

Newly created Remember-Me code and documentation are licensed under
`CPAL-1.0`. Files containing new work should carry an appropriate SPDX
identifier.

The six Stage 7B core modules were independently reimplemented from a frozen
behavioral specification, public contracts, sanitized tests, and data
compatibility requirements through a documented clean-room engineering
process. They carry `SPDX-License-Identifier: CPAL-1.0`.

This engineering process and its similarity reviews do not by themselves
determine copyright ownership, legal independence, or license obligations.
The implementation record is documented in `docs/source-provenance.md`.

The repository separately preserves applicable upstream MIT rights and the
original copyright notice for content and historical distributions that remain
covered, including `Copyright (c) 2026 P0lar1zzZ`. The preserved license text
is stored at `LICENSES/MIT-Ombre-Brain.txt`.

Stage 7C's files under `src/remember_me/standalone/`, its CLI entry point,
HTTP schemas, middleware, tests, and Host documentation are independently
written CPAL-1.0 work. They call the public Remember-Me Core and do not copy
Ombre-Brain `server.py`, Dashboard, Cookie, CSRF, authentication, or MCP
registration code. The Stage 7B core remains CPAL-1.0 work.

The Stage 7D Dashboard files are independently written CPAL-1.0 work. They do
not reuse the Ombre-Brain Dashboard's HTML, CSS, JavaScript, layout, visual
system, or authentication implementation. This new browser work does not
change the separately preserved upstream MIT notice.

The Stage 7E MCP adapter, signed-transfer layer, tools, tests, documentation,
and Viewer are independently written CPAL-1.0 work. They do not read or copy
Ombre-Brain MCP, upload, download, Viewer, or tool-registration
implementations. They call the canonical Remember-Me Core and do not change or
erase the separately preserved upstream MIT notice.

Future product surfaces must reuse the canonical identity metadata:

- Standalone Dashboard: a persistent footer or similarly visible location and
  an About or Credits view.
- CLI: `--version`, `about`, and the source section of help output.
- MCP Host: server metadata, a stable About resource, and connection docs.
- Ombre Brain plugin: visible Remember-Me independent-project attribution.

Attribution must not be deliberately weakened through tiny type, hidden or
collapsed placement, or near-background coloring.

Before the first formally usable release, maintainers must repeat the license
compatibility, file-level provenance, and NOTICE review. This document does not
claim a trademark registration or a legal ruling.
