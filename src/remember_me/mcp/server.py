# SPDX-License-Identifier: CPAL-1.0
"""FastMCP assembly over the shared standalone Remember-Me runtime."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from remember_me.metadata import (
    ATTRIBUTION_LINE,
    DASHBOARD_VERSION,
    DATA_COMPATIBILITY_VERSION,
    HTTP_API_VERSION,
    MCP_API_VERSION,
    OFFICIAL_REPOSITORY,
    ORIGINAL_CREATOR,
    ORIGINAL_CREATOR_HANDLE,
    PROJECT_LICENSE,
    PROJECT_NAME,
    PROJECT_VERSION,
)

from .tools import register_tools
from .transfers import DownloadTicketStore, UploadTicketStore
from .viewer import (
    VIEWER_MIME_TYPE,
    VIEWER_RESOURCE_META,
    VIEWER_RESOURCE_URI,
    load_viewer_html,
)


MCP_TOOL_NAMES = (
    "rm_asset_upload_link",
    "rm_asset_upload_status",
    "rm_asset_get",
    "rm_asset_update_metadata",
    "rm_asset_reindex_embeddings",
    "rm_asset_search",
    "rm_asset_download_link",
    "rm_asset_view",
    "rm_asset_inspect",
)
ABOUT_RESOURCE_URI = "remember-me://about"


class McpBearerAuthMiddleware:
    def __init__(self, app, expected_token):
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.expected_token is None:
            scope.setdefault("state", {})["authenticated"] = True
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        scheme, separator, supplied = headers.get(
            "authorization",
            "",
        ).partition(" ")
        authenticated = (
            bool(separator)
            and scheme.casefold() == "bearer"
            and bool(supplied)
            and secrets.compare_digest(supplied, self.expected_token)
        )
        scope.setdefault("state", {})["authenticated"] = authenticated
        if authenticated:
            await self.app(scope, receive, send)
            return
        payload = json.dumps(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "Authentication is required.",
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


@dataclass(frozen=True)
class RememberMeMcpRuntime:
    server: FastMCP
    asgi_app: object
    upload_tickets: UploadTicketStore
    download_tickets: DownloadTicketStore


def create_mcp_runtime(runtime, config) -> RememberMeMcpRuntime:
    allowed_hosts = [
        "127.0.0.1:*",
        "localhost:*",
        "[::1]:*",
    ]
    allowed_origins = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
    ]
    host_pattern = (
        "[{}]:*".format(config.host)
        if ":" in config.host and not config.host.startswith("[")
        else "{}:*".format(config.host)
    )
    if host_pattern not in allowed_hosts:
        allowed_hosts.append(host_pattern)
    if config.resolved_public_base_url:
        parsed_base = urlsplit(config.resolved_public_base_url)
        if parsed_base.netloc not in allowed_hosts:
            allowed_hosts.append(parsed_base.netloc)
        origin = "{}://{}".format(parsed_base.scheme, parsed_base.netloc)
        if origin not in allowed_origins:
            allowed_origins.append(origin)
    mcp = FastMCP(
        PROJECT_NAME,
        instructions=(
            "Use the nine public Remember-Me image asset tools. "
            "Internal hashes and local paths are never public."
        ),
        website_url=OFFICIAL_REPOSITORY,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        log_level=config.log_level,
        host=config.host,
        port=config.port,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )
    mcp._mcp_server.version = PROJECT_VERSION
    uploads = UploadTicketStore(config.resolved_public_base_url)
    downloads = DownloadTicketStore(config.resolved_public_base_url)
    register_tools(mcp, runtime, uploads, downloads)

    @mcp.resource(
        ABOUT_RESOURCE_URI,
        name="Remember-Me project information",
        description="Canonical public identity and protocol versions.",
        mime_type="application/json",
    )
    def remember_me_about() -> str:
        return json.dumps(
            {
                "project_name": PROJECT_NAME,
                "project_version": PROJECT_VERSION,
                "mcp_api_version": MCP_API_VERSION,
                "http_api_version": HTTP_API_VERSION,
                "dashboard_version": DASHBOARD_VERSION,
                "data_compatibility_version": DATA_COMPATIBILITY_VERSION,
                "official_repository": OFFICIAL_REPOSITORY,
                "license": PROJECT_LICENSE,
                "original_creator": "{} ({})".format(
                    ORIGINAL_CREATOR,
                    ORIGINAL_CREATOR_HANDLE,
                ),
                "attribution": ATTRIBUTION_LINE,
                "origin_statement": (
                    "Remember-Me was originally created by Ting."
                ),
            },
            sort_keys=True,
        )

    @mcp.resource(
        VIEWER_RESOURCE_URI,
        name="Remember-Me asset viewer",
        description=(
            "Original single-image MCP App viewer for privacy-cleaned assets."
        ),
        mime_type=VIEWER_MIME_TYPE,
        meta=VIEWER_RESOURCE_META,
    )
    def remember_me_asset_viewer() -> str:
        return load_viewer_html()

    asgi_app = mcp.streamable_http_app()
    for route in asgi_app.routes:
        route.app = McpBearerAuthMiddleware(
            route.app,
            config.resolved_auth_token,
        )
        route.include_in_schema = False
    return RememberMeMcpRuntime(
        server=mcp,
        asgi_app=asgi_app,
        upload_tickets=uploads,
        download_tickets=downloads,
    )
