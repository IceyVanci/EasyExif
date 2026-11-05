"""Command line interface for EasyExif."""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import __version__, gps
from .bundle import BundleError, import_bundle, load_bundle, write_bundle
from .lensdb import lens_info
from .validate import validate as run_validate
from .batch import (BUILTIN_PROFILES, Profile, apply_template, export_csv,
                    export_json, iter_images, rename, sort_into)
from .jpeg import Jpeg
from .metadata import Metadata, MetadataError
from .template import Template, builtin_templates, render_stamp
from .xmp import Xmp

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


# ---------------------------------------------------------------------------
# Small terminal helpers
# ---------------------------------------------------------------------------
def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(text))


def _pad(text: Any, width: int, right: bool = False) -> str:
    text = str(text)
    fill = " " * max(0, width - _width(text))
    return fill + text if right else text + fill


def table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    rows = [[str(c) for c in row] for row in rows]
    widths = [max([_width(h)] + [_width(r[i]) for r in rows if i < len(r)])
              for i, h in enumerate(headers)]
    sep = "  "
    out = [sep.join(_pad(h, widths[i]) for i, h in enumerate(headers))]
    out.append(sep.join("-" * w for w in widths))
    for row in rows:
        out.append(sep.join(_pad(c, widths[i]) for i, c in enumerate(row)))
    return "\n".join(out)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _emit(payload: Any, as_json: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_jsonable)
          if as_json else payload)


def _error(message: str) -> int:
    print("error: %s" % message, file=sys.stderr)
    return EXIT_ERROR


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_info(args) -> int:
    items = []
    for path in args.files:
        try:
            meta = Metadata.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            print("error: %s: %s" % (path, exc), file=sys.stderr)
            continue
        items.append(meta.summary())
    if args.json:
        _emit(items if len(items) != 1 else items[0], True)
        return EXIT_OK
    for s in items:
        _print_summary(s)
    return EXIT_OK


def _print_summary(s: dict) -> None:
    cam = s["camera"]
    exp = s["exposure"]
    dims = s["dimensions"]
    print("File      : %s" % s["file"])
    print("Format    : %s  %sx%s  %.2f MB" % (
        s["format"], dims[0] or "?", dims[1] or "?", s["size"] / 1048576))
    print("Camera    : %s %s" % (cam["make"], cam["model"]))
    if cam["lens"]:
        print("Lens      : %s" % cam["lens"])
    print("Captured  : %s" % (exp["date"] or "-"))
    print("Exposure  : %s  %s  ISO %s  %s" % (
        exp["shutter"] or "-", exp["aperture"] or "-", exp["iso"] or "-",
        exp["focal"] or "-"))
    if exp["bias"] or exp["program"]:
        print("Mode      : %s  %s  WB %s" % (exp["program"] or "-",
                                            exp["bias"] or "-",
                                            exp["white_balance"] or "-"))
    g = s["gps"]
    if g:
        print("GPS       : %.6f, %.6f  (%s)" % (
            g["latitude"], g["longitude"], gps.format_dms(g["latitude"], "N" if g["latitude"] >= 0 else "S")))
    print("Metadata  : EXIF=%s XMP=%s IPTC=%s ICC=%s MakerNote=%s Thumb=%d B" % (
        "yes" if s["has_exif"] else "no", "yes" if s["has_xmp"] else "no",
        "yes" if s["has_iptc"] else "no", "yes" if s["has_icc"] else "no",
        s["maker_note"] or "no", s["thumbnail_bytes"]))
    for w in s["warnings"][:8]:
        print("Warning   : %s" % w)
    print()


def cmd_dump(args) -> int:
    rows = []
    for path in args.files:
        try:
            meta = Metadata.read(path)
        except (MetadataError, OSError, ValueError) as exc:
            print("error: %s: %s" % (path, exc), file=sys.stderr)
            continue
        for row in meta.rows():
            if args.ifd and row["ifd"] not in args.ifd:
                continue
            rows.append(row)
    if args.json:
        _emit([{k: _jsonable(v) for k, v in r.items()} for r in rows], True)
        return EXIT_OK
    print(table(["IFD", "Tag", "Name", "Type", "Count", "Value"],
                [[r["ifd"], "0x%04X" % r["tag"] if isinstance(r["tag"], int) else r["tag"],
                  r["name"], r["type"], r["count"], r["display"]]
                 for r in rows]))
    return EXIT_OK


