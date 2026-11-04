"""Batch scanning, CSV export, renaming and folder sorting."""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .metadata import Metadata, MetadataError, parse_exif_datetime
from .tags import format_value, tag_info

IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif", ".tif", ".tiff", ".exi", ".exif"}
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

IFD_KEYS = {"0": "IFD0", "1": "EXIF", "2": "GPS", "3": "Interop",
            "4": "MakerNote", "5": "File"}


@dataclass
class Column:
    ifd: str
    tag: Any
    label: str


@dataclass
class Profile:
    name: str = "custom"
    columns: list[Column] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        p = Path(path)
        name = p.stem
        columns: list[Column] = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line.upper().startswith("# NAME:"):
                    name = line.split(":", 1)[1].strip().strip("#").strip()
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 2:
                continue
            ifd = IFD_KEYS.get(parts[0], "IFD0")
            try:
                # the .xpt dialect always stores tag ids as hexadecimal
                tag: Any = int(parts[1], 16)
            except ValueError:
                tag = parts[1]
            columns.append(Column(ifd, tag, _column_label(ifd, tag)))
        return cls(name=name, columns=columns)

    def to_xpt(self, path: str | Path) -> Path:
        lines = ["# NAME:%s #" % self.name, "# MAKER:0, 0 #"]
        rev = {v: k for k, v in IFD_KEYS.items()}
        for col in self.columns:
            if isinstance(col.tag, int):
                lines.append("%s,%X" % (rev.get(col.ifd, "0"), col.tag))
        p = Path(path)
        p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return p


def _column_label(ifd: str, tag: Any) -> str:
    if ifd == "File":
        return {0: "FileName", 1: "FileSize", 4: "ImageWidth", 5: "ImageLength",
                6: "FileType", 9: "FileModifyDate"}.get(tag, "File_%s" % tag)
    if ifd == "MakerNote":
        return "MakerNote_0x%04X" % tag if isinstance(tag, int) else str(tag)
    if isinstance(tag, int):
        return tag_info(ifd, tag).name
    return str(tag)


BUILTIN_PROFILES = {
    "simple": Profile("简要信息", [
        Column("IFD0", 0x010F, "Make"), Column("IFD0", 0x0110, "Model"),
        Column("EXIF", 0x9003, "DateTimeOriginal"), Column("EXIF", 0x829A, "ExposureTime"),
        Column("EXIF", 0x829D, "FNumber"), Column("EXIF", 0x8827, "ISOSpeedRatings"),
        Column("EXIF", 0x920A, "FocalLength"), Column("EXIF", 0xA434, "LensModel"),
    ]),
    "detailed": Profile("详细信息", [
        Column("IFD0", 0x010F, "Make"), Column("IFD0", 0x0110, "Model"),
        Column("IFD0", 0x0131, "Software"), Column("IFD0", 0x0132, "DateTime"),
        Column("EXIF", 0x9003, "DateTimeOriginal"), Column("EXIF", 0x9004, "DateTimeDigitized"),
        Column("EXIF", 0x829A, "ExposureTime"), Column("EXIF", 0x829D, "FNumber"),
        Column("EXIF", 0x8827, "ISOSpeedRatings"), Column("EXIF", 0x9204, "ExposureBiasValue"),
        Column("EXIF", 0x9207, "MeteringMode"), Column("EXIF", 0x9209, "Flash"),
        Column("EXIF", 0x920A, "FocalLength"), Column("EXIF", 0xA405, "FocalLengthIn35mmFilm"),
        Column("EXIF", 0xA434, "LensModel"), Column("EXIF", 0xA431, "BodySerialNumber"),
        Column("EXIF", 0xA002, "PixelXDimension"), Column("EXIF", 0xA003, "PixelYDimension"),
    ]),
    "photography": Profile("摄影常用", [
        Column("IFD0", 0x010F, "Make"), Column("IFD0", 0x0110, "Model"),
        Column("EXIF", 0xA434, "LensModel"), Column("EXIF", 0x829A, "ExposureTime"),
        Column("EXIF", 0x829D, "FNumber"), Column("EXIF", 0x8827, "ISOSpeedRatings"),
        Column("EXIF", 0x9204, "ExposureBiasValue"), Column("EXIF", 0x920A, "FocalLength"),
        Column("EXIF", 0xA405, "FocalLengthIn35mmFilm"), Column("EXIF", 0x9003, "DateTimeOriginal"),
    ]),
    "gps": Profile("GPS 信息", [
        Column("IFD0", 0x010F, "Make"), Column("IFD0", 0x0110, "Model"),
        Column("GPS", 0x0001, "GPSLatitudeRef"), Column("GPS", 0x0002, "GPSLatitude"),
        Column("GPS", 0x0003, "GPSLongitudeRef"), Column("GPS", 0x0004, "GPSLongitude"),
        Column("GPS", 0x0005, "GPSAltitudeRef"), Column("GPS", 0x0006, "GPSAltitude"),
        Column("GPS", 0x001D, "GPSDateStamp"),
    ]),
    "file": Profile("文件属性", [
        Column("File", 0, "FileName"), Column("File", 1, "FileSize"),
        Column("File", 4, "ImageWidth"), Column("File", 5, "ImageLength"),
        Column("File", 6, "FileType"), Column("File", 9, "FileModifyDate"),
        Column("IFD0", 0x010F, "Make"), Column("IFD0", 0x0110, "Model"),
        Column("EXIF", 0x9003, "DateTimeOriginal"),
    ]),
}


