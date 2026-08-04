# SPDX-License-Identifier: CPAL-1.0
"""Independent FastAPI application over the public Remember-Me Core."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from remember_me.core import (
    AssetConflictError,
    AssetFileUnavailable,
    AssetUnavailable,
    DeleteAssetRequest,
    GetAssetRequest,
    ImageValidationError,
    IngestImageRequest,
    InvalidMetadata,
    RememberMeError,
    ResolveAssetRequest,
    SearchAssetsRequest,
    StorageFailure,
    UpdateMetadataRequest,
    UploadSizeMismatch,
    UploadTooLarge,
)
from remember_me.factory import create_local_runtime
from remember_me.mcp import create_mcp_runtime
from remember_me.mcp.tools import read_cleaned_image
from remember_me.mcp.transfers import (
    TransferConflict,
    TransferError,
    TransferExpired,
)
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

from .auth import require_asset_access
from .config import StandaloneConfig
from .middleware import MAX_IMAGE_BYTES, SecureRequestMiddleware
from .schemas import (
    AboutResponse,
    DeleteAssetResponse,
    MetadataPatch,
    PublicAsset,
    SearchAssetsResponse,
    UploadAssetResponse,
    asset_to_public_response,
)


LOGGER = logging.getLogger("remember_me.standalone.app")
ALLOWED_UPLOAD_FIELDS = {
    "file",
    "expected_bytes",
    "filename",
    "mime_type",
    "title",
    "description",
    "tag",
}
DASHBOARD_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' blob: data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self';"
)
DASHBOARD_STATIC_ASSETS = {
    "styles.css": "text/css",
    "app.js": "application/javascript",
    "api.js": "application/javascript",
    "ui.js": "application/javascript",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers=None,
):
    request.state.error_code = code
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request),
            }
        },
        headers=headers,
    )


def _core_error_details(error: RememberMeError):
    if isinstance(error, UploadTooLarge):
        return 413, "Upload is too large."
    if isinstance(error, (AssetUnavailable, AssetFileUnavailable)):
        return 404, "Asset is unavailable."
    if isinstance(error, AssetConflictError):
        return 409, "Stored asset state conflicts with the request."
    if isinstance(error, (ImageValidationError, UploadSizeMismatch, InvalidMetadata)):
        return 400, "The request is invalid."
    if isinstance(error, StorageFailure):
        return 500, "The asset operation could not be completed."
    return 400, "The request is invalid."


def create_app(
    config: StandaloneConfig,
    *,
    runtime=None,
    service=None,
    repository=None,
    blob_store=None,
    clock=None,
) -> FastAPI:
    if runtime is not None and any(
        item is not None for item in (service, repository, blob_store)
    ):
        raise ValueError("runtime_and_components_are_mutually_exclusive")
    if runtime is None and service is None:
        runtime = create_local_runtime(config.data_root, clock=clock)
    if runtime is not None:
        service = runtime.service
        repository = runtime.repository
        blob_store = runtime.blob_store
    if service is None:
        raise ValueError("service_is_required")
    shared_runtime = runtime or SimpleNamespace(
        service=service,
        repository=repository,
        blob_store=blob_store,
    )
    if repository is None or blob_store is None:
        raise ValueError("repository_and_blob_store_are_required")
    mcp_runtime = create_mcp_runtime(shared_runtime, config)

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_runtime.server.session_manager.run():
            yield

    docs_url = "/docs" if config.enable_docs else None
    openapi_url = "/openapi.json" if config.enable_docs else None
    redoc_url = "/redoc" if config.enable_docs else None
    app = FastAPI(
        title=PROJECT_NAME,
        version=HTTP_API_VERSION,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    app.add_middleware(SecureRequestMiddleware)
    app.state.config = config
    app.state.service = service
    app.state.repository = repository
    app.state.blob_store = blob_store
    app.state.mcp_runtime = mcp_runtime
    dashboard_root = Path(__file__).with_name("dashboard")

    @app.exception_handler(RememberMeError)
    async def handle_core_error(request: Request, error: RememberMeError):
        status_code, message = _core_error_details(error)
        return _error_response(
            request,
            status_code,
            error.code,
            message,
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, _error):
        return _error_response(
            request,
            422,
            "validation_error",
            "Request validation failed.",
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException):
        if isinstance(error.detail, dict):
            code = error.detail.get("code", "http_error")
            message = error.detail.get("message", "The request failed.")
        else:
            code = "http_error"
            message = "The request failed."
        return _error_response(
            request,
            error.status_code,
            code,
            message,
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unknown_error(request: Request, _error):
        LOGGER.error(
            "Unhandled request error request_id=%s",
            _request_id(request),
        )
        return _error_response(
            request,
            500,
            "internal_error",
            "An internal error occurred.",
        )

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request):
        repo = request.app.state.repository
        blobs = request.app.state.blob_store
        try:
            ready = (
                repo is not None
                and blobs is not None
                and bool(repo.check_ready())
                and bool(blobs.check_ready())
            )
        except Exception:
            ready = False
        if not ready:
            return _error_response(
                request,
                503,
                "not_ready",
                "Service is not ready.",
            )
        return {"status": "ready"}

    @app.get("/", include_in_schema=False)
    async def dashboard_redirect():
        return RedirectResponse("/dashboard", status_code=307)

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dashboard/", include_in_schema=False)
    async def dashboard():
        return FileResponse(
            dashboard_root / "index.html",
            media_type="text/html",
            headers={"Content-Security-Policy": DASHBOARD_CSP},
        )

    @app.get("/dashboard/static/{asset_name}", include_in_schema=False)
    async def dashboard_static(asset_name: str):
        media_type = DASHBOARD_STATIC_ASSETS.get(asset_name)
        if media_type is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "dashboard_resource_unavailable",
                    "message": "Dashboard resource is unavailable.",
                },
            )
        return FileResponse(
            dashboard_root / asset_name,
            media_type=media_type,
        )

    @app.get("/api/v1/about", response_model=AboutResponse)
    async def about():
        return AboutResponse(
            project_name=PROJECT_NAME,
            project_version=PROJECT_VERSION,
            http_api_version=HTTP_API_VERSION,
            dashboard_version=DASHBOARD_VERSION,
            mcp_api_version=MCP_API_VERSION,
            attribution=ATTRIBUTION_LINE,
            original_creator="{} ({})".format(
                ORIGINAL_CREATOR,
                ORIGINAL_CREATOR_HANDLE,
            ),
            official_repository=OFFICIAL_REPOSITORY,
            license=PROJECT_LICENSE,
            data_compatibility_version=DATA_COMPATIBILITY_VERSION,
        )

    @app.post(
        "/api/v1/assets",
        response_model=UploadAssetResponse,
        dependencies=[Depends(require_asset_access)],
    )
    async def upload_asset(request: Request):
        async with request.form(
            max_files=1,
            max_fields=40,
            max_part_size=MAX_IMAGE_BYTES,
        ) as form:
            unknown = set(form.keys()) - ALLOWED_UPLOAD_FIELDS
            if unknown:
                raise HTTPException(
                    422,
                    detail={
                        "code": "validation_error",
                        "message": "Request validation failed.",
                    },
                )
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                raise HTTPException(
                    422,
                    detail={
                        "code": "validation_error",
                        "message": "Request validation failed.",
                    },
                )
            expected_values = form.getlist("expected_bytes")
            if len(expected_values) != 1:
                raise HTTPException(
                    422,
                    detail={
                        "code": "validation_error",
                        "message": "Request validation failed.",
                    },
                )
            try:
                expected_bytes = int(expected_values[0])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    422,
                    detail={
                        "code": "validation_error",
                        "message": "Request validation failed.",
                    },
                ) from exc

            content = bytearray()
            try:
                while True:
                    chunk = await upload.read(64 * 1024)
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise UploadTooLarge()
            finally:
                await upload.close()
            filename = str(form.get("filename") or upload.filename or "asset.bin")
            mime_type = str(
                form.get("mime_type")
                or upload.content_type
                or "application/octet-stream"
            )
            result = request.app.state.service.ingest_image(
                IngestImageRequest(
                    content=bytes(content),
                    expected_bytes=expected_bytes,
                    filename=filename,
                    mime_type=mime_type,
                    title=str(form.get("title") or ""),
                    description=str(form.get("description") or ""),
                    tags=tuple(str(tag) for tag in form.getlist("tag")),
                )
            )
            public = asset_to_public_response(result.asset)
            payload = UploadAssetResponse(
                **public.model_dump(),
                deduplicated=result.deduplicated,
            )
            return JSONResponse(
                status_code=200 if result.deduplicated else 201,
                content=payload.model_dump(),
            )

    @app.get(
        "/api/v1/assets/{asset_id}",
        response_model=PublicAsset,
        dependencies=[Depends(require_asset_access)],
    )
    async def get_asset(request: Request, asset_id: str):
        asset = request.app.state.service.get_asset(
            GetAssetRequest(asset_id)
        )
        return asset_to_public_response(asset)

    @app.get(
        "/api/v1/assets",
        response_model=SearchAssetsResponse,
        dependencies=[Depends(require_asset_access)],
    )
    async def search_assets(
        request: Request,
        query: str = "",
        tag: Optional[List[str]] = Query(default=None),
        kind: str = "",
        mime_type: str = "",
        created_from: str = "",
        created_to: str = "",
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0),
    ):
        result = await request.app.state.service.search_assets(
            SearchAssetsRequest(
                query=query,
                tags=tuple(tag or ()),
                kind=kind,
                mime_type=mime_type,
                created_from=created_from,
                created_to=created_to,
                limit=limit,
                offset=offset,
            )
        )
        return SearchAssetsResponse(
            total=result.total,
            limit=result.limit,
            offset=result.offset,
            results=[
                asset_to_public_response(item.asset)
                for item in result.results
            ],
        )

    @app.patch(
        "/api/v1/assets/{asset_id}",
        response_model=PublicAsset,
        dependencies=[Depends(require_asset_access)],
    )
    async def update_asset(
        request: Request,
        asset_id: str,
        patch: MetadataPatch,
    ):
        fields = patch.model_fields_set
        if not fields or any(getattr(patch, field) is None for field in fields):
            raise HTTPException(
                422,
                detail={
                    "code": "validation_error",
                    "message": "Request validation failed.",
                },
            )
        updated = request.app.state.service.update_metadata(
            UpdateMetadataRequest(
                asset_id=asset_id,
                title=patch.title if "title" in fields else None,
                description=(
                    patch.description if "description" in fields else None
                ),
                tags=(
                    tuple(patch.tags)
                    if "tags" in fields and patch.tags is not None
                    else None
                ),
            )
        )
        return asset_to_public_response(updated)

    @app.get(
        "/api/v1/assets/{asset_id}/content",
        dependencies=[Depends(require_asset_access)],
    )
    async def get_asset_content(request: Request, asset_id: str):
        resolved = request.app.state.service.resolve_asset(
            ResolveAssetRequest(asset_id)
        )
        blobs = request.app.state.blob_store
        if blobs is None:
            raise AssetFileUnavailable()
        content = blobs.read(resolved.blob_key)
        return Response(
            content=content,
            media_type=resolved.asset.mime_type,
            headers={
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    @app.delete(
        "/api/v1/assets/{asset_id}",
        response_model=DeleteAssetResponse,
        dependencies=[Depends(require_asset_access)],
    )
    async def delete_asset(request: Request, asset_id: str):
        result = request.app.state.service.delete_asset(
            DeleteAssetRequest(asset_id)
        )
        return DeleteAssetResponse(
            asset_id=result.asset_id,
            deleted=result.deleted,
            cleanup_pending=result.cleanup_pending,
        )

    @app.get(
        "/transfers/uploads/{upload_id}",
        include_in_schema=False,
    )
    async def signed_upload_page(
        request: Request,
        upload_id: str,
        ticket: str = Query(...),
    ):
        if set(request.query_params.keys()) != {"ticket"}:
            raise HTTPException(
                404,
                detail={
                    "code": "transfer_unavailable",
                    "message": "The transfer is unavailable.",
                },
            )
        try:
            request.app.state.mcp_runtime.upload_tickets.authorize_pending(
                upload_id,
                ticket,
                consume=False,
            )
        except TransferError as error:
            raise _transfer_http_error(error) from error
        return HTMLResponse(
            """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Remember-Me upload</title></head>
