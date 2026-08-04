# SPDX-License-Identifier: CPAL-1.0
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import ImageContent
from PIL import Image

from remember_me import metadata
from remember_me.mcp.server import (
    ABOUT_RESOURCE_URI,
    MCP_TOOL_NAMES,
)
from remember_me.mcp.transfers import (
    DownloadTicketStore,
    TransferConflict,
    TransferExpired,
    UploadTicketStore,
)
from remember_me.mcp.viewer import (
    VIEWER_RESOURCE_META,
    VIEWER_RESOURCE_URI,
    VIEWER_TOOL_META,
    load_viewer_html,
)
from remember_me.standalone.app import create_app
from remember_me.standalone.config import StandaloneConfig


ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN = "stage7e-" + ("m" * 40)
PRIVATE_MARKERS = (
    "source_sha256",
    "stored_sha256",
    "stored_relpath",
    "blob_key",
    "data_root",
    "assets.sqlite3",
)


def _png(color="purple"):
    output = io.BytesIO()
    image = Image.new("RGBA", (18, 12), color)
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def _jpeg_with_exif():
    output = io.BytesIO()
    image = Image.new("RGB", (17, 11), "gold")
    exif = Image.Exif()
    exif[0x010E] = "private stage7e metadata"
    image.save(output, format="JPEG", quality=95, exif=exif)
    image.close()
    return output.getvalue()


@contextmanager
def _running_host(tmp_path, token=None):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = StandaloneConfig(
        data_root=tmp_path,
        host="127.0.0.1",
        port=port,
        auth_token=token,
    )
    app = create_app(config)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.host,
            port=config.port,
            log_level="warning",
            access_log=False,
            server_header=False,
            date_header=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("test_host_failed_to_start")
    try:
        yield "http://127.0.0.1:{}".format(port)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


async def _with_session(url, callback, token=None):
    headers = (
        {"Authorization": "Bearer " + token}
        if token is not None
        else None
    )
    async with httpx.AsyncClient(headers=headers) as http_client:
        async with streamable_http_client(
            url + "/mcp",
            http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(
                read_stream,
                write_stream,
            ) as session:
                initialize = await session.initialize()
                return await callback(session, initialize)


def _assert_safe_result(result):
    structured = json.dumps(result.structuredContent or {})
    text = "\n".join(
        block.text
        for block in result.content
        if getattr(block, "type", "") == "text"
    )
    for marker in PRIVATE_MARKERS:
        assert marker not in structured
        assert marker not in text
    assert ":\\" not in structured + text


def test_mcp_dependency_python_and_architecture_contract():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in pyproject
    assert '"mcp>=1.28.1,<1.29"' in pyproject
    assert "2.0.0" not in pyproject
    core = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "remember_me" / "core").glob("*.py")
    ).casefold()
    for forbidden in ("fastapi", "starlette", "fastmcp", "import mcp"):
        assert forbidden not in core
    adapter = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "remember_me" / "mcp").glob("*.py")
    ).casefold()
    assert "pillowimagesanitizer" not in adapter
    assert "create table" not in adapter
    assert "insert into assets" not in adapter


