# SPDX-License-Identifier: CPAL-1.0
"""Stage 8H-B0B public asset verification contract."""

from remember_me import core
from remember_me.core.contracts import AssetRepository, RememberMeCore
from remember_me.core.service import RememberMeService


def test_red_begin_verification_public_contract_is_missing():
    assert hasattr(core, "BeginAssetVerificationRequest")
    assert "begin_asset_verification" in RememberMeCore.__dict__
    assert hasattr(RememberMeService, "begin_asset_verification")


def test_red_inventory_page_public_contract_is_missing():
    assert hasattr(core, "ListAssetVerificationPageRequest")
    assert "list_asset_verification_page" in RememberMeCore.__dict__
    assert hasattr(RememberMeService, "list_asset_verification_page")


def test_red_blob_verification_public_contract_is_missing():
    assert hasattr(core, "VerifyAssetBlobRequest")
    assert "verify_asset_blob" in RememberMeCore.__dict__
    assert hasattr(RememberMeService, "verify_asset_blob")


def test_red_completion_public_contract_is_missing():
    assert hasattr(core, "CompleteAssetVerificationRequest")
    assert "complete_asset_verification" in RememberMeCore.__dict__
    assert hasattr(RememberMeService, "complete_asset_verification")


def test_red_timestamped_verification_tag_is_missing():
    assert hasattr(core, "AssetVerificationTag")
    assert hasattr(core, "AssetVerificationRecord")


def test_red_persistent_generation_contract_is_missing():
    assert "get_asset_verification_state" in AssetRepository.__dict__
    assert "count_assets_for_verification" in AssetRepository.__dict__


def test_red_snapshot_mutation_detection_contract_is_missing():
    assert hasattr(core, "VerificationSnapshotChanged")
    assert hasattr(core, "AssetVerificationSnapshot")