<body><main><h1>Upload to Remember-Me</h1>
<form method="post" enctype="multipart/form-data">
<label for="file">PNG or JPEG</label>
<input id="file" name="file" type="file" accept="image/png,image/jpeg" required>
<button type="submit">Upload</button></form></main></body></html>""",
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; form-action 'self'; "
                    "style-src 'none'; script-src 'none'; "
                    "img-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none';"
                )
            },
        )

    @app.post(
        "/transfers/uploads/{upload_id}",
        include_in_schema=False,
    )
    async def signed_upload(
        request: Request,
        upload_id: str,
        ticket: str = Query(...),
    ):
        if set(request.query_params.keys()) != {"ticket"}:
            raise HTTPException(
                404,
                detail={
                    "code": "transfer_unavailable",
                    "message": "The transfer is unavailable.",
                },
            )
        tickets = request.app.state.mcp_runtime.upload_tickets
        try:
            upload_ticket = tickets.authorize_pending(
                upload_id,
                ticket,
                consume=True,
            )
        except TransferError as error:
            raise _transfer_http_error(error) from error
        try:
            async with request.form(
                max_files=1,
                max_fields=1,
                max_part_size=MAX_IMAGE_BYTES,
            ) as form:
                if set(form.keys()) != {"file"}:
                    raise HTTPException(
                        422,
                        detail={
                            "code": "validation_error",
                            "message": "Request validation failed.",
                        },
                    )
                upload = form.get("file")
                if not isinstance(upload, UploadFile):
                    raise HTTPException(
                        422,
                        detail={
                            "code": "validation_error",
                            "message": "Request validation failed.",
                        },
                    )
                content = bytearray()
                try:
                    while True:
                        chunk = await upload.read(64 * 1024)
                        if not chunk:
                            break
                        content.extend(chunk)
                        if len(content) > MAX_IMAGE_BYTES:
                            raise UploadTooLarge()
                finally:
                    await upload.close()
            result = request.app.state.service.ingest_image(
                IngestImageRequest(
                    content=bytes(content),
                    expected_bytes=upload_ticket.expected_bytes,
                    filename=(
                        upload_ticket.filename
                        or upload.filename
                        or "asset.bin"
                    ),
                    mime_type=upload_ticket.mime_type,
                )
            )
            tickets.complete(
                upload_id,
                result.asset,
                result.deduplicated,
            )
            return {
                "ok": True,
                "upload_id": upload_id,
                "status": "completed",
                "asset": asset_to_public_response(result.asset).model_dump(),
                "deduplicated": result.deduplicated,
            }
        except Exception:
            tickets.fail(upload_id)
            raise

    @app.api_route(
        "/transfers/downloads/{download_id}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def signed_download(
        request: Request,
        download_id: str,
        ticket: str = Query(...),
    ):
        if set(request.query_params.keys()) != {"ticket"}:
            raise HTTPException(
                404,
                detail={
                    "code": "transfer_unavailable",
                    "message": "The transfer is unavailable.",
                },
            )
        tickets = request.app.state.mcp_runtime.download_tickets
        consume = request.method == "GET"
        try:
            download_ticket = tickets.authorize(
                download_id,
                ticket,
                consume=consume,
            )
            asset, content = read_cleaned_image(
                shared_runtime,
                download_ticket.asset_id,
            )
        except TransferError as error:
            raise _transfer_http_error(error) from error
        except Exception:
            tickets.invalidate(download_id)
            raise AssetFileUnavailable()
        extension = ".png" if asset.mime_type == "image/png" else ".jpg"
        filename = asset.original_filename or (
            "remember-me-image" + extension
        )
        headers = {
            "Content-Disposition": (
                "attachment; filename=\"remember-me-image{}\"; "
                "filename*=UTF-8''{}"
            ).format(extension, quote(filename, safe="")),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
        }
        if request.method == "HEAD":
            headers["Content-Length"] = str(len(content))
            return Response(
                content=b"",
                media_type=asset.mime_type,
                headers=headers,
            )
        return Response(
            content=content,
            media_type=asset.mime_type,
            headers=headers,
        )

    app.router.routes.extend(mcp_runtime.asgi_app.routes)

    return app


def _transfer_http_error(error: TransferError) -> HTTPException:
    if isinstance(error, TransferExpired):
        status_code = 410
    elif isinstance(error, TransferConflict):
        status_code = 409
    else:
        status_code = 404
    return HTTPException(
        status_code,
        detail={
            "code": error.code,
            "message": "The transfer is unavailable.",
        },
    )
