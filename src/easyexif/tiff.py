"""Lossless TIFF / EXIF container parser and writer.

The writer rebuilds the TIFF payload from the in-memory IFD model.  Values
that were not modified are copied verbatim, so unknown and vendor specific
tags survive a round trip.  Maker notes are re-encoded when their internal
offsets are relative to the TIFF header (Canon, Apple, Nikon type 1) and are
copied unchanged when they are relative to the note itself.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import makernote as mn
from .tags import (ASCII, BYTE, IFD, LONG, RATIONAL, SBYTE, SHORT, SLONG,
                   SRATIONAL, SSHORT, TYPE_NAMES, TYPE_SIZES, UNDEFINED,
                   DOUBLE, FLOAT, IFD_TABLES, tag_info)

POINTER_TAGS = {0x8769: "EXIF", 0x8825: "GPS", 0xA005: "Interop"}
THUMB_OFFSET, THUMB_LENGTH = 0x0201, 0x0202
MAKERNOTE_TAG = 0x927C

# Tags containing absolute offsets that we cannot safely relocate on rebuild.
UNSAFE_TAGS = {0x014A: "SubIFDs"}


class TiffError(ValueError):
    pass


@dataclass
class Entry:
    tag: int
    type: int
    count: int
    value: Any
    raw: bytes | None = None
    dirty: bool = False
    offset: int | None = None

    @property
    def nbytes(self) -> int:
        return TYPE_SIZES.get(self.type, 1) * self.count

    def copy(self) -> "Entry":
        return Entry(self.tag, self.type, self.count, self.value, self.raw, False, self.offset)


@dataclass
class IFD:
    name: str
    entries: dict[int, Entry] = field(default_factory=dict)
    next_offset: int = 0

    def get(self, tag: int, default: Any = None) -> Any:
        e = self.entries.get(tag)
        return default if e is None else e.value

    def text(self, tag: int, default: str = "") -> str:
        v = self.get(tag)
        if v is None:
            return default
        if isinstance(v, str):
            return v.rstrip("\0")
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).rstrip(b"\0").decode("utf-8", "replace")
        return str(v)

    def set(self, tag: int, value: Any, type_id: int | None = None) -> Entry:
        old = self.entries.get(tag)
        if type_id is None:
            if old is not None:
                type_id = old.type
            else:
                type_id = _infer_type(value)
        entry = entry_from_value(tag, value, type_id)
        self.entries[tag] = entry
        return entry

    def delete(self, tag: int) -> bool:
        return self.entries.pop(tag, None) is not None


class Tiff:
    """A TIFF structure: IFD0, ExifIFD, GPS, Interop and IFD1."""

    def __init__(self, endian: str = "<"):
        self.endian = endian
        self.ifds: dict[str, IFD] = {"IFD0": IFD("IFD0")}
        self.thumbnail: bytes | None = None
        self.makernote: mn.MakerNote | None = None
        self.warnings: list[str] = []
        self.dirty = False

    # -- construction ------------------------------------------------------
    @classmethod
    def parse(cls, data: bytes, strict: bool = False) -> "Tiff":
        if len(data) < 8:
            raise TiffError("TIFF data too short")
        if data[:2] == b"II":
            endian = "<"
        elif data[:2] == b"MM":
            endian = ">"
        else:
            raise TiffError("not a TIFF header")
        magic = struct.unpack_from(endian + "H", data, 2)[0]
        if magic != 42:
            raise TiffError("bad TIFF magic %d" % magic)
        first = struct.unpack_from(endian + "I", data, 4)[0]
        obj = cls(endian)
        obj._data = data
        obj._parse_ifd("IFD0", first, data, set())
        # IFD1 chain
        nxt = obj.ifds["IFD0"].next_offset
        idx = 1
        while nxt and idx < 4 and nxt not in (0, first):
            name = "IFD%d" % idx
            if name not in obj.ifds:
                obj._parse_ifd(name, nxt, data, {first})
            nxt = obj.ifds[name].next_offset
            idx += 1
        # linked EXIF / GPS
        ifd0 = obj.ifds["IFD0"]
        if 0x8769 in ifd0.entries:
            off = _as_int(ifd0.get(0x8769))
            if off:
                obj._parse_ifd("EXIF", off, data, {first})
        if 0x8825 in ifd0.entries:
            off = _as_int(ifd0.get(0x8825))
            if off:
                obj._parse_ifd("GPS", off, data, {first})
        if "EXIF" in obj.ifds and 0xA005 in obj.ifds["EXIF"].entries:
            off = _as_int(obj.ifds["EXIF"].get(0xA005))
            if off:
                obj._parse_ifd("Interop", off, data, {first})
        obj._extract_thumbnail()
        obj._parse_makernote()
        return obj

    @classmethod
    def from_bytes(cls, data: bytes) -> "Tiff":
        return cls.parse(data)

    def _parse_ifd(self, name: str, offset: int, data: bytes, seen: set[int]) -> None:
        if offset in seen:
            self.warnings.append("%s: loop at offset 0x%X" % (name, offset))
            return
        seen.add(offset)
        if offset < 8 or offset + 2 > len(data):
            self.warnings.append("%s: IFD offset 0x%X out of range" % (name, offset))
            return
        count = struct.unpack_from(self.endian + "H", data, offset)[0]
        if count == 0 or count > 1000:
            self.warnings.append("%s: implausible entry count %d" % (name, count))
            if count == 0:
                self.ifds[name] = IFD(name)
                return
        if offset + 2 + 12 * count + 4 > len(data):
            self.warnings.append("%s: IFD table truncated" % name)
            count = max(0, (len(data) - offset - 6) // 12)
        ifd = IFD(name)
        for i in range(count):
            base = offset + 2 + 12 * i
            tag, typ, cnt = struct.unpack_from(self.endian + "HHI", data, base)
            size = TYPE_SIZES.get(typ, 0) * cnt
            if typ not in TYPE_SIZES or size == 0:
                self.warnings.append("%s: tag 0x%04X has invalid type %d" % (name, tag, typ))
                continue
            value_offset = base + 8
            if size <= 4:
                raw = data[base + 8:base + 8 + size]
            else:
                voff = struct.unpack_from(self.endian + "I", data, base + 8)[0]
                value_offset = voff
                if voff + size > len(data):
                    self.warnings.append(
                        "%s: tag 0x%04X value 0x%X+%d out of range" % (name, tag, voff, size))
                    raw = data[voff:voff + size] if voff < len(data) else b""
                else:
                    raw = data[voff:voff + size]
            try:
                value = decode_value(raw, typ, cnt, self.endian)
            except Exception as exc:  # keep the entry raw even if decoding fails
                self.warnings.append("%s: tag 0x%04X decode error: %s" % (name, tag, exc))
                value = raw
            ifd.entries[tag] = Entry(tag, typ, cnt, value, raw, False, value_offset)
        if offset + 2 + 12 * count + 4 <= len(data):
            ifd.next_offset = struct.unpack_from(self.endian + "I", data, offset + 2 + 12 * count)[0]
        self.ifds[name] = ifd

    def _extract_thumbnail(self) -> None:
        ifd1 = self.ifds.get("IFD1")
        if not ifd1:
            return
        off = _as_int(ifd1.get(THUMB_OFFSET))
        length = _as_int(ifd1.get(THUMB_LENGTH))
        data = getattr(self, "_data", b"")
        if off and length and off + length <= len(data) and length > 4:
            self.thumbnail = data[off:off + length]

    def _parse_makernote(self) -> None:
        exif = self.ifds.get("EXIF")
        if not exif:
            return
        entry = exif.entries.get(MAKERNOTE_TAG)
        if not entry or not isinstance(entry.value, (bytes, bytearray)):
            return
        make = self.ifds["IFD0"].text(0x010F)
        try:
            self.makernote = mn.parse_makernote(make, bytes(entry.value), self.endian,
                                               entry.offset or 0)
        except Exception as exc:
            self.warnings.append("maker note: %s" % exc)

    # -- accessors ---------------------------------------------------------
    def ifd(self, name: str) -> IFD:
        if name not in self.ifds:
            self.ifds[name] = IFD(name)
            self.dirty = True
        return self.ifds[name]

    def get(self, name: str, tag: int, default: Any = None) -> Any:
        ifd = self.ifds.get(name)
        return default if ifd is None else ifd.get(tag, default)

    def text(self, name: str, tag: int, default: str = "") -> str:
        ifd = self.ifds.get(name)
        return default if ifd is None else ifd.text(tag, default)

    def set(self, name: str, tag: int, value: Any, type_id: int | None = None) -> None:
        self.ifd(name).set(tag, value, type_id)
        self.dirty = True
        if name == "EXIF" and tag == MAKERNOTE_TAG and isinstance(value, (bytes, bytearray)):
            make = self.ifds["IFD0"].text(0x010F)
            try:
                self.makernote = mn.parse_makernote(make, bytes(value), self.endian, 0)
            except Exception as exc:
                self.warnings.append("maker note: %s" % exc)

    def delete(self, name: str, tag: int) -> bool:
        ifd = self.ifds.get(name)
        if ifd and ifd.delete(tag):
            self.dirty = True
            return True
        return False

    def ensure(self, name: str) -> IFD:
        return self.ifd(name)

    def get_makernote_field(self, name: str) -> Any:
        if not self.makernote:
            return None
        return self.makernote.get(name)

    # -- serialization -----------------------------------------------------
    def to_bytes(self) -> bytes:
        self._validate_for_write()
        endian = self.endian
        if self.thumbnail and "IFD1" not in self.ifds:
            self.ifds["IFD1"] = IFD("IFD1")
        names = [n for n in ("IFD0", "EXIF", "GPS", "Interop", "IFD1") if n in self.ifds]
        if "IFD0" not in names:
            names.insert(0, "IFD0")
        # Build the entry plan (tag, type, count, value bytes, external?)
        plan: dict[str, list[tuple[int, int, int, bytes, bool]]] = {}
        extras: dict[str, int] = {}
        for name in names:
            ifd = self.ifds[name]
            entries: list[tuple[int, int, int, bytes, bool]] = []
            for tag in sorted(ifd.entries):
                entry = ifd.entries[tag]
                if tag in POINTER_TAGS or tag in UNSAFE_TAGS:
                    continue
                if name == "IFD1" and tag in (THUMB_OFFSET, THUMB_LENGTH):
                    continue
                if name == "EXIF" and tag == MAKERNOTE_TAG:
                    # keep the table slot; the value is an offset patched later
                    entries.append((tag, entry.type, entry.count, b"\0\0\0\0", False))
                    continue
                if entry.dirty or entry.raw is None or len(entry.raw) != entry.nbytes:
                    data = encode_value(entry.value, entry.type, entry.count, endian)
                else:
                    data = entry.raw
                if len(data) != entry.nbytes:
                    entry.count = max(1, len(data) // TYPE_SIZES.get(entry.type, 1))
                entries.append((tag, entry.type, entry.count, data, len(data) > 4))
            # synthesized pointer entries
            if name == "IFD0":
                if "EXIF" in self.ifds and self.ifds["EXIF"].entries:
                    entries.append((0x8769, LONG, 1, b"\0\0\0\0", False))
                if "GPS" in self.ifds and self.ifds["GPS"].entries:
                    entries.append((0x8825, LONG, 1, b"\0\0\0\0", False))
            if name == "EXIF" and "Interop" in self.ifds and self.ifds["Interop"].entries:
                entries.append((0xA005, LONG, 1, b"\0\0\0\0", False))
            if name == "IFD1" and self.thumbnail:
                entries.append((THUMB_OFFSET, LONG, 1, b"\0\0\0\0", False))
                entries.append((THUMB_LENGTH, LONG, 1, struct.pack(endian + "I", len(self.thumbnail)), False))
            entries.sort(key=lambda e: e[0])
            plan[name] = entries
            extras[name] = 2 + 12 * len(entries) + 4

        # Assign table offsets.
        table_offsets: dict[str, int] = {}
        cursor = 8
        for name in names:
            table_offsets[name] = cursor
            cursor += extras[name]
        # Assign external data offsets.
        data_offsets: dict[tuple[str, int], int] = {}
        cursor = _align(cursor, 4)
        data_start = cursor
        for name in names:
            for tag, typ, count, data, ext in plan[name]:
                if ext:
                    cursor = _align(cursor, 2)
                    data_offsets[(name, tag)] = cursor
                    cursor += len(data)
        thumb_offset = None
        if self.thumbnail:
            cursor = _align(cursor, 2)
            thumb_offset = cursor
            cursor += len(self.thumbnail)
        mn_offset = None
        mn_bytes = b""
        if self.makernote is not None:
            cursor = _align(cursor, 4)
            mn_offset = cursor
            mn_bytes = self.makernote.encode(mn_offset) if self.makernote.encodable else self.makernote.raw
            if not mn_bytes:
                mn_bytes = self.makernote.raw
            cursor += len(mn_bytes)
        total = cursor

        out = bytearray(total)
        out[0:2] = b"II" if endian == "<" else b"MM"
        struct.pack_into(endian + "H", out, 2, 42)
        struct.pack_into(endian + "I", out, 4, table_offsets.get("IFD0", 8))

        # Patch maker note entry into the EXIF plan at its reserved place.
        for name in names:
            ifd = self.ifds[name]
            toff = table_offsets[name]
            entries = plan[name]
            struct.pack_into(endian + "H", out, toff, len(entries))
            for i, (tag, typ, count, data, ext) in enumerate(entries):
                base = toff + 2 + 12 * i
                struct.pack_into(endian + "HHI", out, base, tag, typ, count)
                if tag in POINTER_TAGS and data == b"\0\0\0\0":
                    target = POINTER_TAGS[tag]
                    off = table_offsets.get(target, 0)
                    struct.pack_into(endian + "I", out, base + 8, off)
                elif name == "IFD1" and tag == THUMB_OFFSET:
                    struct.pack_into(endian + "I", out, base + 8, thumb_offset or 0)
                elif name == "EXIF" and tag == MAKERNOTE_TAG:
                    struct.pack_into(endian + "I", out, base + 8, mn_offset or 0)
                elif ext:
                    off = data_offsets[(name, tag)]
                    struct.pack_into(endian + "I", out, base + 8, off)
                    out[off:off + len(data)] = data
                else:
                    out[base + 8:base + 8 + len(data)] = data
            nxt = table_offsets.get("IFD1", 0) if name == "IFD0" and "IFD1" in self.ifds else 0
            struct.pack_into(endian + "I", out, toff + 2 + 12 * len(entries), nxt)

        if self.thumbnail and thumb_offset is not None:
            out[thumb_offset:thumb_offset + len(self.thumbnail)] = self.thumbnail
        if self.makernote is not None and mn_offset is not None and mn_bytes:
            out[mn_offset:mn_offset + len(mn_bytes)] = mn_bytes
        return bytes(out)

    def _validate_for_write(self) -> None:
        for name in list(self.ifds):
            ifd = self.ifds[name]
            for tag in list(ifd.entries):
                if tag in UNSAFE_TAGS:
                    self.warnings.append("dropped unsupported tag %s" % UNSAFE_TAGS[tag])
                    ifd.entries.pop(tag, None)
        if "EXIF" in self.ifds and "IFD0" not in self.ifds:
            raise TiffError("missing IFD0")
        if "IFD1" in self.ifds:
            ifd1 = self.ifds["IFD1"]
            if not self.thumbnail:
                for tag in (THUMB_OFFSET, THUMB_LENGTH):
                    ifd1.entries.pop(tag, None)
                if not ifd1.entries:
                    del self.ifds["IFD1"]

    # -- presentation ------------------------------------------------------
    def describe(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in ("IFD0", "EXIF", "GPS", "Interop", "IFD1"):
            ifd = self.ifds.get(name)
            if not ifd:
                continue
            for tag in sorted(ifd.entries):
                e = ifd.entries[tag]
                rows.append({
                    "ifd": name,
                    "tag": tag,
                    "name": tag_info(name, tag).name,
                    "type": TYPE_NAMES.get(e.type, str(e.type)),
                    "type_id": e.type,
                    "count": e.count,
                    "bytes": e.nbytes,
                    "value": e.value,
                })
        return rows

    def copy(self) -> "Tiff":
        return Tiff.parse(self.to_bytes())


# ---------------------------------------------------------------------------
# Value codec
# ---------------------------------------------------------------------------
def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def _infer_type(value: Any) -> int:
    if isinstance(value, str):
        return ASCII
    if isinstance(value, (bytes, bytearray)):
        return UNDEFINED
    if isinstance(value, bool):
        return SHORT
    if isinstance(value, int):
        return LONG
    if isinstance(value, float):
        return RATIONAL
    if isinstance(value, tuple):
        if len(value) == 2 and all(isinstance(x, int) for x in value):
            return RATIONAL
        return SHORT
    if isinstance(value, list):
        if value and isinstance(value[0], tuple):
            return RATIONAL
        return SHORT
    raise TypeError("cannot infer TIFF type for %r" % (value,))


def _count_of(type_id: int, value: Any) -> int:
    if type_id == ASCII:
        if isinstance(value, str):
            return len(value.encode("utf-8")) + 1
        return len(value)
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


def entry_from_value(tag: int, value: Any, type_id: int) -> Entry:
    count = _count_of(type_id, value)
    return Entry(tag, type_id, count, value, None, True)


def _as_int(v: Any) -> int:
    if isinstance(v, (list, tuple)):
        return int(v[0]) if v else 0
    if isinstance(v, (bytes, bytearray)):
        return int.from_bytes(v, "little")
    return int(v or 0)


def decode_value(raw: bytes, type_id: int, count: int, endian: str) -> Any:
    size = TYPE_SIZES.get(type_id, 1)
    if type_id == ASCII:
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    if type_id in (BYTE, UNDEFINED):
        return raw
    if type_id == SBYTE:
        return struct.unpack(endian + "%db" % count, raw[:count])
    fmt = {SHORT: "H", LONG: "I", SSHORT: "h", SLONG: "i", FLOAT: "f", DOUBLE: "d"}.get(type_id)
    if fmt:
        vals = struct.unpack(endian + "%d%s" % (count, fmt), raw[:size * count])
        return vals[0] if count == 1 else vals
    if type_id in (RATIONAL, SRATIONAL):
        f = "I" if type_id == RATIONAL else "i"
        vals = struct.unpack(endian + "%d%s" % (2 * count, f), raw[:size * count])
        pairs = tuple((vals[i], vals[i + 1]) for i in range(0, len(vals), 2))
        return pairs[0] if count == 1 else pairs
    if type_id == IFD:
        vals = struct.unpack(endian + "%dI" % count, raw[:4 * count])
        return vals[0] if count == 1 else vals
    return raw


def encode_value(value: Any, type_id: int, count: int, endian: str) -> bytes:
    if type_id == ASCII:
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
        else:
            data = str(value).encode("utf-8")
        if not data.endswith(b"\0"):
            data += b"\0"
        return data
    if type_id in (BYTE, UNDEFINED):
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
        elif isinstance(value, str):
            data = value.encode("utf-8")
        elif isinstance(value, (list, tuple)):
            data = bytes(int(x) & 0xFF for x in value)
        else:
            data = bytes([int(value) & 0xFF])
        return data
    if type_id == SBYTE:
        vals = value if isinstance(value, (list, tuple)) else (value,)
        return struct.pack(endian + "%db" % len(vals), *[int(v) for v in vals])
    fmt = {SHORT: "H", LONG: "I", SSHORT: "h", SLONG: "i", FLOAT: "f", DOUBLE: "d"}.get(type_id)
    if fmt:
        vals = value if isinstance(value, (list, tuple)) else (value,)
        vals = [int(v) if fmt not in ("f", "d") else float(v) for v in vals]
        return struct.pack(endian + "%d%s" % (len(vals), fmt), *vals)
    if type_id in (RATIONAL, SRATIONAL):
        f = "I" if type_id == RATIONAL else "i"
        if isinstance(value, tuple) and len(value) == 2 and all(isinstance(x, int) for x in value):
            pairs = [value]
        elif isinstance(value, (list, tuple)):
            pairs = list(value)
        else:
            pairs = [(int(value), 1)]
        flat = [x for pair in pairs for x in (int(pair[0]), int(pair[1]))]
        return struct.pack(endian + "%d%s" % (len(flat), f), *flat)
    if type_id == IFD:
        vals = value if isinstance(value, (list, tuple)) else (value,)
        return struct.pack(endian + "%dI" % len(vals), *[int(v) for v in vals])
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise TypeError("cannot encode type %d" % type_id)
