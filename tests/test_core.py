from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_TMP_ROOT = Path(__file__).resolve().parent / "_tmp"
_TMP_ROOT.mkdir(exist_ok=True)


_COUNTER = [0]


def new_dir() -> Path:
    _COUNTER[0] += 1
    path = _TMP_ROOT / ("t%03d" % _COUNTER[0])
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def tempdir():
    path = new_dir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

from easyexif import Jpeg, Metadata, Tiff, Xmp, validate
from easyexif import gps
from easyexif.jpeg import parse_mpf
from easyexif.batch import BUILTIN_PROFILES, Profile, export_csv, rename, sort_into
from easyexif.makernote import MakerField, MakerNote, _encode_ifd, parse_makernote
from easyexif.metadata import preview_value
from easyexif.tags import ASCII, RATIONAL, SHORT, SRATIONAL, UNDEFINED
from easyexif.template import Template, render_stamp, builtin_templates


def make_jpeg(path: Path, size=(640, 480), color=(120, 140, 160)) -> Path:
    from PIL import Image
    im = Image.new("RGB", size, color)
    # add some structure so histogram/thumbnail checks are meaningful
    for x in range(0, size[0], 16):
        for y in range(0, size[1], 16):
            im.putpixel((x, y), (x % 255, y % 255, (x + y) % 255))
    im.save(path, quality=90)
    return path


def make_exif(thumbnail: bool = True) -> Tiff:
    t = Tiff("<")
    t.set("IFD0", 0x010F, "Canon", ASCII)
    t.set("IFD0", 0x0110, "Canon EOS R5", ASCII)
    t.set("IFD0", 0x0132, "2024:05:01 10:20:30", ASCII)
    t.set("IFD0", 0x0112, 1, SHORT)
    t.set("EXIF", 0x9000, b"0232", UNDEFINED)
    t.set("EXIF", 0x9003, "2024:05:01 10:20:30", ASCII)
    t.set("EXIF", 0x829A, (1, 250), RATIONAL)
    t.set("EXIF", 0x829D, (28, 10), RATIONAL)
    t.set("EXIF", 0x8827, 100, SHORT)
    t.set("EXIF", 0x920A, (50, 1), RATIONAL)
    t.set("EXIF", 0x9209, 16, SHORT)
    t.set("EXIF", 0xA001, 1, SHORT)
    t.set("EXIF", 0xA002, 640, 4)
    t.set("EXIF", 0xA003, 480, 4)
    t.set("EXIF", 0xA434, "RF24-70mm F2.8 L IS USM", ASCII)
    t.set("EXIF", 0x8822, 3, SHORT)
    t.set("GPS", 0x0000, b"\x02\x03\x00\x00")
    t.set("GPS", 0x0001, "N", ASCII)
    t.set("GPS", 0x0002, [(31, 1), (13, 1), (30, 1)], RATIONAL)
    t.set("GPS", 0x0003, "E", ASCII)
    t.set("GPS", 0x0004, [(121, 1), (28, 1), (0, 1)], RATIONAL)
    if thumbnail:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (160, 120), (10, 20, 30)).save(buf, "JPEG")
        t.thumbnail = buf.getvalue()
    return t