def cmd_get(args) -> int:
    meta = Metadata.read(args.file)
    out = {}
    for name in args.tags:
        try:
            out[name] = meta.get_text(name, "")
        except KeyError as exc:
            out[name] = "<%s>" % exc
    if args.json:
        _emit(out, True)
    else:
        for k, v in out.items():
            print("%s: %s" % (k, v))
    return EXIT_OK


def cmd_set(args) -> int:
    meta = Metadata.read(args.file)
    changed = 0
    for assignment in args.assignments:
        if "=" not in assignment:
            return _error("expected TAG=VALUE, got %r" % assignment)
        name, value = assignment.split("=", 1)
        try:
            meta.set(name.strip(), value)
            changed += 1
        except (KeyError, ValueError, TypeError, MetadataError) as exc:
            print("error: %s: %s" % (name, exc), file=sys.stderr)
    if not changed:
        return EXIT_ERROR
    target = meta.save(args.out, backup=args.backup)
    print("wrote %d change(s) to %s" % (changed, target))
    return EXIT_OK


def cmd_delete(args) -> int:
    meta = Metadata.read(args.file)
    count = 0
    for name in args.tags:
        try:
            if meta.delete(name):
                count += 1
        except KeyError as exc:
            print("error: %s" % exc, file=sys.stderr)
    if count:
        target = meta.save(args.out, backup=args.backup)
        print("deleted %d tag(s) in %s" % (count, target))
    else:
        print("nothing deleted")
    return EXIT_OK


def cmd_strip(args) -> int:
    meta = Metadata.read(args.file)
    meta.clear_metadata(keep_icc=args.keep_icc)
    target = meta.save(args.out, backup=args.backup)
    print("stripped metadata -> %s" % target)
    return EXIT_OK


def cmd_segments(args) -> int:
    meta = Metadata.read(args.file)
    if meta.jpeg is None:
        return _error("not a JPEG file")
    changed = False
    for index in sorted(args.remove or [], reverse=True):
        seg = meta.jpeg.get_segment(index)
        if seg is None:
            print("warning: no segment %d" % index, file=sys.stderr)
            continue
        meta.jpeg.remove_index(meta.jpeg.segments.index(seg))
        changed = True
    if args.add_comment:
        meta.jpeg.insert(0xFE, args.add_comment.encode("utf-8"))
        changed = True
    if args.extract is not None:
        index, out = args.extract
        seg = meta.jpeg.get_segment(int(index))
        if seg is None:
            return _error("no segment %d" % int(index))
        Path(out).write_bytes(seg.data)
        print("extracted %s (%d bytes) -> %s" % (seg.label(), len(seg.data), out))
    if changed:
        target = meta.save(args.out, backup=args.backup)
        print("updated segments -> %s" % target)
    if args.json:
        _emit(meta.jpeg.summary(), True)
    else:
        print(table(["#", "Marker", "Type", "Size"],
                    [[s.index, "0x%02X" % s.marker, s.label(), len(s.data)]
                     for s in meta.jpeg.segments]))
        dims = meta.jpeg.dimensions()
        print("\nDimensions: %sx%s" % dims if dims else "")
    return EXIT_OK


def cmd_export_metadata(args) -> int:
    try:
        meta = Metadata.read(args.file)
        out = args.out or (Path(args.file).stem + ".metadata.json")
        data = write_bundle(meta, out)
        print("metadata bundle written -> %s" % out)
        print("tags: %d, source: %s" % (len(data["exif"]["tags"]), data["source"]["format"]))
        return EXIT_OK
    except (MetadataError, BundleError, OSError, ValueError) as exc:
        return _error(str(exc))


def cmd_import_metadata(args) -> int:
    try:
        meta = Metadata.read(args.file)
        bundle = load_bundle(args.bundle)
        result = import_bundle(meta, bundle, args.out, mode=args.mode)
        print("wrote %s" % result["output"])
        print("marker: %s" % result["marker"]["software"])
        if result["dropped_makernote"]:
            print("warning: MakerNote dropped (source/target camera mismatch)")
        return EXIT_OK
    except (MetadataError, BundleError, OSError, ValueError) as exc:
        return _error(str(exc))


cmd_reconstruct = cmd_import_metadata


