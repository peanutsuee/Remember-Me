# SPDX-License-Identifier: CPAL-1.0
"""Request limits, identifiers, safe headers, and metadata-only logging."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from urllib.parse import parse_qs

from .errors import RequestBodyTooLarge


LOGGER = logging.getLogger("remember_me.standalone.http")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_IMAGE_BYTES + 1024 * 1024
MAX_STRUCTURED_BODY_BYTES = 64 * 1024
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (
        b"permissions-policy",
        b"camera=(), microphone=(), geolocation=()",
    ),
)


def safe_request_id(value: str) -> str:
    if isinstance(value, str) and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return secrets.token_hex(16)


class SecureRequestMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        request_id = safe_request_id(headers.get("x-request-id", ""))
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = time.monotonic()
        status_code = 500
        response_started = False
        body_limit = self._body_limit(scope)
        content_length = self._content_length(headers.get("content-length"))

        async def limited_receive():
            message = await receive()
            if message["type"] == "http.request":
                limited_receive.received += len(message.get("body", b""))
                if limited_receive.received > body_limit:
                    raise RequestBodyTooLarge()
            return message

        limited_receive.received = 0

        async def secure_send(message):
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                response_headers = list(message.get("headers", ()))
                lower_names = {name.lower() for name, _ in response_headers}
                for name, value in SECURITY_HEADERS:
                    if name not in lower_names:
                        response_headers.append((name, value))
                if b"cache-control" not in lower_names:
                    response_headers.append((b"cache-control", b"no-store"))
                response_headers.append(
                    (b"x-request-id", request_id.encode("ascii"))
                )
                message["headers"] = response_headers
            await send(message)

        try:
            if content_length is not None and content_length > body_limit:
                self._fail_signed_upload(scope)
                status_code = 413
                await self._send_error(
                    secure_send,
                    status_code,
                    "request_too_large",
                    "Request body is too large.",
                    request_id,
                )
            else:
                await self.app(scope, limited_receive, secure_send)
        except RequestBodyTooLarge:
            self._fail_signed_upload(scope)
            status_code = 413
            if not response_started:
                await self._send_error(
                    secure_send,
                    status_code,
                    "request_too_large",
                    "Request body is too large.",
                    request_id,
                )
        finally:
            route = scope.get("route")
            route_name = getattr(route, "path", scope.get("path", ""))
            state = scope.get("state", {})
            LOGGER.info(
                "request_id=%s method=%s route=%s status=%s duration_ms=%s "
                "authenticated=%s error_code=%s",
                request_id,
                scope.get("method", ""),
                route_name,
                status_code,
                int((time.monotonic() - started_at) * 1000),
                bool(state.get("authenticated", False)),
                state.get("error_code", ""),
            )

    @staticmethod
    def _body_limit(scope) -> int:
        if (
            scope.get("method") == "POST"
            and (
                scope.get("path") == "/api/v1/assets"
                or scope.get("path", "").startswith(
                    "/transfers/uploads/"
                )
            )
        ):
            return MAX_MULTIPART_BYTES
        return MAX_STRUCTURED_BODY_BYTES

    @staticmethod
    def _content_length(value):
        if value is None:
            return None
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    async def _send_error(send, status, code, message, request_id):
        payload = json.dumps(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                }
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    @staticmethod
    def _fail_signed_upload(scope) -> None:
        path = scope.get("path", "")
        prefix = "/transfers/uploads/"
        if not path.startswith(prefix):
            return
        upload_id = path[len(prefix):]
        query = parse_qs(
            scope.get("query_string", b"").decode("ascii", "ignore"),
            keep_blank_values=True,
        )
        values = query.get("ticket", [])
        if len(values) != 1:
            return
        app = scope.get("app")
        try:
            tickets = app.state.mcp_runtime.upload_tickets
            tickets.authorize_pending(
                upload_id,
                values[0],
                consume=True,
            )
            tickets.fail(upload_id, "request_too_large")
        except Exception:
            return
