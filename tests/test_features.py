from __future__ import annotations

import json
import shutil
import struct
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from easyexif import Jpeg, Metadata, MetadataError, __version__
from easyexif.bundle import BundleError, export_bundle, import_bundle, load_bundle, write_bundle
from easyexif.lensdb import LensDatabase, lens_info
from easyexif.makernote import parse_makernote

SAMPLE = ROOT / "examples" / "sample.jpg"
TMP = Path(__file__).resolve().parent / "_tmp"
TMP.mkdir(exist_ok=True)
COUNTER = [0]


def new_dir() -> Path:
    COUNTER[0] += 1
    path = TMP / ("feature%03d" % COUNTER[0])
    path.mkdir(parents=True, exist_ok=True)
    return path


class BundleTests(unittest.TestCase):
    def test_export_import_marker_and_pixels(self):
        folder = new_dir()
        target = folder / "target.jpg"
        shutil.copyfile(SAMPLE, target)
        original = Jpeg.parse(target.read_bytes())
        meta = Metadata.read(SAMPLE)
        bundle = export_bundle(meta)
        bundle_path = folder / "meta.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

        out = folder / "out.jpg"
        result = import_bundle(Metadata.read(target), load_bundle(bundle_path), out)
        self.assertTrue(Path(result["output"]).exists())
        after = Metadata.read(out)
        self.assertEqual(after.get_text("IFD0.Software"), "EasyExif " + __version__)
        self.assertEqual(after.xmp.get("xmp:CreatorTool"), "EasyExif " + __version__)
        self.assertEqual(after.xmp.get("easyexif:Operation"), "metadata-overlay")
        self.assertTrue(after.xmp.get("easyexif:SourcePackageSHA256"))
        self.assertEqual(Jpeg.parse(out.read_bytes()).tail, original.tail)

    def test_no_blank_and_exi_rejected(self):
        folder = new_dir()
        blank = folder / "blank.json"
        blank.write_text(json.dumps({"schema": "easyexif.metadata/1"}), encoding="utf-8")
        with self.assertRaises(BundleError):
            load_bundle(blank)
        exi = folder / "template.exi"
        exi.write_bytes(b"not a real template")
        with self.assertRaises(BundleError):
            load_bundle(exi)

    def test_dimension_mismatch_rejected(self):
        folder = new_dir()
        source = Metadata.read(SAMPLE)
        bundle = export_bundle(source)
        target = folder / "small.jpg"
        with Image.open(SAMPLE) as im:
            im.resize((800, 533)).save(target)
        with self.assertRaises(BundleError):
            import_bundle(Metadata.read(target), bundle, folder / "out.jpg")


class RawReadTests(unittest.TestCase):
    def test_tiff_based_dng_is_readonly(self):
        folder = new_dir()
        source = Metadata.read(SAMPLE)
        dng = folder / "sample.dng"
        dng.write_bytes(source.tiff.to_bytes())
        meta = Metadata.read(dng)
        self.assertTrue(meta.readonly)
        self.assertEqual(meta.info.format, "DNG")
        self.assertEqual(meta.get_text("IFD0.Model"), "Canon EOS R5")
        with self.assertRaises(Exception):
            meta.set("Artist", "blocked")
        with self.assertRaises(Exception):
            meta.save()

    def test_embedded_preview_is_exposed(self):
        folder = new_dir()
        dng = folder / "preview.dng"
        dng.write_bytes(Metadata.read(SAMPLE).tiff.to_bytes() + SAMPLE.read_bytes())
        meta = Metadata.read(dng)
        preview = meta.preview_bytes()
        self.assertIsNotNone(preview)
        self.assertTrue(preview.startswith(b"\xff\xd8"))


