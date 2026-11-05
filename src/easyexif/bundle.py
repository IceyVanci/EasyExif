"""Versioned JSON metadata bundles and restricted reconstruction.

The bundle deliberately carries metadata only: no pixel data, no blank
templates, and no EXIF-template (.exi) compatibility. Reconstruction is a
metadata overlay on an existing JPEG/TIFF; the pixel stream is never rewritten.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .jpeg import MPF_HEADER, PS_HEADER, Segment, Jpeg
from .metadata import Metadata, MetadataError
from .tiff import Tiff, TiffError
from .xmp import Xmp

SCHEMA = "easyexif.metadata/1"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_RAW_BYTES = 48 * 1024 * 1024


class BundleError(ValueError):
    pass


def _b64(data: bytes | bytearray | None) -> str | None:
    if data is None:
        return None
    return base64.b64encode(bytes(data)).decode("ascii")


def _unb64(text: str | None, label: str = "data") -> bytes | None:
    if not text:
        return None
    try:
        data = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise BundleError("%s 不是有效的 base64 数据" % label) from exc
    if len(data) > MAX_RAW_BYTES:
        raise BundleError("%s 超过大小限制" % label)
    return data


def _digest(bundle: dict[str, Any]) -> str:
    raw = json.dumps(bundle, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _source_dimensions(meta: Metadata) -> tuple[int | None, int | None]:
    w, h = meta.info.width, meta.info.height
    if (not w or not h) and meta.tiff is not None:
        w = meta.tiff.get("IFD0", 0x0100) or meta.tiff.get("EXIF", 0xA002)
        h = meta.tiff.get("IFD0", 0x0101) or meta.tiff.get("EXIF", 0xA003)
        if isinstance(w, (list, tuple)):
            w = w[0] if w else None
        if isinstance(h, (list, tuple)):
            h = h[0] if h else None
    return (int(w) if isinstance(w, int) else None,
            int(h) if isinstance(h, int) else None)


def _iptc_payload(jpeg: Jpeg | None) -> bytes | None:
    if jpeg is None:
        return None
    for seg in jpeg.segments:
        if seg.marker == 0xED and seg.data.startswith(PS_HEADER):
            return bytes(seg.data)
    return None


def _set_iptc(jpeg: Jpeg, payload: bytes | None) -> None:
    jpeg.segments = [
        s for s in jpeg.segments
        if not (s.marker == 0xED and s.data.startswith(PS_HEADER))
    ]
    if payload:
        idx = next((i for i, s in enumerate(jpeg.segments)
                    if s.marker in (0xDB, 0xC0, 0xC4, 0xDA)), len(jpeg.segments))
        jpeg.segments.insert(idx, Segment(0xED, payload, 0, idx))
    jpeg._reindex()


def _remove_mpf(jpeg: Jpeg) -> None:
    jpeg.segments = [
        s for s in jpeg.segments
        if not (s.marker == 0xE2 and s.data.startswith(MPF_HEADER))
    ]
    jpeg._reindex()


def export_bundle(meta: Metadata) -> dict[str, Any]:
    """Export a metadata-only bundle from a real JPEG/TIFF file."""
    if meta.tiff is None:
        raise BundleError("文件中没有 EXIF/TIFF 数据，无法导出元数据包")
    width, height = _source_dimensions(meta)
    file_bytes = meta.path.read_bytes() if meta.path.exists() else b""
    rows = []
    for row in meta.rows(include_makernote=False):
        if row["ifd"] == "XMP":
            continue
        rows.append({
            "ifd": row["ifd"],
            "name": row["name"],
            "tag": ("0x%04X" % row["tag"]) if isinstance(row["tag"], int) else row["tag"],
            "value": row.get("display"),
            "type": row.get("type"),
        })
        if len(rows) >= 500:
            break
    return {
        "schema": SCHEMA,
        "generator": {"name": "EasyExif", "version": __version__},
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "file": meta.path.name,
            "sha256": hashlib.sha256(file_bytes).hexdigest() if file_bytes else None,
            "format": meta.info.format,
            "width": width,
            "height": height,
            "make": meta.get_text("IFD0.Make", ""),
            "model": meta.get_text("IFD0.Model", ""),
            "lens": meta.get_text("EXIF.LensModel", ""),
        },
        "exif": {
            "raw_tiff": _b64(meta.tiff.to_bytes()),
            "tags": rows,
        },
        "xmp": {"raw": _b64(meta.xmp.to_bytes()) if meta.xmp.exists else None},
        "iptc": {"raw": _b64(_iptc_payload(meta.jpeg))},
        "thumbnail": _b64(meta.tiff.thumbnail),
        "mpf": meta.jpeg.mpf() if meta.jpeg is not None else None,
    }


def write_bundle(meta: Metadata, path: str | os.PathLike) -> dict[str, Any]:
    data = export_bundle(meta)
    target = Path(path)
    if target.suffix.lower() != ".json":
        raise BundleError("元数据包必须使用 .json 后缀")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_bundle(path: str | os.PathLike) -> dict[str, Any]:
    target = Path(path)
    if target.suffix.lower() == ".exi":
        raise BundleError("不支持 .exi 模板；请使用 EasyExif 导出的 JSON 元数据包")
    if target.suffix.lower() != ".json":
        raise BundleError("只接受 EasyExif 导出的 .json 元数据包")
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise BundleError("无法读取元数据包: %s" % exc) from exc
    if len(data) > MAX_BUNDLE_BYTES:
        raise BundleError("元数据包超过 64 MB 限制")
    try:
        bundle = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise BundleError("元数据包不是有效的 JSON: %s" % exc) from exc
    if not isinstance(bundle, dict):
        raise BundleError("元数据包必须是 JSON 对象")
    if bundle.get("schema") != SCHEMA:
        raise BundleError("不支持的元数据包版本: %r" % bundle.get("schema"))
    source = bundle.get("source")
    if not isinstance(source, dict) or not source.get("sha256"):
        raise BundleError("元数据包缺少来源信息；不接受空白模板")
    exif = bundle.get("exif")
    if not isinstance(exif, dict) or not exif.get("raw_tiff"):
        raise BundleError("元数据包缺少 EXIF 原始数据；不接受空白模板")
    raw_tiff = _unb64(exif.get("raw_tiff"), "EXIF 原始数据")
    if raw_tiff is None or raw_tiff[:2] not in (b"II", b"MM"):
        raise BundleError("元数据包中的 EXIF 数据无效")
    return bundle


def inspect_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    source = bundle.get("source") or {}
    return {
        "schema": bundle.get("schema"),
        "source": {
            "file": source.get("file"),
            "format": source.get("format"),
            "width": source.get("width"),
            "height": source.get("height"),
            "make": source.get("make"),
            "model": source.get("model"),
            "lens": source.get("lens"),
        },
        "digest": _digest(bundle),
        "marker": "EasyExif %s" % __version__,
    }


def _regenerate_thumbnail(meta: Metadata) -> None:
    if meta.tiff is None:
        return
    try:
        from PIL import Image
        import io
        with Image.open(meta.path) as im:
            im = im.convert("RGB")
            im.thumbnail((320, 320))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
        meta.set_thumbnail(buf.getvalue())
    except Exception:
        meta.tiff.thumbnail = None


def _apply_marker(meta: Metadata, digest: str) -> dict[str, str]:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    tool = "EasyExif %s" % __version__
    meta.set("IFD0.Software", tool)
    if not meta.xmp.exists:
        meta.xmp = Xmp()
    meta.xmp.set("xmp:CreatorTool", tool)
    meta.xmp.set("xmp:MetadataDate", now)
    previous = meta.xmp.get("photoshop:History")
    line = "%s %s metadata-overlay sha256=%s" % (now, tool, digest)
    meta.xmp.set("photoshop:History", (str(previous) + "\n" + line) if previous else line)
    meta.xmp.set("easyexif:Operation", "metadata-overlay")
    meta.xmp.set("easyexif:ReconstructedAt", now)
    meta.xmp.set("easyexif:SourcePackageSHA256", digest)
    return {"software": tool, "creator_tool": tool, "time": now, "digest": digest}


def _maker(meta: Metadata) -> tuple[str, str]:
    return (meta.get_text("IFD0.Make", "").strip().lower(),
            meta.get_text("IFD0.Model", "").strip().lower())


def import_bundle(target: Metadata, bundle: dict[str, Any],
                  out: str | os.PathLike | None = None,
                  mode: str = "replace") -> dict[str, Any]:
    """Overlay a bundle on an existing JPEG/TIFF without touching pixels."""
    if getattr(target, "readonly", False):
        raise BundleError("RAW 文件当前为只读模式，不能覆盖元数据")
    if target.tiff is None:
        raise BundleError("目标文件没有 EXIF/TIFF 数据")
    if mode not in ("replace", "fill"):
        raise BundleError("mode 必须是 replace 或 fill")
    source = bundle.get("source") or {}
    if str(source.get("format", "")).upper() != str(target.info.format).upper():
        raise BundleError("目标格式与元数据包来源格式不一致")
    sw, sh = source.get("width"), source.get("height")
    tw, th = _source_dimensions(target)
    if sw and sh and tw and th and (int(sw), int(sh)) != (int(tw), int(th)):
        raise BundleError("目标图像尺寸与元数据包来源不一致，拒绝覆盖")
    raw = _unb64((bundle.get("exif") or {}).get("raw_tiff"), "EXIF 原始数据")
    try:
        donor = Tiff.parse(raw or b"")
    except TiffError as exc:
        raise BundleError("无法解析元数据包中的 EXIF: %s" % exc) from exc
    target_make, target_model = _maker(target)
    donor_make = donor.text("IFD0", 0x010F, "").strip().lower()
    donor_model = donor.text("IFD0", 0x0110, "").strip().lower()
    dropped_makernote = False
    if mode == "replace":
        target.tiff = donor
    else:
        for row in donor.describe():
            if row["ifd"] == "MakerNote":
                continue
            if target.tiff.get(row["ifd"], row["tag"]) is None:
                target.tiff.set(row["ifd"], row["tag"], row["value"], row["type_id"])
    if target.tiff.get("EXIF", 0x927C) is not None and (
            donor_make != target_make or donor_model != target_model):
        target.tiff.delete("EXIF", 0x927C)
        target.tiff.makernote = None
        dropped_makernote = True
    xmp_raw = _unb64((bundle.get("xmp") or {}).get("raw"), "XMP 数据")
    if xmp_raw is not None:
        target.xmp = Xmp(xmp_raw)
    elif mode == "replace":
        target.xmp = Xmp()
    if target.jpeg is not None:
        iptc = _unb64((bundle.get("iptc") or {}).get("raw"), "IPTC 数据")
        _set_iptc(target.jpeg, iptc if mode == "replace" else _iptc_payload(target.jpeg))
        _remove_mpf(target.jpeg)
    _regenerate_thumbnail(target)
    marker = _apply_marker(target, _digest(bundle))
    target_path = Path(out) if out else target.path.with_name(
        target.path.stem + ".reconstructed" + target.path.suffix)
    if target_path.resolve() == target.path.resolve():
        raise BundleError("重建必须另存为新文件，不能覆盖目标文件")
    target.save(target_path)
    return {
        "ok": True,
        "output": str(target_path),
        "dropped_makernote": dropped_makernote,
        "marker": marker,
        "source": inspect_bundle(bundle)["source"],
    }
