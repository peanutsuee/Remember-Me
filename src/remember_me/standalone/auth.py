# SPDX-License-Identifier: CPAL-1.0
"""Bearer Header authentication for standalone asset routes."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status


AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}


def require_asset_access(request: Request) -> None:
    expected = request.app.state.config.resolved_auth_token
    if expected is None:
        request.state.authenticated = True
        return

    header = request.headers.get("authorization", "")
    scheme, separator, supplied = header.partition(" ")
    authenticated = (
        bool(separator)
        and scheme.casefold() == "bearer"
        and bool(supplied)
        and secrets.compare_digest(supplied, expected)
    )
    request.state.authenticated = authenticated
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "authentication_required",
                "message": "Authentication is required.",
            },
            headers=AUTH_HEADERS,
        )
