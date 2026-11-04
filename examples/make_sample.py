"""Generate examples/sample.jpg with rich, entirely synthetic metadata."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw

from easyexif.jpeg import Jpeg
from easyexif.tags import ASCII, RATIONAL, SHORT, UNDEFINED
from easyexif.tiff import Tiff
from easyexif.xmp import Xmp


def build_image() -> Image.Image:
    w, h = 1600, 1067
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(0, w, 4):
            r = int(40 + 180 * x / w)
            g = int(80 + 120 * y / h)
            b = int(160 - 100 * x / w)
            for dx in range(4):
                if x + dx < w:
                    px[x + dx, y] = (r, g, b)
    d = ImageDraw.Draw(im)
    d.ellipse((900, 180, 1250, 530), fill=(250, 230, 170))
    d.polygon([(0, 900), (420, 520), (760, 900)], fill=(30, 60, 45))
    d.polygon([(520, 910), (980, 470), (1400, 910)], fill=(20, 45, 35))
    return im


def build_exif(thumb: bytes) -> Tiff:
    t = Tiff("<")
    t.set("IFD0", 0x010F, "Canon", ASCII)
    t.set("IFD0", 0x0110, "Canon EOS R5", ASCII)
    t.set("IFD0", 0x0132, "2024:05:01 10:20:30", ASCII)
    t.set("IFD0", 0x0112, 1, SHORT)
    t.set("IFD0", 0x011A, (300, 1), RATIONAL)
    t.set("IFD0", 0x011B, (300, 1), RATIONAL)
    t.set("IFD0", 0x0128, 2, SHORT)
    t.set("EXIF", 0x9000, b"0232", UNDEFINED)
    t.set("EXIF", 0x9003, "2024:05:01 10:20:30", ASCII)
    t.set("EXIF", 0x9004, "2024:05:01 10:20:30", ASCII)
    t.set("EXIF", 0x829A, (1, 250), RATIONAL)
    t.set("EXIF", 0x829D, (28, 10), RATIONAL)
    t.set("EXIF", 0x8822, 3, SHORT)
    t.set("EXIF", 0x8827, 100, SHORT)
    t.set("EXIF", 0x9204, (0, 1), RATIONAL)
    t.set("EXIF", 0x9205, (3, 1), RATIONAL)
    t.set("EXIF", 0x9207, 5, SHORT)
    t.set("EXIF", 0x9209, 16, SHORT)
    t.set("EXIF", 0x920A, (50, 1), RATIONAL)
    t.set("EXIF", 0xA000, b"0100", UNDEFINED)
    t.set("EXIF", 0xA001, 1, SHORT)
    t.set("EXIF", 0xA002, 1600, 4)
    t.set("EXIF", 0xA003, 1067, 4)
    t.set("EXIF", 0xA402, 0, SHORT)
    t.set("EXIF", 0xA403, 0, SHORT)
    t.set("EXIF", 0xA405, 50, SHORT)
    t.set("EXIF", 0xA406, 0, SHORT)
    t.set("EXIF", 0xA431, "SN0000001", ASCII)
    t.set("EXIF", 0xA434, "RF24-70mm F2.8 L IS USM", ASCII)
    t.set("GPS", 0x0000, b"\x02\x03\x00\x00")
    t.set("GPS", 0x0001, "N", ASCII)
    t.set("GPS", 0x0002, [(39, 1), (54, 1), (3132, 100)], RATIONAL)
    t.set("GPS", 0x0003, "E", ASCII)
    t.set("GPS", 0x0004, [(116, 1), (23, 1), (5100, 100)], RATIONAL)
    t.set("GPS", 0x0005, b"\x00")
    t.set("GPS", 0x0006, (4380, 100), RATIONAL)
    t.set("GPS", 0x0007, [(2, 1), (20, 1), (30, 1)], RATIONAL)
    t.set("GPS", 0x0012, "WGS-84", ASCII)
    t.set("GPS", 0x001D, "2024:05:01", ASCII)
    t.thumbnail = thumb
    return t


def main() -> None:
    out = Path(__file__).resolve().parent / "sample.jpg"
    im = build_image()
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, progressive=False)
    j = Jpeg.parse(buf.getvalue())
    thumb = io.BytesIO()
    im.copy().resize((320, 213)).save(thumb, "JPEG", quality=80)
    j.set_exif_payload(build_exif(thumb.getvalue()).to_bytes())
    x = Xmp()
    x.set("dc:title", ["EasyExif sample image"])
    x.set("dc:description", ["Synthetic gradient scene, safe to edit."])
    x.set("dc:creator", ["EasyExif contributors"])
    x.set("xmp:CreatorTool", "EasyExif sample generator")
    x.set("photoshop:City", "Beijing")
    j.set_xmp_packet(x.to_bytes())
    out.write_bytes(j.to_bytes())
    print("wrote", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
