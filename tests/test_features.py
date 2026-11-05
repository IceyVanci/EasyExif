from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from easyexif import Jpeg, Metadata
from easyexif.bundle import BundleError, export_bundle, import_bundle, load_bundle, write_bundle
from easyexif.lensdb import LensDatabase, lens_info

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
        self.assertEqual(after.get_text("IFD0.Software"), "EasyExif 0.1.1")
        self.assertEqual(after.xmp.get("xmp:CreatorTool"), "EasyExif 0.1.1")
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


if __name__ == "__main__":
    unittest.main()
