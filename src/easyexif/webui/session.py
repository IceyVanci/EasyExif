"""Web UI backend: document session, snapshots and operations."""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..jpeg import Jpeg
from ..metadata import Metadata, MetadataError
from ..tiff import Tiff
from ..tags import display_name, display_value
from ..xmp import Xmp
from ..validate import validate as run_validate


def jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass
class Snapshot:
    jpeg: bytes | None
    tiff: bytes | None
    xmp: bytes | None
    path: str | None


@dataclass
class DocState:
    """One open image: its metadata, history and preview cache."""
    meta: Metadata
    undo: list[Snapshot] = field(default_factory=list)
    redo: list[Snapshot] = field(default_factory=list)
    dirty: bool = False
    clean_depth: int = 0
    preview_cache: tuple[tuple[float, int], bytes] | None = None


def _path_key(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class Session:
    """Two image slots that can be switched without reloading metadata."""

    MAX_DOCS = 2

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else Path(os.environ.get("LOCALAPPDATA", ".")) / "EasyExif"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._docs: list[DocState] = []
        self._active = 0

    # -- active document ---------------------------------------------------
    @property
    def _doc(self) -> DocState | None:
        return self._docs[self._active] if self._docs else None

    @property
    def meta(self) -> Metadata | None:
        doc = self._doc
        return doc.meta if doc else None

    @property
    def undo(self) -> list[Snapshot]:
        doc = self._doc
        return doc.undo if doc else []

    @property
    def redo(self) -> list[Snapshot]:
        doc = self._doc
        return doc.redo if doc else []

    @property
    def dirty(self) -> bool:
        doc = self._doc
        return bool(doc and doc.dirty)

    @dirty.setter
    def dirty(self, value: bool) -> None:
        doc = self._doc
        if doc:
            doc.dirty = bool(value)

    @property
    def clean_depth(self) -> int:
        doc = self._doc
        return doc.clean_depth if doc else 0

    @clean_depth.setter
    def clean_depth(self, value: int) -> None:
        doc = self._doc
        if doc:
            doc.clean_depth = int(value)

    @property
    def _preview_cache(self):
        doc = self._doc
        return doc.preview_cache if doc else None

    @_preview_cache.setter
    def _preview_cache(self, value) -> None:
        doc = self._doc
        if doc:
            doc.preview_cache = value

    # -- document slots ----------------------------------------------------
    def open(self, path: str | os.PathLike, slot: int | None = None) -> dict:
        target = Path(path)
        key = _path_key(target)
        for index, doc in enumerate(self._docs):
            if _path_key(doc.meta.path) == key:
                self._active = index
                return self.doc()
        if slot is None:
            slot = len(self._docs) if len(self._docs) < self.MAX_DOCS else self._active
        slot = int(slot)
        if slot < 0 or slot >= self.MAX_DOCS:
            raise ValueError("图像槽位必须是 0 或 1")
        if slot > len(self._docs):
            slot = len(self._docs)
        state = DocState(Metadata.read(target))
        if slot == len(self._docs):
            self._docs.append(state)
        else:
            self._docs[slot] = state
        self._active = slot
        return self.doc()

    def activate(self, index: int) -> dict:
        if not self._docs:
            raise ValueError("没有打开文件")
        index = int(index)
        if index < 0 or index >= len(self._docs):
            raise ValueError("图像编号不存在")
        self._active = index
        return self.doc()

    def close(self, index: int | None = None) -> dict:
        if not self._docs:
            self._active = 0
            return self.doc()
        index = self._active if index is None else int(index)
        if index < 0 or index >= len(self._docs):
            raise ValueError("图像编号不存在")
        self._docs.pop(index)
        if not self._docs:
            self._active = 0
        elif index < self._active:
            self._active -= 1
        elif self._active >= len(self._docs):
            self._active = len(self._docs) - 1
        return self.doc()

    def capture(self) -> Snapshot:
        assert self.meta is not None
        jpeg = self.meta.jpeg.to_bytes() if self.meta.jpeg else None
        tiff = None
        if self.meta.tiff is not None:
            try:
                tiff = self.meta.tiff.to_bytes()
            except Exception:
                tiff = None
        xmp = self.meta.xmp.to_bytes() if self.meta.xmp.exists else None
        return Snapshot(jpeg, tiff, xmp, str(self.meta.path))

    def restore(self, snap: Snapshot) -> None:
        assert self.meta is not None
        self.meta.jpeg = Jpeg.parse(snap.jpeg) if snap.jpeg else None
        self.meta.tiff = Tiff.parse(snap.tiff) if snap.tiff else None
        self.meta.xmp = Xmp(snap.xmp) if snap.xmp else Xmp()
        if self.meta.jpeg:
            dims = self.meta.jpeg.dimensions()
            if dims:
                self.meta.info.width, self.meta.info.height = dims
            self.meta.info.format = "JPEG"
        elif self.meta.tiff:
            w, h = self.meta.tiff.get("IFD0", 0x0100), self.meta.tiff.get("IFD0", 0x0101)
            if isinstance(w, int) and isinstance(h, int):
                self.meta.info.width, self.meta.info.height = w, h
            self.meta.info.format = "TIFF"
        self._preview_cache = None

    def _push(self) -> None:
        snap = self.capture()
        self.undo.append(snap)
        if len(self.undo) > 80:
            self.undo.pop(0)
        self.redo.clear()

    def undo_last(self) -> dict:
        if not self.meta or not self.undo:
            raise ValueError("没有可撤销的操作")
        current = self.capture()
        snap = self.undo.pop()
        self.redo.append(current)
        self.restore(snap)
        self.dirty = len(self.undo) != self.clean_depth
        return self.doc()

    def redo_last(self) -> dict:
        if not self.meta or not self.redo:
            raise ValueError("没有可重做的操作")
        current = self.capture()
        snap = self.redo.pop()
        self.undo.append(current)
        self.restore(snap)
        self.dirty = len(self.undo) != self.clean_depth
        return self.doc()

    def edit(self, ops: list[dict]) -> dict:
        if not self.meta:
            raise ValueError("没有打开文件")
        if not ops:
            return self.doc()
        before = self.capture()
        try:
            for op in ops:
                self._apply(op)
        except Exception:
            self.restore(before)
            raise
        self.undo.append(before)
        if len(self.undo) > 80:
            self.undo.pop(0)
        if self.redo:
            self.clean_depth = -1
        self.redo.clear()
        self.dirty = True
        return self.doc()

    def _apply(self, op: dict) -> None:
        assert self.meta is not None
        kind = op.get("op")
        if kind == "set":
            self.meta.set(str(op["name"]), op.get("value", ""))
        elif kind == "delete":
            self.meta.delete(str(op["name"]))
        elif kind == "set_gps":
            self.meta.set_gps(float(op["lat"]), float(op["lon"]),
                              float(op["alt"]) if op.get("alt") not in (None, "") else None,
                              datum=str(op.get("datum", "wgs84")))
        elif kind == "clear_gps":
            self.meta.clear_gps()
        elif kind == "set_xmp":
            text = str(op.get("text", ""))
            self.meta.xmp = Xmp(text)
        elif kind == "sync_datetime":
            self.meta.sync_datetime()
        elif kind == "shift_time":
            from datetime import timedelta
            self.meta.shift_time(timedelta(seconds=float(op.get("seconds", 0))))
        elif kind == "remove_segment":
            if not self.meta.jpeg:
                raise ValueError("不是 JPEG 文件")
            index = int(op["index"])
            seg = self.meta.jpeg.get_segment(index)
            if seg is None:
                raise ValueError("段不存在")
            self.meta.jpeg.remove_index(self.meta.jpeg.segments.index(seg))
        elif kind == "add_comment":
            if not self.meta.jpeg:
                raise ValueError("不是 JPEG 文件")
            self.meta.jpeg.insert(0xFE, str(op.get("text", "")).encode("utf-8"))
        elif kind == "clear_metadata":
            if not self.meta.jpeg:
                raise ValueError("仅支持 JPEG")
            self.meta.clear_metadata()
        else:
            raise ValueError("未知操作: %s" % kind)

    # -- save -------------------------------------------------------------
    def current_bytes(self) -> bytes:
        if not self.meta:
            raise ValueError("没有打开文件")
        if self.meta.jpeg is not None:
            j = Jpeg.parse(self.meta.jpeg.to_bytes())
            if self.meta.tiff is not None:
                j.set_exif_payload(self.meta.tiff.to_bytes())
            if self.meta.xmp.exists:
                j.set_xmp_packet(self.meta.xmp.to_bytes())
            else:
                j.set_xmp_packet(None)
            return j.to_bytes()
        if self.meta.tiff is not None:
            t = Tiff.parse(self.meta.tiff.to_bytes())
            if self.meta.xmp.exists:
                t.set("IFD0", 0x02BC, self.meta.xmp.to_bytes(), 1)
            return t.to_bytes()
        raise ValueError("没有可保存的数据")

    def save(self, path: str | None = None) -> dict:
        if not self.meta:
            raise ValueError("没有打开文件")
        target = Path(path) if path else self.meta.path
        data = self.current_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        if path:
            self.meta.path = target
        self.dirty = False
        self.clean_depth = len(self.undo)
        self._preview_cache = None
        return self.doc()

    # -- views ------------------------------------------------------------
    def doc(self) -> dict:
        if not self.meta:
            return {"open": False, "docs": [], "active_index": -1,
                    "max_docs": self.MAX_DOCS}
        meta = self.meta
        rows = []
        for row in meta.rows():
            rows.append({
                "ifd": row["ifd"],
                "tag": row["tag"] if isinstance(row["tag"], int) else str(row["tag"]),
                "name": row["name"],
                "label": (row["name"] if row["ifd"] in ("MakerNote", "XMP")
                          else display_name(row["ifd"], row["tag"])),
                "type": row["type"],
                "type_id": row.get("type_id"),
                "count": row["count"],
                "bytes": row.get("bytes"),
                "value": display_value(row["display"]),
                "raw": jsonable(row["value"]),
                "technical": row.get("technical"),
                "readonly": bool(row.get("readonly")),
            })
        segments = []
        if meta.jpeg:
            for seg in meta.jpeg.segments:
                segments.append({"index": seg.index, "marker": "0x%02X" % seg.marker,
                                 "label": seg.label(), "size": len(seg.data)})
        summary = meta.summary()
        summary["file"] = str(meta.path)
        summary["size"] = meta.raw_size
        summary["dimensions"] = [meta.info.width, meta.info.height]
        documents = []
        for i, state in enumerate(self._docs):
            info = state.meta.info
            documents.append({
                "index": i,
                "name": state.meta.path.name,
                "path": str(state.meta.path),
                "dirty": state.dirty,
                "format": info.format,
                "width": info.width,
                "height": info.height,
                "active": i == self._active,
            })
        return {
            "open": True,
            "docs": documents,
            "active_index": self._active,
            "max_docs": self.MAX_DOCS,
            "path": str(meta.path),
            "name": meta.path.name,
            "format": meta.info.format,
            "dirty": self.dirty,
            "can_undo": bool(self.undo),
            "can_redo": bool(self.redo),
            "summary": summary,
            "rows": rows,
            "xmp": {"text": meta.xmp.text if meta.xmp.exists else "",
                    "props": jsonable(meta.xmp.to_dict())},
            "segments": segments,
            "gps": jsonable(meta.gps()),
            "warnings": meta.warnings,
        }

    def xmp_text(self) -> str:
        return self.meta.xmp.text if self.meta else ""

    def set_xmp_text(self, text: str) -> dict:
        if not self.meta:
            raise ValueError("没有打开文件")
        before = self.capture()
        self.meta.xmp = Xmp(text)
        self.undo.append(before)
        self.redo.clear()
        self.dirty = True
        return self.doc()

    def segment_hex(self, index: int) -> dict:
        if not self.meta or not self.meta.jpeg:
            raise ValueError("不是 JPEG 文件")
        seg = self.meta.jpeg.get_segment(index)
        if seg is None:
            raise ValueError("段不存在")
        data = seg.data
        lines = []
        for off in range(0, len(data), 16):
            chunk = data[off:off + 16]
            lines.append({"offset": off, "hex": " ".join("%02X" % b for b in chunk),
                          "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)})
        return {"index": index, "label": seg.label(), "size": len(data), "lines": lines}

    def preview(self, max_size: int = 1600, index: int | None = None) -> bytes:
        if index is None:
            state = self._doc
        else:
            state = self._docs[int(index)] if 0 <= int(index) < len(self._docs) else None
        if state is None:
            raise ValueError("没有打开文件")
        meta = state.meta
        key = (os.path.getmtime(meta.path), max_size)
        if state.preview_cache and state.preview_cache[0] == key:
            return state.preview_cache[1]
        from PIL import Image
        import io
        with Image.open(meta.path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_size, max_size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=86)
        data = buf.getvalue()
        state.preview_cache = (key, data)
        return data

    def thumbnail(self, path: str, size: int = 128) -> bytes:
        from PIL import Image
        import io
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
        return buf.getvalue()

    def validate(self) -> dict:
        if not self.meta:
            raise ValueError("没有打开文件")
        if not self.dirty:
            report = run_validate(self.meta.path)
            return report.to_dict()
        tmp = self.data_dir / ("validate-" + uuid.uuid4().hex + (self.meta.path.suffix or ".jpg"))
        tmp.write_bytes(self.current_bytes())
        try:
            report = run_validate(tmp)
            return report.to_dict()
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
