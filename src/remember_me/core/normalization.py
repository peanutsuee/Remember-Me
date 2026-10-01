# SPDX-License-Identifier: CPAL-1.0
"""Value normalization shared by storage and Core orchestration."""

from __future__ import annotations

import re
import unicodedata

from .errors import ImportMetadataValidationError, InvalidMetadata


_WHITESPACE = re.compile(r"\s+")
_CONTROL_CATEGORIES = {"Cc", "Cf"}


def _clean_text(value, *, maximum, error_type):
    if type(value) is not str:
        raise error_type()
    # Display spelling and comparison spelling have separate responsibilities.
    cleaned = _clean_display(value)
    # Keep the old expansion limit as well as the stored-value limit.
    if len(cleaned) > maximum or len(_clean_scalar(value)) > maximum:
        raise error_type()
    return cleaned


def _clean_display(value: str) -> str:
    cleaned = "".join(
        " " if unicodedata.category(character) in _CONTROL_CATEGORIES
        else character
        for character in value
    )
    return _WHITESPACE.sub(" ", cleaned).strip()


def normalize_title(value: str) -> str:
    return _clean_text(value, maximum=200, error_type=InvalidMetadata)


def normalize_description(value: str) -> str:
    return _clean_text(value, maximum=4000, error_type=InvalidMetadata)


def normalize_import_title(value: str) -> str:
    cleaned = _clean_text(
        value,
        maximum=200,
        error_type=ImportMetadataValidationError,
    )
    if cleaned != value:
        raise ImportMetadataValidationError()
    return cleaned


def normalize_import_description(value: str) -> str:
    cleaned = _clean_text(
        value,
        maximum=4000,
        error_type=ImportMetadataValidationError,
    )
    if cleaned != value:
        raise ImportMetadataValidationError()
    return cleaned


def _clean_tag(value, error_type):
    return _clean_text(value, maximum=64, error_type=error_type)


def normalize_tags(values) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise InvalidMetadata()
    first_display: dict[str, str] = {}
    for value in values:
        display = _clean_tag(value, InvalidMetadata)
        if not display:
            continue
        identity = tag_comparison_key(display)
        first_display.setdefault(identity, display)
    if len(first_display) > 30:
        raise InvalidMetadata()
    return tuple(first_display[key] for key in sorted(first_display))


def _clean_scalar(value) -> str:
    if type(value) is not str:
        return ""
    return _clean_display(unicodedata.normalize("NFKC", value))


def tag_comparison_key(value: str) -> str:
    """Compatibility identity; never use this value as a display spelling."""
    return _clean_scalar(value).casefold()


def _normalize_tags(values) -> tuple[str, ...]:
    try:
        return normalize_tags(values)
    except InvalidMetadata:
        return ()


def validate_import_tags(values) -> tuple[tuple[str, str], ...]:
    if type(values) is not tuple:
        raise ImportMetadataValidationError()
    identities: dict[str, str] = {}
    for value in values:
        display = _clean_tag(value, ImportMetadataValidationError)
        if not display or display != value:
            raise ImportMetadataValidationError()
        identity = tag_comparison_key(display)
        if identity in identities:
            raise ImportMetadataValidationError()
        identities[identity] = display
    if len(identities) > 30:
        raise ImportMetadataValidationError()
    return tuple((identity, identities[identity]) for identity in sorted(identities))


def normalize_filename(value: str) -> str:
    if type(value) is not str:
        raise InvalidMetadata()
    filename = value
    # A compatibility copy keeps the existing path checks effective without
    # rewriting safe filename spelling. Only unsafe separators are replaced.
    if unicodedata.normalize("NFKC", filename).startswith("../"):
        for end in range(1, len(filename) + 1):
            if len(unicodedata.normalize("NFKC", filename[:end])) >= 3:
                filename = "_" + filename[end:]
                break
    safe = "".join(
        "_" if any(separator in unicodedata.normalize("NFKC", character)
                   for separator in ("/", "\\")) else character
        for character in filename
    )
    safe = "".join(
        "_" if unicodedata.category(character) in _CONTROL_CATEGORIES
        else character
        for character in safe
    )
    safe = _WHITESPACE.sub(" ", safe).strip()
    if not safe:
        safe = "image"
    return safe


def validate_import_filename(value: str) -> str:
    if (
        type(value) is not str
        or not value
        or "/" in value
        or "\\" in value
        or unicodedata.normalize("NFKC", value) in {".", ".."}
        or normalize_filename(value) != value
    ):
        raise ImportMetadataValidationError()
    return value


__all__ = [
    "normalize_description",
    "normalize_filename",
    "normalize_import_description",
    "normalize_import_title",
    "normalize_tags",
    "normalize_title",
    "tag_comparison_key",
    "validate_import_filename",
    "validate_import_tags",
]
