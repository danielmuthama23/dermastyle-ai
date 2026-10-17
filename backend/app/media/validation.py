"""Pre-flight image checks, so we fail fast before spending API units.

Limits come from the YouCam docs: jpg/png only, under 10 MB; skin analysis
(SD) needs a short side of at least 480 px; clothes try-on needs at least
512x384 and at most 4096 px on a side.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageKind(str, Enum):
    face = "face"
    body = "body"
    garment = "garment"


class ImageRejected(ValueError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    content_type: str  # image/jpeg | image/png
    width: int
    height: int


_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}
_MAX_PIXELS = 50_000_000  # decompression-bomb guard


def validate_image(raw: bytes, kind: ImageKind, max_mb: int = 10) -> ValidatedImage:
    if not raw:
        raise ImageRejected("The file is empty.", "empty")
    if len(raw) >= max_mb * 1024 * 1024:
        raise ImageRejected(f"Images must be smaller than {max_mb} MB.", "too_large")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))  # verify() invalidates the handle
    except (UnidentifiedImageError, OSError):
        raise ImageRejected("That doesn't look like a valid image.", "invalid_image") from None
    ctype = _FORMATS.get(img.format or "")
    if ctype is None:
        raise ImageRejected("Only JPG and PNG images are supported.", "unsupported_format")
    w, h = img.size
    if w * h > _MAX_PIXELS:
        raise ImageRejected("That image has too many pixels.", "too_large")

    short, long_ = min(w, h), max(w, h)
    if kind is ImageKind.face:
        if short < 480:
            raise ImageRejected(
                "Skin analysis needs the short side of the photo to be at least 480 px.", "too_small"
            )
    else:
        if w < 128 or h < 128 or (short < 384 or long_ < 512):
            raise ImageRejected("That photo is too small. Use at least 512x384 px.", "too_small")
        if long_ > 4096:
            raise ImageRejected("The long side must not exceed 4096 px.", "too_large")
    if kind is ImageKind.body and h < w:
        raise ImageRejected(
            "Use a portrait-orientation, full-length photo for try-on.", "wrong_orientation"
        )
    return ValidatedImage(data=raw, content_type=ctype, width=w, height=h)


def normalize_exif(raw: bytes) -> bytes:
    """Apply EXIF rotation (phone photos) and strip metadata such as GPS."""
    img = Image.open(io.BytesIO(raw))
    fmt = img.format or "JPEG"
    img = ImageOps.exif_transpose(img)
    out = io.BytesIO()
    if fmt == "PNG":
        img.save(out, format="PNG")
    else:
        img.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()
