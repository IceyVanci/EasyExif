"""EasyExif - an open source EXIF/XMP metadata editor.

Lossless JPEG segment editing, EXIF/TIFF read-write, maker note decoding,
GPS datum conversion, batch reporting and an originality validator, built on
public format specifications.
"""
from __future__ import annotations

from .jpeg import Jpeg, Segment
from .metadata import Metadata, MetadataError
from .tiff import Tiff, TiffError
from .validate import Report, validate
from .xmp import Xmp

__version__ = "0.1.1"

__all__ = ["Jpeg", "Segment", "Metadata", "MetadataError", "Tiff", "TiffError",
           "Report", "validate", "Xmp", "__version__"]
