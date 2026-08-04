# SPDX-License-Identifier: CPAL-1.0
import concurrent.futures
import sqlite3
import threading
import traceback

import pytest

from remember_me.core import ImportAssetTag, StorageFailure
from remember_me.core.models import AssetRecord, SearchAssetsRequest, UpdateMetadataRequest
from remember_me.storage import SQLiteAssetRepository


def _asset(
    asset_id="a" * 32,
    stored_sha256="b" * 64,
    created_at="2026-07-25T00:00:00+00:00",
    **changes
):
    values = {
        "asset_id": asset_id,
        "source_sha256": "c" * 64,
        "stored_sha256": stored_sha256,
        "stored_relpath": "assets/{}/{}.png".format(
            stored_sha256[:2],
            stored_sha256,
        ),
        "original_filename": "photo.png",
        "mime_type": "image/png",
        "kind": "image",
        "decoded_bytes": 100,
        "stored_bytes": 80,
        "width": 10,
        "height": 10,
        "created_at": created_at,
        "updated_at": created_at,
        "title": "",
        "description": "",
        "tags": (),
    }
    values.update(changes)
    return AssetRecord(**values)


def test_empty_database_initializes_compatible_tables_and_pragmas(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    with repository._connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "assets",
            "asset_tags",
            "asset_embeddings",
            "asset_verification_state",
        }.issubset(tables)
        identity, generation = repository.get_asset_verification_state()
        assert len(identity) == 64
        assert generation == 0
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal"


def test_old_schema_is_incrementally_extended_and_read_in_place(tmp_path):
    database = tmp_path / "assets.sqlite3"
    created_at = "2026-07-01T01:02:03+00:00"
    with sqlite3.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                source_sha256 TEXT NOT NULL,
                stored_sha256 TEXT NOT NULL UNIQUE,
                stored_relpath TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                kind TEXT NOT NULL,
                decoded_bytes INTEGER NOT NULL,
                stored_bytes INTEGER NOT NULL,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        asset = _asset(created_at=created_at)
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                asset.asset_id,
                asset.source_sha256,
                asset.stored_sha256,
                asset.stored_relpath,
                asset.original_filename,
                asset.mime_type,
                asset.kind,
                asset.decoded_bytes,
                asset.stored_bytes,
                asset.width,
                asset.height,
                asset.created_at,
            ),
        )

    repository = SQLiteAssetRepository(tmp_path)
    migrated = repository.get("a" * 32)
    assert migrated.created_at == created_at
    assert migrated.updated_at == created_at
    assert migrated.title == ""
    assert migrated.description == ""
    assert migrated.tags == ()
    identity, generation = repository.get_asset_verification_state()
    assert len(identity) == 64
    assert generation == 0


