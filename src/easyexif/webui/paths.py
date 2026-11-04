"""Runtime paths for the web UI (source tree and PyInstaller onefile)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def static_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "easyexif" / "webui" / "static"
    return package_dir() / "static"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _candidates() -> list[Path]:
    out: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    roaming = os.environ.get("APPDATA")
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    public = os.environ.get("PUBLIC") or r"C:\Users\Public"

    if local:
        out.append(Path(local) / "EasyExif")
    if roaming:
        out.append(Path(roaming) / "EasyExif")
    if getattr(sys, "frozen", False) and sys.executable:
        out.append(Path(sys.executable).resolve().parent / "EasyExifData")
    out.append(Path(profile) / "EasyExifData")
    out.append(Path(public) / "EasyExifData")
    out.append(Path.cwd() / "EasyExifData")
    try:
        out.append(Path(tempfile.gettempdir()) / "EasyExifData")
    except OSError:
        pass

    seen = set()
    unique = []
    for path in out:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def data_dir() -> Path:
    override = os.environ.get("EASYEXIF_DATA_DIR")
    if override:
        path = Path(override)
        if _writable(path):
            return path
        raise RuntimeError("EASYEXIF_DATA_DIR 不可写: %s" % path)

    tried = []
    for path in _candidates():
        tried.append(str(path))
        if _writable(path):
            return path
    raise RuntimeError("找不到可写的数据目录。已尝试:\n" + "\n".join(tried))