class LensfunTests(unittest.TestCase):
    def test_match_camera_and_lens(self):
        folder = new_dir()
        (folder / "db.xml").write_text(
            "<lensdatabase>"
            "<camera><maker>Canon</maker><model>Canon EOS R5</model>"
            "<mount>Canon RF</mount><cropfactor>1.0</cropfactor></camera>"
            "<lens><maker>Canon</maker><model>RF24-70mm F2.8 L IS USM</model>"
            "<mount>Canon RF</mount><cropfactor>1.0</cropfactor>"
            "<focal value=\"24\"/><focal value=\"70\"/>"
            "<aperture value=\"2.8\"/></lens>"
            "</lensdatabase>",
            encoding="utf-8",
        )
        db = LensDatabase.load(folder)
        info = lens_info(Metadata.read(SAMPLE), db)
        self.assertTrue(info["available"])
        self.assertEqual(info["camera"]["model"], "Canon EOS R5")
        self.assertEqual(info["lens"]["model"], "RF24-70mm F2.8 L IS USM")
        self.assertEqual(info["category"], "标准")


class TiffWriteSafetyTests(unittest.TestCase):
    """A metadata edit must never cost the user their pixels."""

    @staticmethod
    def _pixels(path: Path) -> bytes:
        with Image.open(path) as im:
            return im.convert("RGB").tobytes()

    def test_pixels_survive_metadata_edit(self):
        folder = new_dir()
        image = Image.new("RGB", (48, 32))
        for x in range(48):
            for y in range(32):
                image.putpixel((x, y), (x * 5 % 256, y * 7 % 256, (x * y) % 256))
        for compression in ("raw", "tiff_lzw", "jpeg"):
            source = folder / ("src_%s.tif" % compression)
            options = {"quality": 92} if compression == "jpeg" else {}
            image.save(source, compression=compression, **options)
            before = self._pixels(source)
            meta = Metadata.read(source)
            meta.set("Software", "EasyExif")
            out = folder / ("out_%s.tif" % compression)
            meta.save(out)
            self.assertEqual(before, self._pixels(out), compression)
            self.assertEqual(Metadata.read(out).get_text("IFD0.Software"), "EasyExif")

    def test_multi_page_tiff_keeps_every_page(self):
        folder = new_dir()
        first = Image.new("RGB", (24, 18), (12, 130, 210))
        second = Image.new("RGB", (24, 18), (230, 90, 30))
        source = folder / "multi.tif"
        first.save(source, save_all=True, append_images=[second], compression="raw")
        meta = Metadata.read(source)
        meta.set("Software", "EasyExif")
        out = folder / "multi_out.tif"
        meta.save(out)
        with Image.open(out) as im:
            self.assertEqual(getattr(im, "n_frames", 1), 2)
            self.assertEqual(im.convert("RGB").tobytes(), first.tobytes())
            im.seek(1)
            self.assertEqual(im.convert("RGB").tobytes(), second.tobytes())

    def test_subifd_container_is_refused(self):
        folder = new_dir()
        data = bytearray(b"II*\x00\x08\x00\x00\x00")
        data += struct.pack("<H", 2)
        data += struct.pack("<HHI", 0x0100, 3, 1) + struct.pack("<H", 8) + b"\x00\x00"
        data += struct.pack("<HHI", 0x014A, 4, 1) + struct.pack("<I", 64)
        data += struct.pack("<I", 0)
        path = folder / "subifd.tif"
        path.write_bytes(bytes(data))
        with self.assertRaises(MetadataError):
            Metadata.read(path).save(folder / "out.tif")
        self.assertFalse((folder / "out.tif").exists())

    def test_out_of_range_strip_is_refused(self):
        folder = new_dir()
        data = bytearray(b"II*\x00\x08\x00\x00\x00")
        data += struct.pack("<H", 2)
        data += struct.pack("<HHI", 0x0111, 4, 1) + struct.pack("<I", 0x7FFFFF00)
        data += struct.pack("<HHI", 0x0117, 4, 1) + struct.pack("<I", 4096)
        data += struct.pack("<I", 0)
        path = folder / "broken.tif"
        path.write_bytes(bytes(data))
        with self.assertRaises(MetadataError):
            Metadata.read(path).save(folder / "out.tif")


    def test_page_exif_pointer_is_refused(self):
        folder = new_dir()
        data = bytearray(b"II*\x00\x08\x00\x00\x00")
        data += struct.pack("<H", 1)
        data += struct.pack("<HHI", 0x0100, 3, 1) + struct.pack("<H", 8) + b"\x00\x00"
        data += struct.pack("<I", 26)
        data += struct.pack("<H", 1)
        data += struct.pack("<HHI", 0x8769, 4, 1) + struct.pack("<I", 64)
        data += struct.pack("<I", 0)
        path = folder / "page_exif.tif"
        path.write_bytes(bytes(data))
        with self.assertRaises(MetadataError):
            Metadata.read(path).save(folder / "out.tif")

    def test_nrw_is_read_only(self):
        folder = new_dir()
        meta = Metadata.read(SAMPLE)
        path = folder / "coolpix.nrw"
        path.write_bytes(meta.tiff.to_bytes())
        raw = Metadata.read(path)
        self.assertTrue(raw.readonly)
        self.assertEqual(raw.info.format, "NRW")
        with self.assertRaises(MetadataError):
            raw.set("Artist", "blocked")
        with self.assertRaises(MetadataError):
            raw.save(folder / "out.nrw")

    def test_non_tiff_raw_is_reported(self):
        folder = new_dir()
        path = folder / "mirrorless.cr3"
        path.write_bytes(b"\x00\x00\x00\x18ftypcrx \x00\x00\x00\x00crx isom")
        with self.assertRaises(MetadataError):
            Metadata.read(path)


