# SPDX-License-Identifier: CPAL-1.0
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from remember_me.core.errors import (
    AssetFileUnavailable,
    StorageFailure,
    StoredFileConflict,
)
from remember_me.storage import LocalContentStore
from remember_me.storage.content_store import (
    _path_is_within,
    _windows_comparison_parts,
)


def _blob_key(content, extension=".png"):
    digest = hashlib.sha256(content).hexdigest()
    return "assets/{}/{}{}".format(digest[:2], digest, extension)


def test_put_read_and_existing_blob_verification(tmp_path):
    store = LocalContentStore(tmp_path)
    content = b"cleaned image bytes"
    key = _blob_key(content)
    assert store.put(key, content) is True
    assert store.put(key, content) is False
    assert store.exists(key) is True
    assert store.read(key) == content
    assert not list((tmp_path / "assets" / ".tmp").iterdir())


def test_regular_read_and_hash_permission_errors_are_not_retried(
    tmp_path,
    monkeypatch,
):
    store = LocalContentStore(tmp_path)
    content = b"retryable cleaned bytes"
    key = _blob_key(content)
    assert store.put(key, content) is True
    path, _ = store._resolve_blob(key)
    original_read_bytes = Path.read_bytes
    original_open = Path.open
    read_attempts = {"count": 0}
    open_attempts = {"count": 0}
    sleep_attempts = {"count": 0}
    monkeypatch.setattr(
        "remember_me.storage.content_store.time.sleep",
        lambda _seconds: sleep_attempts.__setitem__(
            "count",
            sleep_attempts["count"] + 1,
        ),
    )

    def deny_read(candidate):
        if candidate == path:
            read_attempts["count"] += 1
            raise PermissionError("persistent")
        return original_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", deny_read)
    with pytest.raises(StorageFailure):
        store.read(key)
    assert read_attempts["count"] == 1

    def deny_open(candidate, *args, **kwargs):
        if candidate == path:
            open_attempts["count"] += 1
            raise PermissionError("persistent")
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_open)
    with pytest.raises(StorageFailure):
        store._hash_file(path)
    assert open_attempts["count"] == 1
    assert sleep_attempts["count"] == 0


def test_cas_placement_permission_race_is_bounded(
    tmp_path,
    monkeypatch,
):
    store = LocalContentStore(tmp_path)
    content = b"placement race bytes"
    key = _blob_key(content)
    destination, _ = store._resolve_blob(key)
    original_replace = os.replace
    calls = {"replace": 0, "sleep": 0}

    def concurrent_winner(source, target):
        calls["replace"] += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        raise PermissionError("transient placement")

    monkeypatch.setattr(os, "replace", concurrent_winner)
    assert store.put(key, content) is False
    assert calls["replace"] == 1
    assert destination.read_bytes() == content
    assert not list(store.temp_root.iterdir())

    other = LocalContentStore(tmp_path / "persistent")
    other_key = _blob_key(b"persistent placement")

    def persistent_denial(_source, _target):
        raise PermissionError("persistent placement")

    monkeypatch.setattr(os, "replace", persistent_denial)
    monkeypatch.setattr(
        "remember_me.storage.content_store.time.sleep",
        lambda _seconds: calls.__setitem__(
            "sleep",
            calls["sleep"] + 1,
        ),
    )
    with pytest.raises(StorageFailure):
        other.put(other_key, b"persistent placement")
    assert calls["sleep"] == 50
    assert not list(other.temp_root.iterdir())
    monkeypatch.setattr(os, "replace", original_replace)


def test_existing_conflicting_blob_is_never_overwritten(tmp_path):
    store = LocalContentStore(tmp_path)
    content = b"expected bytes"
    key = _blob_key(content)
    destination = tmp_path / Path(*key.split("/"))
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"conflicting bytes")

    with pytest.raises(StoredFileConflict):
        store.put(key, content)
    assert destination.read_bytes() == b"conflicting bytes"


def test_blob_keys_cannot_escape_assets_root(tmp_path):
    store = LocalContentStore(tmp_path)
    for key in [
        "../outside.png",
        "assets/../outside.png",
        "C:/outside.png",
        "assets/aa/not-a-hash.png",
    ]:
        with pytest.raises(StorageFailure):
            store.read(key)


