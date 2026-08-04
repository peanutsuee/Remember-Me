# SPDX-License-Identifier: CPAL-1.0
"""Canonical Core-owned vector indexing text and content identity."""

from __future__ import annotations

import hashlib
import math

from .models import AssetRecord


def canonical_index_text(asset: AssetRecord) -> str:
    title = asset.title.strip()
    description = asset.description.strip()
    tags = tuple(
        sorted(
            (tag.strip() for tag in asset.tags if tag.strip()),
            key=lambda tag: (tag.casefold(), tag),
        )
    )
    if not title and not description and not tags:
        return ""
    return "\n".join(
        (
            "Title: {}".format(title),
            "Description: {}".format(description),
            "Tags: {}".format(", ".join(tags)),
            "Filename: {}".format(asset.original_filename),
            "Kind: {}".format(asset.kind),
            "MIME type: {}".format(asset.mime_type),
        )
    )


def index_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_embedding_vector(vector, accepted_types):
    if not isinstance(vector, accepted_types) or not vector:
        return None
    normalized = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            normalized_value = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        if not math.isfinite(normalized_value):
            return None
        normalized.append(normalized_value)
    return tuple(normalized)


def validate_embedding_vector(vector):
    """Normalize a provider vector, accepting only the async provider contract."""
    return _normalize_embedding_vector(vector, list)


def validate_stored_embedding_vector(vector):
    """Normalize an immutable persisted vector after repository decoding."""
    return _normalize_embedding_vector(vector, (list, tuple))


def cosine_similarity(left, right):
    left_values = validate_stored_embedding_vector(left)
    right_values = validate_stored_embedding_vector(right)
    if (
        left_values is None
        or right_values is None
        or len(left_values) != len(right_values)
    ):
        return None
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    score = sum(
        left * right for left, right in zip(left_values, right_values)
    ) / (left_norm * right_norm)
    if not math.isfinite(score):
        return None
    return max(-1.0, min(1.0, score))


__all__ = [
    "canonical_index_text",
    "cosine_similarity",
    "index_content_hash",
    "validate_embedding_vector",
    "validate_stored_embedding_vector",
]