def cmd_lens(args) -> int:
    try:
        meta = Metadata.read(args.file)
        info = lens_info(meta)
        if not info.get("available"):
            print("Lensfun 未加载：%s" % info.get("reason", "没有数据包"))
            return EXIT_OK
        camera = info.get("camera") or {}
        lens = info.get("lens") or {}
        print("Camera: %s %s" % (camera.get("maker", ""), camera.get("model", "")))
        print("Lens  : %s %s" % (lens.get("maker", ""), lens.get("model", "")))
        print("Focal : %s mm%s" % (info.get("focal") or "?",
                                     " (35mm: %s mm)" % info["equiv_focal"] if info.get("equiv_focal") else ""))
        print("Aperture: f/%s" % (info.get("fnumber") or "?"))
        print("Category: %s" % (info.get("category") or "未知"))
        for warning in info.get("warnings") or []:
            print("Warning: %s" % warning)
        return EXIT_OK
    except (MetadataError, OSError, ValueError) as exc:
        return _error(str(exc))


def cmd_validate(args) -> int:
    reports = []
    for path in args.files:
        try:
            reports.append(run_validate(path))
        except (MetadataError, OSError, ValueError) as exc:
            print("error: %s: %s" % (path, exc), file=sys.stderr)
    if args.json:
        _emit([r.to_dict() for r in reports], True)
        return EXIT_OK
    for r in reports:
        print("== %s ==" % r.path)
        print(r.render())
        print()
    return EXIT_OK


def cmd_xmp(args) -> int:
    meta = Metadata.read(args.file)
    touched = False
    if args.set:
        for assignment in args.set:
            if "=" not in assignment:
                return _error("expected PROPERTY=VALUE")
            name, value = assignment.split("=", 1)
            meta.xmp.set(name.strip(), value)
            touched = True
    for name in args.delete or []:
        touched = meta.xmp.delete(name) or touched
    if touched:
        target = meta.save(args.out, backup=args.backup)
        print("xmp updated -> %s" % target)
    if args.json:
        _emit(meta.xmp.to_dict(), True)
    elif args.get:
        for name in args.get:
            value = meta.xmp.get(name)
            print("%s: %s" % (name, ", ".join(value) if isinstance(value, list) else value))
    else:
        for key in meta.xmp.keys():
            value = meta.xmp.get(key)
            print("%-32s %s" % (key, ", ".join(value) if isinstance(value, list) else value))
    return EXIT_OK


def cmd_gps(args) -> int:
    meta = Metadata.read(args.file)
    if args.set_gps:
        parts = [p for p in args.set_gps.replace(";", ",").split(",") if p.strip()]
        if len(parts) < 2:
            return _error("expected LAT,LON[,ALT]")
        lat, lon = float(parts[0]), float(parts[1])
        alt = float(parts[2]) if len(parts) > 2 else None
        meta.set_gps(lat, lon, alt, datum=args.datum)
        target = meta.save(args.out, backup=args.backup)
        print("gps written -> %s" % target)
    info = meta.gps()
    if not info:
        print("no GPS data")
        return EXIT_OK
    lat, lon = info["latitude"], info["longitude"]
    print("Latitude : %.7f  %s" % (lat, gps.format_dms(lat, "N" if lat >= 0 else "S")))
    print("Longitude: %.7f  %s" % (lon, gps.format_dms(lon, "E" if lon >= 0 else "W")))
    if info["altitude"] is not None:
        print("Altitude : %.1f m" % info["altitude"])
    if info["date"] or info["timestamp"]:
        print("Time     : %s %s" % (info["date"] or "", info["timestamp"] or ""))
    if args.to:
        clat, clon = gps.convert(lat, lon, "wgs84", args.to)
        print("%s      : %.7f, %.7f" % (args.to.upper(), clat, clon))
        lat, lon = clat, clon
    if args.map:
        for provider in args.map:
            url = gps.map_url(provider, lat, lon, args.zoom)
            print("%-10s %s" % (provider, url))
            if args.open:
                webbrowser.open(url)
    if args.html:
        Path(args.html).write_text(gps.embed_html(lat, lon, args.zoom), encoding="utf-8")
        print("map html -> %s" % args.html)
    return EXIT_OK


def cmd_template(args) -> int:
    if args.action == "list":
        for name, tpl in builtin_templates().items():
            print("%-16s %s" % (name, tpl.description))
        return EXIT_OK
    if args.action == "save":
        tpl = Template.from_file(args.file)
        out = tpl.save(args.out or (Path(args.file).stem + ".template.json"))
        print("template written -> %s" % out)
        return EXIT_OK
    all_files = ([args.file] if args.file else []) + list(args.files)
    if args.action == "apply":
        if not args.template:
            return _error("--template is required")
        tpl = _load_template(args.template)
        results = apply_template(all_files, tpl, dry_run=not args.apply)
        for r in results:
            if r.get("error"):
                print("error: %s: %s" % (r["file"], r["error"]), file=sys.stderr)
            else:
                print("%s: %d change(s)%s" % (r["file"], r["changes"],
                                              "" if args.apply else " (dry run)"))
        return EXIT_OK
    if args.action == "stamp":
        if not args.text:
            return _error("--text is required")
        for path in all_files:
            meta = Metadata.read(path)
            print(render_stamp(args.text, meta, sequence=args.sequence, path=Path(path)))
        return EXIT_OK
    return _error("unknown template action")