def test_quarantine_restore_and_finalize(tmp_path):
    store = LocalContentStore(tmp_path)
    content = b"delete transaction bytes"
    key = _blob_key(content, ".jpg")
    store.put(key, content)

    quarantine_key = store.quarantine(key)
    assert store.exists(key) is False
    store.restore_quarantined(quarantine_key, key)
    assert store.read(key) == content

    quarantine_key = store.quarantine(key)
    assert store.finalize_quarantined(quarantine_key) is True
    assert store.exists(key) is False


def test_missing_blob_cannot_be_quarantined(tmp_path):
    store = LocalContentStore(tmp_path)
    with pytest.raises(AssetFileUnavailable):
        store.quarantine(_blob_key(b"missing"))


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace contract")
@pytest.mark.parametrize(
    ("root", "child"),
    [
        (r"C:\data\assets", r"C:\data\assets\aa\file.png"),
        (r"\\?\C:\data\assets", r"\\?\C:\data\assets\aa\file.png"),
        (r"C:\data\assets", r"\\?\C:\data\assets\aa\file.png"),
        (r"\\?\C:\data\assets", r"C:\data\assets\aa\file.png"),
        (r"C:\DATA\ASSETS", r"c:\data\assets\aa\file.png"),
        (r"C:/data/assets", r"C:\data/assets\aa/file.png"),
        (r"C:\data\assets", r"C:\data\.\assets\aa\file.png"),
        (r"C:\data\assets", r"C:\data\assets\aa\..\bb\file.png"),
        (
            r"\\server\share\assets",
            r"\\?\UNC\SERVER\SHARE\assets\aa\file.png",
        ),
    ],
)
def test_windows_comparison_accepts_equivalent_namespace_forms(root, child):
    assert _path_is_within(child, root) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace contract")
@pytest.mark.parametrize(
    ("root", "candidate"),
    [
        (r"C:\data\assets", r"C:\data\assets\..\outside\file.png"),
        (r"C:\data\assets", r"C:\data\assets-evil\file.png"),
        (r"C:\data\assets", r"D:\data\assets\file.png"),
        (
            r"\\server\share\assets",
            r"\\server\other-share\assets\file.png",
        ),
        (
            r"\\server\share\assets",
            r"\\other-server\share\assets\file.png",
        ),
    ],
)
def test_windows_comparison_rejects_escape_drive_and_share(root, candidate):
    assert _path_is_within(candidate, root) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace contract")
@pytest.mark.parametrize(
    "candidate",
    [
        r"\\.\C:\data\assets\file.png",
        r"\??\C:\data\assets\file.png",
        r"\\?\GLOBALROOT\Device\HarddiskVolume1\file.png",
        r"relative\assets\file.png",
    ],
)
def test_windows_comparison_rejects_unsupported_namespaces(candidate):
    with pytest.raises(ValueError):
        _windows_comparison_parts(candidate)


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace contract")
def test_windows_junction_cannot_escape_assets_root(tmp_path):
    store = LocalContentStore(tmp_path / "root")
    content = b"junction escape"
    key = _blob_key(content)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath(key.rsplit("/", 1)[1]).write_bytes(content)
    junction = store.assets_root / key.split("/")[1]
    completed = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    try:
        with pytest.raises(StorageFailure, match="invalid_blob_key"):
            store.read(key)
    finally:
        junction.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace contract")
def test_blob_key_and_normal_path_remain_stable_after_windows_repair(tmp_path):
    store = LocalContentStore(tmp_path)
    content = b"stable key"
    key = _blob_key(content)
    path, expected_hash = store._resolve_blob(key)
    assert expected_hash == hashlib.sha256(content).hexdigest()
    assert path == tmp_path.resolve() / Path(*key.split("/"))
    assert key == "assets/{}/{}.png".format(expected_hash[:2], expected_hash)
    assert "\\\\?\\" not in key
    assert ".." not in key
    assert not Path(key).is_absolute()
