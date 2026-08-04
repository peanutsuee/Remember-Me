# SPDX-License-Identifier: CPAL-1.0
"""Deterministic keyword matching over immutable asset snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from remember_me.core.models import (
    AssetRecord,
    SearchAssetsRequest,
    SearchAssetsResult,
    SearchResultItem,
)
from remember_me.core.normalization import _clean_scalar, _normalize_tags


_REASON_PRIORITY = {
    "asset_id_exact": 0,
    "tag_exact": 1,
    "title_exact": 2,
    "filename": 3,
    "description": 4,
}


def _timestamp_sort_key(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone()
    except (TypeError, ValueError):
        return datetime.min


def _date_part(value: str) -> str:
    return (value or "")[:10]


def _asset_matches_filters(
    asset: AssetRecord,
    request: SearchAssetsRequest,
    required_tags: tuple[str, ...],
) -> bool:
    if request.kind and asset.kind != request.kind:
        return False
    if request.mime_type and asset.mime_type != request.mime_type:
        return False
    created = _date_part(asset.created_at)
    if request.created_from and created < request.created_from[:10]:
        return False
    if request.created_to and created > request.created_to[:10]:
        return False
    if required_tags:
        identities = {tag.casefold() for tag in asset.tags}
        if any(tag not in identities for tag in required_tags):
            return False
    return True


def _reasons_for(asset: AssetRecord, query: str) -> tuple[tuple[str, ...], int]:
    if not query:
        return (), len(_REASON_PRIORITY)
    reasons: list[str] = []
    query_folded = query.casefold()
    if asset.asset_id.casefold() == query_folded:
        reasons.append("asset_id_exact")
    if any(tag.casefold() == query_folded for tag in asset.tags):
        reasons.append("tag_exact")
    title = asset.title.casefold()
    if title == query_folded or title.startswith(query_folded) or query_folded in title:
        reasons.append("title_exact")
    if query_folded in asset.original_filename.casefold():
        reasons.append("filename")
    if query_folded in asset.description.casefold():
        reasons.append("description")
    if not reasons:
        return (), len(_REASON_PRIORITY)
    rank = min(_REASON_PRIORITY[reason] for reason in reasons)
    return tuple(reasons), rank


def keyword_search(
    assets: Iterable[AssetRecord],
    request: SearchAssetsRequest,
) -> SearchAssetsResult:
    query = _clean_scalar(request.query)
    required_tags = tuple(
        value.casefold() for value in _normalize_tags(request.tags)
    )
    candidates: list[tuple[int, AssetRecord, tuple[str, ...]]] = []
    for asset in tuple(assets):
        if not _asset_matches_filters(asset, request, required_tags):
            continue
        reasons, rank = _reasons_for(asset, query)
        if query and not reasons:
            continue
        candidates.append((rank, asset, reasons))

    candidates.sort(
        key=lambda item: (
            item[0],
            -_timestamp_sort_key(item[1].created_at).timestamp(),
            item[1].asset_id,
        )
    )
    total = len(candidates)
    offset = max(0, request.offset)
    limit = max(0, request.limit)
    selected = candidates[offset : offset + limit]
    return SearchAssetsResult(
        total=total,
        offset=request.offset,
        limit=request.limit,
        results=tuple(
            SearchResultItem(asset=asset, match_reasons=reasons)
            for _, asset, reasons in selected
        ),
    )
