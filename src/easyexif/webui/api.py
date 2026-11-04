"""JSON API used by the local web UI."""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import batch as batchmod
from ..batch import BUILTIN_PROFILES, Profile, export_csv, iter_images, rename, sort_into, apply_template
from ..metadata import MetadataError, preview_value
from ..tags import tag_help
from ..template import Template, builtin_templates
from . import dialogs
from .session import Session, jsonable


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"


def json_response(payload: Any, status: int = 200) -> Response:
    import json
    return Response(status, json.dumps(payload, ensure_ascii=False, default=jsonable).encode("utf-8"))


class Api:
    def __init__(self, session: Session):
        self.session = session

    def dispatch(self, method: str, path: str, query: dict[str, str], body: dict) -> Response:
        try:
            if method == "GET" and path == "/api/health":
                return json_response({"ok": True, "version": "0.1.0"})
            if method == "GET" and path == "/api/doc":
                return json_response({"ok": True, "doc": self.session.doc()})
            if method == "POST" and path == "/api/open":
                return json_response({"ok": True, "doc": self.session.open(
                    body["path"], body.get("slot"))})
            if method == "POST" and path == "/api/activate":
                return json_response({"ok": True, "doc": self.session.activate(int(body["index"]))})
            if method == "POST" and path == "/api/close":
                return json_response({"ok": True, "doc": self.session.close(
                    body.get("index"))})
            if method == "GET" and path == "/api/tag-help":
                return json_response({"ok": True, "data": tag_help(query.get("name", ""))})
            if method == "POST" and path == "/api/format-value":
                return json_response({"ok": True, "data": preview_value(
                    str(body.get("name", "")), str(body.get("value", "")))})
            if method == "POST" and path == "/api/dialog/choose":
                selected = dialogs.open_file()
                if not selected:
                    return json_response({"ok": False, "error": "未选择文件"}, 200)
                return json_response({"ok": True, "path": selected})
            if method == "POST" and path == "/api/dialog/open":
                selected = dialogs.open_file()
                if not selected:
                    return json_response({"ok": False, "error": "未选择文件"}, 200)
                return json_response({"ok": True, "path": selected, "doc": self.session.open(selected)})
            if method == "POST" and path == "/api/dialog/save":
                default = body.get("default") or (self.session.meta.path.name if self.session.meta else "output.jpg")
                selected = dialogs.save_file(default)
                return json_response({"ok": True, "path": selected} if selected else {"ok": False, "error": "已取消"})
            if method == "POST" and path == "/api/edit":
                return json_response({"ok": True, "doc": self.session.edit(body.get("ops", []))})
            if method == "POST" and path == "/api/undo":
                return json_response({"ok": True, "doc": self.session.undo_last()})
            if method == "POST" and path == "/api/redo":
                return json_response({"ok": True, "doc": self.session.redo_last()})
            if method == "POST" and path == "/api/save":
                return json_response({"ok": True, "doc": self.session.save(body.get("path"))})
            if method == "GET" and path == "/api/xmp":
                return json_response({"ok": True, "text": self.session.xmp_text()})
            if method == "POST" and path == "/api/xmp":
                return json_response({"ok": True, "doc": self.session.set_xmp_text(str(body.get("text", "")))})
            if method == "GET" and path.startswith("/api/segments/") and path.endswith("/hex"):
                index = int(path.split("/")[3])
                return json_response({"ok": True, "data": self.session.segment_hex(index)})
            if method == "POST" and path == "/api/segments/remove":
                return json_response({"ok": True, "doc": self.session.edit([{"op": "remove_segment", "index": int(body["index"])}])})
            if method == "POST" and path == "/api/segments/comment":
                return json_response({"ok": True, "doc": self.session.edit([{"op": "add_comment", "text": str(body.get("text", ""))}])})
            if method == "POST" and path == "/api/gps":
                return json_response({"ok": True, "doc": self.session.edit([{
                    "op": "set_gps", "lat": body["lat"], "lon": body["lon"],
                    "alt": body.get("alt"), "datum": body.get("datum", "wgs84")}])})
            if method == "POST" and path == "/api/gps/clear":
                return json_response({"ok": True, "doc": self.session.edit([{"op": "clear_gps"}])})
            if method == "POST" and path == "/api/validate":
                return json_response({"ok": True, "report": self.session.validate()})
            if method == "GET" and path == "/api/preview":
                size = int(query.get("size", "1600"))
                index = int(query["doc"]) if query.get("doc") not in (None, "") else None
                return Response(200, self.session.preview(size, index), "image/jpeg")
            if method == "GET" and path == "/api/thumb":
                thumb_path = query.get("path", "")
                if not thumb_path or not os.path.isfile(thumb_path):
                    raise ValueError("文件不存在")
                size = int(query.get("size", "128"))
                return Response(200, self.session.thumbnail(thumb_path, size), "image/jpeg")
            if method == "GET" and path == "/api/histogram":
                index = int(query["doc"]) if query.get("doc") not in (None, "") else None
                return json_response({"ok": True, "data": self.histogram(index)})
            if method == "POST" and path == "/api/batch/scan":
                return json_response({"ok": True, "data": self.batch_scan(body)})
            if method == "POST" and path == "/api/batch/export":
                return json_response({"ok": True, "data": self.batch_export(body)})
            if method == "POST" and path == "/api/batch/rename":
                return json_response({"ok": True, "data": self.batch_rename(body)})
            if method == "POST" and path == "/api/batch/sort":
                return json_response({"ok": True, "data": self.batch_sort(body)})
            if method == "POST" and path == "/api/batch/template":
                return json_response({"ok": True, "data": self.batch_template(body)})
            if method == "GET" and path == "/api/templates":
                return json_response({"ok": True, "data": [
                    {"name": k, "description": v.description} for k, v in builtin_templates().items()
                ]})
            if method == "POST" and path == "/api/template/apply":
                return json_response({"ok": True, "data": self.apply_template(body)})
            return json_response({"ok": False, "error": "未知接口: %s" % path}, 404)
        except (ValueError, KeyError, MetadataError) as exc:
            return json_response({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            import logging
            logging.getLogger("easyexif.webui").exception("api failure %s %s", method, path)
            return json_response({"ok": False, "error": str(exc)}, 400)

    # -- images -----------------------------------------------------------
    def histogram(self, index: int | None = None) -> dict:
        if not self.session.meta:
            raise ValueError("没有打开文件")
        from PIL import Image
        with Image.open(io.BytesIO(self.session.preview(1200, index))) as im:
            hist = im.convert("L").histogram()
        total = sum(hist) or 1
        return {"bins": list(hist), "mean": sum(i * h for i, h in enumerate(hist)) / total}

    # -- batch ------------------------------------------------------------
    def batch_scan(self, body: dict) -> dict:
        root = body.get("path")
        if not root or not os.path.exists(root):
            raise ValueError("路径不存在")
        files = iter_images(root, recursive=bool(body.get("recursive", True)))
        out = []
        for p in files[:2000]:
            out.append({"path": str(p), "name": p.name, "size": p.stat().st_size})
        return {"files": out, "total": len(files), "truncated": len(files) > len(out)}

    def _profile(self, value: str | None) -> Profile:
        if not value:
            return BUILTIN_PROFILES["simple"]
        if value in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[value]
        return Profile.load(value)

    def _files(self, body: dict) -> list[str]:
        files = body.get("files") or []
        if not files:
            raise ValueError("没有选择文件")
        return [str(Path(f)) for f in files]

    def batch_export(self, body: dict) -> dict:
        files = self._files(body)
        out = body.get("out")
        if not out:
            raise ValueError("没有指定输出文件")
        profile = self._profile(body.get("profile"))
        return export_csv(files, out, profile)

    def batch_rename(self, body: dict) -> dict:
        files = self._files(body)
        pattern = body.get("pattern")
        if not pattern:
            raise ValueError("没有重命名模板")
        return {"plan": rename(files, pattern, dry_run=not bool(body.get("apply")))}

    def batch_sort(self, body: dict) -> dict:
        files = self._files(body)
        root = body.get("root")
        mode = body.get("by", "date")
        if not root:
            raise ValueError("没有指定目标目录")
        return {"plan": sort_into(files, root, by=mode,
                                  dry_run=not bool(body.get("apply")),
                                  move=bool(body.get("move")))}

    def batch_template(self, body: dict) -> dict:
        files = self._files(body)
        template = self._load_template(body.get("template"))
        results = apply_template(files, template, dry_run=not bool(body.get("apply")))
        return {"results": results}

    def apply_template(self, body: dict) -> dict:
        files = self._files(body)
        template = self._load_template(body.get("template"))
        results = apply_template(files, template, dry_run=not bool(body.get("apply")))
        return {"results": results}

    def _load_template(self, value: str | None) -> Template:
        if not value:
            raise ValueError("没有指定模板")
        builtin = builtin_templates()
        if value in builtin:
            return builtin[value]
        return Template.load(value)
