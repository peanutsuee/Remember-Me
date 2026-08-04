# SPDX-License-Identifier: CPAL-1.0
"""Pillow-backed image validation and privacy cleaning."""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from remember_me.core.errors import (
    ImageMimeMismatch,
    ImagePixelLimitExceeded,
    InvalidImage,
    UnsupportedImageFormat,
    UploadTooLarge,
)
from remember_me.core.models import SanitizedImage


SANITIZER_ID = "remember-me-pillow-v1"
PILLOW_BASELINE_VERSION = "10.4.0"
PILLOW_VERSION_RANGE = "Pillow>=10.4,<13"

_MAX_SOURCE_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000
_MIME_BY_FORMAT = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg")}


class PillowImageSanitizer:
    def __init__(
        self,
        max_source_bytes: int = _MAX_SOURCE_BYTES,
        max_image_pixels: int = _MAX_IMAGE_PIXELS,
    ) -> None:
        self.max_source_bytes = max_source_bytes
        self.max_image_pixels = max_image_pixels

    def _read_image(self, content: bytes):
        try:
            stream = io.BytesIO(content)
            image = Image.open(stream)
            image.load()
            return stream, image
        except Image.DecompressionBombError as exc:
            raise ImagePixelLimitExceeded() from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidImage() from exc

    def _check_header(self, image, claimed_mime_type: str) -> tuple[str, str]:
        image_format = (image.format or "").upper()
        if image_format not in _MIME_BY_FORMAT:
            raise UnsupportedImageFormat()
        expected_mime, extension = _MIME_BY_FORMAT[image_format]
        claimed = (claimed_mime_type or "").strip().lower()
        if claimed not in {"application/octet-stream", expected_mime}:
            raise ImageMimeMismatch()
        return expected_mime, extension

    def _check_pixels(self, image) -> None:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise InvalidImage()
        if width * height > self.max_image_pixels:
            raise ImagePixelLimitExceeded()

    @staticmethod
    def _clean_canvas(image, image_format: str):
        oriented = ImageOps.exif_transpose(image)
        try:
            if image_format == "JPEG":
                mode = "RGB"
            elif "A" in oriented.getbands() or oriented.mode in {"LA", "PA"}:
                mode = "RGBA"
            else:
                mode = "RGB"
            converted = oriented.convert(mode)
            canvas = Image.new(mode, converted.size)
            canvas.putdata(list(converted.getdata()))
            return canvas
        finally:
            if oriented is not image:
                oriented.close()

    @staticmethod
    def _encode(canvas, image_format: str) -> bytes:
        output = io.BytesIO()
        if image_format == "JPEG":
            canvas.save(
                output,
                format="JPEG",
                quality=95,
                optimize=False,
                progressive=False,
                subsampling=0,
            )
        else:
            canvas.save(output, format="PNG", optimize=False)
        return output.getvalue()

    def sanitize(self, content: bytes, claimed_mime_type: str) -> SanitizedImage:
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise InvalidImage()
        source = bytes(content)
        if len(source) > self.max_source_bytes:
            raise UploadTooLarge()
        stream, image = self._read_image(source)
        try:
            mime_type, extension = self._check_header(image, claimed_mime_type)
            self._check_pixels(image)
            image_format = image.format.upper()
            canvas = self._clean_canvas(image, image_format)
            try:
                cleaned = self._encode(canvas, image_format)
                width, height = canvas.size
            finally:
                canvas.close()
            return SanitizedImage(
                content=cleaned,
                mime_type=mime_type,
                extension=extension,
                width=width,
                height=height,
            )
        except (ImageMimeMismatch, ImagePixelLimitExceeded, UnsupportedImageFormat):
            raise
        except Exception as exc:
            raise InvalidImage() from exc
        finally:
            image.close()
            stream.close()

    def validate_cleaned(
        self,
        content: bytes,
        claimed_mime_type: str,
    ) -> SanitizedImage:
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise InvalidImage()
        cleaned = bytes(content)
        if len(cleaned) > self.max_source_bytes:
            raise UploadTooLarge()
        stream, image = self._read_image(cleaned)
        try:
            mime_type, extension = self._check_header(image, claimed_mime_type)
            self._check_pixels(image)
            if image.format.upper() == "JPEG" and image.mode != "RGB":
                raise InvalidImage()
            return SanitizedImage(
                content=cleaned,
                mime_type=mime_type,
                extension=extension,
                width=image.width,
                height=image.height,
            )
        except (ImageMimeMismatch, ImagePixelLimitExceeded, UnsupportedImageFormat):
            raise
        except InvalidImage:
            raise
        except Exception as exc:
            raise InvalidImage() from exc
        finally:
            image.close()
            stream.close()
