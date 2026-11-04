"""JPEG segment level reader / writer.

Keeps every segment byte-exact, including the entropy coded scan, so the
editor can add, replace or remove metadata without re-compressing pixels.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterable

SOI, EOI, SOS = 0xD8, 0xD9, 0xDA

MARKER_NAMES = {
    0xC0: "SOF0", 0xC1: "SOF1", 0xC2: "SOF2", 0xC3: "SOF3",
    0xC4: "DHT", 0xC5: "SOF5", 0xC6: "SOF6", 0xC7: "SOF7",
    0xC8: "JPG", 0xC9: "SOF9", 0xCA: "SOF10", 0xCB: "SOF11",
    0xCC: "DAC", 0xCD: "SOF13", 0xCE: "SOF14", 0xCF: "SOF15",
    0xD0: "RST0", 0xD1: "RST1", 0xD2: "RST2", 0xD3: "RST3",
    0xD4: "RST4", 0xD5: "RST5", 0xD6: "RST6", 0xD7: "RST7",
    0xD8: "SOI", 0xD9: "EOI", 0xDA: "SOS", 0xDB: "DQT", 0xDC: "DNL",
    0xDD: "DRI", 0xDE: "DHP", 0xDF: "EXP", 0xE0: "APP0", 0xE1: "APP1",
    0xE2: "APP2", 0xE3: "APP3", 0xE4: "APP4", 0xE5: "APP5", 0xE6: "APP6",
    0xE7: "APP7", 0xE8: "APP8", 0xE9: "APP9", 0xEA: "APP10", 0xEB: "APP11",
    0xEC: "APP12", 0xED: "APP13", 0xEE: "APP14", 0xEF: "APP15",
    0xFE: "COM",
}
EXIF_HEADER = b"Exif\0\0"
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\0"
XMP_EXT_HEADER = b"http://ns.adobe.com/xmp/extension/\0"
MPF_HEADER = b"MPF\0"
ICC_HEADER = b"ICC_PROFILE\0"
PS_HEADER = b"Photoshop 3.0\0"


@dataclass
class Segment:
    marker: int
    data: bytes
    offset: int = 0
    index: int = 0

    @property
    def name(self) -> str:
        return MARKER_NAMES.get(self.marker, "0x%02X" % self.marker)

    @property
    def is_app(self) -> bool:
        return 0xE0 <= self.marker <= 0xEF

    def label(self) -> str:
        if self.marker == 0xE1 and self.data.startswith(EXIF_HEADER):
            return "APP1 (Exif)"
        if self.marker == 0xE1 and self.data.startswith(XMP_HEADER):
            return "APP1 (XMP)"
        if self.marker == 0xE1 and self.data.startswith(XMP_EXT_HEADER):
            return "APP1 (XMP extended)"
        if self.marker == 0xE2 and self.data.startswith(MPF_HEADER):
            return "APP2 (MPF)"
        if self.marker == 0xE2 and self.data.startswith(ICC_HEADER):
            return "APP2 (ICC)"
        if self.marker == 0xE0 and self.data.startswith(b"JFIF\0"):
            return "APP0 (JFIF)"
        if self.marker == 0xE0 and self.data.startswith(b"JFXX\0"):
            return "APP0 (JFXX)"
        if self.marker == 0xED and self.data.startswith(PS_HEADER):
            return "APP13 (Photoshop/IPTC)"
        if self.marker == 0xEE and self.data.startswith(b"Adobe"):
            return "APP14 (Adobe)"
        if self.marker == 0xDB:
            return "DQT"
        if self.marker == 0xC4:
            return "DHT"
        if 0xC0 <= self.marker <= 0xCF and self.marker not in (0xC4, 0xC8, 0xCC):
            return "SOF%d" % (self.marker - 0xC0)
        return self.name


@dataclass
class Jpeg:
    segments: list[Segment] = field(default_factory=list)
    tail: bytes = b""
    warnings: list[str] = field(default_factory=list)
    trailing: bytes = b""

    # -- parsing -----------------------------------------------------------
    @classmethod
    def parse(cls, data: bytes, strict: bool = False) -> "Jpeg":
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            raise ValueError("not a JPEG file (missing SOI)")
        obj = cls()
        pos = 2
        idx = 0
        while pos < len(data):
            if data[pos] != 0xFF:
                obj.warnings.append("expected marker at 0x%X" % pos)
                break
            start = pos
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker == EOI:
                obj.tail = data[start:pos]
                obj.trailing = data[pos:]
                break
            if marker == SOS:
                obj.tail = data[start:]
                break
            if 0xD0 <= marker <= 0xD7:
                obj.segments.append(Segment(marker, b"", start, idx))
                idx += 1
                continue
            if pos + 2 > len(data):
                obj.warnings.append("truncated segment at 0x%X" % start)
                break
            length = struct.unpack_from(">H", data, pos)[0]
            if length < 2 or pos + length > len(data):
                obj.warnings.append("bad segment length at 0x%X" % start)
                break
            payload = data[pos + 2:pos + length]
            obj.segments.append(Segment(marker, payload, start, idx))
            idx += 1
            pos += length
        else:
            obj.warnings.append("file ended before SOS/EOI")
        return obj

    @classmethod
    def from_bytes(cls, data: bytes) -> "Jpeg":
        return cls.parse(data)

    def to_bytes(self) -> bytes:
        out = bytearray(b"\xff\xd8")
        for seg in self.segments:
            out += b"\xff" + bytes([seg.marker])
            if seg.marker in (SOI, EOI):
                continue
            out += struct.pack(">H", len(seg.data) + 2)
            out += seg.data
        out += self.tail if self.tail else b"\xff\xd9"
        return bytes(out)

    # -- segment helpers ---------------------------------------------------
    def _reindex(self) -> None:
        for i, s in enumerate(self.segments):
            s.index = i

    def find(self, marker: int) -> list[Segment]:
        return [s for s in self.segments if s.marker == marker]

    def exif_segment(self) -> Segment | None:
        for s in self.segments:
            if s.marker == 0xE1 and s.data.startswith(EXIF_HEADER):
                return s
        return None

    def xmp_segment(self) -> Segment | None:
        for s in self.segments:
            if s.marker == 0xE1 and s.data.startswith(XMP_HEADER):
                return s
        return None

    def exif_payload(self) -> bytes | None:
        seg = self.exif_segment()
        return seg.data[len(EXIF_HEADER):] if seg else None

    def set_exif_payload(self, tiff: bytes | None) -> None:
        seg = self.exif_segment()
        if tiff is None:
            if seg:
                self.segments.remove(seg)
                self._reindex()
            return
        payload = EXIF_HEADER + tiff
        if seg:
            seg.data = payload
        else:
            idx = 0
            for i, s in enumerate(self.segments):
                if s.marker == 0xE0 and s.data.startswith(b"JFIF\0"):
                    idx = i + 1
            self.segments.insert(idx, Segment(0xE1, payload, 0, idx))
            self._reindex()

    def xmp_packet(self) -> bytes | None:
        seg = self.xmp_segment()
        return seg.data[len(XMP_HEADER):] if seg else None

    def set_xmp_packet(self, packet: bytes | None) -> None:
        seg = self.xmp_segment()
        if packet is None:
            self._remove_where(lambda s: s.marker == 0xE1 and (
                s.data.startswith(XMP_HEADER) or s.data.startswith(XMP_EXT_HEADER)))
            return
        payload = XMP_HEADER + packet
        if seg:
            seg.data = payload
        else:
            idx = len(self.segments)
            exif = self.exif_segment()
            if exif:
                idx = self.segments.index(exif) + 1
            self.segments.insert(idx, Segment(0xE1, payload, 0, idx))
            self._reindex()

    def _remove_where(self, pred) -> int:
        before = len(self.segments)
        self.segments = [s for s in self.segments if not pred(s)]
        self._reindex()
        return before - len(self.segments)

    def remove_index(self, index: int) -> Segment:
        seg = self.segments.pop(index)
        self._reindex()
        return seg

    def insert(self, marker: int, data: bytes, index: int | None = None) -> Segment:
        seg = Segment(marker, data, 0, 0)
        if index is None:
            index = len(self.segments)
        self.segments.insert(index, seg)
        self._reindex()
        return seg

    def remove_metadata(self, keep: Iterable[str] = ()) -> int:
        keep = {k.lower() for k in keep}
        removed = 0
        for s in list(self.segments):
            label = s.label().lower()
            kind = label.split()[0]
            if (s.marker == 0xE1 and (s.data.startswith(EXIF_HEADER) or s.data.startswith(XMP_HEADER))
                    or s.marker == 0xED or s.marker == 0xFE
                    or (s.marker == 0xE2 and s.data.startswith(MPF_HEADER))):
                if kind in keep or label in keep:
                    continue
                self.segments.remove(s)
                removed += 1
        self._reindex()
        return removed

    # -- metadata views ----------------------------------------------------
    def icc_profile(self) -> bytes | None:
        chunks = []
        for s in self.segments:
            if s.marker == 0xE2 and s.data.startswith(ICC_HEADER):
                body = s.data[len(ICC_HEADER):]
                if len(body) >= 2:
                    chunks.append((body[0], body[1], body[2:]))
        if not chunks:
            return None
        chunks.sort()
        return b"".join(c[2] for c in chunks)

    def iptc(self) -> dict[str, str]:
        for s in self.segments:
            if s.marker == 0xED and s.data.startswith(PS_HEADER):
                return parse_photoshop_iptc(s.data[len(PS_HEADER):])
        return {}

    def mpf(self) -> dict | None:
        for s in self.segments:
            if s.marker == 0xE2 and s.data.startswith(MPF_HEADER):
                return parse_mpf(s.data[len(MPF_HEADER):])
        return None

    def dimensions(self) -> tuple[int, int] | None:
        for s in self.segments:
            if 0xC0 <= s.marker <= 0xCF and s.marker not in (0xC4, 0xC8, 0xCC):
                if len(s.data) >= 5:
                    h, w = struct.unpack_from(">HH", s.data, 1)
                    return w, h
        return None

    def sof(self) -> dict | None:
        for s in self.segments:
            if 0xC0 <= s.marker <= 0xCF and s.marker not in (0xC4, 0xC8, 0xCC):
                if len(s.data) < 6:
                    continue
                precision, h, w, comps = struct.unpack_from(">BHHB", s.data, 0)
                return {"marker": s.label(), "precision": precision, "width": w,
                        "height": h, "components": comps,
                        "sampling": list(s.data[6:6 + 3 * comps])}
        return None

    def quant_tables(self) -> list[list[int]]:
        tables = []
        for s in self.segments:
            if s.marker != 0xDB:
                continue
            i = 0
            data = s.data
            while i < len(data):
                pq, tq = data[i] >> 4, data[i] & 15
                i += 1
                n = 64 * (2 if pq else 1)
                if i + n > len(data):
                    break
                if pq:
                    vals = list(struct.unpack(">64H", data[i:i + 128]))
                else:
                    vals = list(data[i:i + 64])
                tables.append(vals)
                i += n
        return tables

    def summary(self) -> dict:
        dims = self.dimensions()
        return {
            "dimensions": dims,
            "segment_count": len(self.segments),
            "segments": [{"index": s.index, "marker": "0x%02X" % s.marker,
                          "name": s.label(), "size": len(s.data)} for s in self.segments],
            "exif": self.exif_segment() is not None,
            "xmp": self.xmp_segment() is not None,
            "icc": self.icc_profile() is not None,
            "iptc": self.iptc(),
            "mpf": self.mpf(),
            "has_thumbnail": bool(self.exif_payload()),
            "trailing_bytes": len(self.trailing),
            "warnings": self.warnings,
        }

    def get_segment(self, index: int) -> Segment | None:
        for s in self.segments:
            if s.index == index:
                return s
        return None


# ---------------------------------------------------------------------------
# APP13 / IPTC
# ---------------------------------------------------------------------------
IPTC_NAMES = {
    5: "ObjectName", 7: "EditStatus", 10: "Urgency", 15: "Category",
    20: "SupplementalCategories", 25: "Keywords", 30: "ReleaseDate",
    35: "ReleaseTime", 40: "SpecialInstructions", 55: "DateCreated",
    60: "TimeCreated", 65: "DigitalCreationDate", 70: "DigitalCreationTime",
    80: "By-line", 85: "By-lineTitle", 90: "City", 92: "Sub-location",
    95: "Province-State", 100: "CountryCode", 101: "CountryName",
    103: "OriginalTransmissionReference", 105: "Headline", 110: "Credit",
    115: "Source", 116: "CopyrightNotice", 118: "Contact",
    120: "Caption-Abstract", 122: "Writer-Editor",
}


def parse_photoshop_iptc(data: bytes) -> dict[str, str]:
    resources = []
    pos = 0
    while pos + 12 <= len(data) and data[pos:pos + 4] == b"8BIM":
        res_id = struct.unpack_from(">H", data, pos + 4)[0]
        name_len = data[pos + 6]
        name_end = pos + 7 + name_len
        if (name_len + 1) % 2:
            name_end += 1
        if name_end + 4 > len(data):
            break
        size = struct.unpack_from(">I", data, name_end)[0]
        body = data[name_end + 4:name_end + 4 + size]
        resources.append((res_id, body))
        pos = name_end + 4 + size + (size % 2)
    out: dict[str, str] = {}
    for res_id, body in resources:
        if res_id != 0x0404:
            continue
        i = 0
        while i + 5 <= len(body) and body[i] == 0x1C:
            record, dataset = body[i + 1], body[i + 2]
            length = struct.unpack_from(">H", body, i + 3)[0]
            i += 5
            if length & 0x8000:
                n = length & 0x7FFF
                if i + n > len(body):
                    break
                length = struct.unpack_from(">I", body, i)[0]
                i += n
            value = body[i:i + length]
            i += length
            if record == 2:
                name = IPTC_NAMES.get(dataset, "IPTC-2:%d" % dataset)
                text = value.decode("utf-8", "replace").rstrip("\0")
                out[name] = (out[name] + "; " + text) if name in out else text
    return out


# ---------------------------------------------------------------------------
# MPF
# ---------------------------------------------------------------------------
def parse_mpf(data: bytes) -> dict:
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        return {"error": "invalid MPF header"}
    endian = "<" if data[:2] == b"II" else ">"
    if struct.unpack_from(endian + "H", data, 2)[0] != 42:
        return {"error": "bad MPF magic"}
    ifd = struct.unpack_from(endian + "I", data, 4)[0]
    result: dict = {"version": None, "images": []}
    if ifd + 2 > len(data):
        return result
    count = struct.unpack_from(endian + "H", data, ifd)[0]
    for i in range(min(count, 100)):
        base = ifd + 2 + 12 * i
        if base + 12 > len(data):
            break
        tag, typ, cnt = struct.unpack_from(endian + "HHI", data, base)
        if typ == 7 and cnt <= 4:
            val = data[base + 8:base + 8 + cnt]
        else:
            off = struct.unpack_from(endian + "I", data, base + 8)[0]
            val = data[off:off + TYPE_SIZE.get(typ, 1) * cnt]
        if tag == 0xB000:
            result["version"] = val.rstrip(b"\0").decode("ascii", "replace")
        elif tag == 0xB001:
            result["declared_images"] = int.from_bytes(val[:4], "little" if endian == "<" else "big")
        elif tag == 0xB002:
            for j in range(0, min(len(val), 16 * 20), 16):
                chunk = val[j:j + 16]
                if len(chunk) < 16:
                    break
                attr = struct.unpack_from(endian + "I", chunk, 0)[0]
                size = struct.unpack_from(endian + "I", chunk, 4)[0]
                off = struct.unpack_from(endian + "I", chunk, 8)[0]
                result["images"].append({
                    "attribute": attr, "size": size, "offset": off,
                    "type": "primary" if attr & 0x20000000 else "dependent",
                })
    return result


TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