def test_add_find_update_and_noop_timestamp_semantics(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    original = repository.add(_asset(tags=(" Work ", "work", "旅行")))
    assert original.tags == ("Work", "旅行")
    assert repository.find_by_stored_sha256(original.stored_sha256) == original

    updated = repository.update_metadata(
        UpdateMetadataRequest(
            asset_id=original.asset_id,
            title="  ＲＭ title\x00  ",
            description="  中文描述\n第二行  ",
            tags=(" Tag ", "tag", "WORK", "旅行"),
        ),
        "2026-07-25T01:00:00+00:00",
    )
    assert updated.title == "RM title"
    assert updated.description == "中文描述 第二行"
    assert updated.tags == ("Tag", "WORK", "旅行")
    assert updated.updated_at == "2026-07-25T01:00:00+00:00"

    no_change = repository.update_metadata(
        UpdateMetadataRequest(
            asset_id=original.asset_id,
            tags=("tag", "work", "旅行"),
        ),
        "2026-07-25T02:00:00+00:00",
    )
    assert no_change.tags == updated.tags
    assert no_change.updated_at == updated.updated_at


def test_import_classification_state_uses_one_read_snapshot(tmp_path, monkeypatch):
    repository = SQLiteAssetRepository(tmp_path)
    tags = (
        ImportAssetTag("Travel", "2026-07-25T00:00:00+00:00"),
        ImportAssetTag("Work", "2026-07-25T01:00:00+00:00"),
    )
    asset = repository.add_import(_asset(), tags)
    before_generation = repository.get_asset_verification_state()[1]
    original_connect = repository._connect
    observations = {
        "connections": 0,
        "begin": 0,
        "asset_selects": 0,
        "tag_selects": 0,
        "closed": 0,
    }

    class TrackingConnection:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            normalized = " ".join(sql.split())
            if normalized == "BEGIN":
                observations["begin"] += 1
            if "SELECT * FROM assets WHERE" in normalized:
                observations["asset_selects"] += 1
            if "SELECT tag_display, created_at FROM asset_tags" in normalized:
                observations["tag_selects"] += 1
            return self._connection.execute(sql, parameters)

        def commit(self):
            return self._connection.commit()

        def rollback(self):
            return self._connection.rollback()

        def close(self):
            observations["closed"] += 1
            return self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def tracked_connect():
        observations["connections"] += 1
        return TrackingConnection(original_connect())

    monkeypatch.setattr(repository, "_connect", tracked_connect)
    state = repository.read_import_classification_state(
        asset.asset_id,
        asset.stored_sha256,
    )

    assert state.existing_asset == asset
    assert state.stored_sha_owner == asset
    assert state.existing_tags == tags
    assert state.stored_sha_owner_tags == tags
    assert observations == {
        "connections": 1,
        "begin": 1,
        "asset_selects": 2,
        "tag_selects": 1,
        "closed": 1,
    }
    with original_connect() as connection:
        generation = connection.execute(
            "SELECT asset_generation FROM asset_verification_state "
            "WHERE singleton = 1"
        ).fetchone()[0]
    assert generation == before_generation


def test_import_classification_snapshot_keeps_record_and_tags_together(
    tmp_path,
    monkeypatch,
):
    repository = SQLiteAssetRepository(tmp_path)
    original_tags = (
        ImportAssetTag("Original", "2026-07-25T00:00:00+00:00"),
    )
    asset = repository.add_import(_asset(), original_tags)
    original_connect = repository._connect
    first_select = threading.Event()
    release_snapshot = threading.Event()
    connect_calls = {"count": 0}

    class ControlledConnection:
        def __init__(self, connection):
            self._connection = connection
            self._blocked = False

        def execute(self, sql, parameters=()):
            cursor = self._connection.execute(sql, parameters)
            if (
                not self._blocked
                and "WHERE asset_id = ?" in sql
            ):
                self._blocked = True
                first_select.set()
                assert release_snapshot.wait(5)
            return cursor

        def commit(self):
            return self._connection.commit()

        def rollback(self):
            return self._connection.rollback()

        def close(self):
            return self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def controlled_connect():
        connect_calls["count"] += 1
        connection = original_connect()
        if connect_calls["count"] == 1:
            return ControlledConnection(connection)
        return connection

    monkeypatch.setattr(repository, "_connect", controlled_connect)
    snapshot_result = {}
    update_result = {}
    update_done = threading.Event()

    def read_snapshot():
        snapshot_result["state"] = (
            repository.read_import_classification_state(
                asset.asset_id,
                asset.stored_sha256,
            )
        )

    def update_asset():
        try:
            update_result["asset"] = repository.update_metadata(
                UpdateMetadataRequest(
                    asset_id=asset.asset_id,
                    title="Updated",
                    tags=("Updated",),
                ),
                "2026-07-25T02:00:00+00:00",
            )
        finally:
            update_done.set()

    snapshot_thread = threading.Thread(target=read_snapshot)
    snapshot_thread.start()
    assert first_select.wait(5)
    update_thread = threading.Thread(target=update_asset)
    update_thread.start()
    assert not update_done.wait(0.05)
    release_snapshot.set()
    snapshot_thread.join(5)
    update_thread.join(5)
    assert not snapshot_thread.is_alive()
    assert not update_thread.is_alive()

    state = snapshot_result["state"]
    assert state.existing_asset == asset
    assert state.stored_sha_owner == asset
    assert state.existing_tags == original_tags
    assert state.stored_sha_owner_tags == original_tags
    next_state = repository.read_import_classification_state(
        asset.asset_id,
        asset.stored_sha256,
    )
    assert next_state.existing_asset == update_result["asset"]
    assert next_state.stored_sha_owner == update_result["asset"]
    assert tuple(tag.value for tag in next_state.existing_tags) == (
        "Updated",
    )
    assert next_state.stored_sha_owner_tags == next_state.existing_tags


def test_import_classification_state_sqlite_error_is_safely_mapped(
    tmp_path,
    monkeypatch,
):
    repository = SQLiteAssetRepository(tmp_path)
    marker = "C:\\private\\SNAPSHOT_DATABASE_SECRET"
    original_connect = repository._connect
    connection = original_connect()
    closed = {"value": False}

    class FailingConnection:
        def execute(self, _sql, _parameters=()):
            raise sqlite3.OperationalError(marker)

        def rollback(self):
            pass

        def close(self):
            closed["value"] = True
            connection.close()

    monkeypatch.setattr(repository, "_connect", lambda: FailingConnection())
    with pytest.raises(StorageFailure) as captured:
        repository.read_import_classification_state(
            "a" * 32,
            "b" * 64,
        )

    formatted = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "storage_failure"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert captured.value.__suppress_context__ is True
    assert marker not in repr(captured.value)
    assert marker not in formatted
    assert closed["value"] is True


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_import_classification_state_propagates_base_exception(
    tmp_path,
    monkeypatch,
    interrupt,
):
    repository = SQLiteAssetRepository(tmp_path)
    original_connect = repository._connect
    connection = original_connect()
    closed = {"value": False}

    class InterruptingConnection:
        def execute(self, _sql, _parameters=()):
            raise interrupt()

        def close(self):
            closed["value"] = True
            connection.close()

    monkeypatch.setattr(
        repository,
        "_connect",
        lambda: InterruptingConnection(),
    )
    with pytest.raises(interrupt):
        repository.read_import_classification_state(
            "a" * 32,
            "b" * 64,
        )
    assert closed["value"] is True


def test_foreign_key_cascade_preserves_schema(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    asset = repository.add(_asset(tags=("delete",)))
    with repository._connect() as connection:
        connection.execute(
            """
            INSERT INTO asset_embeddings (
                asset_id, embedding, model, content_hash, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                asset.asset_id,
                "[0.1]",
                "test-model",
                "content",
                asset.updated_at,
            ),
        )
    assert repository.delete(asset.asset_id) is True
    with repository._connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM asset_tags"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM asset_embeddings"
        ).fetchone()[0] == 0
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"assets", "asset_tags", "asset_embeddings"}.issubset(tables)


def test_concurrent_metadata_updates_and_reads(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    asset = repository.add(_asset())

    def update(index):
        return repository.update_metadata(
            UpdateMetadataRequest(
                asset_id=asset.asset_id,
                title="title-{}".format(index),
                tags=("shared", "tag-{}".format(index % 3)),
            ),
            "2026-07-25T00:{:02d}:00+00:00".format(index),
        )

    def search(_):
        return repository.search(SearchAssetsRequest(query="title"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(update, index) for index in range(12)
        ] + [
            executor.submit(search, index) for index in range(12)
        ]
        for future in futures:
            future.result()
    final = repository.get(asset.asset_id)
    assert final.title.startswith("title-")
    assert "shared" in {tag.casefold() for tag in final.tags}


def test_list_for_embedding_uses_compatible_tie_breaker(tmp_path):
    repository = SQLiteAssetRepository(tmp_path)
    first = repository.add(_asset(asset_id="a" * 32, stored_sha256="a" * 64))
    second = repository.add(_asset(asset_id="b" * 32, stored_sha256="b" * 64))
    assert repository.list_for_embedding() == (first, second)
