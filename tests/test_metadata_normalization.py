# SPDX-License-Identifier: CPAL-1.0
"""W-12 storage spelling, comparison identity and safety contract."""
import pytest

from remember_me.core.errors import ImportMetadataValidationError, InvalidMetadata
from remember_me.core.normalization import (
    _clean_scalar, normalize_description, normalize_filename,
    normalize_import_description, normalize_import_title, normalize_tags,
    normalize_title, tag_comparison_key, validate_import_filename,
    validate_import_tags,
)

UNICODE_CASES = [
    ("ＡＢＣ", "ABC", "abc"),
    ("①", "1", "1"),
    ("Ⅰ", "I", "i"),
    ("Å", "Å", "å"),
    ("ﬁ", "fi", "fi"),
    ("神", "神", "神"),
    ("e\u0301", "é", "é"),
]


@pytest.mark.parametrize("spelling,counterpart,key", UNICODE_CASES)
def test_unicode_storage_and_comparison_contract(spelling, counterpart, key):
    assert normalize_title(spelling) == spelling
    assert normalize_description(spelling) == spelling
    assert normalize_filename(spelling) == spelling
    assert normalize_import_title(spelling) == spelling
    assert normalize_import_description(spelling) == spelling
    assert validate_import_filename(spelling) == spelling
    assert tag_comparison_key(spelling) == key
    assert tag_comparison_key(counterpart) == key
    assert _clean_scalar(spelling).casefold() == key
    assert normalize_tags([spelling, counterpart]) == (spelling,)
    assert normalize_tags([counterpart, spelling]) == (counterpart,)
    assert validate_import_tags((spelling,)) == ((key, spelling),)
    with pytest.raises(ImportMetadataValidationError):
        validate_import_tags((spelling, counterpart))


@pytest.mark.parametrize("values,expected", [
    (["Ａ", "A"], ("Ａ",)),
    (["A", "Ａ"], ("A",)),
    (["b", "Ａ", "c"], ("Ａ", "b", "c")),
    (["Straße", "STRASSE"], ("Straße",)),
    (["a-b", "ab"], ("a-b", "ab")),
    (["a，b", "a,b"], ("a，b",)),
])
def test_tag_representatives_and_canonical_order(values, expected):
    assert normalize_tags(values) == expected


@pytest.mark.parametrize("cleaner", [normalize_title, normalize_description])
def test_text_safety_and_whitespace_unchanged(cleaner):
    assert cleaner(" \tＡ\x00\u200bB\n  C\u00a0D ") == "Ａ B C D"
    assert cleaner("e\u0301") == "e\u0301"
    with pytest.raises(InvalidMetadata):
        cleaner(None)


@pytest.mark.parametrize("cleaner,maximum", [
    (normalize_title, 200), (normalize_description, 4000),
    (lambda value: normalize_tags([value]), 64),
])
def test_limits_cover_display_and_compatibility_expansion(cleaner, maximum):
    with pytest.raises(InvalidMetadata):
        cleaner("x" * (maximum + 1))
    with pytest.raises(InvalidMetadata):
        cleaner("ﬁ" * (maximum // 2 + 1))
    with pytest.raises(InvalidMetadata):
        cleaner("e\u0301" * (maximum // 2 + 1))
    cleaner("x" * maximum)


@pytest.mark.parametrize("raw,expected", [
    ("../../unsafe\\photo.png", "_.._unsafe_photo.png"),
    ("．．／Ａ\\photo.png", "_Ａ_photo.png"),
    ("Ａ／B＼C.png", "Ａ_B_C.png"),
    ("\x00Ａ\u200bB\t C.png ", "_Ａ_B_ C.png"),
    ("   ", "image"),
    ("Ａ" * 300, "Ａ" * 300),
])
def test_filename_safety_without_spelling_rewrite(raw, expected):
    assert normalize_filename(raw) == expected


@pytest.mark.parametrize("value", ["../a", "．．／a", "Ａ／B", "Ａ＼B", "．", "．．", " a ", "a\x00b"])
def test_import_filename_still_rejects_unsafe_values(value):
    with pytest.raises(ImportMetadataValidationError):
        validate_import_filename(value)


def test_import_text_and_tags_require_storage_safety():
    for cleaner in (normalize_import_title, normalize_import_description):
        for value in (" a ", "a\x00b", "a\n  b"):
            with pytest.raises(ImportMetadataValidationError):
                cleaner(value)
    for values in ((" a ",), ("",), ("a\u200bb",), ("a\n b",)):
        with pytest.raises(ImportMetadataValidationError):
            validate_import_tags(values)
    with pytest.raises(InvalidMetadata):
        normalize_tags([str(i) for i in range(31)])
