# SPDX-License-Identifier: CPAL-1.0
from remember_me.core.models import AssetRecord, SearchAssetsRequest
from remember_me.search import keyword_search


def _asset(asset_id, created_at, filename, title="", description="", tags=()):
    digest = asset_id[0] * 64
    return AssetRecord(
        asset_id=asset_id,
        source_sha256=digest,
        stored_sha256=digest,
        stored_relpath="assets/{}/{}.png".format(digest[:2], digest),
        original_filename=filename,
        mime_type="image/png",
        kind="image",
        decoded_bytes=10,
        stored_bytes=10,
        width=1,
        height=1,
        created_at=created_at,
        updated_at=created_at,
        title=title,
        description=description,
        tags=tags,
    )


def test_keyword_priority_and_match_reasons():
    tag = _asset("a" * 32, "2026-07-01T00:00:00+00:00", "tag.png", tags=("Alpha",))
    title = _asset("b" * 32, "2026-07-02T00:00:00+00:00", "title.png", title="ALPHA")
    filename = _asset("c" * 32, "2026-07-03T00:00:00+00:00", "Alpha-file.png")
    description = _asset(
        "d" * 32,
        "2026-07-04T00:00:00+00:00",
        "notes.png",
        description="contains alpha here",
    )
    result = keyword_search(
        (description, filename, title, tag),
        SearchAssetsRequest(query="aLpHa"),
    )
    assert [item.asset.asset_id for item in result.results] == [
        tag.asset_id,
        title.asset_id,
        filename.asset_id,
        description.asset_id,
    ]
    assert [item.match_reasons for item in result.results] == [
        ("tag_exact",),
        ("title_exact",),
        ("filename",),
        ("description",),
    ]


def test_filters_dates_pagination_and_stable_sort():
    first = _asset(
        "a" * 32,
        "2026-07-01T00:00:00+00:00",
        "one.png",
        tags=("shared", "one"),
    )
    second = _asset(
        "b" * 32,
        "2026-07-15T00:00:00+00:00",
        "two.png",
        tags=("shared", "two"),
    )
    third = _asset(
        "c" * 32,
        "2026-07-15T00:00:00+00:00",
        "three.png",
        tags=("shared", "two"),
    )
    filtered = keyword_search(
        (first, third, second),
        SearchAssetsRequest(
            tags=("SHARED", "two"),
            created_from="2026-07-15",
            created_to="2026-07-15",
            limit=1,
            offset=1,
        ),
    )
    assert filtered.total == 2
    assert [item.asset.asset_id for item in filtered.results] == [
        third.asset_id
    ]


def test_asset_id_exact_has_highest_priority():
    exact = _asset("e" * 32, "2026-07-01T00:00:00+00:00", "exact.png")
    tagged = _asset(
        "f" * 32,
        "2026-07-25T00:00:00+00:00",
        "new.png",
        tags=(exact.asset_id,),
    )
    result = keyword_search(
        (tagged, exact),
        SearchAssetsRequest(query=exact.asset_id),
    )
    assert result.results[0].asset.asset_id == exact.asset_id
    assert result.results[0].match_reasons[0] == "asset_id_exact"
