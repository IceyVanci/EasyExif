"""GPS helpers: DMS parsing, datum conversion and map links."""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from typing import Any

# Krasovsky 1940 ellipsoid used by the GCJ-02 obfuscation algorithm.
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lat: float, lon: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if _out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    if _out_of_china(lat, lon):
        return lat, lon
    # iterative refinement (max 5 cm after a handful of steps)
    wlat, wlon = lat, lon
    for _ in range(10):
        glat, glon = wgs84_to_gcj02(wlat, wlon)
        dlat, dlon = glat - lat, glon - lon
        if abs(dlat) < 1e-9 and abs(dlon) < 1e-9:
            break
        wlat -= dlat
        wlon -= dlon
    return wlat, wlon


def gcj02_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * math.pi * 3000.0 / 180.0)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * math.pi * 3000.0 / 180.0)
    return z * math.sin(theta) + 0.006, z * math.cos(theta) + 0.0065


def bd09_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    x, y = lon - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000.0 / 180.0)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000.0 / 180.0)
    return z * math.sin(theta), z * math.cos(theta)


def wgs84_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    return gcj02_to_bd09(*wgs84_to_gcj02(lat, lon))


def bd09_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    return gcj02_to_wgs84(*bd09_to_gcj02(lat, lon))


def convert(lat: float, lon: float, src: str, dst: str) -> tuple[float, float]:
    src, dst = src.lower(), dst.lower()
    if src == dst:
        return lat, lon
    # normalise to WGS-84 first
    if src == "gcj02":
        lat, lon = gcj02_to_wgs84(lat, lon)
    elif src == "bd09":
        lat, lon = bd09_to_wgs84(lat, lon)
    elif src != "wgs84":
        raise ValueError("unknown datum %r" % src)
    if dst == "gcj02":
        return wgs84_to_gcj02(lat, lon)
    if dst == "bd09":
        return wgs84_to_bd09(lat, lon)
    if dst != "wgs84":
        raise ValueError("unknown datum %r" % dst)
    return lat, lon


# ---------------------------------------------------------------------------
# DMS helpers
# ---------------------------------------------------------------------------
_DMS_RE = re.compile(
    r"(?P<lat>[NS])?\s*(?P<d1>-?\d+(?:\.\d+)?)\s*[°d:\s]\s*"
    r"(?P<m1>\d+(?:\.\d+)?)?\s*['m:\s]?\s*(?P<s1>\d+(?:\.\d+)?)?\s*[\"s]?\s*(?P<lat2>[NS])?",
    re.I)


def parse_coordinate(text: str) -> float:
    """Parse 31.23, 31 13 30 N, 31d13'30\"N, N31 13.5 ... into decimal degrees."""
    raw = str(text).strip()
    if not raw:
        raise ValueError("empty coordinate")
    sign = 1
    if raw[0] in "NnSs":
        sign = -1 if raw[0] in "Ss" else 1
        raw = raw[1:].strip()
    if raw[-1] in "NnSsEeWw":
        if raw[-1] in "SsWw":
            sign = -1
        raw = raw[:-1].strip()
    if raw.startswith("-"):
        sign = -1
        raw = raw[1:]
    nums = re.findall(r"\d+(?:\.\d+)?", raw)
    if not nums:
        raise ValueError("no numeric component in %r" % text)
    deg = float(nums[0])
    minutes = float(nums[1]) if len(nums) > 1 else 0.0
    seconds = float(nums[2]) if len(nums) > 2 else 0.0
    if minutes >= 60 or seconds >= 60:
        # probably a signed decimal with stray separators
        return sign * float(nums[0] + "." + "".join(nums[1:])) if len(nums) > 1 else sign * deg
    return sign * (deg + minutes / 60.0 + seconds / 3600.0)


def decimal_to_dms(value: float) -> tuple[int, int, float]:
    sign = -1 if value < 0 else 1
    value = abs(value)
    deg = int(value)
    minutes_f = (value - deg) * 60
    minutes = int(minutes_f)
    seconds = (minutes_f - minutes) * 60
    if sign < 0:
        deg = -deg
    return deg, minutes, seconds