def _load_template(name: str) -> Template:
    builtin = builtin_templates()
    if name in builtin:
        return builtin[name]
    return Template.load(name)


def cmd_batch(args) -> int:
    files = iter_images(args.path, recursive=not args.no_recursive)
    if not files:
        return _error("no supported images found in %s" % args.path)
    result: dict[str, Any] = {"files": len(files)}
    if args.csv:
        profile = _profile(args.profile)
        result["csv"] = export_csv(files, args.csv, profile)
        print("csv: %d rows -> %s" % (result["csv"]["rows"], args.csv))
    if args.json_out:
        result["json"] = export_json(files, args.json_out)
        print("json: %d rows -> %s" % (result["json"]["rows"], args.json_out))
    if args.rename:
        plan = rename(files, args.rename, dry_run=not args.apply)
        result["rename"] = plan
        for row in plan[:20]:
            print("%s -> %s" % (row["src"], row["dst"]))
        if len(plan) > 20:
            print("... %d more" % (len(plan) - 20))
    if args.sort_by:
        plan = sort_into(files, args.sort_root or Path(args.path), by=args.sort_by,
                         dry_run=not args.apply, move=args.move)
        result["sort"] = plan
        for row in plan[:20]:
            print("%s -> %s" % (row["src"], row["dst"]))
    if args.template:
        results = apply_template(files, _load_template(args.template), dry_run=not args.apply)
        result["template"] = results
        print("template applied to %d file(s)%s" % (
            sum(1 for r in results if not r.get("error")),
            "" if args.apply else " (dry run)"))
    if not any([args.csv, args.json_out, args.rename, args.sort_by, args.template]):
        print("found %d supported image(s)" % len(files))
        for p in files[:20]:
            print("  %s" % p)
    if args.json:
        _emit(result, True)
    return EXIT_OK


def _profile(value: str | None) -> Profile:
    if not value:
        return BUILTIN_PROFILES["simple"]
    if value in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[value]
    return Profile.load(value)


def cmd_gui(args) -> int:
    from .gui import run
    return run(args.file)