class JpegStructureTests(unittest.TestCase):
    """A malformed header must never cost the user the rest of the file."""

    @staticmethod
    def _corrupt_app1(folder: Path) -> Path:
        blob = bytearray(SAMPLE.read_bytes())
        pos = blob.find(b"\xff\xe1")
        blob[pos + 2:pos + 4] = b"\x00\x07"   # claim the APP1 is only 7 bytes
        path = folder / "broken.jpg"
        path.write_bytes(bytes(blob))
        return path

    def test_malformed_segment_keeps_every_byte(self):
        folder = new_dir()
        source = self._corrupt_app1(folder)
        meta = Metadata.read(source)
        self.assertTrue(meta.warnings)
        self.assertTrue(meta.jpeg.damaged)
        out = folder / "out.jpg"
        meta.save(out)
        self.assertEqual(source.read_bytes(), out.read_bytes())

    def test_malformed_segment_keeps_tail_after_edit(self):
        folder = new_dir()
        source = self._corrupt_app1(folder)
        original_tail = Jpeg.parse(source.read_bytes()).tail
        meta = Metadata.read(source)
        meta.set("Artist", "EasyExif")
        out = folder / "edited.jpg"
        meta.save(out)
        self.assertTrue(out.read_bytes().endswith(original_tail))

    def test_oversized_xmp_is_refused(self):
        folder = new_dir()
        target = folder / "big.jpg"
        shutil.copyfile(SAMPLE, target)
        meta = Metadata.read(target)
        meta.xmp.set("xmp:Label", "x" * 70000)
        out = folder / "out.jpg"
        with self.assertRaises(MetadataError) as ctx:
            meta.save(out)
        self.assertIn("65533", str(ctx.exception))
        self.assertFalse(out.exists())

    def test_oversized_comment_is_refused(self):
        folder = new_dir()
        target = folder / "bigcomment.jpg"
        shutil.copyfile(SAMPLE, target)
        meta = Metadata.read(target)
        meta.jpeg.insert(0xFE, b"y" * 70000)
        with self.assertRaises(MetadataError):
            meta.save(folder / "out.jpg")


