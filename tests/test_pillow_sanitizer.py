# SPDX-License-Identifier: CPAL-1.0
import io

import pytest
from PIL import ExifTags, Image, PngImagePlugin

from remember_me.core.errors import (
    ImageMimeMismatch,
    ImagePixelLimitExceeded,
    InvalidImage,
    UnsupportedImageFormat,
)
from remember_me.imaging import (
    PILLOW_BASELINE_VERSION,
    PILLOW_VERSION_RANGE,
    SANITIZER_ID,
    PillowImageSanitizer,
)


def _image_bytes(image_format, mode="RGB", size=(20, 10), **save_options):
    image = Image.new(mode, size, (12, 34, 56, 200) if "A" in mode else "red")
    output = io.BytesIO()
    image.save(output, format=image_format, **save_options)
    image.close()
    return output.getvalue()


def _png_with_text():
    image = Image.new("RGBA", (32, 20), (12, 34, 56, 200))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-note", "remove me")
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    image.close()
    return output.getvalue()


def _jpeg_with_exif_gps_orientation():
    image = Image.new("RGB", (20, 10), "red")
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[1] = "N"
    gps[2] = (1.0, 2.0, 3.0)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95, exif=exif)
    image.close()
    return output.getvalue()


def test_png_is_cleaned_and_text_chunks_are_removed():
    cleaned = PillowImageSanitizer().sanitize(_png_with_text(), "image/png")
    assert cleaned.mime_type == "image/png"
    assert cleaned.extension == ".png"
    assert (cleaned.width, cleaned.height) == (32, 20)
    with Image.open(io.BytesIO(cleaned.content)) as image:
        image.load()
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert "private-note" not in image.info
        assert "exif" not in image.info
        assert "icc_profile" not in image.info


def test_jpeg_orientation_exif_and_gps_are_cleaned():
    source = _jpeg_with_exif_gps_orientation()
    cleaned = PillowImageSanitizer().sanitize(source, "image/jpeg")
    assert cleaned.mime_type == "image/jpeg"
    assert cleaned.extension == ".jpg"
    assert (cleaned.width, cleaned.height) == (10, 20)
    with Image.open(io.BytesIO(cleaned.content)) as image:
        image.load()
        assert image.mode == "RGB"
        assert image.size == (10, 20)
        assert not image.getexif()
        assert "exif" not in image.info
        assert "icc_profile" not in image.info


def test_opaque_png_is_rgb_and_cleaned_bytes_can_be_decoded():
    source = _image_bytes("PNG", mode="RGB")
    cleaned = PillowImageSanitizer().sanitize(
        source,
        "application/octet-stream",
    )
    with Image.open(io.BytesIO(cleaned.content)) as image:
        image.load()
        assert image.mode == "RGB"
        assert image.size == (20, 10)


def test_invalid_unsupported_and_mime_mismatch_are_stable_errors():
    sanitizer = PillowImageSanitizer()
    with pytest.raises(InvalidImage):
        sanitizer.sanitize(b"not an image", "application/octet-stream")

    gif = _image_bytes("GIF")
    with pytest.raises(UnsupportedImageFormat):
        sanitizer.sanitize(gif, "application/octet-stream")

    png = _image_bytes("PNG")
    with pytest.raises(ImageMimeMismatch):
        sanitizer.sanitize(png, "image/jpeg")


def test_pixel_limit_boundary_and_overage():
    boundary = _image_bytes("PNG", size=(10, 10))
    sanitizer = PillowImageSanitizer(max_image_pixels=100)
    result = sanitizer.sanitize(boundary, "image/png")
    assert (result.width, result.height) == (10, 10)

    over = _image_bytes("PNG", size=(11, 10))
    with pytest.raises(ImagePixelLimitExceeded):
        sanitizer.sanitize(over, "image/png")


def test_actual_twenty_million_pixel_boundary():
    sanitizer = PillowImageSanitizer()
    boundary = _image_bytes("PNG", size=(5000, 4000))
    result = sanitizer.sanitize(boundary, "image/png")
    assert (result.width, result.height) == (5000, 4000)

    over = _image_bytes("PNG", size=(5000, 4001))
    with pytest.raises(ImagePixelLimitExceeded):
        sanitizer.sanitize(over, "image/png")


def test_public_sanitizer_identity_and_pillow_baseline():
    assert SANITIZER_ID == "remember-me-pillow-v1"
    assert PILLOW_VERSION_RANGE == "Pillow>=10.4,<13"
    assert PILLOW_BASELINE_VERSION == "10.4.0"