def cmd_webui(args) -> int:
    from .webui.launch import main as webui_main
    argv = []
    if args.file:
        argv.append(args.file)
    if args.no_browser:
        argv.append("--no-browser")
    if args.port:
        argv.extend(["--port", str(args.port)])
    return webui_main(argv)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="easyexif",
        description="EasyExif - open source EXIF/XMP metadata editor")
    p.add_argument("--version", action="version", version="EasyExif %s" % __version__)
    sub = p.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="print a one screen summary")
    info.add_argument("files", nargs="+")
    info.add_argument("--json", action="store_true")
    info.set_defaults(func=cmd_info)

    dump = sub.add_parser("dump", help="list all metadata tags")
    dump.add_argument("files", nargs="+")
    dump.add_argument("--ifd", action="append", choices=["IFD0", "EXIF", "GPS", "Interop", "IFD1", "MakerNote", "XMP"])
    dump.add_argument("--json", action="store_true")
    dump.set_defaults(func=cmd_dump)

    get = sub.add_parser("get", help="read one or more tags")
    get.add_argument("file")
    get.add_argument("tags", nargs="+")
    get.add_argument("--json", action="store_true")
    get.set_defaults(func=cmd_get)

    setp = sub.add_parser("set", help="write tags (TAG=VALUE)")
    setp.add_argument("file")
    setp.add_argument("assignments", nargs="+")
    setp.add_argument("--out")
    setp.add_argument("--backup", action="store_true")
    setp.set_defaults(func=cmd_set)

    delete = sub.add_parser("delete", help="delete tags")
    delete.add_argument("file")
    delete.add_argument("tags", nargs="+")
    delete.add_argument("--out")
    delete.add_argument("--backup", action="store_true")
    delete.set_defaults(func=cmd_delete)

    strip = sub.add_parser("strip", help="remove all metadata segments")
    strip.add_argument("file")
    strip.add_argument("--keep-icc", action="store_true")
    strip.add_argument("--out")
    strip.add_argument("--backup", action="store_true")
    strip.set_defaults(func=cmd_strip)

    seg = sub.add_parser("segments", help="inspect or edit JPEG segments")
    seg.add_argument("file")
    seg.add_argument("--remove", type=int, action="append")
    seg.add_argument("--add-comment")
    seg.add_argument("--extract", nargs=2, metavar=("INDEX", "OUT"))
    seg.add_argument("--out")
    seg.add_argument("--backup", action="store_true")
    seg.add_argument("--json", action="store_true")
    seg.set_defaults(func=cmd_segments)

    exp = sub.add_parser("export", help="export a metadata-only JSON bundle")
    exp.add_argument("file")
    exp.add_argument("--out", "-o")
    exp.set_defaults(func=cmd_export_metadata)

    imp = sub.add_parser("import", help="overlay a JSON metadata bundle on JPEG/TIFF")
    imp.add_argument("file")
    imp.add_argument("bundle")
    imp.add_argument("--out", "-o")
    imp.add_argument("--mode", choices=["replace", "fill"], default="replace")
    imp.set_defaults(func=cmd_import_metadata)

    rec = sub.add_parser("reconstruct", help="metadata-overlay reconstruction from JSON")
    rec.add_argument("file")
    rec.add_argument("bundle")
    rec.add_argument("--out", "-o")
    rec.add_argument("--mode", choices=["replace", "fill"], default="replace")
    rec.set_defaults(func=cmd_reconstruct)

    lens = sub.add_parser("lens", help="show optional Lensfun camera/lens info")
    lens.add_argument("file")
    lens.set_defaults(func=cmd_lens)

    val = sub.add_parser("validate", help="originality / consistency report")
    val.add_argument("files", nargs="+")
    val.add_argument("--json", action="store_true")
    val.set_defaults(func=cmd_validate)

    xmp = sub.add_parser("xmp", help="read or write XMP properties")
    xmp.add_argument("file")
    xmp.add_argument("--get", action="append")
    xmp.add_argument("--set", action="append")
    xmp.add_argument("--delete", action="append")
    xmp.add_argument("--out")
    xmp.add_argument("--backup", action="store_true")
    xmp.add_argument("--json", action="store_true")
    xmp.set_defaults(func=cmd_xmp)

    gp = sub.add_parser("gps", help="show, convert or set GPS coordinates")
    gp.add_argument("file")
    gp.add_argument("--set", dest="set_gps")
    gp.add_argument("--datum", default="wgs84", choices=["wgs84", "gcj02", "bd09"])
    gp.add_argument("--to", choices=["wgs84", "gcj02", "bd09"])
    gp.add_argument("--map", action="append", choices=list(gps.PROVIDERS))
    gp.add_argument("--zoom", type=int, default=15)
    gp.add_argument("--open", action="store_true")
    gp.add_argument("--html")
    gp.add_argument("--out")
    gp.add_argument("--backup", action="store_true")
    gp.set_defaults(func=cmd_gps)

    tpl = sub.add_parser("template", help="metadata templates and text stamps")
    tpl.add_argument("action", choices=["list", "save", "apply", "stamp"])
    tpl.add_argument("file", nargs="?")
    tpl.add_argument("files", nargs="*")
    tpl.add_argument("--template")
    tpl.add_argument("--text")
    tpl.add_argument("--out")
    tpl.add_argument("--sequence", type=int)
    tpl.add_argument("--apply", action="store_true")
    tpl.set_defaults(func=cmd_template)

    batch = sub.add_parser("batch", help="batch export, rename, sort or template")
    batch.add_argument("path")
    batch.add_argument("--csv")
    batch.add_argument("--json-out", dest="json_out")
    batch.add_argument("--profile")
    batch.add_argument("--rename")
    batch.add_argument("--sort-by", choices=["date", "camera", "model", "lens", "month"])
    batch.add_argument("--sort-root")
    batch.add_argument("--template")
    batch.add_argument("--apply", action="store_true")
    batch.add_argument("--move", action="store_true")
    batch.add_argument("--no-recursive", action="store_true")
    batch.add_argument("--json", action="store_true")
    batch.set_defaults(func=cmd_batch)

    gui = sub.add_parser("gui", help="launch the Tkinter editor")
    gui.add_argument("file", nargs="?")
    gui.set_defaults(func=cmd_gui)

    web = sub.add_parser("webui", help="launch the WebView2 desktop UI")
    web.add_argument("file", nargs="?")
    web.add_argument("--no-browser", action="store_true")
    web.add_argument("--port", type=int, default=0)
    web.set_defaults(func=cmd_webui)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MetadataError as exc:
        return _error(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