class TiffStructureTests(unittest.TestCase):
    def test_bad_ifd_chain_is_tolerated(self):
        folder = new_dir()
        data = bytearray(b"II*\x00\x08\x00\x00\x00")
        data += struct.pack("<H", 1)
        data += struct.pack("<HHI", 0x0100, 3, 1) + struct.pack("<H", 8) + b"\x00\x00"
        data += struct.pack("<I", 0xFFFFFFF0)
        path = folder / "bad_chain.tif"
        path.write_bytes(bytes(data))
        meta = Metadata.read(path)          # must not raise KeyError
        self.assertTrue(meta.warnings)
        self.assertEqual(meta.tiff.get("IFD0", 0x0100), 8)


class BrokenExifTests(unittest.TestCase):
    def test_corrupt_exif_opens_and_can_be_stripped(self):
        folder = new_dir()
        target = folder / "broken_exif.jpg"
        blob = bytearray(SAMPLE.read_bytes())
        pos = blob.find(b"Exif\x00\x00")
        blob[pos + 6:pos + 8] = b"ZZ"        # invalid byte order marker
        target.write_bytes(bytes(blob))
        meta = Metadata.read(target)
        self.assertIsNone(meta.tiff)
        self.assertTrue(any("EXIF 数据损坏" in w for w in meta.warnings))
        tail = Jpeg.parse(target.read_bytes()).tail
        meta.clear_metadata()
        out = folder / "stripped.jpg"
        meta.save(out)
        saved = Jpeg.parse(out.read_bytes())
        self.assertFalse([s for s in saved.segments
                          if s.marker == 0xE1 and s.data.startswith(b"Exif\0\0")])
        self.assertEqual(tail, saved.tail)


class MakerNoteLayoutTests(unittest.TestCase):
    @staticmethod
    def _ifd(tags, endian="<", base=0):
        body = struct.pack(endian + "H", len(tags))
        ext = b""
        start = base + 2 + 12 * len(tags) + 4
        for tag, typ, count, raw in tags:
            if len(raw) <= 4:
                body += struct.pack(endian + "HHI", tag, typ, count) + raw.ljust(4, b"\x00")
            else:
                body += struct.pack(endian + "HHI", tag, typ, count) \
                    + struct.pack(endian + "I", start + len(ext))
                ext += raw
        return body + struct.pack(endian + "I", 0) + ext

    def test_nikon_type3(self):
        inner = self._ifd([(0x0001, 7, 4, b"0210"),
                           (0x0007, 3, 1, struct.pack(">H", 1))], ">", base=18)
        note = b"Nikon\x00" + b"\x02\x10\x00\x00" + b"MM\x00\x2a" + struct.pack(">I", 8) + inner
        parsed = parse_makernote("NIKON CORPORATION", note, "<", 0)
        self.assertEqual(parsed.maker, "Nikon")
        self.assertEqual(parsed.get("FocusMode"), 1)

    def test_fujifilm(self):
        payload = self._ifd([(0x1001, 2, 4, b"1.00")], ">", base=12)
        note = b"FUJIFILM" + struct.pack(">I", 12) + payload
        parsed = parse_makernote("FUJIFILM", note, "<", 0)
        self.assertEqual(parsed.maker, "Fujifilm")
        self.assertEqual(len(parsed.fields), 1)

    def test_olympus(self):
        payload = self._ifd([(0x0201, 3, 1, struct.pack("<H", 1))], "<", base=8)
        note = b"OLYMP\x00" + b"\x02\x00" + payload
        parsed = parse_makernote("OLYMPUS", note, "<", 0)
        self.assertEqual(parsed.maker, "Olympus")
        self.assertEqual(len(parsed.fields), 1)

    def test_pentax(self):
        payload = self._ifd([(0x0001, 3, 1, struct.pack("<H", 3))], "<", base=6)
        note = b"AOC\x00" + b"\x00\x11" + payload
        parsed = parse_makernote("PENTAX", note, "<", 0)
        self.assertEqual(parsed.maker, "Pentax")
        self.assertEqual(len(parsed.fields), 1)


if __name__ == "__main__":
    unittest.main()