def test_mcp_exact_route_protocol_tools_and_resources(tmp_path):
    async def inspect_protocol(session, initialize):
        tools = await session.list_tools()
        resources = await session.list_resources()
        about = await session.read_resource(ABOUT_RESOURCE_URI)
        viewer = await session.read_resource(VIEWER_RESOURCE_URI)
        return initialize, tools, resources, about, viewer

    with _running_host(tmp_path) as base_url:
        raw = httpx.post(
            base_url + "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "route-test", "version": "1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
            follow_redirects=False,
        )
        assert raw.status_code == 200
        assert "location" not in raw.headers
        assert httpx.post(
            base_url + "/mcp/mcp",
            json={},
            follow_redirects=False,
        ).status_code == 404
        initialize, tools, resources, about, viewer = asyncio.run(
            _with_session(base_url, inspect_protocol)
        )

    assert initialize.serverInfo.name == metadata.PROJECT_NAME
    assert initialize.serverInfo.version == metadata.PROJECT_VERSION
    names = [tool.name for tool in tools.tools]
    assert names == list(MCP_TOOL_NAMES)
    assert len(names) == len(set(names)) == 9
    assert not any(
        fragment in name
        for name in names
        for fragment in ("probe", "diagnostic", "vision", "delete")
    )
    uris = [str(resource.uri) for resource in resources.resources]
    assert uris == [ABOUT_RESOURCE_URI, VIEWER_RESOURCE_URI]
    about_payload = json.loads(about.contents[0].text)
    assert about_payload["mcp_api_version"] == "v1alpha1"
    assert about_payload["origin_statement"] == (
        "Remember-Me was originally created by Ting."
    )
    assert about_payload["original_creator"] == "Ting (peanutsuee)"
    assert "host" not in about.contents[0].text.casefold()
    assert viewer.contents[0].mimeType == "text/html;profile=mcp-app"


def test_tool_schemas_annotations_and_mcp_apps_metadata(tmp_path):
    app = create_app(StandaloneConfig(data_root=tmp_path))
    tools = asyncio.run(app.state.mcp_runtime.server.list_tools())
    by_name = {tool.name: tool for tool in tools}
    upload = by_name["rm_asset_upload_link"]
    properties = upload.inputSchema["properties"]
    assert upload.inputSchema["required"] == ["expected_bytes"]
    assert properties["expected_bytes"]["type"] == "integer"
    assert properties["expected_bytes"]["maximum"] == 10 * 1024 * 1024
    assert properties["filename"]["default"] == ""
    assert properties["mime_type"]["default"] == (
        "application/octet-stream"
    )
    assert "expected_sha256" not in json.dumps(upload.inputSchema)
    for tool in tools:
        assert tool.description
        assert tool.outputSchema["properties"]["ok"]["type"] == "boolean"
        assert tool.annotations.destructiveHint is False
    for name in (
        "rm_asset_get",
        "rm_asset_search",
        "rm_asset_upload_status",
        "rm_asset_view",
        "rm_asset_inspect",
    ):
        assert by_name[name].annotations.readOnlyHint is True
        assert by_name[name].annotations.idempotentHint is True
    for name in ("rm_asset_upload_link", "rm_asset_download_link"):
        assert by_name[name].annotations.readOnlyHint is False
        assert by_name[name].annotations.idempotentHint is False
        assert by_name[name].annotations.openWorldHint is True
    assert by_name["rm_asset_view"].meta == VIEWER_TOOL_META
    resources = asyncio.run(app.state.mcp_runtime.server.list_resources())
    viewer = next(
        resource
        for resource in resources
        if str(resource.uri) == VIEWER_RESOURCE_URI
    )
    assert viewer.meta == VIEWER_RESOURCE_META


