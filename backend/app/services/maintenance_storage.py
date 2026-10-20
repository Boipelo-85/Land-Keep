"""Private maintenance-chat image validation and metadata-stripping storage."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from ..database import BASE_DIR

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1600
PRIVATE_IMAGE_DIR = BASE_DIR / "storage" / "maintenance-chat"
NOTICE_VERSION = "maintenance-photo-sharing-v1"
FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


@dataclass(frozen=True)
class SanitizedImage:
    data: bytes
    content_type: str
    extension: str


@dataclass(frozen=True)
class StoredAttachment:
    storage_path: str
    content_type: str
    size: int


def sanitize_image(data: bytes) -> SanitizedImage:
    """Validate image bytes, resize phone photos and re-encode without EXIF."""
    if not data:
        raise ValueError("Photo file is empty")
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("Photo must be 5 MB or smaller")

    try:
        with Image.open(BytesIO(data)) as source:
            image_format = source.format
            if image_format not in FORMATS:
                raise ValueError("Photo must contain a valid JPG, PNG, or WEBP image")
            if getattr(source, "is_animated", False):
                raise ValueError("Animated images are not supported")
            source.load()
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            content_type, extension = FORMATS[image_format]
            output = BytesIO()
            if image_format == "JPEG":
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(output, format="JPEG", quality=85, optimize=True)
            elif image_format == "PNG":
                image.save(output, format="PNG", optimize=True)
            else:
                image.save(output, format="WEBP", quality=85, method=6)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Photo is not a valid or supported image") from exc

    sanitized = output.getvalue()
    if not sanitized or len(sanitized) > MAX_PHOTO_BYTES:
        raise ValueError("Processed photo exceeds the 5 MB limit")
    return SanitizedImage(sanitized, content_type, extension)


def store_maintenance_photo(data: bytes) -> StoredAttachment:
    """Store a sanitized image under a non-public directory with a random name."""
    image = sanitize_image(data)
    PRIVATE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{image.extension}"
    destination = (PRIVATE_IMAGE_DIR / filename).resolve()
    if PRIVATE_IMAGE_DIR.resolve() not in destination.parents:
        raise ValueError("Invalid private storage path")
    with destination.open("xb") as output:
        output.write(image.data)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        # Windows does not provide POSIX mode semantics; the directory is still
        # kept outside any static/public web root.
        pass
    return StoredAttachment(
        storage_path=destination.relative_to(BASE_DIR).as_posix(),
        content_type=image.content_type,
        size=len(image.data),
    )


def read_private_attachment(storage_path: str) -> bytes:
    """Read only a path beneath private maintenance-chat storage."""
    root = PRIVATE_IMAGE_DIR.resolve()
    path = (BASE_DIR / storage_path).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError("Maintenance attachment not found")
    return path.read_bytes()
