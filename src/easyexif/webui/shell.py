"""pywebview / WebView2 window shell.

The application only uses an embedded WebView2 window. There is deliberately
no browser (`msedge --app`) fallback: launching a full Edge process would
bring its profile, sync prompts and extensions into what should be a local
desktop tool.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import __version__


def launch_pywebview(url: str, server=None, session=None, width: int = 1440,
                     height: int = 900) -> int:
    # .NET Framework refuses to load assemblies from a remote/removable path
    # unless this switch is set; harmless for normal local installations.
    os.environ.setdefault("COMPLUS_LoadFromRemoteSources", "1")
    os.environ["PYTHONNET_RUNTIME"] = "netfx"
    import webview

    class Bridge:
        def __init__(self):
            self._window = None

        def choose_file(self):
            """Open the native picker and return every selected path."""
            try:
                result = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=(
                        "Images (*.jpg;*.jpeg;*.jpe;*.tif;*.tiff;*.exi;*.exif;*.dng;*.cr2;*.nef;*.arw)",
                        "All files (*.*)",
                    ),
                )
                if result:
                    return [str(path) for path in result]
            except Exception:
                pass
            return []

        def choose_json(self):
            try:
                result = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    file_types=("JSON (*.json)", "All files (*.*)"),
                )
                if result:
                    return str(result[0] if isinstance(result, (list, tuple)) else result)
            except Exception:
                pass
            return ""

        def choose_json_save(self, default="metadata.json"):
            try:
                result = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=default or "metadata.json",
                    file_types=("JSON (*.json)", "All files (*.*)"),
                )
                if result:
                    return str(result[0] if isinstance(result, (list, tuple)) else result)
            except Exception:
                pass
            return ""

    bridge = Bridge()
    window = webview.create_window(
        "EasyExif " + __version__,
        url,
        width=width,
        height=height,
        min_size=(1100, 700),
        background_color="#f4f6fb",
        text_select=True,
        confirm_close=False,
        js_api=bridge,
    )
    bridge._window = window

    def _on_drop(event):
        try:
            files = event.get("dataTransfer", {}).get("files", []) if isinstance(event, dict) else []
            paths = []
            for item in files:
                path = item.get("pywebviewFullPath") or ""
                if path and path not in paths:
                    paths.append(path)
            if paths:
                window.evaluate_js("window.easyexifOpenDropped(%s)"
                                   % json.dumps(paths, ensure_ascii=False))
        except Exception:
            pass

    def _register_drop():
        try:
            window.dom.body.events.drop += _on_drop
        except Exception:
            pass

    window.events.loaded += _register_drop

    def _closing():
        if session is not None and getattr(session, "dirty", False):
            return window.create_confirmation_dialog(
                "EasyExif", "有未保存的修改，确定退出吗？")
        return True

    window.events.closing += _closing
    webview.start(debug=False, gui="edgechromium")
    return 0


def launch(url: str, data_dir: Path, server=None, session=None) -> int:
    """Open the only supported shell: embedded WebView2 via pywebview."""
    return launch_pywebview(url, server, session)
