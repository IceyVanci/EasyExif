"""Standalone native file dialog helper.

Runs Tk in a separate process so the HTTP worker thread never owns a Tk
interpreter.  The parent reads one JSON line from stdout.
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from tkinter import filedialog


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    kind = args[0] if args else "open"
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    root.update_idletasks()
    path = ""
    try:
        if kind == "save":
            path = filedialog.asksaveasfilename(
                parent=root,
                title="保存图像",
                initialfile=args[1] if len(args) > 1 else "output.jpg",
                defaultextension=".jpg",
                filetypes=[("JPEG", "*.jpg"), ("TIFF", "*.tif"), ("所有文件", "*.*")],
            )
        else:
            path = filedialog.askopenfilename(
                parent=root,
                title="打开图像",
                filetypes=[("JPEG / TIFF", "*.jpg *.jpeg *.jpe *.tif *.tiff *.exi *.exif"),
                           ("所有文件", "*.*")],
            )
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    print(json.dumps({"path": path or ""}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
