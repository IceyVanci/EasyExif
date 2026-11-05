"""High level metadata facade used by the CLI, GUI and tests."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import gps as gpsmod
from .jpeg import Jpeg
from .tags import (ASCII, BYTE, LONG, RATIONAL, SHORT, SRATIONAL, UNDEFINED,
                   TYPE_NAMES, TYPE_SIZES, display_value, fnumber_to_apex,
                   format_value, is_technical, rational_to_float, resolve_name,
                   seconds_to_apex_shutter, tag_info, technical_value)
from .tiff import Tiff, TiffError
from .xmp import Xmp


class MetadataError(RuntimeError):
    pass


EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"

RAW_SUFFIXES = {".dng", ".cr2", ".nef", ".arw", ".orf", ".rw2", ".pef", ".srw", ".raw"}


def _find_embedded_jpeg(data: bytes) -> bytes | None:
    """Return the largest embedded JPEG preview in a RAW container."""
    best: bytes | None = None
    pos = 0
    while True:
        start = data.find(b"\xff\xd8", pos)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            break
        chunk = data[start:end + 2]
        if len(chunk) >= 1024 and (best is None or len(chunk) > len(best)):
            best = chunk
        pos = end + 2
    return best


def _source_size(meta: "Metadata") -> tuple[int | None, int | None]:
    w = meta.tiff.get("IFD0", 0x0100) if meta.tiff else None
    h = meta.tiff.get("IFD0", 0x0101) if meta.tiff else None
    if not w:
        w = meta.tiff.get("EXIF", 0xA002) if meta.tiff else None
    if not h:
        h = meta.tiff.get("EXIF", 0xA003) if meta.tiff else None
    if isinstance(w, (list, tuple)):
        w = w[0] if w else None
    if isinstance(h, (list, tuple)):
        h = h[0] if h else None
    return (int(w) if isinstance(w, int) else None,
            int(h) if isinstance(h, int) else None)


def parse_exif_datetime(text: str) -> datetime:
    text = str(text).strip()
    for fmt in (EXIF_DATE_FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y:%m:%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise MetadataError("时间格式应为 YYYY:MM:DD HH:MM:SS，收到 %r" % text)


def format_exif_datetime(dt: datetime) -> str:
    return dt.strftime(EXIF_DATE_FMT)


@dataclass
class ImageInfo:
    width: int | None = None
    height: int | None = None
    format: str = "JPEG"
    bits: int | None = None


class Metadata:
    """Read, edit and write the metadata of one JPEG or TIFF file."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.jpeg: Jpeg | None = None
        self.tiff: Tiff | None = None
        self.xmp = Xmp()
        self.info = ImageInfo()
        self.warnings: list[str] = []
        self.raw_size = 0
        self.mtime: float | None = None
        self.readonly = False
        self.raw_format: str | None = None
        self.preview_data: bytes | None = None

    # -- reading -----------------------------------------------------------
    @classmethod
    def read(cls, path: str | os.PathLike) -> "Metadata":
        obj = cls(path)
        data = obj.path.read_bytes()
        obj.raw_size = len(data)
        obj.mtime = obj.path.stat().st_mtime
        suffix = obj.path.suffix.lower()
        if suffix in RAW_SUFFIXES:
            if data[:2] not in (b"II", b"MM"):
                raise MetadataError("暂不支持该 RAW 容器（仅支持 TIFF-based RAW）: %s" % path)
            obj.readonly = True
            obj.raw_format = suffix[1:].upper()
            obj.info.format = obj.raw_format
            try:
                obj.tiff = Tiff.parse(data)
                obj.warnings.extend(obj.tiff.warnings)
            except TiffError as exc:
                raise MetadataError("无法解析 RAW 元数据: %s" % exc) from exc
            w, h = _source_size(obj)
            obj.info.width, obj.info.height = w, h
            packet = obj.tiff.get("IFD0", 0x02BC)
            if isinstance(packet, (bytes, bytearray)):
                obj.xmp = Xmp(bytes(packet).rstrip(b"\0"))
            obj.preview_data = _find_embedded_jpeg(data)
            return obj
        if data[:2] == b"\xff\xd8":
            obj.jpeg = Jpeg.parse(data)
            obj.warnings.extend(obj.jpeg.warnings)
            obj.info.format = "JPEG"
            dims = obj.jpeg.dimensions()
            if dims:
                obj.info.width, obj.info.height = dims
            payload = obj.jpeg.exif_payload()
            if payload:
                try:
                    obj.tiff = Tiff.parse(payload)
                    obj.warnings.extend(obj.tiff.warnings)
                except TiffError as exc:
                    raise MetadataError("cannot parse EXIF: %s" % exc) from exc
            packet = obj.jpeg.xmp_packet()
            if packet:
                obj.xmp = Xmp(packet)
        elif data[:2] in (b"II", b"MM"):
            obj.info.format = "TIFF"
            obj.tiff = Tiff.parse(data)
            obj.warnings.extend(obj.tiff.warnings)
            w, h = obj.tiff.get("IFD0", 0x0100), obj.tiff.get("IFD0", 0x0101)
            if isinstance(w, int) and isinstance(h, int):
                obj.info.width, obj.info.height = w, h
            packet = obj.tiff.get("IFD0", 0x02BC)
            if isinstance(packet, (bytes, bytearray)):
                obj.xmp = Xmp(bytes(packet).rstrip(b"\0"))
        else:
            raise MetadataError("unsupported file type (expected JPEG or TIFF): %s" % path)
        return obj

    # -- writing -----------------------------------------------------------
    def save(self, out: str | os.PathLike | None = None, *,
             backup: bool = False, preserve_time: bool = True,
             atomic: bool = True) -> Path:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式，不支持写回")
        target = Path(out) if out else self.path
        if self.jpeg is not None:
            if self.tiff is not None:
                self.jpeg.set_exif_payload(self.tiff.to_bytes())
            if self.xmp.exists:
                self.jpeg.set_xmp_packet(self.xmp.to_bytes())
            else:
                self.jpeg.set_xmp_packet(None)
            data = self.jpeg.to_bytes()
        elif self.tiff is not None:
            if self.xmp.exists:
                self.tiff.set("IFD0", 0x02BC, self.xmp.to_bytes(), BYTE)
            else:
                self.tiff.delete("IFD0", 0x02BC)
            data = self.tiff.to_bytes()
        else:
            raise MetadataError("nothing to save")
        if backup and target.exists():
            shutil.copy2(target, str(target) + ".bak")
        if atomic:
            fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp",
                                       dir=str(target.parent))
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        else:
            target.write_bytes(data)
        if preserve_time and self.mtime is not None and target == self.path:
            os.utime(target, (self.mtime, self.mtime))
        return target

    # -- generic tag access ------------------------------------------------
    def _require_tiff(self, create: bool = False) -> Tiff:
        if self.tiff is None:
            if not create:
                raise MetadataError("file has no EXIF/TIFF metadata")
            self.tiff = Tiff()
        return self.tiff

    def get(self, name: str, default: Any = None) -> Any:
        if name.upper().startswith("XMP."):
            return self.xmp.get(name[4:], default)
        ifd, tag = resolve_name(name)
        ifd_name = "IFD0" if ifd == "IFD1" else ifd
        if self.tiff is None:
            return default
        return self.tiff.get(ifd_name, tag, default)

    def get_text(self, name: str, default: str = "") -> str:
        if name.upper().startswith("XMP."):
            value = self.xmp.get(name[4:])
            if value is None:
                return default
            return ", ".join(value) if isinstance(value, list) else str(value)
        ifd, tag = resolve_name(name)
        value = self.get(name)
        if value is None:
            return default
        return format_value(ifd, tag, value)

    def set(self, name: str, value: Any) -> None:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        if name.upper().startswith("XMP."):
            self.xmp.set(name[4:], value)
            return
        ifd, tag = resolve_name(name)
        if ifd == "IFD1":
            ifd = "IFD0"
        value = _normalize_natural_value(ifd, tag, value)
        tiff = self._require_tiff(create=True)
        info = tag_info(ifd, tag)
        old = tiff.ifds.get(ifd)
        old_type = old.entries[tag].type if old and tag in old.entries else (info.type or ASCII)
        if info.fmt == "datetime" or tag in (0x0132, 0x9003, 0x9004):
            value = format_exif_datetime(value if isinstance(value, datetime)
                                         else parse_exif_datetime(str(value)))
        if tag == 0x9286:  # UserComment
            value = _encode_user_comment(value)
            old_type = UNDEFINED
        if tag in (0x010F, 0x0110, 0x0131, 0x013B, 0x8298, 0x010E):
            old_type = ASCII
        if ifd == "GPS" and tag in (0x0002, 0x0004):
            number = _as_number(value)
            if number is not None:
                self._set_gps_component(tag, number)
                return
        if (ifd, tag) in _BYTE_NUMERIC_TAGS:
            coerced = _coerce_byte_numbers(value)
        else:
            coerced = _coerce(old_type, value)
        tiff.set(ifd, tag, coerced, old_type)
        self._sync_derived(ifd, tag, coerced)

    def _sync_derived(self, ifd: str, tag: int, value: Any) -> None:
        """Keep the paired APEX tag in step with its natural-value tag."""
        if ifd != "EXIF" or self.tiff is None:
            return
        if tag == 0x829D:  # FNumber -> ApertureValue, only if it already exists
            number = rational_to_float(value)
            if number and number > 0 and self.tiff.get("EXIF", 0x9202) is not None:
                self.tiff.set("EXIF", 0x9202,
                              _coerce(RATIONAL, fnumber_to_apex(number)), RATIONAL)
        elif tag == 0x829A:  # ExposureTime -> ShutterSpeedValue
            seconds = rational_to_float(value)
            if seconds and seconds > 0 and self.tiff.get("EXIF", 0x9201) is not None:
                self.tiff.set("EXIF", 0x9201,
                              _coerce(SRATIONAL, seconds_to_apex_shutter(seconds)), SRATIONAL)

    def delete(self, name: str) -> bool:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        if name.upper().startswith("XMP."):
            return self.xmp.delete(name[4:])
        ifd, tag = resolve_name(name)
        if self.tiff is None:
            return False
        return self.tiff.delete("IFD0" if ifd == "IFD1" else ifd, tag)

    def rows(self, include_makernote: bool = True) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if self.tiff:
            for row in self.tiff.describe():
                ifd, tag = row["ifd"], row["tag"]
                row = dict(row)
                row["display"] = format_value(ifd, tag, row["value"])
                row["technical"] = technical_value(ifd, tag, row["value"])
                row["readonly"] = is_technical(ifd, tag)
                rows.append(row)
            if include_makernote and self.tiff.makernote:
                for f in self.tiff.makernote.describe():
                    rows.append({"ifd": "MakerNote", "tag": f["tag"],
                                 "name": f["name"], "type": str(f["type"]),
                                 "type_id": f["type"],
                                 "count": f["count"],
                                 "bytes": TYPE_SIZES.get(f["type"], 1) * f["count"],
                                 "value": f["value"],
                                 "display": f["display"]})
        for key in self.xmp.keys():
            value = self.xmp.get(key)
            text = ", ".join(value) if isinstance(value, list) else str(value)
            rows.append({"ifd": "XMP", "tag": key, "name": key, "type": "XMP",
                         "type_id": 0, "count": 1, "bytes": len(text.encode("utf-8")),
                         "value": value, "display": text})
        return rows

    # -- convenience -------------------------------------------------------
    def camera(self) -> dict[str, str]:
        make = self.get_text("Make", "")
        model = self.get_text("Model", "")
        if model.lower().startswith(make.lower()) and make:
            model = model[len(make):].strip()
        return {
            "make": make,
            "model": model,
            "lens": self.get_text("LensModel", "") or self._makernote_text("LensModel")
                    or self._makernote_text("DerivedLens"),
            "serial": self.get_text("BodySerialNumber", "")
                      or self._makernote_text("SerialNumber"),
            "software": self.get_text("Software", ""),
        }

    def _apex_text(self, tag: int) -> str:
        value = self.tiff.get("EXIF", tag) if self.tiff is not None else None
        return format_value("EXIF", tag, value) if value is not None else ""

    def _makernote_text(self, name: str) -> str:
        if not self.tiff or not self.tiff.makernote:
            return ""
        v = self.tiff.makernote.get(name)
        if v is None:
            return ""
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).rstrip(b"\0").decode("utf-8", "replace")
        return str(v)

    def exposure(self) -> dict[str, str]:
        return {
            "date": self.get_text("DateTimeOriginal", "") or self.get_text("DateTime", ""),
            "shutter": self.get_text("ExposureTime", "") or self._apex_text(0x9201),
            "aperture": self.get_text("FNumber", "") or self._apex_text(0x9202),
            "iso": self.get_text("ISOSpeedRatings", "")
                   or self._makernote_text("DerivedISO"),
            "focal": self.get_text("FocalLength", ""),
            "focal35": self.get_text("FocalLengthIn35mmFilm", ""),
            "program": self.get_text("ExposureProgram", ""),
            "metering": self.get_text("MeteringMode", ""),
            "flash": self.get_text("Flash", ""),
            "white_balance": self.get_text("WhiteBalance", ""),
            "bias": self.get_text("ExposureBiasValue", ""),
            "orientation": self.get_text("Orientation", ""),
        }

    def gps(self) -> dict[str, Any] | None:
        if not self.tiff:
            return None
        lat_parts = self.tiff.get("GPS", 0x0002)
        lon_parts = self.tiff.get("GPS", 0x0004)
        lat = gpsmod.rationals_to_decimal(lat_parts)
        lon = gpsmod.rationals_to_decimal(lon_parts)
        if lat is None or lon is None:
            # try XMP
            flat = self.xmp.get("exif:GPSLatitude")
            flon = self.xmp.get("exif:GPSLongitude")
            if flat and flon:
                try:
                    lat = gpsmod.parse_coordinate(str(flat))
                    lon = gpsmod.parse_coordinate(str(flon))
                except ValueError:
                    return None
            else:
                return None
        lat_ref = self.tiff.text("GPS", 0x0001, "N").strip().upper()[:1] or "N"
        lon_ref = self.tiff.text("GPS", 0x0003, "E").strip().upper()[:1] or "E"
        if lat_ref == "S":
            lat = -abs(lat)
        if lon_ref == "W":
            lon = -abs(lon)
        alt = rational_to_float(self.tiff.get("GPS", 0x0006))
        alt_ref = self.tiff.get("GPS", 0x0005)
        if isinstance(alt_ref, (bytes, bytearray)) and alt_ref and alt_ref[0] == 1 and alt is not None:
            alt = -alt
        return {
            "latitude": lat, "longitude": lon, "altitude": alt,
            "datum": self.tiff.text("GPS", 0x0012, "WGS-84") or "WGS-84",
            "timestamp": format_value("GPS", 0x0007, self.tiff.get("GPS", 0x0007))
            if self.tiff.get("GPS", 0x0007) is not None else None,
            "date": self.tiff.text("GPS", 0x001D, "") or None,
        }

    def set_gps(self, lat: float, lon: float, alt: float | None = None,
                datum: str = "wgs84", address: str | None = None) -> None:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        lat, lon = gpsmod.convert(lat, lon, datum, "wgs84")
        tiff = self._require_tiff(create=True)
        tiff.set("GPS", 0x0000, b"\x02\x03\x00\x00", BYTE)
        tiff.set("GPS", 0x0001, "N" if lat >= 0 else "S", ASCII)
        tiff.set("GPS", 0x0002, gpsmod.dms_to_rationals(abs(lat)), RATIONAL)
        tiff.set("GPS", 0x0003, "E" if lon >= 0 else "W", ASCII)
        tiff.set("GPS", 0x0004, gpsmod.dms_to_rationals(abs(lon)), RATIONAL)
        if alt is not None:
            tiff.set("GPS", 0x0005, b"\x00" if alt >= 0 else b"\x01", BYTE)
            tiff.set("GPS", 0x0006, (abs(int(round(alt * 100))), 100), RATIONAL)
        if address:
            tiff.set("GPS", 0x001B, b"ASCII\0\0\0" + address.encode("utf-8"), UNDEFINED)
        self.xmp.set("exif:GPSLatitude", "%.7f" % lat)
        self.xmp.set("exif:GPSLongitude", "%.7f" % lon)

    def clear_gps(self) -> None:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        if self.tiff and "GPS" in self.tiff.ifds:
            del self.tiff.ifds["GPS"]
            self.tiff.dirty = True
        self.xmp.delete("exif:GPSLatitude")
        self.xmp.delete("exif:GPSLongitude")
        self.xmp.delete("exif:GPSAltitude")

    def _set_gps_component(self, tag: int, value: float) -> None:
        cur = self.gps()
        lat = lon = None
        if cur is not None:
            lat, lon = cur["latitude"], cur["longitude"]
        if tag == 0x0002:
            lat = value if value <= 90 else lat
            lon = lon if lon is not None else 0.0
        else:
            lon = value
            lat = lat if lat is not None else 0.0
        self.set_gps(lat or 0.0, lon or 0.0)

    def shift_time(self, delta: timedelta) -> int:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        if not self.tiff:
            return 0
        count = 0
        for ifd, tag in (("IFD0", 0x0132), ("EXIF", 0x9003), ("EXIF", 0x9004)):
            text = self.tiff.text(ifd, tag, "")
            if text:
                try:
                    dt = parse_exif_datetime(text)
                except MetadataError:
                    continue
                self.tiff.set(ifd, tag, format_exif_datetime(dt + delta), ASCII)
                count += 1
        return count

    def sync_datetime(self) -> None:
        """Copy DateTimeOriginal into DateTime and DateTimeDigitized."""
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        if not self.tiff:
            return
        original = self.tiff.text("EXIF", 0x9003, "")
        if not original:
            return
        self.tiff.set("IFD0", 0x0132, original, ASCII)
        if not self.tiff.text("EXIF", 0x9004, ""):
            self.tiff.set("EXIF", 0x9004, original, ASCII)

    def clear_metadata(self, keep_icc: bool = True) -> None:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        jpeg = self.jpeg
        if jpeg is None:
            raise MetadataError("clearing metadata is only supported for JPEG")
        removed = []
        for s in list(jpeg.segments):
            if s.marker == 0xE1 and (s.data.startswith(b"Exif\0\0")
                                     or s.data.startswith(b"http://ns.adobe.com/xap")):
                removed.append(s)
            elif s.marker in (0xED, 0xFE):
                removed.append(s)
            elif s.marker == 0xE2 and s.data.startswith(b"MPF\0"):
                removed.append(s)
            elif s.marker == 0xE2 and s.data.startswith(b"ICC_PROFILE\0") and not keep_icc:
                removed.append(s)
        for s in removed:
            jpeg.segments.remove(s)
        jpeg._reindex()
        self.tiff = None
        self.xmp = Xmp()
        self.warnings.append("removed %d metadata segments" % len(removed))

    def thumbnail(self) -> bytes | None:
        return self.tiff.thumbnail if self.tiff else None

    def preview_bytes(self) -> bytes | None:
        """Embedded preview for RAW files, if one can be extracted."""
        return self.preview_data if self.readonly else None

    def set_thumbnail(self, data: bytes | None) -> None:
        if self.readonly:
            raise MetadataError("RAW 文件当前为只读模式")
        tiff = self._require_tiff(create=True)
        tiff.thumbnail = data
        if data is None and "IFD1" in tiff.ifds:
            del tiff.ifds["IFD1"]

    def summary(self) -> dict[str, Any]:
        camera = self.camera()
        exposure = self.exposure()
        gps = self.gps()
        return {
            "file": str(self.path),
            "size": self.raw_size,
            "format": self.info.format,
            "dimensions": [self.info.width, self.info.height],
            "camera": camera,
            "exposure": exposure,
            "gps": gps,
            "has_exif": self.tiff is not None,
            "has_xmp": self.xmp.exists,
            "has_iptc": bool(self.jpeg and self.jpeg.iptc()),
            "has_icc": bool(self.jpeg and self.jpeg.icc_profile()),
            "maker_note": self.tiff.makernote.maker if self.tiff and self.tiff.makernote else None,
            "thumbnail_bytes": len(self.tiff.thumbnail) if self.tiff and self.tiff.thumbnail else 0,
            "warnings": self.warnings,
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), ensure_ascii=False, indent=2, default=str)

    def __repr__(self) -> str:
        return "<Metadata %s %s>" % (self.path.name, self.info.format)


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------
def _coerce(type_id: int, value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
    if type_id == ASCII:
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        return str(value)
    if type_id in (BYTE, UNDEFINED):
        if isinstance(value, str):
            if value.lower().startswith("0x"):
                return bytes.fromhex(value[2:])
            return value.encode("utf-8")
        if isinstance(value, int):
            return bytes([value & 0xFF])
        return value
    if type_id in (SHORT, LONG):
        if isinstance(value, str):
            parts = [p for p in value.replace(",", " ").split() if p]
            nums = [int(float(p)) for p in parts]
        elif isinstance(value, (list, tuple)):
            nums = [int(v) for v in value]
        else:
            nums = [int(value)]
        return nums[0] if len(nums) == 1 else tuple(nums)
    if type_id in (RATIONAL, SRATIONAL):
        if isinstance(value, str):
            parts = [p for p in value.replace(",", " ").split() if p]
            if not parts:
                raise ValueError("empty rational value")
            pairs = [_rational(part) for part in parts]
            return pairs[0] if len(pairs) == 1 else tuple(pairs)
        if isinstance(value, tuple) and len(value) == 2 and all(isinstance(x, int) for x in value):
            return value
        f = float(value)
        if float(f).is_integer():
            return (int(f), 1)
        den = 10000
        return (int(round(f * den)), den)
    return value


def _rational(text: str) -> tuple[int, int]:
    """Parse one rational token: 28/10, 2.8, -1/3 or 0."""
    token = text.strip()
    if "/" in token:
        num, den = token.split("/", 1)
        return (int(float(num)), int(float(den)))
    number = float(token)
    if number.is_integer():
        return (int(number), 1)
    return (int(round(number * 10000)), 10000)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_byte_numbers(value: Any) -> bytes:
    """Bytes for tags that store small numeric codes (3, 2 3 0 0, 0x03)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    text = str(value).strip()
    if text.lower().startswith("0x"):
        return bytes.fromhex(text[2:])
    parts = [p for p in text.replace(",", " ").split() if p]
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return text.encode("utf-8")
    return bytes(number & 0xFF for number in numbers)


# Tags whose BYTE/UNDEFINED payload is a numeric code, not text.
_BYTE_NUMERIC_TAGS = {
    ("GPS", 0x0000),   # GPSVersionID
    ("GPS", 0x0005),   # GPSAltitudeRef
    ("EXIF", 0x9101),  # ComponentsConfiguration
    ("EXIF", 0xA300),  # FileSource
    ("EXIF", 0xA301),  # SceneType
}


def _numeric_text(text: str) -> float:
    token = text.strip()
    if "/" in token:
        num, den = token.split("/", 1)
        return float(num) / float(den)
    return float(token)


def _normalize_natural_value(ifd: str, tag: int, value: Any) -> Any:
    """Accept natural editor input while keeping raw APEX available as advanced input.

    FNumber and ExposureTime are natural-value tags.  ApertureValue and
    ShutterSpeedValue remain raw APEX tags by default; ``f/`` and second
    suffixes are accepted only when the user explicitly types a natural
    value into an advanced field.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if tag == 0x829D:  # FNumber
        match = re.match(r"^[fF]\s*/?\s*([0-9]+(?:\.[0-9]+)?)$", text)
        if match:
            if float(match.group(1)) <= 0:
                raise MetadataError("光圈 F 数必须大于 0")
            return match.group(1)
        return text
    if tag == 0x829A:  # ExposureTime
        return re.sub(r"\s*(?:s|sec|秒|\"|″)\s*$", "", text, flags=re.IGNORECASE)
    if tag in (0x9202, 0x9205):  # ApertureValue / MaxApertureValue
        if text.lower().startswith("apex:"):
            return text.split(":", 1)[1].strip()
        match = re.match(r"^[fF]\s*/?\s*([0-9]+(?:\.[0-9]+)?)$", text)
        if match:
            fnumber = float(match.group(1))
            if fnumber <= 0:
                raise MetadataError("光圈 F 数必须大于 0")
            return fnumber_to_apex(fnumber)
        return text
    if tag == 0x9201:  # ShutterSpeedValue
        if text.lower().startswith("apex:"):
            return text.split(":", 1)[1].strip()
        natural = re.sub(r"\s*(?:s|sec|秒|\"|″)\s*$", "", text, flags=re.IGNORECASE)
        if "/" in natural or natural != text:
            try:
                seconds = _numeric_text(natural)
            except (ValueError, ZeroDivisionError):
                return text
            if seconds <= 0:
                raise MetadataError("快门时间必须大于 0")
            return seconds_to_apex_shutter(seconds)
        return text
    return value


def preview_value(name: str, text: str) -> dict[str, Any]:
    """Mirror Metadata.set coercion so the editor can preview a typed value."""
    raw = str(name or "").strip()
    if raw.upper().startswith("XMP."):
        return {"display": text, "type": "XMP", "ifd": "XMP",
                "tag": raw[4:], "count": 1}
    if not raw:
        raise MetadataError("请填写标签名")
    ifd, tag = resolve_name(raw)
    if ifd == "IFD1":
        ifd = "IFD0"
    info = tag_info(ifd, tag)
    type_id = info.type or ASCII
    normalized = _normalize_natural_value(ifd, tag, text)
    if info.fmt == "datetime" or tag in (0x0132, 0x9003, 0x9004):
        value: Any = format_exif_datetime(parse_exif_datetime(text))
    elif tag == 0x9286:
        value = _encode_user_comment(text)
    elif (ifd, tag) in _BYTE_NUMERIC_TAGS:
        value = _coerce_byte_numbers(text)
    elif ifd == "GPS" and tag in (0x0002, 0x0004) and _as_number(text) is not None:
        value = gpsmod.dms_to_rationals(abs(float(_as_number(text) or 0.0)))
    else:
        value = _coerce(type_id, normalized)
    result = {
        "display": display_value(format_value(ifd, tag, value, type_id)),
        "type": TYPE_NAMES.get(type_id, str(type_id)),
        "ifd": ifd,
        "tag": "0x%04X" % tag,
        "count": _count_value(type_id, value),
        "readonly": is_technical(ifd, tag),
    }
    number = rational_to_float(value)
    if tag == 0x829D and number and number > 0:
        apex = fnumber_to_apex(number)
        result["unit"] = "F 数"
        result["derived"] = [{
            "name": "ApertureValue",
            "display": "APEX %g（等效 f/%g）" % (apex, round(number, 1)),
            "value": "%g" % apex,
        }]
        result["note"] = "若文件中已有 ApertureValue，将同步为上面的 APEX 值"
    elif tag == 0x829A and number and number > 0:
        apex = seconds_to_apex_shutter(number)
        result["unit"] = "秒"
        result["derived"] = [{
            "name": "ShutterSpeedValue",
            "display": "APEX %g（等效 %s）" % (
                apex, format_value("EXIF", 0x9201, _coerce(SRATIONAL, apex), SRATIONAL)),
            "value": "%g" % apex,
        }]
        result["note"] = "若文件中已有 ShutterSpeedValue，将同步为上面的 APEX 值"
    elif tag in (0x9202, 0x9205) and number is not None:
        result["technical"] = "APEX %g" % number
        result["unit"] = "APEX"
    elif tag == 0x9201 and number is not None:
        result["technical"] = "APEX %g" % number
        result["unit"] = "APEX"
    elif tag == 0x9203 and number is not None:
        result["technical"] = "APEX %g" % number
        result["unit"] = "APEX/EV"
    return result


def _count_value(type_id: int, value: Any) -> int:
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if type_id in (RATIONAL, SRATIONAL):
        if isinstance(value, tuple) and len(value) == 2 and all(isinstance(x, int) for x in value):
            return 1
        if isinstance(value, (list, tuple)):
            return len(value)
        return 1
    if isinstance(value, (list, tuple)):
        return len(value)
    return 1


def _encode_user_comment(value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    text = str(value)
    try:
        text.encode("ascii")
        return b"ASCII\0\0\0" + text.encode("ascii")
    except UnicodeEncodeError:
        return b"UNICODE\0" + text.encode("utf-16-be")