class TiffTests(unittest.TestCase):
    def test_roundtrip_all_ifds(self):
        t = make_exif()
        data = t.to_bytes()
        u = Tiff.parse(data)
        self.assertEqual(u.text("IFD0", 0x0110), "Canon EOS R5")
        self.assertEqual(u.get("EXIF", 0x8827), 100)
        self.assertEqual(u.text("EXIF", 0x9003), "2024:05:01 10:20:30")
        self.assertEqual(u.get("EXIF", 0x829D), (28, 10))
        self.assertIsNotNone(u.get("GPS", 0x0002))
        self.assertIsNotNone(u.thumbnail)
        self.assertEqual(u.warnings, [])

    def test_modify_after_roundtrip(self):
        t = Tiff.parse(make_exif().to_bytes())
        t.set("EXIF", 0xA434, "RF70-200mm F2.8 L IS USM", ASCII)
        u = Tiff.parse(t.to_bytes())
        self.assertEqual(u.text("EXIF", 0xA434), "RF70-200mm F2.8 L IS USM")
        self.assertEqual(u.get("EXIF", 0x8827), 100)

    def test_unknown_tag_preserved(self):
        t = make_exif()
        t.set("IFD0", 0xC7A1, b"\x01\x02\x03\x04", UNDEFINED)
        u = Tiff.parse(t.to_bytes())
        self.assertEqual(u.get("IFD0", 0xC7A1), b"\x01\x02\x03\x04")

    def test_ifd1_removed_without_thumbnail(self):
        t = Tiff("<")
        t.set("IFD0", 0x010F, "Canon", ASCII)
        t.ifd("IFD1").set(0x0103, 6, SHORT)
        t.ifd("IFD1").set(0x0201, 1234, 4)
        t.ifd("IFD1").set(0x0202, 5678, 4)
        u = Tiff.parse(t.to_bytes())
        self.assertNotIn(0x0201, u.ifds.get("IFD1").entries)
        self.assertNotIn(0x0202, u.ifds.get("IFD1").entries)

    def test_big_endian(self):
        t = Tiff(">")
        t.set("IFD0", 0x010F, "Nikon", ASCII)
        t.set("EXIF", 0x829D, (28, 10), RATIONAL)
        u = Tiff.parse(t.to_bytes())
        self.assertEqual(u.endian, ">")
        self.assertEqual(u.text("IFD0", 0x010F), "Nikon")
        self.assertEqual(u.get("EXIF", 0x829D), (28, 10))


class JpegTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = new_dir()
        self.path = make_jpeg(self.tmp_path / "photo.jpg")

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def test_segments_and_scan_preserved(self):
        original = self.path.read_bytes()
        j = Jpeg.parse(original)
        scan = j.tail
        data = j.to_bytes()
        self.assertEqual(data[:2], b"\xff\xd8")
        self.assertIn(scan, data)

    def test_inject_exif_xmp_and_read(self):
        j = Jpeg.parse(self.path.read_bytes())
        j.set_exif_payload(make_exif().to_bytes())
        x = Xmp()
        x.set("xmp:CreatorTool", "EasyExif test")
        j.set_xmp_packet(x.to_bytes())
        self.path.write_bytes(j.to_bytes())
        m = Metadata.read(self.path)
        self.assertEqual(m.get_text("Model"), "Canon EOS R5")
        self.assertEqual(m.get_text("ExposureTime"), "1/250 s")
        self.assertEqual(m.info.width, 640)
        self.assertEqual(m.xmp.get("xmp:CreatorTool"), "EasyExif test")
        self.assertAlmostEqual(m.gps()["latitude"], 31.225, places=4)

    def test_zero_metadata_strip(self):
        j = Jpeg.parse(self.path.read_bytes())
        j.set_exif_payload(make_exif().to_bytes())
        j.insert(0xFE, b"hello")
        self.path.write_bytes(j.to_bytes())
        m = Metadata.read(self.path)
        m.clear_metadata()
        m.save()
        m2 = Metadata.read(self.path)
        self.assertFalse(m2.jpeg.exif_segment())
        self.assertIsNone(m2.tiff)
        self.assertTrue(m2.jpeg.dimensions())


