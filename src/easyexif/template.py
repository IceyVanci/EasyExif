"""Metadata templates and text stamps.

A template is a small JSON document. Text stamps use a compact placeholder
dialect, for example:

    [[EXIF.DateTimeOriginal {YYYY-MM-DD HH:MM:SS}]]
    [[IFD0.Model {'Unknown Model'}]], [[EXIF.LensModel {'Unknown Lens'}]]

The second value after a comma is the fallback used when the tag is missing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .metadata import Metadata, MetadataError, parse_exif_datetime
from .tags import resolve_name

PLACEHOLDER = re.compile(r"\[\[([^\]]+?)\]\]", re.S)
DATE_TOKENS = ("YYYY", "YY", "MM", "DD", "HH", "SS")

# Offsets and pointers must never be copied from one file to another.
STRUCTURAL_TAGS = {
    "ExifIFDPointer", "GPSInfoIFDPointer", "InteroperabilityIFDPointer",
    "JPEGInterchangeFormat", "JPEGInterchangeFormatLength", "MakerNote",
    "SubIFDs", "StripOffsets", "StripByteCounts",
}


@dataclass
class Template:
    name: str = "untitled"
    description: str = ""
    exif: dict[str, Any] = field(default_factory=dict)
    xmp: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Template":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(name=data.get("name", Path(path).stem),
                   description=data.get("description", ""),
                   exif=data.get("exif", {}),
                   xmp=data.get("xmp", {}),
                   options=data.get("options", {}))

    @classmethod
    def from_file(cls, path: str | Path, tags: list[str] | None = None) -> "Template":
        meta = Metadata.read(path)
        exif = {}
        xmp = {}
        for row in meta.rows():
            name = row["name"]
            if row["ifd"] == "IFD1" or name in STRUCTURAL_TAGS:
                continue
            if tags and name not in tags:
                continue
            value = row["value"]
            if isinstance(value, (bytes, bytearray)):
                continue
            key = "%s.%s" % (row["ifd"], name) if row["ifd"] not in ("XMP", "MakerNote") else name
            if row["ifd"] == "XMP":
                xmp[name] = value
            elif row["ifd"] != "MakerNote" and name != "MakerNote":
                exif[key] = value
        return cls(name=Path(path).stem, exif=exif, xmp=xmp)

    def save(self, path: str | Path) -> Path:
        data = {"name": self.name, "description": self.description,
                "exif": self.exif, "xmp": self.xmp, "options": self.options}
        p = Path(path)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def apply(self, meta: Metadata, overwrite: bool = True) -> int:
        count = 0
        for name, value in self.exif.items():
            try:
                _, tag = resolve_name(name)
                if tag in (0x8769, 0x8825, 0xA005, 0x0201, 0x0202, 0x927C, 0x014A):
                    continue
            except Exception:
                pass
            if not overwrite and meta.get_text(name, "") not in ("", "0"):
                continue
            try:
                meta.set(name, value)
                count += 1
            except (MetadataError, KeyError, ValueError):
                continue
        for name, value in self.xmp.items():
            if not overwrite and meta.xmp.get(name) is not None:
                continue
            meta.xmp.set(name, value)
            count += 1
        if self.options.get("clear_gps"):
            meta.clear_gps()
        if self.options.get("sync_datetime"):
            meta.sync_datetime()
        if self.options.get("software"):
            meta.set("Software", self.options["software"])
        return count

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "exif": self.exif, "xmp": self.xmp, "options": self.options}


def builtin_templates() -> dict[str, Template]:
    return {
        "clean-gps": Template(
            name="clean-gps",
            description="移除 GPS 与位置相关 XMP 字段",
            exif={"IFD0.Software": "EasyExif"},
            options={"clear_gps": True},
        ),
        "copyright": Template(
            name="copyright",
            description="写入作者与版权信息",
            exif={"IFD0.Artist": "Your Name", "IFD0.Copyright": "© Your Name"},
            xmp={"dc:creator": ["Your Name"], "dc:rights": "© Your Name"},
        ),
        "camera-defaults": Template(
            name="camera-defaults",
            description="统一相机型号与镜头描述（用于多机位素材）",
            exif={"IFD0.Make": "Canon", "IFD0.Model": "Canon EOS R5",
                  "EXIF.LensModel": "RF24-70mm F2.8 L IS USM"},
            options={"sync_datetime": True},
        ),
        "stock-metadata": Template(
            name="stock-metadata",
            description="图库常用字段：标题、关键词、说明",
            xmp={"dc:title": ["Title"], "dc:description": ["Description"],
                 "dc:subject": ["keyword1", "keyword2"]},
        ),
    }


def render_stamp(text: str, meta: Metadata, sequence: int | None = None,
                 path: Path | None = None) -> str:
    def replace(match: re.Match) -> str:
        token = match.group(1).strip()
        path_part, _, spec = token.partition("{")
        spec = spec.rstrip("}").strip() if spec else ""
        name = path_part.strip().rstrip(",").strip()
        value = ""
        try:
            value = meta.get_text(name, "")
        except (KeyError, MetadataError):
            value = ""
        fmt, default = _split_spec(spec)
        if name.lower() in ("file.name", "filename", "name"):
            value = (path or meta.path).name
        elif name.lower() in ("file.stem", "stem"):
            value = (path or meta.path).stem
        elif name.lower() in ("file.ext", "ext"):
            value = (path or meta.path).suffix.lstrip(".")
        elif name.lower() in ("seq", "sequence"):
            value = "" if sequence is None else str(sequence)
        if not value:
            return _apply_date_format(default, meta, None)
        if fmt:
            try:
                dt = parse_exif_datetime(value)
                return _apply_date_format(fmt, meta, dt)
            except MetadataError:
                return value
        return value

    return PLACEHOLDER.sub(replace, text)


def _split_spec(spec: str) -> tuple[str, str]:
    if not spec:
        return "", ""
    if spec.startswith("{") and spec.endswith("}"):
        spec = spec[1:-1]
    # default after a comma; respect quotes
    parts: list[str] = []
    buf = []
    quote = None
    for ch in spec:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "," and not parts:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    first = parts[0].strip()
    default = parts[1].strip() if len(parts) > 1 else ""
    if len(parts) == 1 and first[:1] in ("'", '"') and first[-1:] == first[0]:
        # a single quoted literal is a fallback, not a date format
        return "", first[1:-1]
    fmt = first.strip("'\"")
    if default.startswith(("'", '"')) and default[-1:] == default[0]:
        default = default[1:-1]
    return fmt, default


def _apply_date_format(fmt: str, meta: Metadata, dt: datetime | None) -> str:
    if not fmt:
        return ""
    if dt is None:
        try:
            text = meta.get_text("DateTimeOriginal", "") or meta.get_text("DateTime", "")
            dt = parse_exif_datetime(text) if text else None
        except MetadataError:
            dt = None
    if dt is None:
        return fmt
    values = {
        "YYYY": "%04d" % dt.year, "YY": "%02d" % (dt.year % 100),
        "MM": "%02d" % dt.month, "DD": "%02d" % dt.day,
        "HH": "%02d" % dt.hour, "mm": "%02d" % dt.minute,
        "SS": "%02d" % dt.second,
    }
    return re.sub(r"YYYY|YY|MM|DD|HH|mm|SS", lambda m: values[m.group(0)], fmt)
