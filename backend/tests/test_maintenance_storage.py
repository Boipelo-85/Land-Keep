from io import BytesIO

import pytest
from PIL import Image

from app.services import maintenance_storage as storage


def _image_bytes(image_format="JPEG", size=(2200, 1200), exif=None):
    image = Image.new("RGB", size, color=(30, 80, 120))
    buffer = BytesIO()
    image.save(buffer, format=image_format, exif=exif or b"")
    return buffer.getvalue()


def test_sanitizer_uses_image_content_resizes_and_strips_exif():
    exif = Image.Exif()
    exif[271] = "Phone camera"
    exif[274] = 6
    result = storage.sanitize_image(_image_bytes(exif=exif))

    assert result.content_type == "image/jpeg"
    assert result.extension == ".jpg"
    with Image.open(BytesIO(result.data)) as cleaned:
        assert max(cleaned.size) <= storage.MAX_IMAGE_DIMENSION
        assert not cleaned.getexif()


def test_sanitizer_rejects_invalid_and_oversized_images():
    with pytest.raises(ValueError, match="valid or supported image"):
        storage.sanitize_image(b"not an image")
    with pytest.raises(ValueError, match="5 MB"):
        storage.sanitize_image(b"x" * (storage.MAX_PHOTO_BYTES + 1))


def test_private_storage_round_trip_and_path_traversal_rejection(tmp_path, monkeypatch):
    private_dir = tmp_path / "storage" / "maintenance-chat"
    monkeypatch.setattr(storage, "BASE_DIR", tmp_path)
    monkeypatch.setattr(storage, "PRIVATE_IMAGE_DIR", private_dir)
    source = _image_bytes("WEBP", size=(640, 480))

    saved = storage.store_maintenance_photo(source)

    assert saved.storage_path.startswith("storage/maintenance-chat/")
    assert saved.content_type == "image/webp"
    assert storage.read_private_attachment(saved.storage_path)
    with pytest.raises(FileNotFoundError):
        storage.read_private_attachment("storage/maintenance-chat/../../outside.jpg")