def format_dms(value: float, ref: str | None = None, precision: int = 4) -> str:
    d, m, s = decimal_to_dms(value)
    hemi = ref if ref else ("S" if value < 0 else "N")
    return "%d° %d' %.*f\" %s" % (abs(d), m, precision, s, hemi)


def dms_to_rationals(value: float) -> list[tuple[int, int]]:
    d, m, s = decimal_to_dms(abs(value))
    return [(d, 1), (m, 1), (int(round(s * 10000)), 10000)]


def rationals_to_decimal(parts: Any) -> float | None:
    if not isinstance(parts, (list, tuple)) or len(parts) != 3:
        return None
    total = 0.0
    for i, p in enumerate(parts):
        if isinstance(p, (list, tuple)) and len(p) == 2:
            num, den = p
            if den == 0:
                return None
            total += (num / den) / (60 ** i)
        elif isinstance(p, (int, float)):
            total += float(p) / (60 ** i)
        else:
            return None
    return total


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Map links
# ---------------------------------------------------------------------------
PROVIDERS = ("google", "google_cn", "osm", "baidu", "amap", "arcgis", "carto",
             "mapbox", "wikimedia")


def map_url(provider: str, lat: float, lon: float, zoom: int = 15,
            label: str = "") -> str:
    provider = provider.lower()
    q = urllib.parse.quote(label or ("%.6f, %.6f" % (lat, lon)))
    if provider in ("google", "google_cn"):
        host = "maps.google.cn" if provider == "google_cn" else "www.google.com"
        return "https://%s/maps?q=%.7f,%.7f&z=%d" % (host, lat, lon, zoom)
    if provider == "osm":
        return ("https://www.openstreetmap.org/?mlat=%.7f&mlon=%.7f#map=%d/%.7f/%.7f"
                % (lat, lon, zoom, lat, lon))
    if provider == "baidu":
        return ("https://api.map.baidu.com/marker?location=%.7f,%.7f&title=%s"
                "&content=%s&output=html&coord_type=wgs84&zoom=%d"
                % (lat, lon, q, q, zoom))
    if provider == "amap":
        return ("https://uri.amap.com/marker?position=%.7f,%.7f&name=%s&src=easyexif"
                % (lon, lat, q))
    if provider == "arcgis":
        return ("https://www.arcgis.com/apps/mapviewer/index.html?center=%.7f,%.7f&level=%d"
                % (lon, lat, zoom))
    if provider == "carto":
        return "https://carto.com/attributions#%.7f,%.7f,%d" % (lat, lon, zoom)
    if provider == "mapbox":
        return "https://www.mapbox.com/?q=%.7f,%.7f#%d/%.7f/%.7f" % (lat, lon, zoom, lat, lon)
    if provider == "wikimedia":
        return ("https://maps.wikimedia.org/#%d/%.7f/%.7f" % (zoom, lat, lon))
    raise ValueError("unknown map provider %r (choose from %s)"
                     % (provider, ", ".join(PROVIDERS)))


def embed_html(lat: float, lon: float, zoom: int = 15, label: str = "") -> str:
    d = 0.01
    bbox = "%.6f,%.6f,%.6f,%.6f" % (lon - d, lat - d, lon + d, lat + d)
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>EasyExif location</title>"
        "<style>html,body,iframe{margin:0;height:100%;width:100%;border:0}</style>"
        "<iframe src='https://www.openstreetmap.org/export/embed.html?bbox=%s"
        "&layer=mapnik&marker=%.6f,%.6f'></iframe>" % (bbox, lat, lon))


# ---------------------------------------------------------------------------
# Optional online geocoding (explicit network use)
# ---------------------------------------------------------------------------
def reverse_geocode(lat: float, lon: float, timeout: float = 10.0,
                    language: str = "zh-CN") -> dict:
    """Query Nominatim for an address.  This performs a network request."""
    url = ("https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=%.7f&lon=%.7f"
           "&accept-language=%s" % (lat, lon, urllib.parse.quote(language)))
    req = urllib.request.Request(url, headers={"User-Agent": "EasyExif/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
