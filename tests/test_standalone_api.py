# SPDX-License-Identifier: CPAL-1.0
import asyncio
import io
import json
import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from remember_me.core import AssetFileUnavailable
from remember_me.factory import create_local_runtime
from remember_me.standalone.app import create_app
from remember_me.standalone.config import StandaloneConfig
from remember_me.standalone.middleware import (
    MAX_MULTIPART_BYTES,
    SecureRequestMiddleware,
)


TEST_TOKEN = "stage7c-" + ("t" * 32)
AUTH = {"Authorization": "Bearer " + TEST_TOKEN}
PRIVATE_FIELDS = {
    "source_sha256",
    "stored_sha256",
    "stored_relpath",
    "blob_key",
    "data_root",
}


class FakeClock:
    def now(self):
        return datetime(2026, 7, 25, 8, 9, 10, tzinfo=timezone.utc)


def _image(format_name="PNG", color="blue"):
    image = Image.new("RGB", (8, 6), color)
    output = io.BytesIO()
    options = {"quality": 95} if format_name == "JPEG" else {}
    image.save(output, format=format_name, **options)
    image.close()
    return output.getvalue()


def _client(tmp_path, token=TEST_TOKEN, docs=False, raise_errors=True):
    config = StandaloneConfig(
        data_root=tmp_path,
        auth_token=token,
        enable_docs=docs,
    )
    runtime = create_local_runtime(tmp_path, clock=FakeClock())
    app = create_app(config, runtime=runtime)
    return TestClient(app, raise_server_exceptions=raise_errors), runtime


def _upload(
    client,
    content,
    *,
    filename="photo.png",
    mime_type="image/png",
    title="",
    description="",
    tags=(),
    headers=AUTH,
    expected_bytes=None,
):
    data = {
        "expected_bytes": str(
            len(content) if expected_bytes is None else expected_bytes
        ),
        "title": title,
        "description": description,
        "tag": list(tags),
    }
    return client.post(
        "/api/v1/assets",
        data=data,
        files={"file": (filename, content, mime_type)},
        headers=headers,
    )


def _assert_no_private_fields(payload):
    serialized = json.dumps(payload)
    for field in PRIVATE_FIELDS:
        assert field not in serialized
    assert ":\\" not in serialized


def test_public_routes_and_security_headers(tmp_path):
    client, _ = _client(tmp_path)
    for path, expected in [
        ("/healthz", {"status": "ok"}),
        ("/readyz", {"status": "ready"}),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == expected
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-request-id"]

    about = client.get("/api/v1/about")
    assert about.status_code == 200
    assert about.json()["project_version"] == "0.1.0.dev7"
    assert about.json()["http_api_version"] == "v1alpha1"
    assert about.json()["dashboard_version"] == "v1alpha1"
    assert about.json()["mcp_api_version"] == "v1alpha1"
    assert about.json()["original_creator"] == "Ting (peanutsuee)"


def test_token_authentication_is_header_only(tmp_path):
    client, _ = _client(tmp_path)
    for request in [
        client.get("/api/v1/assets"),
        client.get("/api/v1/assets", headers={"Authorization": "Bearer wrong"}),
        client.get("/api/v1/assets?token=" + TEST_TOKEN),
    ]:
        assert request.status_code == 401
        assert request.headers["www-authenticate"] == "Bearer"
        assert request.json()["error"]["code"] == "authentication_required"
        assert TEST_TOKEN not in request.text
    client.cookies.set("token", TEST_TOKEN)
    cookie_request = client.get("/api/v1/assets")
    client.cookies.clear()
    assert cookie_request.status_code == 401
    assert client.get("/api/v1/assets", headers=AUTH).status_code == 200
    assert client.get(
        "/api/v1/assets",
        headers={"Authorization": "bEaReR " + TEST_TOKEN},
    ).status_code == 200


def test_loopback_without_token_allows_local_asset_routes(tmp_path):
    client, _ = _client(tmp_path, token=None)
    assert client.get("/api/v1/assets").status_code == 200


def test_search_limit_matches_public_core_contract_and_openapi(tmp_path):
    client, _ = _client(tmp_path)
    at_limit = client.get(
        "/api/v1/assets",
        params={"limit": 50},
        headers=AUTH,
    )
    assert at_limit.status_code == 200
    assert at_limit.json()["limit"] == 50

    over_limit = client.get(
        "/api/v1/assets",
        params={"limit": 51},
        headers=AUTH,
    )
    assert over_limit.status_code == 422
    assert over_limit.json()["error"]["code"] == "validation_error"

    schema = create_app(
        StandaloneConfig(data_root=tmp_path / "openapi", enable_docs=True)
    ).openapi()
    operation = schema["paths"]["/api/v1/assets"]["get"]
    limit_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "limit"
    )
    assert limit_parameter["schema"]["default"] == 20
    assert limit_parameter["schema"]["maximum"] == 50


