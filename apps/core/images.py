"""Small, deterministic WebP optimizer for user/course image uploads."""
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


def optimize_image(upload, *, max_size=(1600, 1200), quality=82):
    """Resize and re-encode an uploaded raster image as WebP.

    Returns a Django ContentFile with a .webp name. The original upload remains
    untouched, and transparent PNGs retain alpha transparency.
    """
    if upload is None:
        return upload
    try:
        upload.seek(0)
        with Image.open(upload) as source:
            source.load()
            if source.width > 12000 or source.height > 12000:
                raise ValueError('Image dimensions are too large.')
            image = ImageOps.exif_transpose(source)
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            if 'A' in image.getbands() or image.mode in ('RGBA', 'LA'):
                image = image.convert('RGBA')
            else:
                image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format='WEBP', quality=quality, method=6)
            output.seek(0)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError('Upload a valid image file.') from exc
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass

    name = f'{Path(upload.name).stem or "image"}.webp'
    return ContentFile(output.read(), name=name)