def iter_images(root: str | Path, recursive: bool = True) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in IMAGE_EXTS else []
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in root.glob(pattern)
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def _value(meta: Metadata, col: Column) -> str:
    if col.ifd == "File":
        for key, value in (("FileName", meta.path.name), ("FileSize", meta.raw_size),
                           ("ImageWidth", meta.info.width), ("ImageLength", meta.info.height),
                           ("FileType", meta.info.format),
                           ("FileModifyDate", _mtime(meta))):
            if col.label == key:
                return "" if value is None else str(value)
        return ""
    if col.ifd == "MakerNote":
        if not meta.tiff or not meta.tiff.makernote:
            return ""
        for f in meta.tiff.makernote.fields:
            if f.tag == col.tag:
                return f.display()
        return ""
    if not isinstance(col.tag, int):
        return ""
    try:
        return meta.get_text("%s.%s" % (col.ifd, tag_info(col.ifd, col.tag).name), "")
    except (KeyError, MetadataError):
        return ""


def _mtime(meta: Metadata) -> str:
    try:
        from datetime import datetime
        return datetime.fromtimestamp(meta.path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def export_csv(files: Iterable[str | Path], out: str | Path,
               profile: Profile | None = None, encoding: str = "utf-8-sig") -> dict:
    profile = profile or BUILTIN_PROFILES["simple"]
    columns = [Column("File", 0, "FileName"), Column("File", 1, "FileSize"),
               Column("File", 4, "ImageWidth"), Column("File", 5, "ImageLength")]
    for col in profile.columns:
        if all(col.label != c.label for c in columns):
            columns.append(col)
    rows = []
    errors = []
    for path in files:
        try:
            meta = Metadata.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            errors.append({"file": str(path), "error": str(exc)})
            continue
        row = {"Path": str(path)}
        for col in columns:
            row[col.label] = _value(meta, col)
        rows.append(row)
    with open(out, "w", encoding=encoding, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Path"] + [c.label for c in columns])
        writer.writeheader()
        writer.writerows(rows)
    return {"out": str(out), "rows": len(rows), "errors": errors, "columns": [c.label for c in columns]}


def export_json(files: Iterable[str | Path], out: str | Path) -> dict:
    payload = []
    for path in files:
        try:
            payload.append(Metadata.read(path).summary())
        except (MetadataError, OSError, ValueError) as exc:
            payload.append({"file": str(path), "error": str(exc)})
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    return {"out": str(out), "rows": len(payload)}


TOKEN_RE = re.compile(r"\{([a-zA-Z_]+)(?::(\d+)d)?\}")


def render_name(pattern: str, meta: Metadata, sequence: int = 1) -> str:
    try:
        captured = parse_exif_datetime(meta.get_text("DateTimeOriginal", ""))
    except MetadataError:
        captured = None
    values = {
        "name": meta.path.stem, "ext": meta.path.suffix.lstrip("."),
        "camera": meta.get_text("Make", "Unknown"), "model": meta.get_text("Model", "Unknown"),
        "lens": meta.get_text("LensModel", "Unknown"),
        "iso": meta.get_text("ISOSpeedRatings", "0"),
        "shutter": meta.get_text("ExposureTime", "0").replace("/", "-").replace(" ", ""),
        "aperture": meta.get_text("FNumber", "0").replace("/", "-"),
        "focal": meta.get_text("FocalLength", "0").replace(" ", ""),
        "date": captured.strftime("%Y%m%d") if captured else "00000000",
        "time": captured.strftime("%H%M%S") if captured else "000000",
        "year": captured.strftime("%Y") if captured else "0000",
        "month": captured.strftime("%m") if captured else "00",
        "day": captured.strftime("%d") if captured else "00",
        "seq": str(sequence), "counter": str(sequence),
    }

    def repl(m: re.Match) -> str:
        key = m.group(1).lower()
        pad = m.group(2)
        val = values.get(key)
        if val is None:
            return m.group(0)
        if pad and key in ("seq", "counter"):
            return val.zfill(int(pad))
        return val

    name = TOKEN_RE.sub(repl, pattern)
    name = INVALID_CHARS.sub("_", name).strip(" .")
    if not name:
        name = meta.path.stem
    if "." not in name and meta.path.suffix:
        name += meta.path.suffix
    return name


def rename(files: Iterable[str | Path], pattern: str, dry_run: bool = True,
           start: int = 1) -> list[dict]:
    plan = []
    for i, path in enumerate(files, start=start):
        path = Path(path)
        try:
            meta = Metadata.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            plan.append({"src": str(path), "dst": None, "error": str(exc)})
            continue
        new_name = render_name(pattern, meta, i)
        dst = path.with_name(new_name)
        if dst.exists() and dst != path:
            n = 1
            while dst.with_name("%s_%d%s" % (dst.stem, n, dst.suffix)).exists():
                n += 1
            dst = dst.with_name("%s_%d%s" % (dst.stem, n, dst.suffix))
        plan.append({"src": str(path), "dst": str(dst)})
        if not dry_run and dst != path:
            path.rename(dst)
    return plan


def sort_into(files: Iterable[str | Path], root: str | Path, by: str = "date",
              dry_run: bool = True, move: bool = False) -> list[dict]:
    root = Path(root)
    plan = []
    for path in files:
        path = Path(path)
        try:
            meta = Metadata.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            plan.append({"src": str(path), "dst": None, "error": str(exc)})
            continue
        if by == "date":
            try:
                dt = parse_exif_datetime(meta.get_text("DateTimeOriginal", ""))
                sub = Path("%04d" % dt.year) / ("%02d" % dt.month)
            except MetadataError:
                sub = Path("unknown-date")
        elif by in ("camera", "model"):
            make = _safe(meta.get_text("Make", "Unknown"))
            model = _safe(meta.get_text("Model", "Unknown"))
            sub = Path(make) / model
        elif by == "lens":
            sub = Path(_safe(meta.get_text("LensModel", "Unknown")))
        elif by == "month":
            try:
                dt = parse_exif_datetime(meta.get_text("DateTimeOriginal", ""))
                sub = Path(dt.strftime("%Y-%m"))
            except MetadataError:
                sub = Path("unknown-date")
        else:
            raise ValueError("unknown sort mode %r" % by)
        dst = root / sub / path.name
        n = 1
        while dst.exists() and dst != path:
            dst = root / sub / ("%s_%d%s" % (path.stem, n, path.suffix))
            n += 1
        plan.append({"src": str(path), "dst": str(dst)})
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(path), str(dst))
            else:
                shutil.copy2(path, dst)
    return plan


def apply_template(files: Iterable[str | Path], template, dry_run: bool = True) -> list[dict]:
    results = []
    for path in files:
        path = Path(path)
        try:
            meta = Metadata.read(path)
            count = template.apply(meta)
        except (MetadataError, OSError, ValueError) as exc:
            results.append({"file": str(path), "error": str(exc)})
            continue
        if not dry_run and count:
            meta.save()
        results.append({"file": str(path), "changes": count})
    return results


def _safe(text: str) -> str:
    text = INVALID_CHARS.sub("_", text or "Unknown").strip(" .")
    return text or "Unknown"
