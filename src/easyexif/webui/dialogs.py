"""Native file dialogs, run in a separate process.

Tk must own the main thread of its process.  The HTTP server handles requests
in worker threads, so the dialog is delegated to a short-lived helper process
and the selected path is returned as one JSON line.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def _run_helper(kind: str, default_name: str = "") -> str:
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--dialog-helper", kind]
    else:
        command = [sys.executable, "-m", "easyexif.webui.dialog_helper", kind]
    if kind == "save":
        command.append(default_name or "output.jpg")
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return str(json.loads(line).get("path") or "")
        except ValueError:
            continue
    return ""


def open_file() -> str:
    return _run_helper("open")


def save_file(default_name: str = "output.jpg") -> str:
    return _run_helper("save", default_name)