@pytest.mark.parametrize(
    "format_name,filename,mime_type",
    [
        ("PNG", "photo.png", "image/png"),
        ("JPEG", "photo.jpg", "image/jpeg"),
        ("PNG", "transport.bin", "application/octet-stream"),
    ],
)
def test_upload_get_search_content_and_delete(
    tmp_path,
    format_name,
    filename,
    mime_type,
):
    client, _ = _client(tmp_path)
    content = _image(format_name)
    uploaded = _upload(
        client,
        content,
        filename=filename,
        mime_type=mime_type,
        title="Summer",
        description="local trip",
        tags=("Travel", "Blue"),
    )
    assert uploaded.status_code == 201
    payload = uploaded.json()
    assert payload["deduplicated"] is False
    assert payload["title"] == "Summer"
    assert payload["tags"] == ["Blue", "Travel"]
    _assert_no_private_fields(payload)
    asset_id = payload["asset_id"]

    fetched = client.get("/api/v1/assets/" + asset_id, headers=AUTH)
    assert fetched.status_code == 200
    _assert_no_private_fields(fetched.json())

    searched = client.get(
        "/api/v1/assets",
        params=[
            ("query", "summer"),
            ("tag", "travel"),
            ("tag", "blue"),
            ("created_from", "2026-07-25"),
            ("limit", "5"),
            ("offset", "0"),
        ],
        headers=AUTH,
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    _assert_no_private_fields(searched.json())

    downloaded = client.get(
        "/api/v1/assets/{}/content".format(asset_id),
        headers=AUTH,
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith(payload["mime_type"])
    assert downloaded.headers["content-disposition"] == "inline"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(downloaded.content)) as image:
        image.load()
        assert image.format in {"PNG", "JPEG"}

    deleted = client.delete("/api/v1/assets/" + asset_id, headers=AUTH)
    assert deleted.status_code == 200
    assert deleted.json() == {
        "asset_id": asset_id,
        "deleted": True,
        "cleanup_pending": False,
    }
    assert client.get(
        "/api/v1/assets/" + asset_id,
        headers=AUTH,
    ).status_code == 404
    assert client.get(
        "/api/v1/assets/{}/content".format(asset_id),
        headers=AUTH,
    ).status_code == 404


def test_upload_validation_dedup_and_no_metadata_overwrite(tmp_path):
    client, _ = _client(tmp_path)
    content = _image()
    first = _upload(
        client,
        content,
        title="original",
        description="keep",
        tags=("first",),
    )
    assert first.status_code == 201
    duplicate = _upload(
        client,
        content,
        title="replacement",
        description="overwrite",
        tags=("second",),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["deduplicated"] is True
    assert duplicate.json()["title"] == "original"
    assert duplicate.json()["description"] == "keep"
    assert duplicate.json()["tags"] == ["first"]

    mismatch = _upload(client, content, expected_bytes=len(content) + 1)
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "upload_size_mismatch"
    mime = _upload(client, content, mime_type="image/jpeg")
    assert mime.status_code == 400
    invalid = _upload(
        client,
        b"not an image",
        filename="bad.bin",
        mime_type="application/octet-stream",
    )
    assert invalid.status_code == 400


def test_upload_rejects_internal_and_unknown_fields(tmp_path):
    client, _ = _client(tmp_path)
    content = _image()
    for field in [
        "expected_sha256",
        "source_sha256",
        "stored_sha256",
        "blob_key",
        "target_path",
    ]:
        response = client.post(
            "/api/v1/assets",
            data={
                "expected_bytes": str(len(content)),
                field: "not-accepted",
            },
            files={"file": ("photo.png", content, "image/png")},
            headers=AUTH,
        )
        assert response.status_code == 422


def test_patch_semantics_and_rejections(tmp_path):
    client, _ = _client(tmp_path)
    content = _image()
    asset_id = _upload(
        client,
        content,
        title="title",
        description="description",
        tags=("one", "two"),
    ).json()["asset_id"]

    changed = client.patch(
        "/api/v1/assets/" + asset_id,
        json={"title": "", "description": "", "tags": []},
        headers=AUTH,
    )
    assert changed.status_code == 200
    assert changed.json()["title"] == ""
    assert changed.json()["description"] == ""
    assert changed.json()["tags"] == []

    title_only = client.patch(
        "/api/v1/assets/" + asset_id,
        json={"title": "new"},
        headers=AUTH,
    )
    assert title_only.status_code == 200
    assert title_only.json()["title"] == "new"
    assert title_only.json()["description"] == ""

    for body in [
        {},
        {"title": None},
        {"description": None},
        {"tags": None},
        {"unknown": "value"},
    ]:
        response = client.patch(
            "/api/v1/assets/" + asset_id,
            json=body,
            headers=AUTH,
        )
        assert response.status_code == 422


def test_missing_blob_has_safe_error(tmp_path):
    client, runtime = _client(tmp_path)
    asset_id = _upload(client, _image()).json()["asset_id"]
    resolved = runtime.service.resolve_asset(
        __import__(
            "remember_me.core",
            fromlist=["ResolveAssetRequest"],
        ).ResolveAssetRequest(asset_id)
    )
    runtime.blob_store.delete(resolved.blob_key)
    response = client.get(
        "/api/v1/assets/{}/content".format(asset_id),
        headers=AUTH,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_file_unavailable"
    _assert_no_private_fields(response.json())


def test_request_id_rules_and_error_envelope(tmp_path):
    client, _ = _client(tmp_path)
    valid = "client-request_123"
    response = client.get(
        "/api/v1/assets/not-an-id",
        headers={**AUTH, "X-Request-ID": valid},
    )
    assert response.status_code == 404
    assert response.headers["x-request-id"] == valid
    assert response.json() == {
        "error": {
            "code": "asset_unavailable",
            "message": "Asset is unavailable.",
            "request_id": valid,
        }
    }

    invalid = client.get(
        "/api/v1/assets/not-an-id",
        headers={**AUTH, "X-Request-ID": "bad\r\nvalue"},
    )
    assert invalid.headers["x-request-id"] != "bad\r\nvalue"
    assert len(invalid.headers["x-request-id"]) == 32


def test_not_ready_and_no_default_cors(tmp_path, monkeypatch):
    client, runtime = _client(tmp_path)
    monkeypatch.setattr(runtime.repository, "check_ready", lambda: False)
    response = client.get(
        "/readyz",
        headers={"Origin": "https://example.invalid"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"
    assert "access-control-allow-origin" not in response.headers


def test_content_length_limit_rejects_before_parsing(tmp_path):
    client, _ = _client(tmp_path)
    response = client.post(
        "/api/v1/assets",
        content=b"",
        headers={
            **AUTH,
            "Content-Type": "multipart/form-data; boundary=unused",
            "Content-Length": str(MAX_MULTIPART_BYTES + 1),
        },
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_file_and_structured_body_limits(tmp_path):
    client, _ = _client(tmp_path)
    oversized_file = b"x" * (10 * 1024 * 1024 + 1)
    upload = _upload(
        client,
        oversized_file,
        filename="large.bin",
        mime_type="application/octet-stream",
    )
    assert upload.status_code == 413
    assert upload.json()["error"]["code"] == "upload_too_large"

    structured = client.patch(
        "/api/v1/assets/" + ("a" * 32),
        content=b"{" + (b" " * (64 * 1024)) + b"}",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert structured.status_code == 413
    assert structured.json()["error"]["code"] == "request_too_large"


def test_streaming_limit_works_without_content_length():
    consumed = []
    sent = []
    chunks = [
        b"x" * (MAX_MULTIPART_BYTES // 2),
        b"y" * (MAX_MULTIPART_BYTES // 2 + 2),
    ]

    async def receive():
        body = chunks.pop(0)
        consumed.append(len(body))
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(chunks),
        }

    async def send(message):
        sent.append(message)

    async def consume_app(_scope, receive_call, _send):
        while True:
            message = await receive_call()
            if not message.get("more_body"):
                break

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/assets",
        "headers": [],
        "state": {},
    }
    asyncio.run(SecureRequestMiddleware(consume_app)(scope, receive, send))
    assert [message["status"] for message in sent if message["type"] == "http.response.start"] == [413]
    assert sum(consumed) > MAX_MULTIPART_BYTES


def test_docs_default_off_and_safe_when_enabled(tmp_path):
    default_client, _ = _client(tmp_path)
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert default_client.get(path).status_code == 404

    docs_client, _ = _client(tmp_path / "docs", docs=True)
    assert docs_client.get("/docs").status_code == 200
    assert docs_client.get("/redoc").status_code == 200
    schema_response = docs_client.get("/openapi.json")
    assert schema_response.status_code == 200
    schema = json.dumps(schema_response.json())
    for forbidden in [
        "expected_sha256",
        "source_sha256",
        "stored_sha256",
        "stored_relpath",
        "blob_key",
        "auth_token",
    ]:
        assert forbidden not in schema


def test_unknown_exception_is_not_returned_or_logged_with_private_values(
    tmp_path,
    monkeypatch,
    caplog,
):
    client, runtime = _client(tmp_path, raise_errors=False)
    private_marker = "private-title-" + ("z" * 20)

    def fail(_request):
        raise RuntimeError(private_marker)

    monkeypatch.setattr(runtime.service, "get_asset", fail)
    caplog.set_level(logging.INFO)
    response = client.get("/api/v1/assets/" + ("a" * 32), headers=AUTH)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert private_marker not in response.text
    assert TEST_TOKEN not in caplog.text
    assert private_marker not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_delete_cleanup_pending_is_exposed_safely(tmp_path, monkeypatch):
    client, runtime = _client(tmp_path)
    asset_id = _upload(client, _image()).json()["asset_id"]
    monkeypatch.setattr(
        runtime.blob_store,
        "finalize_quarantined",
        lambda _key: False,
    )
    response = client.delete("/api/v1/assets/" + asset_id, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["cleanup_pending"] is True
    _assert_no_private_fields(response.json())