class NaturalValueTests(unittest.TestCase):
    def setUp(self):
        self.meta = Metadata(new_dir() / "virtual.jpg")
        self.meta.tiff = make_exif(thumbnail=False)
        self.meta.tiff.set("EXIF", 0x9202, (297, 100), RATIONAL)
        self.meta.tiff.set("EXIF", 0x9201, (7966, 1000), SRATIONAL)

    def tearDown(self):
        shutil.rmtree(self.meta.path.parent, ignore_errors=True)

    def test_fnumber_updates_aperture_value(self):
        self.meta.set("FNumber", "f/3.5")
        self.assertEqual(self.meta.get_text("FNumber"), "f/3.5")
        self.assertEqual(self.meta.get_text("ApertureValue"), "f/3.5")
        self.assertEqual(self.meta.exposure()["aperture"], "f/3.5")

    def test_exposure_time_updates_shutter_speed(self):
        self.meta.set("ExposureTime", "1/500")
        self.assertEqual(self.meta.get_text("ExposureTime"), "1/500 s")
        self.assertEqual(self.meta.get_text("ShutterSpeedValue"), "1/500 s")
        self.assertEqual(self.meta.exposure()["shutter"], "1/500 s")

    def test_raw_apex_remains_apex(self):
        self.meta.set("ApertureValue", "3.5")
        self.assertEqual(self.meta.get_text("ApertureValue"), "f/3.4")
        self.assertEqual(self.meta.get_text("FNumber"), "f/2.8")

    def test_adding_fnumber_updates_existing_apex(self):
        self.meta.delete("FNumber")
        self.meta.set("FNumber", "2.0")
        self.assertEqual(self.meta.get_text("FNumber"), "f/2")
        self.assertEqual(self.meta.get_text("ApertureValue"), "f/2")

    def test_preview_returns_natural_and_derived(self):
        aperture = preview_value("EXIF.FNumber", "f/3.5")
        self.assertEqual(aperture["display"], "f/3.5")
        self.assertEqual(aperture["derived"][0]["name"], "ApertureValue")
        self.assertAlmostEqual(float(aperture["derived"][0]["value"]), 3.6147, places=3)

        shutter = preview_value("EXIF.ExposureTime", "1/500")
        self.assertEqual(shutter["display"], "1/500 s")
        self.assertEqual(shutter["derived"][0]["name"], "ShutterSpeedValue")
        self.assertAlmostEqual(float(shutter["derived"][0]["value"]), 8.9658, places=3)

    def test_technical_rows_are_readonly(self):
        rows = {row["name"]: row for row in self.meta.rows() if row["ifd"] == "EXIF"}
        self.assertTrue(rows["ApertureValue"]["readonly"])
        self.assertEqual(rows["ApertureValue"]["technical"], "APEX 2.97")
        self.assertTrue(rows["ShutterSpeedValue"]["readonly"])
        self.assertFalse(rows["FNumber"]["readonly"])

    def test_exposure_falls_back_to_apex(self):
        self.meta.delete("FNumber")
        self.meta.delete("ExposureTime")
        self.assertEqual(self.meta.exposure()["aperture"], "f/2.8")
        self.assertEqual(self.meta.exposure()["shutter"], "1/250 s")


class GpsTests(unittest.TestCase):
    def test_parse_formats(self):
        for text in ("31.225", "31 13 30 N", "31d13'30\"N", "N31 13 30"):
            self.assertAlmostEqual(gps.parse_coordinate(text), 31.225, places=4)
        self.assertAlmostEqual(gps.parse_coordinate("121 28 0 E"), 121.4667, places=4)
        self.assertAlmostEqual(gps.parse_coordinate("31 13 30 S"), -31.225, places=4)

    def test_datum_roundtrip(self):
        lat, lon = 39.9087, 116.3975
        glat, glon = gps.wgs84_to_gcj02(lat, lon)
        self.assertNotAlmostEqual(glat, lat, places=4)
        back = gps.gcj02_to_wgs84(glat, glon)
        self.assertAlmostEqual(back[0], lat, places=6)
        self.assertAlmostEqual(back[1], lon, places=6)
        blat, blon = gps.wgs84_to_bd09(lat, lon)
        back2 = gps.bd09_to_wgs84(blat, blon)
        self.assertAlmostEqual(back2[0], lat, places=5)
        self.assertAlmostEqual(back2[1], lon, places=5)

    def test_map_urls(self):
        for provider in gps.PROVIDERS:
            url = gps.map_url(provider, 31.2, 121.4)
            self.assertTrue(url.startswith("https://"), provider)


class XmpTests(unittest.TestCase):
    def test_new_packet(self):
        x = Xmp()
        x.set("dc:title", ["Hello", "World"])
        x.set("xmp:CreatorTool", "EasyExif")
        self.assertTrue(x.exists)
        y = Xmp(x.to_bytes())
        self.assertEqual(y.get("xmp:CreatorTool"), "EasyExif")
        self.assertEqual(y.get("dc:title"), ["Hello", "World"])

    def test_preserves_unknown(self):
        raw = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
               'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
               '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
               'xmlns:custom="http://example.com/ns/1.0/">'
               '<dc:format>image/jpeg</dc:format>'
               '<custom:Thing>keep me</custom:Thing>'
               '</rdf:Description></rdf:RDF></x:xmpmeta>')
        x = Xmp(raw)
        x.set("dc:title", "New title")
        y = Xmp(x.to_bytes())
        self.assertEqual(y.get("custom:Thing"), "keep me")
        self.assertEqual(y.get("dc:title"), "New title")

    def test_delete(self):
        x = Xmp()
        x.set("dc:title", "A")
        self.assertTrue(x.delete("dc:title"))
        self.assertIsNone(Xmp(x.to_bytes()).get("dc:title"))


