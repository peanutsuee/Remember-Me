<!-- SPDX-License-Identifier: CPAL-1.0 -->

# Dashboard

The Stage 7D Dashboard is a local, single-user interface mounted on the
Standalone Host at `/dashboard`. It calls the existing public HTTP API and does
not read SQLite, blob files, or local filesystem paths directly.

The HTML document is available only at `/dashboard` and `/dashboard/`.
`/dashboard/static` serves the allowlisted stylesheet and JavaScript modules,
not the complete packaged Dashboard directory.

## Windows local preview

Run the following commands from the repository root:

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

Stop with `Ctrl+C`.

The `.dashboard-preview` directory is only local test data. It does not connect
to Ombre Brain, Render, or production data. It can be deleted after the Host is
stopped. Loopback mode has no Token by default. Do not run two writers against
the same data directory.

## macOS and Linux

```sh
cd /path/to/Remember-Me
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[standalone,test]"
./.venv/bin/python -m remember_me serve \
  --data-root "./.dashboard-preview"
```

Open `http://127.0.0.1:8787/dashboard` and stop with `Ctrl+C`.

## Archive workflows

The main grid loads metadata from `GET /api/v1/assets`. Search state remains in
page memory and is not written to browser history. Query, repeated tags, MIME,
date range, limit, and offset use the existing search contract.

Image bytes are requested from the existing content route with a Bearer Header
when needed. The browser creates Blob Object URLs and revokes them when cards,
pages, previews, or the tab are closed. IntersectionObserver and a four-request
queue avoid loading an entire 50-item page at once.

Upload accepts PNG or JPEG files up to 10 MiB on the client and sends `file`,
`expected_bytes`, filename, MIME, title, description, and repeated tags. The
server remains authoritative. No client hash or path field is sent.

Details support title, description, and tags. Only changed fields are sent.
Empty strings and an empty tag list clear values. Null, unknown fields, and
empty modifications are not sent.

Deletion has a separate confirmation dialog. `cleanup_pending=true` produces a
warning without exposing internal cleanup paths.

## Token mode

When an asset request returns 401, the Dashboard opens its Unlock dialog. The
Token is placed in `sessionStorage` under `remember_me_session_token` and lasts
only for the current tab session. It is cleared on authentication failure or
with Clear Token.

The Token is not placed in localStorage, Cookies, URLs, logs, HTML, or About
content. Public health, readiness, about, Dashboard, and static-resource
requests do not need it.

## Visual acceptance

Automated tests cover routes, static safety, responsive rules, accessibility
markers, and end-to-end HTTP workflows. Final visual approval belongs to the
project maintainer in a local browser.
