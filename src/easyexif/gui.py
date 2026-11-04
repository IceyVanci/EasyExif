"""Tkinter desktop editor for EasyExif.

The layout is an IFD tree on the left, an image preview in the middle and a
tabbed inspector (metadata / XMP / JPEG segments / GPS / validation) on the
right.
"""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, gps
from .jpeg import Jpeg
from .metadata import Metadata, MetadataError
from .tags import format_value, resolve_name
from .validate import validate as run_validate
from .xmp import Xmp

APP_TITLE = "EasyExif %s 元数据编辑器" % __version__


class EditDialog(simpledialog.Dialog):
    def __init__(self, parent, title: str, name: str = "", value: str = ""):
        self._name = name
        self._value = value
        self.result: tuple[str, str] | None = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="标签 (IFD.Name 或名称)").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.name_var = tk.StringVar(value=self._name)
        name_entry = ttk.Entry(master, textvariable=self.name_var, width=42)
        name_entry.grid(row=0, column=1, padx=4, pady=4, sticky="we")
        ttk.Label(master, text="值").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.value_var = tk.StringVar(value=self._value)
        value_entry = ttk.Entry(master, textvariable=self.value_var, width=42)
        value_entry.grid(row=1, column=1, padx=4, pady=4, sticky="we")
        self.name_var.trace_add("write", lambda *_: self.name_var.set(self.name_var.get()))
        return name_entry

    def validate(self):
        if not self.name_var.get().strip():
            messagebox.showwarning(APP_TITLE, "请输入标签名称", parent=self)
            return False
        return True

    def apply(self):
        self.result = (self.name_var.get().strip(), self.value_var.get())