class MakerNoteTests(unittest.TestCase):
    def test_canon_reencode_offsets(self):
        fields = [
            MakerField(0x0006, "ImageType", ASCII, 20, "Canon EOS R5", b""),
            MakerField(0x0007, "FirmwareVersion", ASCII, 8, "1.0.0", b""),
            MakerField(0x0095, "LensModel", ASCII, 20, "RF24-70mm F2.8", b""),
        ]
        raw = _encode_ifd(fields, 0, "<", 0, b"")
        note = parse_makernote("Canon", raw, "<", 0)
        self.assertIsNotNone(note)
        self.assertTrue(note.encodable)
        moved = note.encode(500)
        again = parse_makernote("Canon", moved, "<", 500)
        self.assertEqual(again.get("LensModel"), "RF24-70mm F2.8")
        self.assertEqual(again.get("FirmwareVersion"), "1.0.0")

    def test_unknown_note_kept(self):
        t = make_exif()
        t.set("EXIF", 0x927C, b"\xde\xad\xbe\xef" * 8, UNDEFINED)
        u = Tiff.parse(t.to_bytes())
        self.assertEqual(u.get("EXIF", 0x927C), b"\xde\xad\xbe\xef" * 8)


class TemplateTests(unittest.TestCase):
    def test_stamp(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "a.jpg")
            m = Metadata.read(path)
            m.tiff = make_exif(thumbnail=False)
            out = render_stamp("[[EXIF.DateTimeOriginal {YYYY-MM-DD}]] "
                               "[[IFD0.Model {'Unknown Model'}]] "
                               "[[EXIF.LensModel {Unknown Lens}]]", m)
            self.assertEqual(out, "2024-05-01 Canon EOS R5 RF24-70mm F2.8 L IS USM")

    def test_missing_default(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "b.jpg")
            m = Metadata.read(path)
            out = render_stamp("[[IFD0.Model {'no model'}]]", m)
            self.assertEqual(out, "no model")

    def test_template_excludes_pointers(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "d.jpg")
            j = Jpeg.parse(path.read_bytes())
            j.set_exif_payload(make_exif().to_bytes())
            path.write_bytes(j.to_bytes())
            tpl = Template.from_file(path)
            self.assertNotIn("ExifIFDPointer", tpl.exif)
            self.assertNotIn("JPEGInterchangeFormat", tpl.exif)
            self.assertFalse(any(k.startswith("IFD1.") for k in tpl.exif))

    def test_template_apply(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "c.jpg")
            m = Metadata.read(path)
            tpl = builtin_templates()["copyright"]
            n = tpl.apply(m)
            self.assertGreater(n, 0)
            self.assertEqual(m.get_text("Artist"), "Your Name")
            m.save()
            m2 = Metadata.read(path)
            self.assertEqual(m2.get_text("Copyright"), "© Your Name")


class MpfTests(unittest.TestCase):
    def test_inline_number_of_images(self):
        def entry(tag, typ, count, payload):
            return struct.pack("<HHI", tag, typ, count) + payload.ljust(4, b"\0")

        header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
        entries = [
            entry(0xB000, 7, 4, b"0100"),
            entry(0xB001, 4, 1, struct.pack("<I", 2)),
            entry(0xB002, 7, 32, struct.pack("<I", 8 + 2 + 3 * 12 + 4)),
        ]
        ifd = struct.pack("<H", len(entries)) + b"".join(entries) + struct.pack("<I", 0)
        body = header + ifd
        body += b"\0" * (50 - len(body)) + b"\0" * 32
        parsed = parse_mpf(body)
        self.assertEqual(parsed["declared_images"], 2)
        self.assertEqual(len(parsed["images"]), 2)


