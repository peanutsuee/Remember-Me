# SPDX-License-Identifier: CPAL-1.0
"""SQLite metadata repository with compatible on-disk state."""

from __future__ import annotations

import json
import math
from pathlib import Path
import secrets
import sqlite3

from remember_me.compat.ombre_brain import DATABASE_FILENAME, OB_SCHEMA_SQL
from remember_me.core.contracts import ImportClassificationState
from remember_me.core.errors import (
    AssetConflictError,
    AssetUnavailable,
    StorageFailure,
)
from remember_me.core.models import (
    AssetRecord,
    AssetVerificationRecord,
    AssetVerificationTag,
    EmbeddingRecord,
    ImportAssetTag,
    SearchAssetsRequest,
    UpdateMetadataRequest,
)
from remember_me.core.normalization import (
    normalize_description,
    normalize_tags,
    normalize_title,
    tag_comparison_key,
)
from remember_me.core.vector_index import validate_stored_embedding_vector
from remember_me.search.keyword import keyword_search


_ASSET_FIELDS = (
    "asset_id",
    "source_sha256",
    "stored_sha256",
    "stored_relpath",
    "original_filename",
    "mime_type",
    "kind",
    "decoded_bytes",
    "stored_bytes",
    "width",
    "height",
    "created_at",
    "title",
    "description",
    "updated_at",
)


