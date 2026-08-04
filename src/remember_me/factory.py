# SPDX-License-Identifier: CPAL-1.0
"""Explicit local assembly without host configuration."""

from dataclasses import dataclass

from remember_me.core import RememberMeService, SystemClock
from remember_me.imaging import PillowImageSanitizer
from remember_me.search import NullVectorProvider
from remember_me.storage import LocalContentStore, SQLiteAssetRepository


@dataclass(frozen=True)
class LocalRuntime:
    service: RememberMeService
    repository: SQLiteAssetRepository
    blob_store: LocalContentStore


def create_local_runtime(data_root, clock=None, vector_provider=None):
    repository = SQLiteAssetRepository(data_root)
    blob_store = LocalContentStore(data_root)
    service = RememberMeService(
        repository=repository,
        blob_store=blob_store,
        image_sanitizer=PillowImageSanitizer(),
        clock=clock or SystemClock(),
        vector_provider=(
            vector_provider
            if vector_provider is not None
            else NullVectorProvider()
        ),
    )
    return LocalRuntime(
        service=service,
        repository=repository,
        blob_store=blob_store,
    )


def create_local_service(data_root, clock=None, vector_provider=None):
    return create_local_runtime(
        data_root,
        clock=clock,
        vector_provider=vector_provider,
    ).service
