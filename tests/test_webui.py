from __future__ import annotations

import http.client
import json
import shutil
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from easyexif.webui.api import Api
from easyexif.webui.server import WebUIServer
from easyexif.webui.session import Session

SAMPLE = ROOT / "examples" / "sample.jpg"
TMP = Path(__file__).resolve().parent / "_tmp"
TMP.mkdir(exist_ok=True)
COUNTER = [0]


def new_dir() -> Path:
    COUNTER[0] += 1
    p = TMP / ("web%03d" % COUNTER[0])
    p.mkdir(parents=True, exist_ok=True)
    return p


class WebUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SAMPLE.exists():
            raise unittest.SkipTest("sample image missing")
        cls.data = new_dir()
        cls.session = Session(cls.data)
        cls.server = WebUIServer(Api(cls.session), "test-token")
        cls.server.start()
        cls.base = cls.server.url

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def request(self, method: str, path: str, body=None, token="test-token"):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-EasyExif-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type", ""), exc.read()

    def test_index_and_assets(self):
        status, ctype, body = self.request("GET", "/", token="")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"EasyExif", body)
        self.assertIn(b'id="modeSwitch"', body)
        self.assertIn(b'id="docTabs"', body)
        self.assertIn(b'id="readonlyBadge"', body)
        self.assertIn(b'id="appVersion"', body)
        self.assertIn(b'v0.1.0', body)
        self.assertIn(b'validate-disclaimer', body)
        self.assertIn("不能证明图像未经编辑".encode("utf-8"), body)
        status, ctype, body = self.request("GET", "/css/app.css", token="")
        self.assertEqual(status, 200)
        self.assertIn(b"--accent", body)
        status, ctype, body = self.request("GET", "/js/app.js", token="")
        self.assertEqual(status, 200)
        self.assertIn(b"preview-derived", body)
        self.assertIn(b"readonly-row", body)
        self.assertIn("技术字段只读".encode("utf-8"), body)

    def test_health_reports_version(self):
        status, _, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["version"], "0.1.0")

    def test_auth(self):
        status, _, _ = self.request("GET", "/api/doc", token="")
        self.assertEqual(status, 401)

    def test_heartbeat(self):
        status, _, body = self.request("POST", "/api/heartbeat", {})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertLess(self.server.heartbeat_age(), 5)

    def test_post_body_does_not_desync_keepalive(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        headers = {"X-EasyExif-Token": "test-token", "Content-Type": "application/json"}
        conn.request("POST", "/api/heartbeat", body="{}", headers=headers)
        first = conn.getresponse()
        self.assertEqual(first.status, 200)
        first.read()
        conn.request("GET", "/api/health", headers=headers)
        second = conn.getresponse()
        self.assertEqual(second.status, 200)
        self.assertTrue(json.loads(second.read())["ok"])
        conn.close()

    def test_open_edit_undo_save(self):
        status, _, body = self.request("POST", "/api/open", {"path": str(SAMPLE)})
        self.assertEqual(status, 200)
        doc = json.loads(body)["doc"]
        self.assertTrue(doc["open"])
        self.assertIn("Canon EOS R5", json.dumps(doc, ensure_ascii=False))

        status, _, body = self.request("POST", "/api/edit", {"ops": [
            {"op": "set", "name": "Artist", "value": "Web Test"},
            {"op": "set", "name": "Copyright", "value": "(c) 2026"},
        ]})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["doc"]["dirty"])

        status, _, body = self.request("POST", "/api/undo", {})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["doc"]["dirty"])

        target = new_dir() / "saved.jpg"
        status, _, body = self.request("POST", "/api/save", {"path": str(target)})
        self.assertEqual(status, 200)
        self.assertTrue(target.exists())
        self.assertGreater(target.stat().st_size, 1000)

    def test_preview_histogram_and_segments(self):
        self.request("POST", "/api/open", {"path": str(SAMPLE)})
        status, ctype, body = self.request("GET", "/api/preview?size=600")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "image/jpeg")
        self.assertEqual(body[:2], b"\xff\xd8")
        status, _, body = self.request("GET", "/api/histogram")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["data"]["bins"]), 256)
        status, _, body = self.request("GET", "/api/segments/1/hex")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["data"]["lines"])

    def test_tag_help_and_value_preview(self):
        status, _, body = self.request("GET", "/api/tag-help?name=EXIF.BrightnessValue")
        self.assertEqual(status, 200)
        help_data = json.loads(body)["data"]
        self.assertEqual(help_data["type"], "SRATIONAL")
        self.assertIn("亮度", help_data["desc"])
        self.assertTrue(help_data["readonly"])
        self.assertIn("APEX", help_data["format"])

        status, _, body = self.request("GET", "/api/tag-help?name=EXIF.ApertureValue")
        self.assertEqual(status, 200)
        aperture_help = json.loads(body)["data"]
        self.assertTrue(aperture_help["readonly"])
        self.assertIn("FNumber", aperture_help["desc"])

        status, _, body = self.request("GET", "/api/tag-help?name=Orientation")
        self.assertEqual(status, 200)
        options = json.loads(body)["data"]["options"]
        self.assertIn({"value": "6", "label": "顺时针旋转 90°"}, options)

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "EXIF.FNumber", "value": "28/10"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"]["display"], "f/2.8")

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "EXIF.FNumber", "value": "f/3.5"})
        self.assertEqual(status, 200)
        fnumber = json.loads(body)["data"]
        self.assertEqual(fnumber["display"], "f/3.5")
        self.assertEqual(fnumber["derived"][0]["name"], "ApertureValue")
        self.assertAlmostEqual(float(fnumber["derived"][0]["value"]), 3.6147, places=3)

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "EXIF.ExposureTime", "value": "1/500"})
        self.assertEqual(status, 200)
        exposure = json.loads(body)["data"]
        self.assertEqual(exposure["display"], "1/500 s")
        self.assertEqual(exposure["derived"][0]["name"], "ShutterSpeedValue")
        self.assertAlmostEqual(float(exposure["derived"][0]["value"]), 8.9658, places=3)

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "EXIF.ApertureValue", "value": "3.5"})
        self.assertEqual(status, 200)
        apex = json.loads(body)["data"]
        self.assertTrue(apex["readonly"])
        self.assertEqual(apex["display"], "f/3.4")
        self.assertEqual(apex["technical"], "APEX 3.5")

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "EXIF.ApertureValue", "value": "f/3.5"})
        self.assertEqual(status, 200)
        apex_natural = json.loads(body)["data"]
        self.assertEqual(apex_natural["display"], "f/3.5")
        self.assertIn("APEX 3.6147", apex_natural["technical"])

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "GPS.GPSLatitude", "value": "39.9087"})
        self.assertEqual(status, 200)
        self.assertIn("39 deg", json.loads(body)["data"]["display"])

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "IFD0.Orientation", "value": "6"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"]["display"], "顺时针旋转 90°")

        status, _, body = self.request("POST", "/api/format-value", {
            "name": "EXIF.DateTimeOriginal", "value": "not-a-date"})
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(body)["ok"])

    def test_two_documents_switch_and_close(self):
        while json.loads(self.request("GET", "/api/doc")[2])["doc"]["docs"]:
            self.request("POST", "/api/close", {})
        folder = new_dir()
        first = folder / "first.jpg"
        second = folder / "second.jpg"
        shutil.copyfile(SAMPLE, first)
        shutil.copyfile(SAMPLE, second)

        status, _, body = self.request("POST", "/api/open", {"path": str(first)})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["doc"]["docs"]), 1)

        status, _, body = self.request("POST", "/api/open", {"path": str(second)})
        self.assertEqual(status, 200)
        doc = json.loads(body)["doc"]
        self.assertEqual(len(doc["docs"]), 2)
        self.assertEqual(doc["active_index"], 1)
        self.assertEqual(doc["docs"][1]["name"], "second.jpg")

        status, _, body = self.request("POST", "/api/edit", {"ops": [
            {"op": "set", "name": "Artist", "value": "second only"}]})
        self.assertTrue(json.loads(body)["doc"]["dirty"])

        status, _, body = self.request("POST", "/api/activate", {"index": 0})
        doc = json.loads(body)["doc"]
        self.assertEqual(doc["name"], "first.jpg")
        self.assertFalse(doc["dirty"])
        self.assertEqual(len(doc["docs"]), 2)

        status, _, body = self.request("POST", "/api/activate", {"index": 1})
        self.assertTrue(json.loads(body)["doc"]["dirty"])

        status, _, body = self.request("POST", "/api/close", {})
        doc = json.loads(body)["doc"]
        self.assertTrue(doc["open"])
        self.assertEqual(len(doc["docs"]), 1)
        self.assertEqual(doc["name"], "first.jpg")

        status, _, body = self.request("POST", "/api/close", {})
        self.assertFalse(json.loads(body)["doc"]["open"])

    def test_validate_and_batch(self):
        self.request("POST", "/api/open", {"path": str(SAMPLE)})
        status, _, body = self.request("POST", "/api/validate", {})
        self.assertEqual(status, 200)
        report = json.loads(body)["report"]
        self.assertEqual(len(report["checks"]), 13)
        self.assertIn("disclaimer", report)
        self.assertIn("不能证明", report["disclaimer"])
        status, _, body = self.request("POST", "/api/batch/scan", {"path": str(SAMPLE)})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["data"]["files"]), 1)
        out = new_dir() / "report.csv"
        status, _, body = self.request("POST", "/api/batch/export", {
            "files": [str(SAMPLE)], "out": str(out), "profile": "simple"})
        self.assertEqual(status, 200)
        self.assertTrue(out.exists())
        self.assertIn("Canon EOS R5", out.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