class SegmentHex(tk.Toplevel):
    def __init__(self, master, segment):
        super().__init__(master)
        self.title("%s  0x%02X  %d bytes" % (segment.label(), segment.marker, len(segment.data)))
        self.geometry("720x480")
        text = tk.Text(self, wrap="none", font=("Consolas", 10))
        scroll = ttk.Scrollbar(self, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        data = segment.data
        lines = []
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            hexpart = " ".join("%02X" % b for b in chunk)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append("%08X  %-47s  %s" % (i, hexpart, asc))
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")


class EasyExifApp(tk.Tk):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x720")
        self.minsize(900, 560)
        self.meta: Metadata | None = None
        self.dirty = False
        self._photo = None
        self._rows: dict[str, dict[str, Any]] = {}
        self._segments: dict[str, Any] = {}
        self._build_style()
        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if path:
            self.open_file(path)
        else:
            self.status("打开一张 JPEG 或 TIFF 图像开始")

    # -- UI -------------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self)
        for theme in ("vista", "winnative", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Treeview", rowheight=22)
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开...", accelerator="Ctrl+O", command=self.open_dialog)
        file_menu.add_command(label="保存", accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(label="另存为...", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="关闭文件", command=self.close_file)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="添加标签...", accelerator="Insert", command=self.add_tag)
        edit_menu.add_command(label="编辑标签...", accelerator="Return", command=self.edit_selected)
        edit_menu.add_command(label="删除标签", accelerator="Delete", command=self.delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="同步拍摄时间", command=self.sync_datetime)
        edit_menu.add_command(label="清除全部元数据", command=self.strip_metadata)
        menubar.add_cascade(label="编辑", menu=edit_menu)

        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="原始性校验", accelerator="F5", command=self.validate_now)
        tools.add_command(label="在浏览器中查看 GPS", command=self.open_map)
        tools.add_command(label="移除 GPS", command=self.clear_gps)
        menubar.add_cascade(label="工具", menu=tools)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于 EasyExif", command=self.about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.config(menu=menubar)
        self.bind("<Control-o>", lambda e: self.open_dialog())
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<F5>", lambda e: self.validate_now())

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=(6, 4))
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="打开", command=self.open_dialog).pack(side="left", padx=2)
        ttk.Button(toolbar, text="保存", command=self.save).pack(side="left", padx=2)
        ttk.Button(toolbar, text="校验", command=self.validate_now).pack(side="left", padx=2)
        ttk.Button(toolbar, text="移除 GPS", command=self.clear_gps).pack(side="left", padx=2)
        ttk.Button(toolbar, text="地图", command=self.open_map).pack(side="left", padx=2)
        self.path_var = tk.StringVar(value="未打开文件")
        ttk.Label(toolbar, textvariable=self.path_var, foreground="#555").pack(side="left", padx=12)

        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(side="top", fill="both", expand=True)

        left = ttk.Frame(pan, padding=4)
        self.preview_label = ttk.Label(left, text="图像预览", anchor="center")
        self.preview_label.pack(side="top", fill="x", pady=(0, 6))
        self.summary = tk.Text(left, height=10, wrap="word", relief="flat",
                               background="#f7f7f7", font=("Segoe UI", 9))
        self.summary.pack(side="top", fill="x")
        self.summary.configure(state="disabled")
        pan.add(left, weight=1)

        right = ttk.Frame(pan, padding=4)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self._build_metadata_tab()
        self._build_xmp_tab()
        self._build_segments_tab()
        self._build_gps_tab()
        self._build_validate_tab()
        pan.add(right, weight=3)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w",
                  padding=(6, 2)).pack(side="bottom", fill="x")

    def _build_metadata_tab(self):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text="元数据")
        bar = ttk.Frame(frame)
        bar.pack(side="top", fill="x", pady=(0, 4))
        ttk.Button(bar, text="添加", command=self.add_tag).pack(side="left", padx=2)
        ttk.Button(bar, text="编辑", command=self.edit_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="删除", command=self.delete_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="同步时间", command=self.sync_datetime).pack(side="left", padx=2)

        wrap = ttk.Frame(frame)
        wrap.pack(fill="both", expand=True)
        columns = ("tag", "name", "type", "value")
        self.tree = ttk.Treeview(wrap, columns=columns, show="tree headings")
        self.tree.heading("#0", text="IFD")
        self.tree.heading("tag", text="Tag")
        self.tree.heading("name", text="名称")
        self.tree.heading("type", text="类型")
        self.tree.heading("value", text="值")
        self.tree.column("#0", width=90, stretch=False)
        self.tree.column("tag", width=70, stretch=False)
        self.tree.column("name", width=190, stretch=False)
        self.tree.column("type", width=80, stretch=False)
        self.tree.column("value", width=420, stretch=True)
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<Return>", lambda e: self.edit_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Insert>", lambda e: self.add_tag())

    def _build_xmp_tab(self):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text="XMP")
        bar = ttk.Frame(frame)
        bar.pack(side="top", fill="x", pady=(0, 4))
        ttk.Button(bar, text="应用 XML 修改", command=self.apply_xmp).pack(side="left", padx=2)
        ttk.Button(bar, text="格式化", command=self.pretty_xmp).pack(side="left", padx=2)
        self.xmp_text = ScrolledText(frame, wrap="none", font=("Consolas", 9))
        self.xmp_text.pack(fill="both", expand=True)

    def _build_segments_tab(self):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text="JPEG 段")
        bar = ttk.Frame(frame)
        bar.pack(side="top", fill="x", pady=(0, 4))
        ttk.Button(bar, text="查看十六进制", command=self.show_segment_hex).pack(side="left", padx=2)
        ttk.Button(bar, text="删除所选段", command=self.delete_segment).pack(side="left", padx=2)
        ttk.Button(bar, text="添加注释段", command=self.add_comment).pack(side="left", padx=2)
        columns = ("marker", "type", "size")
        self.seg_tree = ttk.Treeview(frame, columns=columns, show="headings")
        self.seg_tree.heading("marker", text="标记")
        self.seg_tree.heading("type", text="类型")
        self.seg_tree.heading("size", text="大小")
        self.seg_tree.column("marker", width=80, stretch=False)
        self.seg_tree.column("type", width=220, stretch=False)
        self.seg_tree.column("size", width=100, stretch=False)
        self.seg_tree.pack(fill="both", expand=True)
        self.seg_tree.bind("<Double-1>", lambda e: self.show_segment_hex())

    def _build_gps_tab(self):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text="GPS / 地图")
        self.gps_label = ttk.Label(frame, text="没有 GPS 数据", font=("Segoe UI", 11))
        self.gps_label.pack(anchor="w", padx=8, pady=8)
        btns = ttk.Frame(frame)
        btns.pack(anchor="w", padx=8)
        for name, provider in (("OpenStreetMap", "osm"), ("Google", "google"),
                               ("百度", "baidu"), ("高德", "amap")):
            ttk.Button(btns, text=name,
                       command=lambda p=provider: self.open_map(p)).pack(side="left", padx=2)
        ttk.Button(btns, text="设置坐标...", command=self.set_gps_dialog).pack(side="left", padx=12)
        ttk.Button(btns, text="移除 GPS", command=self.clear_gps).pack(side="left", padx=2)

    def _build_validate_tab(self):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text="原始性校验")
        self.validate_text = ScrolledText(frame, wrap="word", font=("Consolas", 9))
        self.validate_text.pack(fill="both", expand=True)

    # -- file operations --------------------------------------------------
    def open_dialog(self):
        path = filedialog.askopenfilename(
            title="打开图像",
            filetypes=[("JPEG / TIFF", "*.jpg *.jpeg *.tif *.tiff *.exi *.exif"),
                       ("所有文件", "*.*")])
        if path:
            self.open_file(path)

    def open_file(self, path: str):
        if not self.confirm_discard():
            return
        try:
            meta = Metadata.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, "无法打开文件:\n%s" % exc)
            return
        self.meta = meta
        self.dirty = False
        self.path_var.set(str(meta.path))
        self.title("%s - %s" % (meta.path.name, APP_TITLE))
        self.refresh_all()
        self.status("已打开 %s  (%s)" % (meta.path.name, meta.info.format))

    def close_file(self):
        if not self.confirm_discard():
            return
        self.meta = None
        self.dirty = False
        self.path_var.set("未打开文件")
        self.title(APP_TITLE)
        self.tree.delete(*self.tree.get_children())
        self.seg_tree.delete(*self.seg_tree.get_children())
        self.xmp_text.delete("1.0", "end")
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.configure(state="disabled")
        self.preview_label.configure(image="", text="图像预览")
        self._photo = None
        self.gps_label.configure(text="没有 GPS 数据")
        self.validate_text.delete("1.0", "end")

    def save(self):
        if not self.meta:
            return
        try:
            target = self.meta.save(preserve_time=False)
        except (MetadataError, OSError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, "保存失败:\n%s" % exc)
            return
        self.dirty = False
        self.status("已保存 %s" % target)

    def save_as(self):
        if not self.meta:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("TIFF", "*.tif"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            target = self.meta.save(path, preserve_time=False)
        except (MetadataError, OSError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, "保存失败:\n%s" % exc)
            return
        self.meta.path = Path(path)
        self.path_var.set(str(path))
        self.dirty = False
        self.status("已另存为 %s" % target)

    # -- refresh ----------------------------------------------------------
    def refresh_all(self):
        if not self.meta:
            return
        self.refresh_tree()
        self.refresh_summary()
        self.refresh_preview()
        self.refresh_xmp()
        self.refresh_segments()
        self.refresh_gps()

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        if not self.meta:
            return
        groups = ("IFD0", "EXIF", "GPS", "Interop", "IFD1", "MakerNote", "XMP")
        nodes = {}
        for group in groups:
            nodes[group] = self.tree.insert("", "end", text=group, open=group in ("IFD0", "EXIF"))
        for row in self.meta.rows():
            parent = nodes.get(row["ifd"])
            if parent is None:
                continue
            iid = self.tree.insert(
                parent, "end",
                values=("0x%04X" % row["tag"] if isinstance(row["tag"], int) else row["tag"],
                        row["name"], row["type"], row["display"]))
            self._rows[iid] = row

    def refresh_summary(self):
        if not self.meta:
            return
        s = self.meta.summary()
        cam = s["camera"]
        exp = s["exposure"]
        dims = s["dimensions"]
        lines = [
            "%s  %sx%s  %.2f MB" % (s["format"], dims[0] or "?", dims[1] or "?", s["size"] / 1048576),
            "%s %s" % (cam["make"], cam["model"]),
            cam["lens"] or "",
            exp["date"] or "",
            "%s  %s  ISO %s  %s" % (exp["shutter"] or "-", exp["aperture"] or "-",
                                    exp["iso"] or "-", exp["focal"] or "-"),
        ]
        g = s["gps"]
        if g:
            lines.append("GPS %.6f, %.6f" % (g["latitude"], g["longitude"]))
        if s["warnings"]:
            lines.append("警告: " + s["warnings"][0])
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", "\n".join(x for x in lines if x))
        self.summary.configure(state="disabled")

    def refresh_preview(self):
        if not self.meta:
            return
        try:
            from PIL import Image, ImageTk
            with Image.open(self.meta.path) as im:
                im.thumbnail((420, 300))
                self._photo = ImageTk.PhotoImage(im.copy())
            self.preview_label.configure(image=self._photo, text="")
        except Exception as exc:
            self.preview_label.configure(image="", text="无法加载预览: %s" % exc)
            self._photo = None

    def refresh_xmp(self):
        self.xmp_text.delete("1.0", "end")
        if self.meta and self.meta.xmp.exists:
            self.xmp_text.insert("1.0", self.meta.xmp.text)

    def refresh_segments(self):
        self.seg_tree.delete(*self.seg_tree.get_children())
        self._segments.clear()
        if not self.meta or not self.meta.jpeg:
            return
        for seg in self.meta.jpeg.segments:
            iid = self.seg_tree.insert("", "end", values=("0x%02X" % seg.marker,
                                                         seg.label(), len(seg.data)))
            self._segments[iid] = seg

    def refresh_gps(self):
        info = self.meta.gps() if self.meta else None
        if not info:
            self.gps_label.configure(text="没有 GPS 数据")
            return
        self.gps_label.configure(text=(
            "纬度 %.7f (%s)\n经度 %.7f (%s)\n海拔 %s m" % (
                info["latitude"], gps.format_dms(info["latitude"]),
                info["longitude"], gps.format_dms(info["longitude"]),
                "%.1f" % info["altitude"] if info["altitude"] is not None else "-")))

    # -- editing ----------------------------------------------------------
    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._rows.get(sel[0])

    def add_tag(self):
        if not self.meta:
            return
        dlg = EditDialog(self, "添加标签")
        if not dlg.result:
            return
        name, value = dlg.result
        try:
            self.meta.set(name, value)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "无法添加标签:\n%s" % exc)
            return
        self.dirty = True
        self.refresh_all()
        self.status("已添加 %s" % name)

    def edit_selected(self):
        row = self._selected_row()
        if not row or not self.meta:
            return
        if row["ifd"] == "MakerNote":
            messagebox.showinfo(APP_TITLE, "厂商注释字段为只读；修改标准 EXIF 后会自动保留。")
            return
        name = "%s.%s" % (row["ifd"], row["name"]) if row["ifd"] != "XMP" else row["name"]
        dlg = EditDialog(self, "编辑标签", name, row["display"])
        if not dlg.result:
            return
        new_name, value = dlg.result
        try:
            if new_name != name:
                self.meta.delete(name)
            self.meta.set(new_name, value)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "无法修改标签:\n%s" % exc)
            return
        self.dirty = True
        self.refresh_all()
        self.status("已修改 %s" % new_name)

    def delete_selected(self):
        row = self._selected_row()
        if not row or not self.meta:
            return
        if row["ifd"] == "MakerNote":
            messagebox.showinfo(APP_TITLE, "厂商注释字段为只读。")
            return
        name = "%s.%s" % (row["ifd"], row["name"]) if row["ifd"] != "XMP" else row["name"]
        if not messagebox.askyesno(APP_TITLE, "删除 %s ?" % name):
            return
        try:
            self.meta.delete(name)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.dirty = True
        self.refresh_all()
        self.status("已删除 %s" % name)

    def sync_datetime(self):
        if not self.meta:
            return
        self.meta.sync_datetime()
        self.dirty = True
        self.refresh_all()
        self.status("已同步 DateTime / DateTimeDigitized")

    def apply_xmp(self):
        if not self.meta:
            return
        text = self.xmp_text.get("1.0", "end")
        self.meta.xmp = Xmp(text)
        self.dirty = True
        self.refresh_tree()
        self.status("已应用 XMP 修改")

    def pretty_xmp(self):
        text = self.xmp_text.get("1.0", "end")
        try:
            import xml.dom.minidom as minidom
            pretty = minidom.parseString(text.encode("utf-8")).toprettyxml(indent="  ")
            self.xmp_text.delete("1.0", "end")
            self.xmp_text.insert("1.0", pretty)
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, "XML 解析失败: %s" % exc)

    # -- segments ---------------------------------------------------------
    def _selected_segment(self):
        sel = self.seg_tree.selection()
        return self._segments.get(sel[0]) if sel else None

    def show_segment_hex(self):
        seg = self._selected_segment()
        if seg:
            SegmentHex(self, seg)

    def delete_segment(self):
        seg = self._selected_segment()
        if not seg or not self.meta or not self.meta.jpeg:
            return
        if not messagebox.askyesno(APP_TITLE, "删除 %s 段?" % seg.label()):
            return
        self.meta.jpeg.remove_index(self.meta.jpeg.segments.index(seg))
        self.dirty = True
        self.refresh_segments()
        self.status("已删除 %s" % seg.label())

    def add_comment(self):
        if not self.meta or not self.meta.jpeg:
            return
        text = simpledialog.askstring(APP_TITLE, "注释内容:", parent=self)
        if not text:
            return
        self.meta.jpeg.insert(0xFE, text.encode("utf-8"))
        self.dirty = True
        self.refresh_segments()
        self.status("已添加 COM 段")

    # -- GPS --------------------------------------------------------------
    def open_map(self, provider: str = "osm"):
        info = self.meta.gps() if self.meta else None
        if not info:
            messagebox.showinfo(APP_TITLE, "当前文件没有 GPS 数据")
            return
        webbrowser.open(gps.map_url(provider, info["latitude"], info["longitude"]))

    def set_gps_dialog(self):
        if not self.meta:
            return
        text = simpledialog.askstring(APP_TITLE, "输入纬度,经度 (WGS-84):", parent=self)
        if not text:
            return
        try:
            lat_s, lon_s = [x.strip() for x in text.replace("，", ",").split(",")[:2]]
            self.meta.set_gps(float(lat_s), float(lon_s))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "坐标无效: %s" % exc)
            return
        self.dirty = True
        self.refresh_all()
        self.status("GPS 已更新")

    def clear_gps(self):
        if not self.meta:
            return
        self.meta.clear_gps()
        self.dirty = True
        self.refresh_all()
        self.status("GPS 已移除")

    # -- validation -------------------------------------------------------
    def validate_now(self):
        if not self.meta:
            return
        if self.dirty:
            self.save()
        try:
            report = run_validate(self.meta.path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "校验失败: %s" % exc)
            return
        self.validate_text.delete("1.0", "end")
        self.validate_text.insert("1.0", report.render())
        self.tabs.select(4)
        self.status("校验完成：%d 级" % report.score)

    def strip_metadata(self):
        if not self.meta:
            return
        if not messagebox.askyesno(APP_TITLE, "清除所有 EXIF/XMP/IPTC 元数据？此操作不可撤销。"):
            return
        self.meta.clear_metadata()
        self.dirty = True
        self.refresh_all()
        self.status("元数据已清除（尚未保存）")

    def about(self):
        messagebox.showinfo("关于 EasyExif", (
            "EasyExif %s\n\n"
            "开源 EXIF / XMP 元数据编辑器\n"
            "支持 JPEG 段编辑、厂商注释、GPS 坐标转换、批量导出与原始性校验。\n\n"
            "所有格式实现均基于公开规范独立完成。" % __version__))

    # -- lifecycle --------------------------------------------------------
    def status(self, text: str):
        self.status_var.set(text)

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(APP_TITLE, "当前修改尚未保存，是否保存？")
        if answer is None:
            return False
        if answer:
            self.save()
        return True

    def on_close(self):
        if self.confirm_discard():
            self.destroy()


def run(path: str | None = None) -> int:
    app = EasyExifApp(path)
    app.mainloop()
    return 0
