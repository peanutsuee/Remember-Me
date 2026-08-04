# SPDX-License-Identifier: CPAL-1.0
"""Confined local content-addressed storage."""

from __future__ import annotations

import hashlib
import ntpath
import os
from pathlib import Path
import re
import secrets
import time

from remember_me.core.errors import (
    AssetFileUnavailable,
    StorageFailure,
    StoredFileConflict,
)


_KEY_PATTERN = re.compile(
    r"assets/([0-9a-f]{2})/([0-9a-f]{64})(\.png|\.jpg)\Z"
)
_PLACEMENT_RETRIES = 50


def _windows_comparison_parts(value):
    text = os.fspath(value).replace("/", "\\")
    lowered = text.casefold()
    if lowered.startswith("\\\\.\\") or lowered.startswith("\\??\\"):
        raise ValueError("unsupported_windows_namespace")
    if lowered.startswith("\\\\?\\globalroot\\"):
        raise ValueError("unsupported_windows_namespace")
    if lowered.startswith("\\\\?\\unc\\"):
        text = "\\\\" + text[8:]
    elif lowered.startswith("\\\\?\\"):
        text = text[4:]
    if not ntpath.isabs(text):
        raise ValueError("relative_windows_path")
    normalized = ntpath.normpath(text)
    drive, tail = ntpath.splitdrive(normalized)
    if not drive:
        raise ValueError("missing_windows_root")
    components = tuple(
        component.casefold()
        for component in tail.split("\\")
        if component
    )
    return drive.casefold(), components


def _path_is_within(candidate, root):
    if os.name == "nt" or (
        isinstance(candidate, str)
        and ("\\" in candidate or re.match(r"^[A-Za-z]:", candidate))
    ):
        try:
            candidate_drive, candidate_parts = _windows_comparison_parts(candidate)
            root_drive, root_parts = _windows_comparison_parts(root)
        except ValueError:
            return False
        return (
            candidate_drive == root_drive
            and candidate_parts[: len(root_parts)] == root_parts
        )
    candidate_path = Path(candidate).resolve(strict=False)
    root_path = Path(root).resolve(strict=False)
    try:
        candidate_path.relative_to(root_path)
    except ValueError:
        return False
    return True


class LocalContentStore:
    def __init__(self, data_root):
        self.data_root = Path(data_root).resolve()
        self.assets_root = self.data_root / "assets"
        self.temp_root = self.assets_root / ".tmp"
        try:
            self.temp_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise StorageFailure() from None

    def _ensure_confined(self, path: Path) -> None:
        try:
            actual_root = Path(os.path.realpath(self.assets_root))
            actual_path = Path(os.path.realpath(path))
        except (OSError, ValueError):
            raise StorageFailure("invalid_blob_key") from None
        if not _path_is_within(str(actual_path), str(actual_root)):
            raise StorageFailure("invalid_blob_key") from None

    def _resolve_blob(self, blob_key):
        if type(blob_key) is not str:
            raise StorageFailure("invalid_blob_key")
        match = _KEY_PATTERN.fullmatch(blob_key)
        if match is None or match.group(1) != match.group(2)[:2]:
            raise StorageFailure("invalid_blob_key")
        path = self.data_root.joinpath(*blob_key.split("/"))
        self._ensure_confined(path)
        return path, match.group(2)

    def _resolve_quarantine(self, quarantine_key):
        if type(quarantine_key) is not str:
            raise StorageFailure("invalid_quarantine_key")
        name = quarantine_key.removeprefix("quarantine/")
        if (
            not quarantine_key.startswith("quarantine/")
            or not re.fullmatch(r"[0-9a-f]{32}", name)
        ):
            raise StorageFailure("invalid_quarantine_key")
        path = self.temp_root / ("quarantine-" + name)
        self._ensure_confined(path)
        return path

    def _hash_file(self, path):
        digest = hashlib.sha256()
        try:
            with Path(path).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            raise StorageFailure() from None
        return digest.hexdigest()

    def _existing_matches(self, destination, content, expected_hash):
        try:
            if not destination.is_file():
                return None
            if destination.stat().st_size != len(content):
                return False
            return self._hash_file(destination) == expected_hash
        except StorageFailure:
            raise
        except OSError:
            raise StorageFailure() from None

    def put(self, blob_key, content):
        if type(content) is not bytes:
            raise StorageFailure()
        destination, expected_hash = self._resolve_blob(blob_key)
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise StoredFileConflict()
        try:
            existing = self._existing_matches(
                destination,
                content,
                expected_hash,
            )
        except StorageFailure:
            existing = None
        if existing is True:
            return False
        if existing is False:
            raise StoredFileConflict()
        temporary = self.temp_root / ("publish-" + secrets.token_hex(16))
        self._ensure_confined(temporary)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_confined(destination)
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(_PLACEMENT_RETRIES + 1):
                try:
                    os.replace(temporary, destination)
                    return True
                except PermissionError:
                    try:
                        existing = self._existing_matches(
                            destination,
                            content,
                            expected_hash,
                        )
                    except StorageFailure:
                        existing = None
                    if existing is True:
                        return False
                    if existing is False:
                        raise StoredFileConflict() from None
                    if attempt == _PLACEMENT_RETRIES:
                        raise StorageFailure() from None
                    time.sleep(0.01)
                except OSError:
                    existing = self._existing_matches(
                        destination,
                        content,
                        expected_hash,
                    )
                    if existing is True:
                        return False
                    if existing is False:
                        raise StoredFileConflict() from None
                    raise StorageFailure() from None
        except (StorageFailure, StoredFileConflict):
            raise
        except OSError:
            raise StorageFailure() from None
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def read(self, blob_key):
        path, _ = self._resolve_blob(blob_key)
        try:
            return path.read_bytes()
        except OSError:
            raise StorageFailure() from None

    def exists(self, blob_key):
        path, _ = self._resolve_blob(blob_key)
        try:
            return path.is_file()
        except OSError:
            raise StorageFailure() from None

    def delete(self, blob_key):
        path, _ = self._resolve_blob(blob_key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise StorageFailure() from None

    def quarantine(self, blob_key):
        source, _ = self._resolve_blob(blob_key)
        quarantine_key = "quarantine/" + secrets.token_hex(16)
        destination = self._resolve_quarantine(quarantine_key)
        try:
            if not source.is_file():
                raise AssetFileUnavailable()
            os.replace(source, destination)
        except AssetFileUnavailable:
            raise
        except FileNotFoundError:
            raise AssetFileUnavailable() from None
        except OSError:
            raise StorageFailure() from None
        return quarantine_key

    def restore_quarantined(self, quarantine_key, blob_key):
        source = self._resolve_quarantine(quarantine_key)
        destination, _ = self._resolve_blob(blob_key)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
        except OSError:
            raise StorageFailure() from None

    def finalize_quarantined(self, quarantine_key):
        path = self._resolve_quarantine(quarantine_key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def check_ready(self):
        probe = self.temp_root / ("ready-" + secrets.token_hex(16))
        moved = self.temp_root / ("ready-" + secrets.token_hex(16))
        try:
            self.temp_root.mkdir(parents=True, exist_ok=True)
            self._ensure_confined(probe)
            probe.write_bytes(b"ready")
            if probe.read_bytes() != b"ready":
                return False
            os.replace(probe, moved)
            return moved.read_bytes() == b"ready"
        except (OSError, StorageFailure):
            return False
        finally:
            for path in (probe, moved):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


__all__ = ["LocalContentStore"]
