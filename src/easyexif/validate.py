"""Originality / consistency checks for photo metadata.

Each test returns one of Missing / Pass / Uncertain / Suspect / Fail.  The
checks are evidence based heuristics, not a cryptographic proof that a file is
an unedited camera original; the report says so explicitly.
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .jpeg import MPF_HEADER, Jpeg
from .metadata import Metadata, MetadataError, parse_exif_datetime
from .tags import rational_to_float

MISSING, PASS, UNCERTAIN, SUSPECT, HIGH_SUSPECT, FAIL = (
    "Missing", "Pass", "Uncertain", "Suspect", "HighSuspect", "Fail")

STATUS_ZH = {MISSING: "缺失", PASS: "通过", UNCERTAIN: "未知",
             SUSPECT: "怀疑", HIGH_SUSPECT: "高度怀疑", FAIL: "不通过"}

SOFTWARE_TRACES = [
    ("Photoshop", "Adobe Photoshop"), ("Lightroom", "Adobe Lightroom"),
    ("GIMP", "GIMP"), ("Capture One", "Capture One"),
    ("Snapseed", "Snapseed"), ("Meitu", "美图"), ("美图", "美图"),
    ("Microsoft Windows", "Windows"), ("Windows Photo", "Windows 照片"),
    ("gd-jpeg", "gd-jpeg"), ("ImageMagick", "ImageMagick"),
    ("Pixelmator", "Pixelmator"), ("Affinity", "Affinity"),
    ("ACDSee", "ACDSee"), ("Picasa", "Picasa"),
    ("Instagram", "Instagram"), ("WeChat", "微信"), ("微信", "微信"),
    ("Canva", "Canva"), ("Paint.NET", "Paint.NET"),
    ("SnapSeed", "Snapseed"), ("VSCO", "VSCO"), ("PicsArt", "PicsArt"),
    ("Adobe", "Adobe"), ("Apple", "Apple Photos"),
]

RATING_TEXT = {
    1: "文件中的证据表明该图像曾被发现编辑痕迹，并非相机原图",
    2: "文件中的证据表明该图像极可能曾经被编辑",
    3: "文件中的证据不足以准确判断图像的编辑历史",
    4: "未发现明显编辑痕迹，可能是来自未知型号相机的原图",
    5: "通过全部原始性检测，极可能为相机原图",
}

DISCLAIMER = (
    "本报告是基于文件结构、软件字段和元数据一致性的启发式检查，"
    "不能证明图像未经编辑，也不能作为司法鉴定或取证结论。"
    "文件可能被有意清洗或伪造；相机固件、手机系统、社交平台写入的正常字段"
    "也可能造成误报或漏报。1–5 级仅表示证据强弱：5 级不代表绝对原图，"
    "1 级也不代表一定篡改。"
)


def _has_editor(meta: Metadata) -> bool:
    texts = [
        meta.get_text("IFD0.Software", ""),
        meta.get_text("IFD0.ProcessingSoftware", ""),
        meta.get_text("IFD0.HostComputer", ""),
        str(meta.xmp.get("xmp:CreatorTool") or ""),
        str(meta.xmp.get("tiff:Software") or ""),
    ]
    return any(any(tok.lower() in text.lower() for tok, _ in SOFTWARE_TRACES)
               for text in texts if text)


@dataclass
class Check:
    key: str
    title: str
    status: str
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "status": self.status,
                "status_zh": STATUS_ZH[self.status], "detail": self.detail,
                "evidence": self.evidence}


@dataclass
class Report:
    path: str
    checks: list[Check] = field(default_factory=list)
    score: int | None = 3
    summary: str = ""
    available: bool = True

    def add(self, key: str, title: str, status: str, detail: str,
            evidence: list[str] | None = None) -> None:
        self.checks.append(Check(key, title, status, detail, evidence or []))

    def finalize(self) -> "Report":
        if not self.available:
            self.score = None
            self.summary = "文件中没有 EXIF/TIFF 数据，无法评估原图可信度"
            return self
        fails = sum(1 for c in self.checks if c.status == FAIL)
        high = sum(1 for c in self.checks if c.status == HIGH_SUSPECT)
        suspects = sum(1 for c in self.checks if c.status == SUSPECT)
        uncertain = sum(1 for c in self.checks if c.status == UNCERTAIN)
        passes = sum(1 for c in self.checks if c.status == PASS)
        if fails >= 2 or (fails >= 1 and high >= 1):
            score = 1
        elif fails == 1 or high >= 1 or suspects >= 2:
            score = 2
        elif suspects == 1 or uncertain >= 2:
            score = 3
        elif uncertain == 1:
            score = 4
        elif passes >= 6:
            score = 5
        else:
            score = 4
        self.score = score
        self.summary = RATING_TEXT[score]
        return self

    def to_dict(self) -> dict[str, Any]:
        rating = ("%d 级" % self.score) if self.score is not None else "未知"
        return {"path": self.path, "available": self.available,
                "score": self.score, "rating": rating,
                "summary": self.summary, "disclaimer": DISCLAIMER,
                "checks": [c.to_dict() for c in self.checks]}

    def render(self) -> str:
        lines = [DISCLAIMER, ""]
        if self.score is None:
            lines.extend(["原图可信度: 未知  %s" % self.summary, ""])
        else:
            lines.extend(["原图可信度: %d 级  %s" % (self.score, self.summary), ""])
        width = max((len(c.title) for c in self.checks), default=10)
        for c in self.checks:
            lines.append("%-*s  %-10s %s" % (width, c.title, c.status, c.detail))
        return "\n".join(lines)


def validate(path: str | os.PathLike) -> Report:
    meta = Metadata.read(path)
    report = Report(str(path))
    # Without an EXIF/TIFF directory there is no evidence to grade.  The
    # individual checks still run so the UI can explain what is missing, but
    # the report must stay "unknown" rather than pretending to be a 5-level
    # camera original.
    report.available = meta.tiff is not None
    with open(path, "rb") as fh:
        data = fh.read()

    _check_structure(report, meta, data)
    _check_software(report, meta, data)
    _check_makernote(report, meta)
    _check_compression(report, meta)
    _check_internal(report, meta)
    _check_external(report, meta)
    _check_mpf(report, meta)
    _check_flashpix(report, meta)
    _check_legacy(report, meta, data)
    _check_histogram(report, meta, path)
    _check_aspect(report, meta)
    _check_embedded(report, meta, path)
    _check_size(report, meta)
    return report.finalize()


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def _check_structure(report: Report, meta: Metadata, data: bytes) -> None:
    problems = list(meta.warnings)
    if meta.tiff is None:
        report.add("exif", "EXIF 格式检验", MISSING,
                   "文件中没有 EXIF/TIFF 数据", ["no APP1 Exif segment"])
        return
    required = [("IFD0", 0x010F, "Make"), ("IFD0", 0x0110, "Model"),
                ("EXIF", 0x9003, "DateTimeOriginal")]
    missing = [name for ifd, tag, name in required if meta.tiff.get(ifd, tag) in (None, "")]
    if missing:
        problems.append("缺少关键标签: " + ", ".join(missing))
    if meta.jpeg:
        if meta.jpeg.exif_segment() is None:
            problems.append("找不到 APP1 Exif 段")
        if not meta.jpeg.dimensions():
            problems.append("找不到 SOF 尺寸信息")
        if len(meta.jpeg.trailing) > 0:
            problems.append("EOI 之后存在 %d 字节附加数据" % len(meta.jpeg.trailing))
    if problems:
        report.add("exif", "EXIF 格式检验", SUSPECT if missing else UNCERTAIN,
                   "; ".join(problems[:6]), problems)
    else:
        report.add("exif", "EXIF 格式检验", PASS, "EXIF 结构完整，关键标签齐全")


def _looks_like_camera_software(meta: Metadata, text: str) -> bool:
    """Recognise firmware strings that cameras write into Software.

    A camera firmware value is not evidence of a third-party editor.  Match
    the body model first, then common firmware spellings and camera model
    prefixes.  The check stays conservative: unknown values still become
    Uncertain, just like before.
    """
    low = text.strip().lower()
    if not low:
        return False
    make = meta.get_text("IFD0.Make", "").strip().lower()
    model = meta.get_text("IFD0.Model", "").strip().lower()
    if model and model in low:
        return True
    if make and make in low and re.search(r"\b(?:firmware|ver\.?|version)\b", low):
        return True
    if re.search(r"\b(?:firmware|ver\.?|version)\s*[:\-]?\s*\d", low):
        return True
    if re.search(r"\b(?:ilce|dsc|eos|nikon|finepix|om-d|e-m|gx|gh|dc-)[-_ ]?[a-z0-9]", low):
        return True
    return False


def _check_software(report: Report, meta: Metadata, data: bytes) -> None:
    hits: list[str] = []
    for ifd, tag, label in (("IFD0", 0x0131, "Software"), ("IFD0", 0x000B, "ProcessingSoftware"),
                            ("IFD0", 0x013C, "HostComputer")):
        text = meta.get_text("%s.%s" % (ifd, label), "")
        if text:
            hits.append("%s=%s" % (label, text))
    creator = meta.xmp.get("xmp:CreatorTool") or meta.xmp.get("tiff:Software")
    if creator:
        hits.append("XMP CreatorTool=%s" % creator)
    if meta.jpeg and meta.jpeg.iptc():
        iptc = meta.jpeg.iptc()
        for key in ("By-line", "Credit", "Source"):
            if iptc.get(key):
                hits.append("IPTC %s=%s" % (key, iptc[key]))
    com_hits = []
    if meta.jpeg:
        for s in meta.jpeg.segments:
            if s.marker == 0xEE and s.data.startswith(b"Adobe"):
                hits.append("APP14 Adobe 标记")
            if s.marker == 0xFE:
                text = s.data.decode("utf-8", "replace").strip()
                hits.append("COM=%s" % text[:60])
                if any(tok.lower() in text.lower() for tok, _ in SOFTWARE_TRACES):
                    com_hits.append(text[:60])
    for token, name in SOFTWARE_TRACES:
        if token.encode("utf-8", "replace") in data:
            hits.append("发现字符串 %s" % name)
            break
    known = [h for h in hits if any(tok.lower() in h.lower() for tok, _ in SOFTWARE_TRACES)]
    firmware = [h for h in hits
                if h not in known
                and h.startswith(("Software=", "ProcessingSoftware=",
                                  "HostComputer=", "XMP CreatorTool="))
                and _looks_like_camera_software(meta, h.split("=", 1)[1])]
    unknown = [h for h in hits if h not in known and h not in firmware]
    if known:
        report.add("software", "第三方软件数据", FAIL,
                   "当前图像曾被以下软件修改: "
                   + "; ".join(dict.fromkeys(known))[:300], list(dict.fromkeys(known)))
    elif firmware and not unknown:
        report.add("software", "第三方软件数据", PASS,
                   "发现相机固件字段，不构成第三方编辑证据: "
                   + "; ".join(dict.fromkeys(firmware))[:240], firmware)
    elif unknown:
        report.add("software", "第三方软件数据", UNCERTAIN,
                   "存在软件/主机字段但不在已知编辑器特征库中: "
                   + "; ".join(dict.fromkeys(unknown))[:240], unknown)
    else:
        report.add("software", "第三方软件数据", PASS, "未发现常见编辑软件写入的痕迹")


def _check_makernote(report: Report, meta: Metadata) -> None:
    if not meta.tiff:
        report.add("makernote", "厂商注释数据信度", MISSING, "没有 EXIF 数据")
        return
    if meta.tiff.makernote is None:
        if _has_editor(meta):
            report.add("makernote", "厂商注释数据信度", FAIL,
                       "相机本应写入厂商注释，但 MakerNote 缺失；可能被编辑软件移除")
        else:
            report.add("makernote", "厂商注释数据信度", PASS,
                       "文件没有厂商注释；该机型可能不写入 MakerNote，不构成异常")
        return
    note = meta.tiff.makernote
    make = meta.get_text("Make", "").lower()
    if note.maker == "Unknown":
        report.add("makernote", "厂商注释数据信度", UNCERTAIN,
                   "存在厂商注释数据，但无法识别厂商结构", ["offset=%d" % (note.offset_delta)])
        return
    detail = "识别为 %s 厂商注释，共 %d 个字段" % (note.maker, len(note.fields))
    if make and note.maker.lower() not in make:
        report.add("makernote", "厂商注释数据信度", SUSPECT,
                   detail + "，但与 Make 标签 (%s) 不一致" % make)
        return
    if note.warnings:
        report.add("makernote", "厂商注释数据信度", UNCERTAIN,
                   detail + "；" + "; ".join(note.warnings))
    else:
        report.add("makernote", "厂商注释数据信度", PASS, detail)


def _check_compression(report: Report, meta: Metadata) -> None:
    if not meta.jpeg:
        report.add("compression", "压缩指纹信度", MISSING, "仅对 JPEG 有效")
        return
    tables = meta.jpeg.quant_tables()
    if not tables:
        report.add("compression", "压缩指纹信度", MISSING, "未找到 DQT 量化表")
        return
    quality = match_libjpeg_quality(tables)
    adobe = any(s.marker == 0xEE and s.data.startswith(b"Adobe")
                for s in meta.jpeg.segments)
    editor = _has_editor(meta)
    if editor and (adobe or quality is not None):
        report.add("compression", "压缩指纹信度", FAIL,
                   "检测到编辑软件重编码特征 (Adobe APP14=%s, libjpeg=%s)"
                   % ("是" if adobe else "否", quality),
                   ["tables=%d" % len(tables)])
    elif quality is not None:
        report.add("compression", "压缩指纹信度", UNCERTAIN,
                   "量化表与 libjpeg 质量 %d 一致（常见于软件重新编码）" % quality,
                   ["tables=%d" % len(tables)])
    else:
        report.add("compression", "压缩指纹信度", PASS,
                   "量化表不是标准 libjpeg 表，更接近相机内编码特征")


def _check_internal(report: Report, meta: Metadata) -> None:
    if not meta.tiff:
        report.add("internal", "EXIF 数据内部一致性", MISSING, "没有 EXIF 数据")
        return
    issues: list[str] = []
    if meta.jpeg:
        dims = meta.jpeg.dimensions()
        px = meta.tiff.get("EXIF", 0xA002)
        py = meta.tiff.get("EXIF", 0xA003)
        if dims and isinstance(px, int) and isinstance(py, int):
            if (px, py) != dims:
                issues.append("PixelX/YDimension (%dx%d) 与 JPEG SOF (%dx%d) 不一致"
                              % (px, py, dims[0], dims[1]))
    orientation = meta.tiff.get("IFD0", 0x0112)
    if isinstance(orientation, int) and not 1 <= orientation <= 8:
        issues.append("Orientation 值 %d 超出 1–8" % orientation)
    iso = meta.tiff.get("EXIF", 0x8827)
    note_iso = meta.tiff.makernote.get("DerivedISO") if meta.tiff.makernote else None
    if iso is not None and note_iso is not None:
        iso_val = iso[0] if isinstance(iso, (list, tuple)) else iso
        try:
            if int(iso_val) != int(str(note_iso)):
                issues.append("EXIF ISO (%s) 与厂商注释 ISO (%s) 不一致" % (iso_val, note_iso))
        except (TypeError, ValueError):
            pass
    date_issue = False
    original = meta.tiff.text("EXIF", 0x9003, "")
    changed = meta.tiff.text("IFD0", 0x0132, "")
    digitized = meta.tiff.text("EXIF", 0x9004, "")
    if original:
        try:
            parse_exif_datetime(original)
        except MetadataError:
            issues.append("DateTimeOriginal 格式无法解析")
            date_issue = True
    if original and changed:
        try:
            if abs((parse_exif_datetime(changed) - parse_exif_datetime(original)).total_seconds()) > 60:
                issues.append("DateTime 与 DateTimeOriginal 不一致")
                date_issue = True
        except MetadataError:
            issues.append("DateTime 格式无法解析")
            date_issue = True
    if original and digitized:
        try:
            if abs((parse_exif_datetime(digitized) - parse_exif_datetime(original)).total_seconds()) > 86400:
                issues.append("DateTimeDigitized 与拍摄时间相差超过一天")
                date_issue = True
        except MetadataError:
            issues.append("DateTimeDigitized 格式无法解析")
            date_issue = True
    if meta.tiff.get("EXIF", 0x9000) is None:
        issues.append("缺少 ExifVersion")
    if issues:
        report.add("internal", "EXIF 数据内部一致性",
                   HIGH_SUSPECT if date_issue else SUSPECT,
                   "; ".join(issues), issues)
    else:
        report.add("internal", "EXIF 数据内部一致性", PASS, "尺寸、ISO 等关键字段未发现矛盾")


def _check_external(report: Report, meta: Metadata) -> None:
    if not meta.tiff:
        report.add("external", "EXIF 数据外部一致性", MISSING, "没有 EXIF 数据")
        return
    issues: list[str] = []
    original = meta.tiff.text("EXIF", 0x9003, "") or meta.tiff.text("IFD0", 0x0132, "")
    if original:
        try:
            captured = parse_exif_datetime(original).timestamp()
            mtime = os.path.getmtime(meta.path)
            if mtime + 86400 < captured:
                issues.append("文件修改时间早于拍摄时间超过一天")
        except (MetadataError, OSError, OverflowError):
            pass
    gps_date = meta.tiff.text("GPS", 0x001D, "")
    if gps_date and original:
        try:
            gd = datetime.strptime(gps_date.strip(), "%Y:%m:%d")
            od = parse_exif_datetime(original)
            if abs((gd - od).days) > 1:
                issues.append("GPS 日期与拍摄日期不一致")
        except (ValueError, MetadataError):
            issues.append("GPS 日期格式异常")
    if issues:
        report.add("external", "EXIF 数据外部一致性", SUSPECT, "; ".join(issues), issues)
    else:
        report.add("external", "EXIF 数据外部一致性", PASS, "拍摄时间与文件时间、GPS 日期一致")


def _check_mpf(report: Report, meta: Metadata) -> None:
    if not meta.jpeg:
        report.add("mpf", "MPF 数据信度", MISSING, "仅对 JPEG 有效")
        return
    mpf = meta.jpeg.mpf()
    if not mpf:
        report.add("mpf", "MPF 数据信度", PASS, "没有 MPF；单图 JPEG 不构成异常")
        return
    if "error" in mpf:
        # A malformed MPF header is a structure problem, not proof that the
        # image was edited.  Keep it distinct from an image edit finding.
        report.add("mpf", "MPF 数据信度", UNCERTAIN,
                   "MPF 结构无法完整解析: %s" % mpf["error"])
        return
    images = mpf.get("images", [])
    base = int(mpf.get("base_offset") or 0)
    issues = []
    parse_issue = False
    # MP Entry offsets are relative to the MP Endian field.  Some writers
    # use the MP Header start for the first image instead, so accept either
    # base when checking the file bounds.
    bases = {base}
    if base >= len(MPF_HEADER):
        bases.add(base - len(MPF_HEADER))
    for img in images:
        offset = int(img.get("offset") or 0)
        size = int(img.get("size") or 0)
        valid = any(0 <= b + offset and b + offset + size <= meta.raw_size
                    for b in bases)
        if not valid:
            issues.append("MPF 图像偏移/长度越过文件末尾")
            break
    declared = mpf.get("declared_images")
    if declared is not None and declared != len(images):
        if declared <= 0 or declared > 1000:
            issues.append("MPF 声明图像数异常 (%s)，可能是解析错误" % declared)
            parse_issue = True
        else:
            issues.append("声明 %s 张图像但解析到 %d 条 MP Entry"
                          % (declared, len(images)))
    if issues:
        status = UNCERTAIN if parse_issue else SUSPECT
        report.add("mpf", "MPF 数据信度", status, "; ".join(issues), issues)
    else:
        report.add("mpf", "MPF 数据信度", PASS,
                   "MPF 版本 %s，共 %d 张关联图像" % (mpf.get("version"), len(images)))


def _check_flashpix(report: Report, meta: Metadata) -> None:
    if not meta.tiff:
        report.add("flashpix", "FlashPix Ready 数据信度", MISSING, "没有 EXIF 数据")
        return
    version = meta.tiff.get("EXIF", 0xA000)
    if version is None:
        report.add("flashpix", "FlashPix Ready 数据信度", PASS,
                   "没有 FlashPix 扩展数据；不构成异常")
    elif isinstance(version, (bytes, bytearray)) and bytes(version).rstrip(b"\0") in (b"0100", b"0101"):
        report.add("flashpix", "FlashPix Ready 数据信度", PASS,
                   "FlashpixVersion=%s" % bytes(version).decode("ascii", "replace"))
    else:
        report.add("flashpix", "FlashPix Ready 数据信度", UNCERTAIN,
                   "FlashpixVersion 值异常: %r" % (version,))


def _check_legacy(report: Report, meta: Metadata, data: bytes) -> None:
    hits = []
    lower = data.lower()
    for marker, label in ((b"exiftool", "ExifTool"), (b"exif editor", "Exif Editor")):
        if marker in lower:
            hits.append("文件字节中出现 %s 标识" % label)
    if hits:
        report.add("legacy", "其他编辑器痕迹", FAIL,
                   "发现其他编辑器写入的标记: " + "; ".join(hits), hits)
    else:
        report.add("legacy", "其他编辑器痕迹", PASS,
                   "未发现 ExifTool、Exif Editor 等其他编辑器写入的标记")


def _check_histogram(report: Report, meta: Metadata, path: str) -> None:
    try:
        from PIL import Image
    except ImportError:
        report.add("histogram", "直方图信度", MISSING, "未安装 Pillow，跳过图像分析")
        return
    try:
        with Image.open(path) as im:
            hist = im.convert("L").histogram()
    except Exception as exc:
        report.add("histogram", "直方图信度", MISSING, "无法读取图像: %s" % exc)
        return
    total = sum(hist) or 1
    black = sum(hist[:8]) / total
    white = sum(hist[-8:]) / total
    mean = sum(i * h for i, h in enumerate(hist)) / total
    if black > 0.75 or white > 0.75:
        report.add("histogram", "直方图信度", SUSPECT,
                   "直方图严重截断 (黑 %.1f%%, 白 %.1f%%)" % (black * 100, white * 100))
    else:
        report.add("histogram", "直方图信度", PASS,
                   "直方图无严重截断 (黑 %.1f%%, 白 %.1f%%, 均值 %.1f)"
                   % (black * 100, white * 100, mean))


def _check_aspect(report: Report, meta: Metadata) -> None:
    w, h = meta.info.width, meta.info.height
    if not w or not h:
        report.add("aspect", "长宽比信度", MISSING, "无法获取图像尺寸")
        return
    ratio = w / h
    common = [(3 / 2, "3:2"), (4 / 3, "4:3"), (16 / 9, "16:9"),
              (1.0, "1:1"), (5 / 4, "5:4"), (7 / 5, "7:5"), (16 / 10, "16:10")]
    for value, label in common:
        if abs(ratio - value) < 0.01:
            report.add("aspect", "长宽比信度", PASS, "%dx%d 为常见 %s 比例" % (w, h, label))
            return
    report.add("aspect", "长宽比信度", UNCERTAIN,
               "%dx%d (%.3f) 不是常见相机画幅比例" % (w, h, ratio))


def _check_embedded(report: Report, meta: Metadata, path: str) -> None:
    thumb = meta.thumbnail()
    if not thumb:
        report.add("embedded", "内嵌图特征一致性", MISSING, "没有内嵌缩略图")
        return
    try:
        from PIL import Image
    except ImportError:
        report.add("embedded", "内嵌图特征一致性", MISSING, "未安装 Pillow，跳过内嵌图比较")
        return
    try:
        with Image.open(io.BytesIO(thumb)) as a, Image.open(path) as b:
            ga = a.convert("L").resize((64, 64))
            gb = b.convert("L").resize((64, 64))
            pa, pb = ga.tobytes(), gb.tobytes()
            diff = sum(abs(x - y) for x, y in zip(pa, pb)) / (64 * 64) / 255
    except Exception as exc:
        report.add("embedded", "内嵌图特征一致性", UNCERTAIN, "缩略图无法解码: %s" % exc)
        return
    if diff > 0.30:
        report.add("embedded", "内嵌图特征一致性", SUSPECT,
                   "内嵌缩略图与主图差异过大 (%.2f)" % diff, ["mean_abs_diff=%.3f" % diff])
    elif diff > 0.18:
        report.add("embedded", "内嵌图特征一致性", UNCERTAIN,
                   "缩略图与主图存在中等差异 (%.2f)" % diff)
    else:
        report.add("embedded", "内嵌图特征一致性", PASS,
                   "缩略图与主图内容一致 (差异 %.2f)" % diff)


def _check_size(report: Report, meta: Metadata) -> None:
    w, h = meta.info.width, meta.info.height
    if not w or not h:
        report.add("size", "图像尺寸信度", MISSING, "无法获取图像尺寸")
        return
    mp = w * h / 1_000_000
    if w < 640 or h < 480:
        report.add("size", "图像尺寸信度", SUSPECT, "%dx%d 尺寸过小，不似相机原图" % (w, h))
    elif mp < 0.8:
        report.add("size", "图像尺寸信度", UNCERTAIN, "仅 %.1f MP，可能是网络传输版本" % mp)
    else:
        report.add("size", "图像尺寸信度", PASS, "%dx%d (%.1f MP)" % (w, h, mp))


# ---------------------------------------------------------------------------
# JPEG quantization table fingerprint
# ---------------------------------------------------------------------------
LUMA = [
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
CHROMA = [
    17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99]


def libjpeg_table(base: list[int], quality: int) -> list[int]:
    quality = max(1, min(100, quality))
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    return [max(1, min(255, (v * scale + 50) // 100)) for v in base]


def match_libjpeg_quality(tables: list[list[int]]) -> int | None:
    luma = [t for t in tables if len(t) == 64]
    if not luma:
        return None
    for q in range(1, 101):
        if luma[0] == libjpeg_table(LUMA, q):
            return q
    # tolerate small differences caused by 16-bit DQT
    best, best_diff = None, 10 ** 9
    for q in range(1, 101):
        table = libjpeg_table(LUMA, q)
        diff = sum(abs(a - b) for a, b in zip(luma[0], table))
        if diff < best_diff:
            best, best_diff = q, diff
    if best is not None and best_diff <= 8:
        return best
    return None
