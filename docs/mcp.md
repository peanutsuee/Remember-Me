<!-- SPDX-License-Identifier: CPAL-1.0 -->

# Standalone MCP

Remember-Me Stage 7E provides a public MCP API `v1alpha1` through the existing
Standalone Host. It uses the official Model Context Protocol Python SDK
`1.28.x`, FastMCP, and Streamable HTTP.

## Start locally

Install the normal Standalone extra:

```powershell
cd <PATH-TO-REMEMBER-ME>
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[standalone,test]"
.\.venv\Scripts\python.exe -m remember_me serve `
  --data-root ".\.mcp-preview"
```

Connect an MCP client to:

```text
http://127.0.0.1:8787/mcp
```

The endpoint is exactly `/mcp`. It does not require `/mcp/mcp` and does not
redirect the initial POST.

## Authentication

Loopback mode without a configured Token remains available for local use.
When a Standalone Token is configured, every MCP request must include:

```text
Authorization: Bearer <YOUR_TOKEN>
```

Tokens are not accepted in URLs or Cookies. Use the same Token file guidance
as the HTTP API. The official SDK's Origin and DNS-rebinding validation remains
enabled.

## Signed transfers

`rm_asset_upload_link` and `rm_asset_download_link` create separate,
short-lived Ticket URLs. Ticket plaintext is returned only as part of the
signed URL; the server stores only a SHA-256 digest in bounded process memory.

- Upload Tickets expire after five minutes and can complete once.
- A failed upload cannot be replayed.
- Download Tickets expire after five minutes.
- HEAD does not consume a download.
- At most three successful GET requests are accepted.
- Host restart invalidates all outstanding Tickets.

For local loopback use, Remember-Me safely derives
`http://127.0.0.1:<port>`. For network use, configure:

```text
REMEMBER_ME_PUBLIC_BASE_URL=https://remember-me.example
```

The value must be absolute and must not contain credentials, query, or
fragment. Non-loopback use requires HTTPS. Remember-Me does not trust Host,
`X-Forwarded-Host`, or `X-Forwarded-Proto` to construct signed URLs.

## Claude attachment boundary

A standard MCP call does not automatically receive bytes from the current
Claude chat attachment. An environment with code execution must request an
upload link and multipart POST the original bytes to that exact short-lived
URL.

Only allow the precise hostname of the user's own Remember-Me Host. Do not use
an `All domains` network policy. Never place the Standalone Bearer Token,
signed URL, complete hashes, image base64, or local paths in prompts, logs, or
stored metadata.

Stage 7E is not deployed and does not provide automatic TLS or trusted-proxy
configuration.