class SQLiteAssetRepository:
    def __init__(self, data_root):
        self.data_root = Path(data_root)
        self.database_path = self.data_root / DATABASE_FILENAME
        try:
            self.data_root.mkdir(parents=True, exist_ok=True)
            self._initialize()
        except StorageFailure:
            raise
        except Exception:
            raise StorageFailure() from None

    def _connect(self):
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=30.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'assets'"
            ).fetchone()
            if table is None:
                for statement in OB_SCHEMA_SQL:
                    connection.execute(statement)
            else:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(assets)")
                }
                additions = (
                    ("title", "TEXT NOT NULL DEFAULT ''"),
                    ("description", "TEXT NOT NULL DEFAULT ''"),
                    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                )
                for name, declaration in additions:
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE assets ADD COLUMN {name} {declaration}"
                        )
                connection.execute(
                    "UPDATE assets SET updated_at = created_at "
                    "WHERE updated_at = ''"
                )
                connection.execute(OB_SCHEMA_SQL[1].replace(
                    "CREATE TABLE asset_tags",
                    "CREATE TABLE IF NOT EXISTS asset_tags",
                ))
                connection.execute(OB_SCHEMA_SQL[2].replace(
                    "CREATE TABLE asset_embeddings",
                    "CREATE TABLE IF NOT EXISTS asset_embeddings",
                ))
            duplicates = connection.execute(
                "SELECT count(*) FROM ("
                "SELECT stored_sha256 FROM assets "
                "GROUP BY stored_sha256 HAVING count(*) > 1)"
            ).fetchone()[0]
            duplicate_ids = connection.execute(
                "SELECT count(*) FROM ("
                "SELECT asset_id FROM assets "
                "GROUP BY asset_id HAVING count(*) > 1)"
            ).fetchone()[0]
            if duplicates or duplicate_ids:
                raise StorageFailure()
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_verification_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    target_identity TEXT NOT NULL,
                    asset_generation INTEGER NOT NULL
                )
                """
            )
            state = connection.execute(
                "SELECT singleton FROM asset_verification_state "
                "WHERE singleton = 1"
            ).fetchone()
            if state is None:
                identity = secrets.token_hex(32)
                connection.execute(
                    "INSERT INTO asset_verification_state "
                    "(singleton, target_identity, asset_generation) "
                    "VALUES (1, ?, 0)",
                    (identity,),
                )

    def _increment_asset_generation(self, connection):
        connection.execute(
            "UPDATE asset_verification_state "
            "SET asset_generation = asset_generation + 1 "
            "WHERE singleton = 1"
        )

    def _load_tags(self, connection, asset_id):
        return tuple(
            row["tag_display"]
            for row in connection.execute(
                "SELECT tag_display FROM asset_tags "
                "WHERE asset_id = ? ORDER BY tag_normalized",
                (asset_id,),
            )
        )

    def _record_from_row(self, connection, row):
        if row is None:
            return None
        values = {name: row[name] for name in _ASSET_FIELDS}
        values["tags"] = self._load_tags(connection, row["asset_id"])
        return AssetRecord(**values)

    def _get_with_connection(self, connection, asset_id):
        row = connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        return self._record_from_row(connection, row)

    def get(self, asset_id):
        try:
            with self._connect() as connection:
                return self._get_with_connection(connection, asset_id)
        except StorageFailure:
            raise
        except Exception:
            raise StorageFailure() from None

    def find_by_stored_sha256(self, stored_sha256):
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM assets WHERE stored_sha256 = ?",
                    (stored_sha256,),
                ).fetchone()
                return self._record_from_row(connection, row)
        except Exception:
            raise StorageFailure() from None

    def _insert_asset(self, connection, asset):
        connection.execute(
            """
            INSERT INTO assets (
                asset_id, source_sha256, stored_sha256, stored_relpath,
                original_filename, mime_type, kind, decoded_bytes,
                stored_bytes, width, height, created_at, title,
                description, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(getattr(asset, field) for field in _ASSET_FIELDS),
        )

    def add(self, asset):
        title = normalize_title(asset.title)
        description = normalize_description(asset.description)
        tags = normalize_tags(asset.tags)
        normalized = AssetRecord(
            **{
                **{field: getattr(asset, field) for field in _ASSET_FIELDS},
                "title": title,
                "description": description,
                "tags": tags,
            }
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._insert_asset(connection, normalized)
                for display in tags:
                    connection.execute(
                        "INSERT INTO asset_tags "
                        "(asset_id, tag_normalized, tag_display, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            normalized.asset_id,
                            tag_comparison_key(display),
                            display,
                            normalized.created_at,
                        ),
                    )
                self._increment_asset_generation(connection)
                connection.commit()
            return normalized
        except sqlite3.IntegrityError:
            raise AssetConflictError() from None
        except (AssetConflictError, StorageFailure):
            raise
        except Exception:
            raise StorageFailure() from None

    def add_import(self, asset, tags):
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._insert_asset(connection, asset)
                for tag in tags:
                    connection.execute(
                        "INSERT INTO asset_tags "
                        "(asset_id, tag_normalized, tag_display, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            asset.asset_id,
                            tag_comparison_key(tag.value),
                            tag.value,
                            tag.created_at,
                        ),
                    )
                self._increment_asset_generation(connection)
                connection.commit()
            return AssetRecord(
                **{
                    **{field: getattr(asset, field) for field in _ASSET_FIELDS},
                    "tags": tuple(tag.value for tag in tags),
                }
            )
        except sqlite3.IntegrityError:
            raise AssetConflictError() from None
        except (AssetConflictError, StorageFailure):
            raise
        except Exception:
            raise StorageFailure() from None

    def get_import_tags(self, asset_id):
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT tag_display, created_at FROM asset_tags "
                    "WHERE asset_id = ? ORDER BY tag_normalized",
                    (asset_id,),
                )
                return tuple(
                    ImportAssetTag(row["tag_display"], row["created_at"])
                    for row in rows
                )
        except Exception:
            raise StorageFailure() from None

    def read_import_classification_state(self, asset_id, stored_sha256):
        connection = None
        failure = None
        result = None
        try:
            connection = self._connect()
            connection.execute("BEGIN")
            existing_row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            owner_row = connection.execute(
                "SELECT * FROM assets WHERE stored_sha256 = ?",
                (stored_sha256,),
            ).fetchone()
            tag_cache = {}

            def imported_tags(row):
                if row is None:
                    return ()
                key = row["asset_id"]
                if key not in tag_cache:
                    tag_cache[key] = tuple(
                        ImportAssetTag(item["tag_display"], item["created_at"])
                        for item in connection.execute(
                            "SELECT tag_display, created_at FROM asset_tags "
                            "WHERE asset_id = ? ORDER BY tag_normalized",
                            (key,),
                        )
                    )
                return tag_cache[key]

            existing = self._record_from_row(connection, existing_row)
            owner = (
                existing
                if existing_row is not None
                and owner_row is not None
                and existing_row["asset_id"] == owner_row["asset_id"]
                else self._record_from_row(connection, owner_row)
            )
            result = ImportClassificationState(
                existing,
                imported_tags(existing_row),
                owner,
                imported_tags(owner_row),
            )
            connection.commit()
        except Exception:
            failure = StorageFailure()
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        if failure is not None:
            failure.__suppress_context__ = True
            raise failure
        return result

    def update_metadata(self, request, updated_at):
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = self._get_with_connection(connection, request.asset_id)
                if current is None:
                    raise AssetUnavailable()
                title = (
                    current.title
                    if request.title is None
                    else normalize_title(request.title)
                )
                description = (
                    current.description
                    if request.description is None
                    else normalize_description(request.description)
                )
                tags = current.tags
                replace_tags = False
                if request.tags is not None:
                    proposed = normalize_tags(request.tags)
                    if tuple(tag_comparison_key(tag) for tag in proposed) != tuple(
                        tag_comparison_key(tag) for tag in current.tags
                    ):
                        tags = proposed
                        replace_tags = True
                changed = (
                    title != current.title
                    or description != current.description
                    or replace_tags
                )
                if not changed:
                    connection.rollback()
                    return current
                connection.execute(
                    "UPDATE assets SET title = ?, description = ?, "
                    "updated_at = ? WHERE asset_id = ?",
                    (title, description, updated_at, current.asset_id),
                )
                if replace_tags:
                    connection.execute(
                        "DELETE FROM asset_tags WHERE asset_id = ?",
                        (current.asset_id,),
                    )
                    for display in tags:
                        connection.execute(
                            "INSERT INTO asset_tags "
                            "(asset_id, tag_normalized, tag_display, created_at) "
                            "VALUES (?, ?, ?, ?)",
                            (
                                current.asset_id,
                                tag_comparison_key(display),
                                display,
                                updated_at,
                            ),
                        )
                self._increment_asset_generation(connection)
                connection.commit()
                return self._get_with_connection(connection, current.asset_id)
        except (AssetUnavailable, StorageFailure):
            raise
        except Exception:
            raise StorageFailure() from None

    def delete(self, asset_id):
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM assets WHERE asset_id = ?",
                    (asset_id,),
                )
                if cursor.rowcount == 0:
                    connection.rollback()
                    return False
                self._increment_asset_generation(connection)
                connection.commit()
                return True
        except StorageFailure:
            raise
        except Exception:
            raise StorageFailure() from None

    def list_assets_for_search(self):
        try:
            with self._connect() as connection:
                connection.execute("BEGIN")
                rows = connection.execute(
                    "SELECT * FROM assets ORDER BY asset_id"
                ).fetchall()
                records = tuple(
                    self._record_from_row(connection, row) for row in rows
                )
                connection.commit()
                return records
        except Exception:
            raise StorageFailure() from None

    def search(self, request, semantic_scores=None, assets=None):
        if assets is not None:
            snapshot = tuple(assets)
        else:
            try:
                with self._connect() as connection:
                    connection.execute("BEGIN")
                    rows = connection.execute(
                        "SELECT * FROM assets ORDER BY asset_id"
                    ).fetchall()
                    snapshot = tuple(
                        self._record_from_row(connection, row) for row in rows
                    )
                    connection.commit()
            except Exception:
                raise StorageFailure() from None
        return keyword_search(snapshot, request)

    def list_for_embedding(self, limit=100):
        return self.list_assets_for_search()[:limit]

    def _decode_embedding(self, row):
        try:
            decoded = json.loads(row["embedding"])
            vector = validate_stored_embedding_vector(decoded)
            if vector is None:
                raise ValueError
            return EmbeddingRecord(
                asset_id=row["asset_id"],
                embedding=vector,
                model_id=row["model"],
                content_hash=row["content_hash"],
                updated_at=row["updated_at"],
            )
        except Exception:
            raise StorageFailure() from None

    def get_embedding(self, asset_id):
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT asset_id, embedding, model, content_hash, updated_at "
                    "FROM asset_embeddings WHERE asset_id = ?",
                    (asset_id,),
                ).fetchone()
                return None if row is None else self._decode_embedding(row)
        except StorageFailure:
            raise
        except Exception:
            raise StorageFailure() from None

    def list_embeddings_for_search(self, model_id):
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT asset_id, embedding, model, content_hash, updated_at "
                    "FROM asset_embeddings WHERE model = ? ORDER BY asset_id",
                    (model_id,),
                ).fetchall()
            records = []
            for row in rows:
                try:
                    records.append(self._decode_embedding(row))
                except StorageFailure:
                    continue
            return tuple(records)
        except StorageFailure:
            raise
        except Exception:
            raise StorageFailure() from None

    def delete_embedding(self, asset_id):
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM asset_embeddings WHERE asset_id = ?",
                    (asset_id,),
                )
                return cursor.rowcount > 0
        except Exception:
            raise StorageFailure() from None

    def store_embedding(self, asset_id, embedding, model, content_hash, updated_at):
        vector = validate_stored_embedding_vector(embedding)
        if vector is None:
            raise StorageFailure()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO asset_embeddings "
                    "(asset_id, embedding, model, content_hash, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(asset_id) DO UPDATE SET "
                    "embedding=excluded.embedding, model=excluded.model, "
                    "content_hash=excluded.content_hash, "
                    "updated_at=excluded.updated_at",
                    (
                        asset_id,
                        json.dumps(vector, separators=(",", ":")),
                        model,
                        content_hash,
                        updated_at,
                    ),
                )
        except Exception:
            raise StorageFailure() from None

    def store_embedding_if_asset_current(self, expected_asset, embedding_record):
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = self._get_with_connection(
                    connection,
                    expected_asset.asset_id,
                )
                if current != expected_asset:
                    connection.rollback()
                    return False
                vector = validate_stored_embedding_vector(
                    embedding_record.embedding
                )
                if vector is None:
                    connection.rollback()
                    return False
                connection.execute(
                    "INSERT INTO asset_embeddings "
                    "(asset_id, embedding, model, content_hash, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(asset_id) DO UPDATE SET "
                    "embedding=excluded.embedding, model=excluded.model, "
                    "content_hash=excluded.content_hash, "
                    "updated_at=excluded.updated_at",
                    (
                        embedding_record.asset_id,
                        json.dumps(vector, separators=(",", ":")),
                        embedding_record.model_id,
                        embedding_record.content_hash,
                        embedding_record.updated_at,
                    ),
                )
                connection.commit()
                return True
        except Exception:
            raise StorageFailure() from None

    def get_asset_verification_state(self):
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT target_identity, asset_generation "
                    "FROM asset_verification_state WHERE singleton = 1"
                ).fetchone()
                return row["target_identity"], row["asset_generation"]
        except Exception:
            raise StorageFailure() from None

    def count_assets_for_verification(self, kind):
        try:
            with self._connect() as connection:
                if kind is None:
                    return connection.execute(
                        "SELECT count(*) FROM assets"
                    ).fetchone()[0]
                return connection.execute(
                    "SELECT count(*) FROM assets WHERE kind = ?",
                    (kind,),
                ).fetchone()[0]
        except Exception:
            raise StorageFailure() from None

    def list_assets_for_verification_after(self, kind, last_asset_id, limit):
        try:
            with self._connect() as connection:
                parameters = []
                clauses = ["asset_id > ?"]
                parameters.append(last_asset_id)
                if kind is not None:
                    clauses.append("kind = ?")
                    parameters.append(kind)
                parameters.append(limit + 1)
                rows = connection.execute(
                    "SELECT * FROM assets WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY asset_id LIMIT ?",
                    tuple(parameters),
                ).fetchall()
                has_more = len(rows) > limit
                selected = rows[:limit]
                records = []
                for row in selected:
                    tag_rows = connection.execute(
                        "SELECT tag_display, created_at FROM asset_tags "
                        "WHERE asset_id = ? ORDER BY tag_normalized",
                        (row["asset_id"],),
                    )
                    records.append(
                        AssetVerificationRecord(
                            asset_id=row["asset_id"],
                            source_sha256=row["source_sha256"],
                            stored_sha256=row["stored_sha256"],
                            original_filename=row["original_filename"],
                            mime_type=row["mime_type"],
                            kind=row["kind"],
                            decoded_bytes=row["decoded_bytes"],
                            stored_bytes=row["stored_bytes"],
                            width=row["width"],
                            height=row["height"],
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                            title=row["title"],
                            description=row["description"],
                            tags=tuple(
                                AssetVerificationTag(
                                    tag["tag_display"],
                                    tag["created_at"],
                                )
                                for tag in tag_rows
                            ),
                        )
                    )
                return tuple(records), has_more
        except Exception:
            raise StorageFailure() from None

    def get_asset_verification_integrity(self, kind):
        try:
            with self._connect() as connection:
                where = "" if kind is None else " WHERE kind = ?"
                params = () if kind is None else (kind,)
                total = connection.execute(
                    "SELECT count(*) FROM assets" + where,
                    params,
                ).fetchone()[0]
                duplicate_ids = connection.execute(
                    "SELECT count(*) FROM (SELECT asset_id FROM assets"
                    + where
                    + " GROUP BY asset_id HAVING count(*) > 1)",
                    params,
                ).fetchone()[0]
                duplicate_sha = connection.execute(
                    "SELECT count(*) FROM (SELECT stored_sha256 FROM assets"
                    + where
                    + " GROUP BY stored_sha256 HAVING count(*) > 1)",
                    params,
                ).fetchone()[0]
                return total, duplicate_ids, duplicate_sha
        except Exception:
            raise StorageFailure() from None

    def check_ready(self):
        try:
            with self._connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except Exception:
            return False


__all__ = ["SQLiteAssetRepository"]
