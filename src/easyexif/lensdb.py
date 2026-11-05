"""Optional Lensfun XML database adapter.

The database is deliberately not bundled with EasyExif.  Set
EASYEXIF_LENSFUN_DIR to a directory containing Lensfun XML files, or place the
files in a local lensfun directory.  Lensfun data is normally CC BY-SA; keep it
as a separate data package and preserve its attribution.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metadata import Metadata
from .tags import rational_to_float


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _numbers(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


@dataclass
class Camera:
    maker: str
    model: str
    mount: str = ""
    crop: float | None = None


@dataclass
class Lens:
    maker: str
    model: str
    mount: str = ""
    crop: float | None = None
    focal_min: float | None = None
    focal_max: float | None = None
    aperture_min: float | None = None
    aperture_max: float | None = None
    aliases: list[str] = field(default_factory=list)


class LensDatabase:
    def __init__(self, root: Path, cameras: list[Camera], lenses: list[Lens]):
        self.root = root
        self.cameras = cameras
        self.lenses = lenses
        self._camera_index = [(c, _norm(c.model)) for c in cameras]
        self._lens_index = [(l, _norm(l.model), _norm(l.maker)) for l in lenses]

    @classmethod
    def load(cls, root: str | os.PathLike) -> "LensDatabase":
        base = Path(root)
        cameras: list[Camera] = []
        lenses: list[Lens] = []
        for path in sorted(base.rglob("*.xml")):
            try:
                tree = ET.parse(path)
            except Exception:
                continue
            for node in tree.getroot().iter():
                tag = node.tag.split("}")[-1]
                if tag == "camera":
                    maker = _text(node, "maker")
                    model = _text(node, "model")
                    if model:
                        cameras.append(Camera(maker, model, _text(node, "mount"),
                                              _float(_text(node, "cropfactor"))))
                elif tag == "lens":
                    model = _text(node, "model")
                    if not model:
                        continue
                    focal = _values(node, "focal")
                    aperture = _values(node, "aperture")
                    lenses.append(Lens(
                        _text(node, "maker"), model, _text(node, "mount"),
                        _float(_text(node, "cropfactor")),
                        min(focal) if focal else None,
                        max(focal) if focal else None,
                        min(aperture) if aperture else None,
                        max(aperture) if aperture else None,
                    ))
        return cls(base, cameras, lenses)

    def match_camera(self, make: str, model: str) -> Camera | None:
        target = _norm(model)
        if not target:
            return None
        best: tuple[int, Camera] | None = None
        make_n = _norm(make)
        for camera, name in self._camera_index:
            score = 0
            if name == target:
                score = 4
            elif target in name or name in target:
                score = 3
            elif make_n and make_n in _norm(camera.maker):
                score = 1
            if score and (best is None or score > best[0]):
                best = (score, camera)
        return best[1] if best else None

    def match_lens(self, make: str, model: str, mount: str = "") -> Lens | None:
        target = _norm(model)
        if not target:
            return None
        make_n = _norm(make)
        mount_n = _norm(mount)
        best: tuple[int, Lens] | None = None
        for lens, name, lens_make in self._lens_index:
            score = 0
            if name == target:
                score = 5
            elif target in name or name in target:
                score = 4
            elif make_n and make_n in lens_make and target in name:
                score = 2
            if mount_n and _norm(lens.mount) == mount_n:
                score += 1
            if score and (best is None or score > best[0]):
                best = (score, lens)
        return best[1] if best else None


def _text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None else ""


def _values(node: ET.Element, name: str) -> list[float]:
    out: list[float] = []
    for child in node.findall(name):
        out.extend(_numbers(child.get("value") or child.text))
    return out


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def default_root() -> Path | None:
    env = os.environ.get("EASYEXIF_LENSFUN_DIR")
    candidates = [Path(env)] if env else []
    candidates.extend([Path.cwd() / "lensfun", Path.home() / "EasyExif" / "lensfun"])
    for path in candidates:
        if path.is_dir() and any(path.rglob("*.xml")):
            return path
    return None


_CACHE: tuple[str, LensDatabase] | None = None


def load_default() -> LensDatabase | None:
    global _CACHE
    root = default_root()
    if root is None:
        return None
    key = str(root.resolve())
    if _CACHE and _CACHE[0] == key:
        return _CACHE[1]
    try:
        db = LensDatabase.load(root)
    except Exception:
        return None
    _CACHE = (key, db)
    return db


def lens_info(meta: Metadata, db: LensDatabase | None = None) -> dict[str, Any]:
    db = db or load_default()
    make = meta.get_text("IFD0.Make", "")
    model = meta.get_text("IFD0.Model", "")
    lens_model = meta.get_text("EXIF.LensModel", "") or meta.get_text("EXIF.LensSpecification", "")
    if db is None:
        return {"available": False, "reason": "未加载 Lensfun 数据",
                "camera": None, "lens": None, "warnings": []}
    camera = db.match_camera(make, model)
    lens = db.match_lens(meta.get_text("EXIF.LensMake", ""), lens_model,
                         camera.mount if camera else "")
    crop = (camera.crop if camera and camera.crop else None) or (lens.crop if lens and lens.crop else None)
    focal = rational_to_float(meta.tiff.get("EXIF", 0x920A)) if meta.tiff else None
    fnumber = rational_to_float(meta.tiff.get("EXIF", 0x829D)) if meta.tiff else None
    equiv = round(focal * crop, 1) if focal and crop else None
    category = None
    if equiv is not None:
        category = "广角" if equiv < 28 else ("长焦" if equiv > 70 else "标准")
    elif focal:
        category = "广角" if focal < 28 else ("长焦" if focal > 70 else "标准")
    warnings: list[str] = []
    if lens and focal:
        if lens.focal_min is not None and focal < lens.focal_min - 0.1:
            warnings.append("焦距 %.1f mm 小于镜头范围 %.1f–%.1f mm" % (
                focal, lens.focal_min, lens.focal_max or lens.focal_min))
        if lens.focal_max is not None and focal > lens.focal_max + 0.1:
            warnings.append("焦距 %.1f mm 超出镜头范围 %.1f–%.1f mm" % (
                focal, lens.focal_min or lens.focal_max, lens.focal_max))
    if lens and fnumber and lens.aperture_min is not None and fnumber < lens.aperture_min - 0.05:
        warnings.append("光圈 f/%.1f 小于镜头最大光圈 f/%.1f" % (fnumber, lens.aperture_min))
    return {
        "available": True,
        "camera": {"maker": camera.maker, "model": camera.model,
                   "mount": camera.mount, "crop": camera.crop} if camera else None,
        "lens": {"maker": lens.maker, "model": lens.model,
                 "mount": lens.mount, "focal_min": lens.focal_min,
                 "focal_max": lens.focal_max, "aperture_min": lens.aperture_min,
                 "aperture_max": lens.aperture_max} if lens else None,
        "focal": focal,
        "fnumber": fnumber,
        "equiv_focal": equiv,
        "category": category,
        "warnings": warnings,
        "source": str(db.root),
    }