def test_mcp_bearer_auth_is_header_only_and_redacted(tmp_path):
    async def list_tools(session, _initialize):
        return await session.list_tools()

    with _running_host(tmp_path, token=TEST_TOKEN) as base_url:
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "auth-test", "version": "1"},
            },
        }
        for kwargs in (
            {},
            {"headers": {"Authorization": "Bearer wrong"}},
            {"params": {"token": TEST_TOKEN}},
            {"cookies": {"token": TEST_TOKEN}},
        ):
            response = httpx.post(
                base_url + "/mcp",
                json=initialize,
                follow_redirects=False,
                **kwargs,
            )
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
            assert TEST_TOKEN not in response.text
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["cache-control"] == "no-store"
        tools = asyncio.run(
            _with_session(base_url, list_tools, token=TEST_TOKEN)
        )
        assert len(tools.tools) == 9
        rejected_origin = httpx.post(
            base_url + "/mcp",
            json=initialize,
            headers={
                "Authorization": "Bearer " + TEST_TOKEN,
                "Origin": "https://untrusted.invalid",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert rejected_origin.status_code in {403, 421}


def test_public_base_url_validation_and_repr(tmp_path):
    loopback = StandaloneConfig(data_root=tmp_path, port=9876)
    assert loopback.resolved_public_base_url == "http://127.0.0.1:9876"
    configured = StandaloneConfig(
        data_root=tmp_path,
        public_base_url="https://example.invalid/remember-me/",
    )
    assert configured.resolved_public_base_url == (
        "https://example.invalid/remember-me"
    )
    for value in (
        "relative",
        "https://user:pass@example.invalid",
        "https://example.invalid/path?query=yes",
        "https://example.invalid/path#fragment",
    ):
        with pytest.raises(Exception):
            StandaloneConfig(data_root=tmp_path, public_base_url=value)
    with pytest.raises(Exception):
        StandaloneConfig(
            data_root=tmp_path,
            host="0.0.0.0",
            allow_network=True,
            auth_token=TEST_TOKEN,
            public_base_url="http://example.invalid",
        )
    config = StandaloneConfig(
        data_root=tmp_path,
        auth_token=TEST_TOKEN,
    )
    assert TEST_TOKEN not in repr(config)
    assert TEST_TOKEN not in str(config)


def test_ticket_expiry_replay_and_download_counting():
    clock = [1000.0]
    uploads = UploadTicketStore(
        "http://127.0.0.1:8787",
        ttl_seconds=300,
        now=lambda: clock[0],
    )
    upload, upload_url = uploads.create(10, "x.png", "image/png")
    token = upload_url.rsplit("ticket=", 1)[1]
    uploads.authorize_pending(upload.upload_id, token, consume=True)
    uploads.fail(upload.upload_id)
    with pytest.raises(TransferConflict):
        uploads.authorize_pending(upload.upload_id, token, consume=True)

    expired, expired_url = uploads.create(10, "y.png", "image/png")
    clock[0] += 301
    assert uploads.inspect(expired.upload_id).status == "expired"
    with pytest.raises(TransferExpired):
        uploads.authorize_pending(
            expired.upload_id,
            expired_url.rsplit("ticket=", 1)[1],
            consume=False,
        )

    downloads = DownloadTicketStore(
        "http://127.0.0.1:8787",
        now=lambda: clock[0],
    )
    download, download_url = downloads.create("a" * 32)
    download_token = download_url.rsplit("ticket=", 1)[1]
    downloads.authorize(
        download.download_id,
        download_token,
        consume=False,
    )
    for _ in range(3):
        downloads.authorize(
            download.download_id,
            download_token,
            consume=True,
        )
    with pytest.raises(Exception):
        downloads.authorize(
            download.download_id,
            download_token,
            consume=True,
        )


def test_complete_mcp_generated_image_workflow(tmp_path):
    content = _jpeg_with_exif()

    async def workflow(session, _initialize):
        tools = {}

        async def call(name, arguments):
            result = await session.call_tool(name, arguments)
            assert result.isError is False
            _assert_safe_result(result)
            tools[name] = result
            return result

        link = await call(
            "rm_asset_upload_link",
            {
                "expected_bytes": len(content),
                "filename": "../../private-name.jpg",
                "mime_type": "image/jpeg",
            },
        )
        upload_url = link.structuredContent["upload_url"]
        async with httpx.AsyncClient() as client:
            uploaded = await client.post(
                upload_url,
                files={"file": ("generated.jpg", content, "image/jpeg")},
            )
            assert uploaded.status_code == 200
            replay = await client.post(
                upload_url,
                files={"file": ("generated.jpg", content, "image/jpeg")},
            )
            assert replay.status_code == 409
        status = await call(
            "rm_asset_upload_status",
            {"upload_id": link.structuredContent["upload_id"]},
        )
        assert status.structuredContent["status"] == "completed"
        asset_id = status.structuredContent["asset"]["asset_id"]

        await call("rm_asset_get", {"asset_id": asset_id})
        changed = await call(
            "rm_asset_update_metadata",
            {
                "asset_id": asset_id,
                "title": "<script>alert(1)</script>",
                "description": '<img src=x onerror=alert(1)> & "quoted"',
                "tags": ["One", "one", "<b>Two</b>"],
            },
        )
        assert changed.structuredContent["asset"]["tags"] == [
            "<b>Two</b>",
            "One",
        ]
        searched = await call(
            "rm_asset_search",
            {"query": "script", "tags": ["one"], "limit": 50},
        )
        assert searched.structuredContent["total"] == 1
        reindex = await call("rm_asset_reindex_embeddings", {})
        assert reindex.structuredContent["enabled"] is False
        assert reindex.structuredContent["model_id"].endswith(
            "null-vector-provider-v1"
        )

        inspected = await call(
            "rm_asset_inspect",
            {"asset_id": asset_id},
        )
        image = next(
            block
            for block in inspected.content
            if isinstance(block, ImageContent)
        )
        cleaned = base64.b64decode(image.data)
        with Image.open(io.BytesIO(cleaned)) as decoded:
            decoded.load()
            assert decoded.format == "JPEG"
            assert not decoded.getexif()
        assert image.data not in json.dumps(inspected.structuredContent)
        assert image.data not in inspected.content[0].text

        viewed = await call(
            "rm_asset_view",
            {"asset_id": asset_id},
        )
        assert viewed.meta["remember_me"]["image"]["data"]
        assert "data" not in viewed.structuredContent
        assert viewed.meta["remember_me"]["asset"]["asset_id"] == asset_id

        download = await call(
            "rm_asset_download_link",
            {"asset_id": asset_id},
        )
        download_url = download.structuredContent["download_url"]
        async with httpx.AsyncClient() as client:
            head = await client.head(download_url)
            assert head.status_code == 200
            assert head.headers["x-content-type-options"] == "nosniff"
            assert head.headers["cache-control"] == "private, no-store"
            for _ in range(3):
                response = await client.get(download_url)
                assert response.status_code == 200
                assert response.content == cleaned
            assert (await client.get(download_url)).status_code in {404, 409}

        second_download = await call(
            "rm_asset_download_link",
            {"asset_id": asset_id},
        )
        return (
            asset_id,
            second_download.structuredContent["download_url"],
        )

    with _running_host(tmp_path) as base_url:
        asset_id, remaining_download_url = asyncio.run(
            _with_session(base_url, workflow)
        )
        deleted = httpx.delete(
            base_url + "/api/v1/assets/" + asset_id,
        )
        assert deleted.status_code == 200
        assert httpx.get(remaining_download_url).status_code == 404


def test_signed_upload_validation_and_failure_is_not_replayable(tmp_path):
    content = _png()

    async def get_link(session, _initialize):
        return await session.call_tool(
            "rm_asset_upload_link",
            {
                "expected_bytes": len(content) + 1,
                "filename": "wrong.png",
                "mime_type": "image/png",
            },
        )

    with _running_host(tmp_path) as base_url:
        link = asyncio.run(_with_session(base_url, get_link))
        url = link.structuredContent["upload_url"]
        first = httpx.post(
            url,
            files={"file": ("wrong.png", content, "image/png")},
        )
        assert first.status_code == 400
        assert "upload_size_mismatch" in first.text
        assert httpx.post(
            url,
            files={"file": ("wrong.png", content, "image/png")},
        ).status_code == 409


def test_early_oversized_signed_upload_consumes_ticket(tmp_path):
    content = _png()
    app = create_app(StandaloneConfig(data_root=tmp_path))
    with TestClient(
        app,
        base_url="http://127.0.0.1:8787",
    ) as client:
        link = asyncio.run(
            app.state.mcp_runtime.server.call_tool(
            "rm_asset_upload_link",
            {
                "expected_bytes": len(content),
                "filename": "large.png",
                "mime_type": "image/png",
            },
        )
        )
        url = link.structuredContent["upload_url"]
        rejected = client.post(
            url,
            content=b"",
            headers={
                "Content-Type": "multipart/form-data; boundary=unused",
                "Content-Length": str(12 * 1024 * 1024),
            },
        )
        assert rejected.status_code == 413
        assert client.post(
            url,
            files={"file": ("large.png", content, "image/png")},
        ).status_code == 409


def test_viewer_is_original_self_contained_and_xss_safe():
    viewer = load_viewer_html()
    assert "SPDX-License-Identifier: CPAL-1.0" in viewer
    assert "Ting (peanutsuee)" in viewer
    assert "http://" not in viewer
    assert "https://" not in viewer
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "new Function",
        "eval(",
    ):
        assert forbidden not in viewer
    assert "textContent" in viewer
    assert "createElement" in viewer
    assert 'request("ui/initialize"' in viewer
    assert '"ui/notifications/initialized"' in viewer
    assert 'data.method === "ui/notifications/tool-result"' in viewer
    assert 'data.type === "ui/notifications/tool-result"' not in viewer
    assert "prefers-reduced-motion" in viewer
    assert 'aria-live="polite"' in viewer
    assert VIEWER_RESOURCE_META["ui"]["csp"] == {
        "connectDomains": [],
        "resourceDomains": [],
        "frameDomains": [],
    }


def test_viewer_standard_mcp_apps_protocol_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    result = subprocess.run(
        [node, str(ROOT / "tests" / "viewer_protocol_test.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "viewer protocol simulation passed" in result.stdout


def test_mcp_is_outside_openapi_and_shares_host_runtime(tmp_path):
    app = create_app(
        StandaloneConfig(data_root=tmp_path, enable_docs=True)
    )
    assert app.state.mcp_runtime.server.settings.stateless_http is True
    assert app.state.mcp_runtime.server.settings.json_response is True
    schema = app.openapi()
    assert "/mcp" not in schema["paths"]
    assert not any(
        path.startswith("/transfers/")
        for path in schema["paths"]
    )
    tool = app.state.mcp_runtime.server._tool_manager.get_tool(
        "rm_asset_get"
    )
    closure_values = [
        cell.cell_contents
        for cell in (tool.fn.__closure__ or ())
    ]
    shared = next(
        value
        for value in closure_values
        if hasattr(value, "service")
    )
    assert shared.service is app.state.service
    assert shared.repository is app.state.repository
    assert shared.blob_store is app.state.blob_store


def test_mcp_routes_log_templates_without_signed_query(
    tmp_path,
    caplog,
):
    content = _png()

    async def get_link(session, _initialize):
        return await session.call_tool(
            "rm_asset_upload_link",
            {
                "expected_bytes": len(content),
                "filename": "logged.png",
                "mime_type": "image/png",
            },
        )

    caplog.set_level("INFO", logger="remember_me.standalone.http")
    with _running_host(tmp_path) as base_url:
        link = asyncio.run(_with_session(base_url, get_link))
        signed_url = link.structuredContent["upload_url"]
        ticket_value = signed_url.rsplit("ticket=", 1)[1]
        response = httpx.post(
            signed_url,
            files={"file": ("logged.png", content, "image/png")},
        )
        assert response.status_code == 200
    assert ticket_value not in caplog.text
    assert "?ticket=" not in caplog.text
    assert "/transfers/uploads/{upload_id}" in caplog.text


def test_wheel_contains_mcp_adapter_and_viewer(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".stage7e-venv",
            ".venv",
            ".pytest_cache",
            "__pycache__",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    output = tmp_path / "dist"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(output),
        ],
        cwd=source,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next(output.glob("*.whl"))
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert {
        "remember_me/mcp/__init__.py",
        "remember_me/mcp/server.py",
        "remember_me/mcp/tools.py",
        "remember_me/mcp/transfers.py",
        "remember_me/mcp/schemas.py",
        "remember_me/mcp/viewer.py",
        "remember_me/mcp/asset-viewer.html",
    } <= names
