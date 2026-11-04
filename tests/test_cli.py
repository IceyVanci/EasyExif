from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from easyexif.cli import main
from easyexif.metadata import Metadata

SAMPLE = ROOT / "examples" / "sample.jpg"
_TMP = Path(__file__).resolve().parent / "_tmp"
_TMP.mkdir(exist_ok=True)
_COUNTER = [0]


def new_dir() -> Path:
    _COUNTER[0] += 1
    p = _TMP / ("cli%03d" % _COUNTER[0])
    p.mkdir(parents=True, exist_ok=True)
    return p


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        if not SAMPLE.exists():
            self.skipTest("examples/sample.jpg is missing")

    def test_info_and_get(self):
        code, out, err = run(["info", str(SAMPLE)])
        self.assertEqual(code, 0, err)
        self.assertIn("Canon EOS R5", out)
        code, out, _ = run(["get", str(SAMPLE), "Model", "ExposureTime"])
        self.assertIn("Canon EOS R5", out)
        self.assertIn("1/250", out)

    def test_dump_json(self):
        code, out, err = run(["dump", str(SAMPLE), "--json"])
        self.assertEqual(code, 0, err)
        rows = json.loads(out)
        names = {r["name"] for r in rows}
        self.assertIn("Model", names)
        self.assertIn("DateTimeOriginal", names)

    def test_validate_json(self):
        code, out, err = run(["validate", str(SAMPLE), "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)[0]
        self.assertEqual(len(data["checks"]), 13)
        self.assertIn(data["score"], (1, 2, 3, 4, 5))

    def test_set_and_delete(self):
        tmp = new_dir()
        target = tmp / "edit.jpg"
        shutil.copy2(SAMPLE, target)
        code, out, err = run(["set", str(target), "Artist=Test User",
                              "Copyright=(c) 2026", "FNumber=4.0"])
        self.assertEqual(code, 0, err)
        meta = Metadata.read(target)
        self.assertEqual(meta.get_text("Artist"), "Test User")
        self.assertEqual(meta.get_text("FNumber"), "f/4")
        code, _, _ = run(["delete", str(target), "Artist"])
        self.assertEqual(code, 0)
        self.assertEqual(Metadata.read(target).get_text("Artist"), "")

    def test_segments(self):
        tmp = new_dir()
        target = tmp / "seg.jpg"
        shutil.copy2(SAMPLE, target)
        code, out, err = run(["segments", str(target)])
        self.assertEqual(code, 0, err)
        self.assertIn("APP1 (Exif)", out)
        code, _, err = run(["segments", str(target), "--add-comment", "hello", "--out", str(tmp / "out.jpg")])
        self.assertEqual(code, 0, err)
        _, out, _ = run(["segments", str(tmp / "out.jpg"), "--json"])
        self.assertIn("COM", out)

    def test_batch_csv(self):
        tmp = new_dir()
        code, out, err = run(["batch", str(SAMPLE), "--csv", str(tmp / "r.csv"),
                              "--profile", "detailed"])
        self.assertEqual(code, 0, err)
        text = (tmp / "r.csv").read_text(encoding="utf-8-sig")
        self.assertIn("Canon EOS R5", text)
        self.assertIn("DateTimeOriginal", text)

    def test_template_stamp(self):
        code, out, err = run(["template", "stamp", "--text",
                              "[[IFD0.Model]] [[IFD0.Make]]", str(SAMPLE)])
        self.assertEqual(code, 0, err)
        self.assertIn("Canon EOS R5", out)
        self.assertIn("Canon", out)

    def test_strip(self):
        tmp = new_dir()
        target = tmp / "strip.jpg"
        shutil.copy2(SAMPLE, target)
        code, _, err = run(["strip", str(target)])
        self.assertEqual(code, 0, err)
        meta = Metadata.read(target)
        self.assertIsNone(meta.tiff)
        self.assertFalse(meta.xmp.exists)


if __name__ == "__main__":
    unittest.main()