class ValidateTests(unittest.TestCase):
    def test_camera_like_file(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "v.jpg")
            j = Jpeg.parse(path.read_bytes())
            j.set_exif_payload(make_exif().to_bytes())
            path.write_bytes(j.to_bytes())
            report = validate(path)
            self.assertEqual(len(report.checks), 13)
            self.assertIn(report.score, (1, 2, 3, 4, 5))
            statuses = {c.key: c.status for c in report.checks}
            self.assertEqual(statuses["exif"], "Pass")
            self.assertEqual(statuses["software"], "Pass")
            self.assertIn("disclaimer", report.to_dict())
            self.assertIn("不能证明", report.render())
            legacy = next(c for c in report.checks if c.key == "legacy")
            self.assertEqual(legacy.title, "其他编辑器痕迹")

    def test_camera_firmware_is_not_an_editor(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "sony.jpg")
            j = Jpeg.parse(path.read_bytes())
            exif = make_exif()
            exif.set("IFD0", 0x010F, "SONY", ASCII)
            exif.set("IFD0", 0x0110, "ILCE-6300", ASCII)
            exif.set("IFD0", 0x0131, "ILCE-6300 v2.01", ASCII)
            j.set_exif_payload(exif.to_bytes())
            path.write_bytes(j.to_bytes())
            report = validate(path)
            statuses = {c.key: c.status for c in report.checks}
            self.assertEqual(statuses["software"], "Pass")
            self.assertIn("相机固件", next(c.detail for c in report.checks
                                          if c.key == "software"))

    def test_no_exif_is_unknown(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "plain.jpg")
            report = validate(path)
            self.assertFalse(report.available)
            self.assertIsNone(report.score)
            data = report.to_dict()
            self.assertIsNone(data["score"])
            self.assertEqual(data["rating"], "未知")
            self.assertIn("未知", report.render())
            self.assertEqual(len(data["checks"]), 13)

    def test_software_detected(self):
        with tempdir() as tmp:
            path = make_jpeg(Path(tmp) / "edited.jpg")
            j = Jpeg.parse(path.read_bytes())
            exif = make_exif()
            exif.set("IFD0", 0x0131, "Adobe Photoshop 25.0", ASCII)
            j.set_exif_payload(exif.to_bytes())
            j.insert(0xFE, b"Edited with GIMP")
            path.write_bytes(j.to_bytes())
            report = validate(path)
            statuses = {c.key: c.status for c in report.checks}
            self.assertEqual(statuses["software"], "Fail")
            self.assertLessEqual(report.score, 2)


class BatchTests(unittest.TestCase):
    def test_csv_and_planning(self):
        with tempdir() as tmp:
            tmp = Path(tmp)
            paths = []
            for i in range(2):
                p = make_jpeg(tmp / ("img%d.jpg" % i))
                j = Jpeg.parse(p.read_bytes())
                j.set_exif_payload(make_exif(thumbnail=False).to_bytes())
                p.write_bytes(j.to_bytes())
                paths.append(p)
            out = tmp / "report.csv"
            res = export_csv(paths, out, BUILTIN_PROFILES["detailed"])
            self.assertEqual(res["rows"], 2)
            text = out.read_text(encoding="utf-8-sig")
            self.assertIn("Canon EOS R5", text)
            plan = rename(paths, "{date}_{seq:03d}.{ext}", dry_run=True)
            self.assertTrue(plan[0]["dst"].endswith("20240501_001.jpg"))
            plan = sort_into(paths, tmp / "sorted", by="date", dry_run=True)
            self.assertIn("2024", plan[0]["dst"])

    def test_xpt_hex_tag_parsing(self):
        with tempdir() as tmp:
            p = Path(tmp) / "p.xpt"
            p.write_text("# NAME:test #\n2,9003\n1,112\n", encoding="utf-8")
            prof = Profile.load(p)
            self.assertEqual(prof.columns[0].tag, 0x9003)
            self.assertEqual(prof.columns[1].tag, 0x0112)

    def test_profile_roundtrip(self):
        with tempdir() as tmp:
            p = Profile.load(Path(tmp) / "x.xpt") if False else BUILTIN_PROFILES["gps"]
            out = p.to_xpt(Path(tmp) / "gps.xpt")
            q = Profile.load(out)
            self.assertEqual(len(q.columns), len(p.columns))


if __name__ == "__main__":
    unittest.main()
