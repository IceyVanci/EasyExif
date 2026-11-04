"""EXIF / TIFF tag registry and human readable value formatting.

The tables below cover the most commonly edited tags (IFD0, ExifIFD, GPS,
Interop) plus a curated set of vendor tags.
Unknown tags are still preserved losslessly by easyexif.tiff.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# TIFF field types
# ---------------------------------------------------------------------------
BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5
SBYTE, UNDEFINED, SSHORT, SLONG, SRATIONAL = 6, 7, 8, 9, 10
FLOAT, DOUBLE, IFD = 11, 12, 13

TYPE_NAMES = {
    BYTE: "BYTE", ASCII: "ASCII", SHORT: "SHORT", LONG: "LONG",
    RATIONAL: "RATIONAL", SBYTE: "SBYTE", UNDEFINED: "UNDEFINED",
    SSHORT: "SSHORT", SLONG: "SLONG", SRATIONAL: "SRATIONAL",
    FLOAT: "FLOAT", DOUBLE: "DOUBLE", IFD: "IFD",
}
TYPE_SIZES = {BYTE: 1, ASCII: 1, SHORT: 2, LONG: 4, RATIONAL: 8, SBYTE: 1,
              UNDEFINED: 1, SSHORT: 2, SLONG: 4, SRATIONAL: 8, FLOAT: 4,
              DOUBLE: 8, IFD: 4}


@dataclass(frozen=True)
class TagInfo:
    name: str
    type: int | None = None
    fmt: str | None = None
    desc: str = ""


def _t(name: str, type: int | None = None, fmt: str | None = None,
       desc: str = "") -> TagInfo:
    return TagInfo(name, type, fmt, desc)


IFD0_TAGS: dict[int, TagInfo] = {
    0x000B: _t("ProcessingSoftware", ASCII),
    0x00FE: _t("NewSubfileType", LONG),
    0x00FF: _t("SubfileType", SHORT),
    0x0100: _t("ImageWidth", LONG, "px"),
    0x0101: _t("ImageLength", LONG, "px"),
    0x0102: _t("BitsPerSample", SHORT),
    0x0103: _t("Compression", SHORT, "compression"),
    0x0106: _t("PhotometricInterpretation", SHORT, "photometric"),
    0x010E: _t("ImageDescription", ASCII),
    0x010F: _t("Make", ASCII),
    0x0110: _t("Model", ASCII),
    0x0111: _t("StripOffsets", LONG),
    0x0112: _t("Orientation", SHORT, "orientation"),
    0x0115: _t("SamplesPerPixel", SHORT),
    0x0116: _t("RowsPerStrip", LONG),
    0x0117: _t("StripByteCounts", LONG),
    0x011A: _t("XResolution", RATIONAL, "dpi"),
    0x011B: _t("YResolution", RATIONAL, "dpi"),
    0x011C: _t("PlanarConfiguration", SHORT),
    0x0128: _t("ResolutionUnit", SHORT, "unit"),
    0x012D: _t("TransferFunction", SHORT),
    0x0131: _t("Software", ASCII),
    0x0132: _t("DateTime", ASCII, "datetime"),
    0x013B: _t("Artist", ASCII),
    0x013C: _t("HostComputer", ASCII),
    0x013E: _t("WhitePoint", RATIONAL),
    0x013F: _t("PrimaryChromaticities", RATIONAL),
    0x014A: _t("SubIFDs", LONG),
    0x0156: _t("TransferRange", SHORT),
    0x0200: _t("JPEGProc", SHORT),
    0x0201: _t("JPEGInterchangeFormat", LONG, "offset"),
    0x0202: _t("JPEGInterchangeFormatLength", LONG, "bytes"),
    0x0211: _t("YCbCrCoefficients", RATIONAL),
    0x0212: _t("YCbCrSubSampling", SHORT),
    0x0213: _t("YCbCrPositioning", SHORT, "ycbcr_position"),
    0x0214: _t("ReferenceBlackWhite", RATIONAL),
    0x02BC: _t("XMLPacket", BYTE),
    0x4746: _t("Rating", SHORT),
    0x4749: _t("RatingPercent", SHORT),
    0x8298: _t("Copyright", ASCII),
    0x8769: _t("ExifIFDPointer", LONG, "offset"),
    0x8825: _t("GPSInfoIFDPointer", LONG, "offset"),
    0x83BB: _t("IPTC-NAA", LONG),
    0x8649: _t("Photoshop", BYTE),
    0x8773: _t("ICCProfile", UNDEFINED),
    0x9C9B: _t("XPTitle", BYTE, "xptext"),
    0x9C9C: _t("XPComment", BYTE, "xptext"),
    0x9C9D: _t("XPAuthor", BYTE, "xptext"),
    0x9C9E: _t("XPKeywords", BYTE, "xptext"),
    0x9C9F: _t("XPSubject", BYTE, "xptext"),
    0xA480: _t("GDALMetadata", ASCII),
    0xA481: _t("GDALNoData", ASCII),
    0xC4A5: _t("PrintImageMatching", UNDEFINED),
    0xC612: _t("DNGVersion", BYTE),
    0xC613: _t("DNGBackwardVersion", BYTE),
    0xC614: _t("UniqueCameraModel", ASCII),
    0xC615: _t("LocalizedCameraModel", ASCII),
    0xC621: _t("ColorMatrix1", SRATIONAL),
    0xC622: _t("ColorMatrix2", SRATIONAL),
    0xC628: _t("AsShotNeutral", RATIONAL),
    0xC62F: _t("CameraSerialNumber", ASCII),
    0xC630: _t("DNGLensInfo", RATIONAL),
    0xC634: _t("DNGPrivateData", BYTE),
    0xC65A: _t("CalibrationIlluminant1", SHORT),
    0xC65B: _t("CalibrationIlluminant2", SHORT),
    0xC68B: _t("OriginalRawFileName", ASCII),
    0xC68D: _t("ActiveArea", LONG),
    0xC6F3: _t("CameraCalibrationSig", ASCII),
    0xC6F4: _t("ProfileCalibrationSig", ASCII),
    0xC6F6: _t("AsShotProfileName", ASCII),
    0xC6F8: _t("ProfileName", ASCII),
    0xC6FC: _t("ProfileHueSatMapDims", LONG),
    0xC714: _t("ForwardMatrix1", SRATIONAL),
    0xC715: _t("ForwardMatrix2", SRATIONAL),
    0xC717: _t("ProfileEmbedPolicy", LONG),
    0xC71A: _t("PreviewApplicationName", ASCII),
    0xC71B: _t("PreviewApplicationVersion", ASCII),
    0xC71C: _t("PreviewSettingsName", ASCII),
    0xC71D: _t("PreviewSettingsDigest", BYTE),
    0xC71E: _t("PreviewColorSpace", LONG),
    0xC71F: _t("PreviewDateTime", ASCII),
    0xC740: _t("AsShotProfileName", ASCII),
    0xC761: _t("NoiseProfile", DOUBLE),
}

EXIF_TAGS: dict[int, TagInfo] = {
    0x829A: _t("ExposureTime", RATIONAL, "exposure"),
    0x829D: _t("FNumber", RATIONAL, "fnumber"),
    0x8822: _t("ExposureProgram", SHORT, "exposure_program"),
    0x8824: _t("SpectralSensitivity", ASCII),
    0x8827: _t("ISOSpeedRatings", SHORT, "iso"),
    0x8828: _t("OECF", UNDEFINED),
    0x8830: _t("SensitivityType", SHORT, "sensitivity_type"),
    0x8831: _t("StandardOutputSensitivity", LONG),
    0x8832: _t("RecommendedExposureIndex", LONG),
    0x8833: _t("ISOSpeed", LONG),
    0x8834: _t("ISOSpeedLatitudeyyy", LONG),
    0x8835: _t("ISOSpeedLatitudezzz", LONG),
    0x9000: _t("ExifVersion", UNDEFINED, "version"),
    0x9003: _t("DateTimeOriginal", ASCII, "datetime"),
    0x9004: _t("DateTimeDigitized", ASCII, "datetime"),
    0x9009: _t("GooglePlusUploadCode", UNDEFINED),
    0x9010: _t("OffsetTime", ASCII),
    0x9011: _t("OffsetTimeOriginal", ASCII),
    0x9012: _t("OffsetTimeDigitized", ASCII),
    0x9101: _t("ComponentsConfiguration", UNDEFINED, "components"),
    0x9102: _t("CompressedBitsPerPixel", RATIONAL),
    0x9201: _t("ShutterSpeedValue", SRATIONAL, "apex_shutter"),
    0x9202: _t("ApertureValue", RATIONAL, "apex_aperture"),
    0x9203: _t("BrightnessValue", SRATIONAL, "ev"),
    0x9204: _t("ExposureBiasValue", SRATIONAL, "ev"),
    0x9205: _t("MaxApertureValue", RATIONAL, "apex_aperture"),
    0x9206: _t("SubjectDistance", RATIONAL, "distance"),
    0x9207: _t("MeteringMode", SHORT, "metering"),
    0x9208: _t("LightSource", SHORT, "light_source"),
    0x9209: _t("Flash", SHORT, "flash"),
    0x920A: _t("FocalLength", RATIONAL, "focal"),
    0x9214: _t("SubjectArea", SHORT),
    0x927C: _t("MakerNote", UNDEFINED),
    0x9286: _t("UserComment", UNDEFINED, "user_comment"),
    0x9290: _t("SubSecTime", ASCII),
    0x9291: _t("SubSecTimeOriginal", ASCII),
    0x9292: _t("SubSecTimeDigitized", ASCII),
    0x9400: _t("Temperature", SRATIONAL, "temperature"),
    0x9401: _t("Humidity", RATIONAL),
    0x9402: _t("Pressure", RATIONAL),
    0x9403: _t("WaterDepth", SRATIONAL),
    0x9404: _t("Acceleration", RATIONAL),
    0x9405: _t("CameraElevationAngle", SRATIONAL),
    0xA000: _t("FlashpixVersion", UNDEFINED, "version"),
    0xA001: _t("ColorSpace", SHORT, "colorspace"),
    0xA002: _t("PixelXDimension", LONG, "px"),
    0xA003: _t("PixelYDimension", LONG, "px"),
    0xA004: _t("RelatedSoundFile", ASCII),
    0xA005: _t("InteroperabilityIFDPointer", LONG, "offset"),
    0xA20B: _t("FlashEnergy", RATIONAL),
    0xA20C: _t("SpatialFrequencyResponse", UNDEFINED),
    0xA20E: _t("FocalPlaneXResolution", RATIONAL, "dpi"),
    0xA20F: _t("FocalPlaneYResolution", RATIONAL, "dpi"),
    0xA210: _t("FocalPlaneResolutionUnit", SHORT, "unit"),
    0xA214: _t("SubjectLocation", SHORT),
    0xA215: _t("ExposureIndex", RATIONAL),
    0xA217: _t("SensingMethod", SHORT, "sensing_method"),
    0xA300: _t("FileSource", UNDEFINED, "file_source"),
    0xA301: _t("SceneType", UNDEFINED, "scene_type"),
    0xA302: _t("CFAPattern", UNDEFINED),
    0xA401: _t("CustomRendered", SHORT, "custom_rendered"),
    0xA402: _t("ExposureMode", SHORT, "exposure_mode"),
    0xA403: _t("WhiteBalance", SHORT, "white_balance"),
    0xA404: _t("DigitalZoomRatio", RATIONAL, "zoom"),
    0xA405: _t("FocalLengthIn35mmFilm", SHORT, "focal35"),
    0xA406: _t("SceneCaptureType", SHORT, "scene_capture"),
    0xA407: _t("GainControl", SHORT, "gain_control"),
    0xA408: _t("Contrast", SHORT, "contrast"),
    0xA409: _t("Saturation", SHORT, "saturation"),
    0xA40A: _t("Sharpness", SHORT, "sharpness"),
    0xA40B: _t("DeviceSettingDescription", UNDEFINED),
    0xA40C: _t("SubjectDistanceRange", SHORT, "subject_distance_range"),
    0xA420: _t("ImageUniqueID", ASCII),
    0xA430: _t("CameraOwnerName", ASCII),
    0xA431: _t("BodySerialNumber", ASCII),
    0xA432: _t("LensSpecification", RATIONAL, "lens_spec"),
    0xA433: _t("LensMake", ASCII),
    0xA434: _t("LensModel", ASCII),
    0xA435: _t("LensSerialNumber", ASCII),
    0xA460: _t("CompositeImage", SHORT),
    0xA461: _t("SourceImageNumberOfCompositeImage", SHORT),
    0xA462: _t("SourceExposureTimesOfCompositeImage", UNDEFINED),
    0xA500: _t("Gamma", RATIONAL),
    0xA480: _t("GDALMetadata", ASCII),
    0xA481: _t("GDALNoData", ASCII),
    0xA490: _t("PrintImageMatching", UNDEFINED),
}

GPS_TAGS: dict[int, TagInfo] = {
    0x0000: _t("GPSVersionID", BYTE, "gps_version"),
    0x0001: _t("GPSLatitudeRef", ASCII),
    0x0002: _t("GPSLatitude", RATIONAL, "gps_coord"),
    0x0003: _t("GPSLongitudeRef", ASCII),
    0x0004: _t("GPSLongitude", RATIONAL, "gps_coord"),
    0x0005: _t("GPSAltitudeRef", BYTE, "gps_altref"),
    0x0006: _t("GPSAltitude", RATIONAL, "gps_alt"),
    0x0007: _t("GPSTimeStamp", RATIONAL, "gps_time"),
    0x0008: _t("GPSSatellites", ASCII),
    0x0009: _t("GPSStatus", ASCII, "gps_status"),
    0x000A: _t("GPSMeasureMode", ASCII, "gps_measure"),
    0x000B: _t("GPSDOP", RATIONAL),
    0x000C: _t("GPSSpeedRef", ASCII, "gps_speedref"),
    0x000D: _t("GPSSpeed", RATIONAL, "gps_speed"),
    0x000E: _t("GPSTrackRef", ASCII),
    0x000F: _t("GPSTrack", RATIONAL),
    0x0010: _t("GPSImgDirectionRef", ASCII),
    0x0011: _t("GPSImgDirection", RATIONAL),
    0x0012: _t("GPSMapDatum", ASCII),
    0x0013: _t("GPSDestLatitudeRef", ASCII),
    0x0014: _t("GPSDestLatitude", RATIONAL, "gps_coord"),
    0x0015: _t("GPSDestLongitudeRef", ASCII),
    0x0016: _t("GPSDestLongitude", RATIONAL, "gps_coord"),
    0x0017: _t("GPSDestBearingRef", ASCII),
    0x0018: _t("GPSDestBearing", RATIONAL),
    0x0019: _t("GPSDestDistanceRef", ASCII),
    0x001A: _t("GPSDestDistance", RATIONAL),
    0x001B: _t("GPSProcessingMethod", UNDEFINED, "gps_processing"),
    0x001C: _t("GPSAreaInformation", UNDEFINED),
    0x001D: _t("GPSDateStamp", ASCII, "date"),
    0x001E: _t("GPSDifferential", SHORT),
    0x001F: _t("GPSHPositioningError", RATIONAL, "distance"),
}

INTEROP_TAGS: dict[int, TagInfo] = {
    0x0001: _t("InteroperabilityIndex", ASCII),
    0x0002: _t("InteroperabilityVersion", UNDEFINED, "version"),
    0x1000: _t("RelatedImageFileFormat", ASCII),
    0x1001: _t("RelatedImageWidth", LONG, "px"),
    0x1002: _t("RelatedImageLength", LONG, "px"),
}

IFD_TABLES = {
    "IFD0": IFD0_TAGS,
    "IFD1": IFD0_TAGS,
    "EXIF": EXIF_TAGS,
    "GPS": GPS_TAGS,
    "Interop": INTEROP_TAGS,
}

# Friendly aliases accepted by the CLI / public API.
ALIASES: dict[str, tuple[str, int]] = {
    "make": ("IFD0", 0x010F), "model": ("IFD0", 0x0110),
    "software": ("IFD0", 0x0131), "artist": ("IFD0", 0x013B),
    "copyright": ("IFD0", 0x8298), "description": ("IFD0", 0x010E),
    "orientation": ("IFD0", 0x0112), "datetime": ("IFD0", 0x0132),
    "width": ("EXIF", 0xA002), "height": ("EXIF", 0xA003),
    "datetimeoriginal": ("EXIF", 0x9003), "created": ("EXIF", 0x9003),
    "datetimedigitized": ("EXIF", 0x9004),
    "exposuretime": ("EXIF", 0x829A), "shutter": ("EXIF", 0x829A),
    "fnumber": ("EXIF", 0x829D), "aperture": ("EXIF", 0x829D),
    "iso": ("EXIF", 0x8827), "isospeedratings": ("EXIF", 0x8827),
    "focallength": ("EXIF", 0x920A), "lens": ("EXIF", 0xA434),
    "lensmodel": ("EXIF", 0xA434), "lensmake": ("EXIF", 0xA433),
    "flash": ("EXIF", 0x9209), "meteringmode": ("EXIF", 0x9207),
    "whitebalance": ("EXIF", 0xA403), "exposureprogram": ("EXIF", 0x8822),
    "exposurebias": ("EXIF", 0x9204), "maxaperture": ("EXIF", 0x9205),
    "serial": ("EXIF", 0xA431), "bodyserial": ("EXIF", 0xA431),
    "lensserial": ("EXIF", 0xA435), "uniqueid": ("EXIF", 0xA420),
    "usercomment": ("EXIF", 0x9286),
    "gpslatitude": ("GPS", 0x0002), "gpslongitude": ("GPS", 0x0004),
    "gpsaltitude": ("GPS", 0x0006), "gpsdate": ("GPS", 0x001D),
    "gpstime": ("GPS", 0x0007),
}

# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------
ORIENTATION = {1: "Normal", 2: "Mirror horizontal", 3: "Rotate 180",
               4: "Mirror vertical", 5: "Mirror horizontal and rotate 270 CW",
               6: "Rotate 90 CW", 7: "Mirror horizontal and rotate 90 CW",
               8: "Rotate 270 CW"}
COMPRESSION = {1: "Uncompressed", 6: "JPEG (old-style)", 7: "JPEG"}
PHOTOMETRIC = {0: "WhiteIsZero", 1: "BlackIsZero", 2: "RGB", 3: "Palette",
               5: "CMYK", 6: "YCbCr", 8: "CIELab"}
EXPOSURE_PROGRAM = {0: "Not defined", 1: "Manual", 2: "Normal program",
                    3: "Aperture priority", 4: "Shutter priority", 5: "Creative",
                    6: "Action", 7: "Portrait", 8: "Landscape"}
METERING = {0: "Unknown", 1: "Average", 2: "Center-weighted average",
            3: "Spot", 4: "Multi-spot", 5: "Pattern", 6: "Partial",
            255: "Other"}
LIGHT_SOURCE = {0: "Unknown", 1: "Daylight", 2: "Fluorescent", 3: "Tungsten",
                4: "Flash", 9: "Fine weather", 10: "Cloudy", 11: "Shade",
                12: "Daylight fluorescent", 13: "Day white fluorescent",
                14: "Cool white fluorescent", 15: "White fluorescent",
                17: "Standard light A", 18: "Standard light B",
                19: "Standard light C", 20: "D55", 21: "D65", 22: "D75",
                23: "D50", 24: "ISO studio tungsten", 255: "Other"}
COLOR_SPACE = {1: "sRGB", 2: "Adobe RGB", 0xFFFD: "Wide Gamut RGB",
               0xFFFE: "ICC Profile", 0xFFFF: "Uncalibrated"}
SENSING = {1: "Not defined", 2: "One-chip color area", 3: "Two-chip color area",
           4: "Three-chip color area", 5: "Color sequential area",
           7: "Trilinear", 8: "Color sequential linear"}
CUSTOM_RENDERED = {0: "Normal", 1: "Custom"}
EXPOSURE_MODE = {0: "Auto", 1: "Manual", 2: "Auto bracket"}
WHITE_BALANCE = {0: "Auto", 1: "Manual"}
SCENE_CAPTURE = {0: "Standard", 1: "Landscape", 2: "Portrait", 3: "Night"}
GAIN = {0: "None", 1: "Low gain up", 2: "High gain up", 3: "Low gain down",
        4: "High gain down"}
CONTRAST = {0: "Normal", 1: "Soft", 2: "Hard"}
SATURATION = {0: "Normal", 1: "Low", 2: "High"}
SHARPNESS = {0: "Normal", 1: "Soft", 2: "Hard"}
DISTANCE_RANGE = {0: "Unknown", 1: "Macro", 2: "Close", 3: "Distant"}
SENSITIVITY_TYPE = {0: "Unknown", 1: "Standard output", 2: "Recommended exposure index",
                    3: "ISO speed", 4: "SOS", 5: "REI", 6: "ISO speed", 7: "SOS and REI"}
COMPONENTS = {0: "-", 1: "Y", 2: "Cb", 3: "Cr", 4: "R", 5: "G", 6: "B"}
FILE_SOURCE = {3: "DSC"}
SCENE_TYPE = {1: "Directly photographed"}
UNIT = {1: "none", 2: "inch", 3: "cm"}
YCBCR_POSITION = {1: "Centered", 2: "Co-sited"}
GPS_STATUS = {"A": "Measurement in progress", "V": "Measurement interrupted"}
GPS_MEASURE = {"2": "2-dimensional", "3": "3-dimensional"}
GPS_SPEEDREF = {"K": "km/h", "M": "mph", "N": "knots"}


def decode_flash(value: Any) -> str:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return str(value)
    parts = ["Fired" if v & 1 else "Did not fire"]
    if v & 0x20:
        parts.append("no flash function")
    else:
        mode = (v >> 3) & 3
        label = {1: "on", 2: "off", 3: "auto"}.get(mode)
        if label:
            parts.append(label)
    if v & 0x40:
        parts.append("red-eye reduction")
    return ", ".join(parts)


def rational_to_float(value: Any) -> float | None:
    if isinstance(value, tuple) and len(value) == 2:
        num, den = value
        if den == 0:
            return None
        return num / den
    if isinstance(value, list) and len(value) == 1:
        return rational_to_float(value[0])
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _fmt_exposure(v: Any) -> str:
    f = rational_to_float(v)
    if f is None:
        return str(v)
    if f and f < 1:
        return "1/%d s" % round(1 / f)
    return ("%g s" % f)


def _fmt_fnumber(v: Any) -> str:
    f = rational_to_float(v)
    return "f/%g" % f if f is not None else str(v)


def _fmt_focal(v: Any) -> str:
    f = rational_to_float(v)
    return ("%g mm" % f) if f is not None else str(v)


def _fmt_ev(v: Any) -> str:
    f = rational_to_float(v)
    return ("%+.1f EV" % f) if f is not None else str(v)


def _fmt_dpi(v: Any) -> str:
    f = rational_to_float(v)
    return ("%g dpi" % f) if f is not None else str(v)


def _fmt_apex_aperture(v: Any) -> str:
    f = rational_to_float(v)
    if f is None:
        return str(v)
    return "f/%g" % round(2 ** (f / 2), 1)


def _fmt_apex_shutter(v: Any) -> str:
    f = rational_to_float(v)
    if f is None:
        return str(v)
    t = 2 ** (-f)
    return ("1/%d s" % round(1 / t)) if t and t < 1 else ("%g s" % t)


def _fmt_distance(v: Any) -> str:
    f = rational_to_float(v)
    return ("%g m" % f) if f is not None else str(v)


def _fmt_zoom(v: Any) -> str:
    f = rational_to_float(v)
    return ("%gx" % f) if f is not None else str(v)


def _fmt_version(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        data = bytes(v).rstrip(b"\0")
        text = data.decode("ascii", "replace")
        if len(text) == 4 and text.isdigit():
            major = text[:2].lstrip("0") or "0"
            return "%s.%s" % (major, text[2:])
        if text and all(32 <= b < 127 for b in data):
            return text
        return ".".join(str(b) for b in v)
    return str(v)


def _fmt_user_comment(v: Any) -> str:
    if not isinstance(v, (bytes, bytearray)):
        return str(v)
    data = bytes(v)
    if data[:8] == b"ASCII\0\0\0":
        return data[8:].rstrip(b"\0").decode("ascii", "replace")
    if data[:8] == b"UNICODE\0":
        return data[8:].decode("utf-16-be" if data[8:9] == b"\0" else "utf-16-le", "replace").rstrip("\0")
    if data[:8] == b"JIS\0\0\0\0\0":
        return data[8:].rstrip(b"\0").decode("shift_jis", "replace")
    return data.rstrip(b"\0").decode("utf-8", "replace")


def _fmt_xp(v: Any) -> str:
    if not isinstance(v, (bytes, bytearray)):
        return str(v)
    try:
        return bytes(v).decode("utf-16-le", "replace").rstrip("\0")
    except Exception:
        return str(v)


def format_gps_coord(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return str(value)
    parts = []
    for r in value:
        f = rational_to_float(r)
        if f is None:
            return str(value)
        parts.append(f)
    deg, minutes, seconds = parts
    return "%d deg %d' %.4f\"" % (int(deg), int(minutes), seconds)


def _fmt_gps_alt(v: Any) -> str:
    f = rational_to_float(v)
    return ("%g m" % f) if f is not None else str(v)


def _fmt_gps_time(v: Any) -> str:
    if isinstance(v, (list, tuple)) and len(v) == 3:
        vals = [rational_to_float(x) or 0 for x in v]
        return "%02d:%02d:%06.3f" % (int(vals[0]), int(vals[1]), vals[2])
    return str(v)


def _fmt_gps_processing(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)) and bytes(v)[:8] == b"ASCII\0\0\0":
        return bytes(v)[8:].rstrip(b"\0").decode("ascii", "replace")
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).rstrip(b"\0").decode("utf-8", "replace")
    return str(v)


def _fmt_lens_spec(v: Any) -> str:
    if isinstance(v, (list, tuple)) and len(v) == 4:
        vals = [rational_to_float(x) for x in v]
        if all(x is not None for x in vals):
            return "%g-%g mm f/%g-%g" % (vals[0], vals[1], vals[2], vals[3])
    return str(v)


FORMATTERS: dict[str, Callable[[Any], str]] = {
    "orientation": lambda v: ORIENTATION.get(int(v), str(v)),
    "compression": lambda v: COMPRESSION.get(int(v), str(v)),
    "photometric": lambda v: PHOTOMETRIC.get(int(v), str(v)),
    "exposure_program": lambda v: EXPOSURE_PROGRAM.get(int(v), str(v)),
    "metering": lambda v: METERING.get(int(v), str(v)),
    "light_source": lambda v: LIGHT_SOURCE.get(int(v), str(v)),
    "flash": decode_flash,
    "colorspace": lambda v: COLOR_SPACE.get(int(v), str(v)),
    "sensing_method": lambda v: SENSING.get(int(v), str(v)),
    "custom_rendered": lambda v: CUSTOM_RENDERED.get(int(v), str(v)),
    "exposure_mode": lambda v: EXPOSURE_MODE.get(int(v), str(v)),
    "white_balance": lambda v: WHITE_BALANCE.get(int(v), str(v)),
    "scene_capture": lambda v: SCENE_CAPTURE.get(int(v), str(v)),
    "gain_control": lambda v: GAIN.get(int(v), str(v)),
    "contrast": lambda v: CONTRAST.get(int(v), str(v)),
    "saturation": lambda v: SATURATION.get(int(v), str(v)),
    "sharpness": lambda v: SHARPNESS.get(int(v), str(v)),
    "subject_distance_range": lambda v: DISTANCE_RANGE.get(int(v), str(v)),
    "sensitivity_type": lambda v: SENSITIVITY_TYPE.get(int(v), str(v)),
    "components": lambda v: " ".join(COMPONENTS.get(int(b), str(b)) for b in v)
    if isinstance(v, (bytes, bytearray)) else str(v),
    "file_source": lambda v: FILE_SOURCE.get(v[0] if isinstance(v, (bytes, bytearray)) else int(v), str(v)),
    "scene_type": lambda v: SCENE_TYPE.get(v[0] if isinstance(v, (bytes, bytearray)) else int(v), str(v)),
    "unit": lambda v: UNIT.get(int(v), str(v)),
    "ycbcr_position": lambda v: YCBCR_POSITION.get(int(v), str(v)),
    "gps_status": lambda v: GPS_STATUS.get(str(v).strip(), str(v)),
    "gps_measure": lambda v: GPS_MEASURE.get(str(v).strip(), str(v)),
    "gps_speedref": lambda v: GPS_SPEEDREF.get(str(v).strip(), str(v)),
    "gps_coord": format_gps_coord,
    "gps_alt": _fmt_gps_alt,
    "gps_time": _fmt_gps_time,
    "gps_processing": _fmt_gps_processing,
    "gps_altref": lambda v: "below sea level" if v == 1 else "above sea level",
    "gps_version": lambda v: ".".join(str(b) for b in v) if isinstance(v, (bytes, bytearray)) else str(v),
    "exposure": _fmt_exposure,
    "fnumber": _fmt_fnumber,
    "focal": _fmt_focal,
    "focal35": lambda v: "%d mm" % int(v),
    "ev": _fmt_ev,
    "dpi": _fmt_dpi,
    "apex_aperture": _fmt_apex_aperture,
    "apex_shutter": _fmt_apex_shutter,
    "distance": _fmt_distance,
    "zoom": _fmt_zoom,
    "version": _fmt_version,
    "user_comment": _fmt_user_comment,
    "xptext": _fmt_xp,
    "iso": lambda v: str(v[0] if isinstance(v, (list, tuple)) else v),
    "px": lambda v: "%d px" % int(v),
    "bytes": lambda v: "%d bytes" % int(v),
    "offset": lambda v: "0x%X" % int(v),
    "datetime": lambda v: str(v).strip().replace(":", "-", 2) if len(str(v)) >= 10 else str(v),
    "date": lambda v: str(v).strip(),
    "temperature": lambda v: "%+g C" % (rational_to_float(v) or 0),
    "lens_spec": _fmt_lens_spec,
}


def tag_info(ifd: str, tag: int) -> TagInfo:
    table = IFD_TABLES.get(ifd, {})
    return table.get(tag, TagInfo("0x%04X" % tag))


def format_value(ifd: str, tag: int, value: Any, type_id: int | None = None) -> str:
    info = tag_info(ifd, tag)
    if info.fmt and info.fmt in FORMATTERS:
        try:
            return FORMATTERS[info.fmt](value)
        except Exception:
            pass
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        if data and all(32 <= b < 127 for b in data.rstrip(b"\0")):
            return data.rstrip(b"\0").decode("ascii")
        return " ".join("%02X" % b for b in data[:32]) + ("..." if len(data) > 32 else "")
    if isinstance(value, tuple):
        return str(value[0]) if len(value) == 1 else "(" + ", ".join(map(str, value)) + ")"
    if isinstance(value, list):
        if len(value) == 1:
            return format_value(ifd, tag, value[0], type_id)
        return ", ".join(format_value(ifd, tag, v, type_id) for v in value)
    return str(value)


def resolve_name(name: str) -> tuple[str, int]:
    """Resolve EXIF.FNumber / FNumber / 0x829D style names."""
    raw = name.strip()
    if "." in raw:
        ifd, rest = raw.split(".", 1)
        ifd_map = {"IFD0": "IFD0", "IFD1": "IFD1", "EXIF": "EXIF", "EXIFIFD": "EXIF",
                   "GPS": "GPS", "GPSIFD": "GPS", "INTEROP": "Interop"}
        ifd = ifd_map.get(ifd.upper(), ifd)
        return ifd, _tag_id(rest, ifd)
    low = raw.lower()
    if low in ALIASES:
        return ALIASES[low]
    for ifd in ("IFD0", "EXIF", "GPS", "Interop"):
        table = IFD_TABLES[ifd]
        for tag, info in table.items():
            if info.name.lower() == low:
                return ifd, tag
    return "IFD0", _tag_id(raw, "IFD0")

ZH_NAMES = {
    "ImageWidth": "图像宽度", "ImageLength": "图像高度",
    "BitsPerSample": "每成分比特数", "SamplesPerPixel": "每像素成分数",
    "PhotometricInterpretation": "色彩合成方式", "ImageDescription": "图像描述",
    "Make": "制造商", "Model": "型号", "Orientation": "方向",
    "XResolution": "水平分辨率", "YResolution": "垂直分辨率",
    "ResolutionUnit": "分辨率单位", "Software": "软件", "DateTime": "修改时间",
    "Artist": "作者", "Copyright": "版权", "Compression": "压缩方式",
    "JPEGInterchangeFormat": "缩略图偏移量", "JPEGInterchangeFormatLength": "缩略图大小",
    "ExifVersion": "EXIF 版本", "FlashpixVersion": "FlashPix 版本",
    "ExifIFDPointer": "EXIF 子目录偏移量", "GPSInfoIFDPointer": "GPS 子目录偏移量",
    "InteroperabilityIFDPointer": "互操作子目录偏移量",
    "ExposureTime": "曝光时间", "FNumber": "光圈值", "ExposureProgram": "曝光程序",
    "ISOSpeedRatings": "感光度", "PhotographicSensitivity": "感光度",
    "SensitivityType": "感光度类型", "RecommendedExposureIndex": "推荐曝光指数",
    "DateTimeOriginal": "拍摄时间", "DateTimeDigitized": "数字化时间",
    "OffsetTime": "时区", "OffsetTimeOriginal": "原始时区",
    "ShutterSpeedValue": "快门速度", "ApertureValue": "光圈",
    "BrightnessValue": "亮度", "ExposureBiasValue": "曝光补偿",
    "MaxApertureValue": "最大光圈", "MeteringMode": "测光模式",
    "LightSource": "光源", "Flash": "闪光灯", "FocalLength": "镜头焦距",
    "SubjectArea": "主体区域", "UserComment": "用户注释",
    "FocalPlaneXResolution": "焦平面水平分辨率",
    "FocalPlaneYResolution": "焦平面垂直分辨率",
    "FocalPlaneResolutionUnit": "焦平面分辨率单位",
    "SensingMethod": "感光方式", "FileSource": "文件来源", "SceneType": "场景类型",
    "CustomRendered": "自定义处理", "ExposureMode": "曝光模式",
    "WhiteBalance": "白平衡", "DigitalZoomRatio": "数码变焦比例",
    "FocalLengthIn35mmFilm": "35mm等效焦距",
    "SceneCaptureType": "场景拍摄类型", "Contrast": "对比度",
    "Saturation": "饱和度", "Sharpness": "锐度",
    "DeviceSettingDescription": "设备设置描述",
    "SubjectDistanceRange": "主体距离范围", "ImageUniqueID": "图像唯一ID",
    "CameraOwnerName": "相机所有者", "BodySerialNumber": "机身序列号",
    "LensSpecification": "镜头参数", "LensMake": "镜头制造商",
    "LensModel": "镜头型号", "LensSerialNumber": "镜头序列号",
    "ColorSpace": "色彩空间", "PixelXDimension": "有效图像宽度",
    "PixelYDimension": "有效图像高度", "ComponentsConfiguration": "组件配置",
    "CompressedBitsPerPixel": "压缩位深度", "FlashEnergy": "闪光能量",
    "ExposureIndex": "曝光指数", "MakerNote": "厂商注释",
    "GPSVersionID": "GPS 版本", "GPSLatitudeRef": "纬度参考",
    "GPSLatitude": "GPS 纬度", "GPSLongitudeRef": "经度参考",
    "GPSLongitude": "GPS 经度", "GPSAltitudeRef": "海拔参考",
    "GPSAltitude": "GPS 海拔", "GPSTimeStamp": "GPS 时间",
    "GPSSatellites": "GPS 卫星", "GPSStatus": "GPS 状态",
    "GPSMeasureMode": "GPS 测量模式", "GPSDOP": "GPS 精度",
    "GPSSpeedRef": "速度单位", "GPSSpeed": "GPS 速度",
    "GPSMapDatum": "GPS 基准", "GPSDateStamp": "GPS 日期",
    "GPSProcessingMethod": "GPS 处理方法", "GPSHPositioningError": "GPS 水平误差",
    "InteroperabilityIndex": "互操作索引", "InteroperabilityVersion": "互操作版本",
}


def display_name(ifd: str, tag: int) -> str:
    """Human friendly item name; falls back to the canonical EXIF name."""
    info = tag_info(ifd, tag)
    return ZH_NAMES.get(info.name, info.name)



def _tag_id(text: str, ifd: str) -> int:
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    try:
        return int(text)
    except ValueError:
        pass
    for tag, info in IFD_TABLES[ifd].items():
        if info.name.lower() == text.lower():
            return tag
    raise KeyError("unknown tag name: %s" % text)

VALUE_ZH = {
    "Normal": "正常", "Manual": "手动", "Auto": "自动", "Unknown": "未知",
    "Not defined": "未定义", "Other": "其他", "None": "无",
    "Aperture priority": "光圈优先", "Shutter priority": "快门优先",
    "Normal program": "正常程序", "Creative": "创意", "Action": "运动",
    "Portrait": "人像", "Landscape": "风景", "Auto bracket": "自动包围",
    "Average": "平均测光", "Center-weighted average": "中央重点平均测光",
    "Spot": "点测光", "Multi-spot": "多点测光", "Partial": "局部测光",
    "Pattern": "中央重点测光",
    "Daylight": "日光", "Fluorescent": "荧光灯", "Tungsten": "钨丝灯",
    "Fine weather": "晴天", "Cloudy": "阴天", "Shade": "阴影",
    "Flash": "闪光灯", "Standard": "标准", "Soft": "柔和", "Hard": "强烈",
    "Low": "低", "High": "高",
    "Directly photographed": "直接拍摄", "DSC": "数码照相机 (DSC)",
    "Uncompressed": "未压缩", "JPEG": "JPEG 压缩",
    "inch": "英寸", "cm": "厘米",
    "Did not fire": "未闪光", "Fired": "已闪光",
    "Did not fire, compulsory flash mode": "关闭（强制）",
    "Fired, compulsory flash mode": "开启（强制）",
    "Did not fire, auto mode": "关闭（自动）",
    "Fired, auto mode": "开启（自动）",
    "Mirror horizontal": "水平镜像",
    "Rotate 180": "旋转 180°",
    "Mirror vertical": "垂直镜像",
    "Mirror horizontal and rotate 270 CW": "水平镜像后顺时针 270°",
    "Rotate 90 CW": "顺时针旋转 90°",
    "Mirror horizontal and rotate 90 CW": "水平镜像后顺时针 90°",
    "Rotate 270 CW": "逆时针旋转 90°",
    "WhiteIsZero": "白为零", "BlackIsZero": "黑为零",
    "Palette": "调色板", "CMYK": "CMYK", "YCbCr": "YCbCr", "CIELab": "CIELab",
    "One-chip color area": "单芯片彩色区域",
    "Two-chip color area": "双芯片彩色区域",
    "Three-chip color area": "三芯片彩色区域",
    "Color sequential area": "彩色顺序区域",
    "Trilinear": "三线性", "Color sequential linear": "彩色顺序线性",
    "Centered": "居中", "Co-sited": "与采样点一致",
    "above sea level": "海平面以上", "below sea level": "海平面以下",
    "2-dimensional": "二维", "3-dimensional": "三维",
    "Measurement in progress": "测量中", "Measurement interrupted": "测量中断",
    "km/h": "公里/小时", "mph": "英里/小时", "knots": "节",
}


def display_value(text: str) -> str:
    return VALUE_ZH.get(text, text)

# ---------------------------------------------------------------------------
# Editor help
# ---------------------------------------------------------------------------
# (description, expected input format) keyed by canonical tag name.
TAG_HELP: dict[str, tuple[str, str]] = {
    "ImageWidth": ("主图像的像素宽度。", "整数，例如 6000"),
    "ImageLength": ("主图像的像素高度。", "整数，例如 4000"),
    "BitsPerSample": ("每个颜色成分的位数，JPEG 常见为 8 8 8。", "整数；多个成分用空格分隔，例如 8 8 8"),
    "Compression": ("图像压缩方式代码。JPEG 文件通常是 6 或 7。", "整数代码，例如 7"),
    "PhotometricInterpretation": ("色彩合成方式代码，YCbCr JPEG 通常为 6。", "整数代码，例如 6"),
    "ImageDescription": ("图像标题或说明，可写中文。", "任意文本，例如 海边日落"),
    "Make": ("相机或设备制造商。", "文本，例如 SONY"),
    "Model": ("相机型号。", "文本，例如 ILCE-6300"),
    "Software": ("写入或处理过该图像的软件。修改它会影响原图可信度校验。", "文本，例如 Adobe Photoshop 25.0"),
    "Artist": ("摄影师或作者署名。", "文本，例如 Zhang San"),
    "Copyright": ("版权声明。", "文本，例如 (c) 2026 Zhang San"),
    "HostComputer": ("处理图像的计算机名称。", "文本"),
    "Orientation": ("图像显示方向。修改后部分查看器会旋转图像。", "整数代码；可直接点选常用值"),
    "XResolution": ("水平分辨率，单位由 ResolutionUnit 决定。", "分数或小数，例如 300/1"),
    "YResolution": ("垂直分辨率，单位由 ResolutionUnit 决定。", "分数或小数，例如 300/1"),
    "ResolutionUnit": ("分辨率的单位。", "整数代码，例如 2 表示英寸"),
    "DateTime": ("文件最后修改时间，格式固定。", "YYYY:MM:DD HH:MM:SS，例如 2026:01:02 15:30:00"),
    "Rating": ("星级评分，Windows 资源管理器会读取。", "0 到 5 的整数"),
    "RatingPercent": ("百分比评分。", "0 到 100 的整数"),
    "ExposureTime": ("快门开启时间，单位秒。", "分数或小数，例如 1/250 或 0.008"),
    "FNumber": ("镜头光圈 F 数。28/10 表示 F2.8。", "分数或小数，例如 28/10 或 2.8"),
    "ExposureProgram": ("相机使用的曝光程序。", "整数代码；可直接点选常用值"),
    "ISOSpeedRatings": ("拍摄感光度。", "整数，例如 100、400、3200"),
    "SensitivityType": ("ISO 灵敏度的定义方式。", "整数代码；可直接点选常用值"),
    "StandardOutputSensitivity": ("标准输出灵敏度（SOS）。", "整数，例如 100"),
    "RecommendedExposureIndex": ("推荐曝光指数（REI）。", "整数"),
    "ExifVersion": ("EXIF 标准版本，固定 4 位 ASCII 数字。", "4 位数字，例如 0231"),
    "DateTimeOriginal": ("照片拍摄时间，原图校验会与其它时间字段比对。", "YYYY:MM:DD HH:MM:SS，例如 2026:01:02 15:30:00"),
    "DateTimeDigitized": ("图像数字化时间，通常与拍摄时间一致。", "YYYY:MM:DD HH:MM:SS"),
    "OffsetTime": ("修改时间对应的 UTC 偏移。", "±HH:MM，例如 +08:00"),
    "OffsetTimeOriginal": ("拍摄时间对应的 UTC 偏移。", "±HH:MM，例如 +08:00"),
    "ShutterSpeedValue": ("APEX 快门速度值；8/1 约等于 1/256 秒。", "APEX 分数，例如 7965784/1000000"),
    "ApertureValue": ("APEX 光圈值；297/100 约等于 F2.8。", "APEX 分数，例如 297/100"),
    "BrightnessValue": ("APEX 亮度值，可正可负，0 表示中等亮度。", "有符号分数或小数，例如 -4196/2560 或 -1.64"),
    "ExposureBiasValue": ("曝光补偿，单位 EV。", "有符号分数或小数，例如 -1/3、1/2、0"),
    "MaxApertureValue": ("镜头最大光圈对应的 APEX 值。", "APEX 分数，例如 3/1"),
    "SubjectDistance": ("对焦距离，单位米。0 表示未知，0xFFFFFFFF 表示无穷远。", "分数或小数，例如 25/10"),
    "MeteringMode": ("测光模式。", "整数代码；可直接点选常用值"),
    "LightSource": ("白平衡使用的光源类型。", "整数代码；可直接点选常用值"),
    "Flash": ("闪光灯状态与功能，按位组合。", "整数代码，例如 16 表示强制关闭，24 表示自动开启"),
    "FocalLength": ("实际镜头焦距，单位毫米。", "分数或小数，例如 500/10"),
    "UserComment": ("用户注释文本。写入时会自动选择 ASCII 或 Unicode 编码。", "任意文本"),
    "SubSecTime": ("秒的小数部分。", "数字字符串，例如 123"),
    "ColorSpace": ("色彩空间定义。", "整数代码；可直接点选常用值"),
    "PixelXDimension": ("有效图像宽度（像素）。", "整数，例如 6000"),
    "PixelYDimension": ("有效图像高度（像素）。", "整数，例如 4000"),
    "FlashEnergy": ("闪光灯能量。", "分数或小数"),
    "FocalPlaneXResolution": ("焦平面水平分辨率。", "分数或小数，例如 6000/1"),
    "FocalPlaneYResolution": ("焦平面垂直分辨率。", "分数或小数"),
    "FocalPlaneResolutionUnit": ("焦平面分辨率的单位。", "整数代码，例如 2 表示英寸"),
    "SensingMethod": ("传感器类型。", "整数代码；可直接点选常用值"),
    "FileSource": ("文件来源。3 表示数码相机。", "整数代码，例如 3"),
    "SceneType": ("场景类型。1 表示直接拍摄。", "整数代码，例如 1"),
    "CustomRendered": ("是否经过特殊处理。", "整数代码，例如 0"),
    "ExposureMode": ("曝光模式。", "整数代码；可直接点选常用值"),
    "WhiteBalance": ("白平衡模式。", "整数代码；可直接点选常用值"),
    "DigitalZoomRatio": ("数码变焦倍率。1 表示未使用数码变焦。", "分数或小数，例如 1/1"),
    "FocalLengthIn35mmFilm": ("折算到 35mm 画幅的等效焦距。", "整数，例如 75"),
    "SceneCaptureType": ("场景拍摄类型。", "整数代码；可直接点选常用值"),
    "GainControl": ("增益控制方式。", "整数代码；可直接点选常用值"),
    "Contrast": ("对比度设置。", "整数代码，例如 0"),
    "Saturation": ("饱和度设置。", "整数代码，例如 0"),
    "Sharpness": ("锐度设置。", "整数代码，例如 0"),
    "SubjectDistanceRange": ("主体距离范围。", "整数代码；可直接点选常用值"),
    "ImageUniqueID": ("图像唯一标识，通常为十六进制字符串。", "32 位十六进制文本"),
    "CameraOwnerName": ("相机所有者名称。", "文本"),
    "BodySerialNumber": ("相机机身序列号。", "文本"),
    "LensSpecification": ("镜头规格：最短焦距 最长焦距 最小光圈 最大光圈。", "四个分数，例如 24/1 70/1 28/10 28/10"),
    "LensMake": ("镜头制造商。", "文本，例如 Sony"),
    "LensModel": ("镜头型号。", "文本，例如 E 35mm F1.8 OSS"),
    "LensSerialNumber": ("镜头序列号。", "文本"),
    "GPSVersionID": ("GPS 信息版本，通常为 2.3.0.0。", "4 个字节值，例如 2 3 0 0"),
    "GPSLatitudeRef": ("纬度参考方向。", "N（北纬）或 S（南纬）"),
    "GPSLatitude": ("纬度坐标。可直接填十进制度，或度/分/秒三个分数。", "十进制 39.9087，或 39/1 54/1 3123/100"),
    "GPSLongitudeRef": ("经度参考方向。", "E（东经）或 W（西经）"),
    "GPSLongitude": ("经度坐标。可直接填十进制度，或度/分/秒三个分数。", "十进制 116.3975，或 116/1 23/1 5100/100"),
    "GPSAltitudeRef": ("海拔参考：海平面以上或以下。", "0 海平面以上，1 海平面以下"),
    "GPSAltitude": ("海拔高度，单位米。", "分数或小数，例如 4356/100"),
    "GPSTimeStamp": ("UTC 时间，三个分数表示时、分、秒。", "三个分数，例如 7/1 30/1 1234/100"),
    "GPSDateStamp": ("UTC 日期。", "YYYY:MM:DD，例如 2026:01:02"),
    "GPSStatus": ("GPS 接收器状态。", "A 测量中，V 测量中断"),
    "GPSMeasureMode": ("GPS 测量维度。", "2 二维，3 三维"),
    "GPSSpeedRef": ("速度单位。", "K 公里/小时，M 英里/小时，N 节"),
    "GPSMapDatum": ("大地基准面。", "文本，例如 WGS-84"),
    "GPSProcessingMethod": ("定位计算方法说明。", "文本，例如 CELLID、GPS"),
    "GPSDifferential": ("是否使用差分校正。", "0 无差分，1 差分校正"),
    "InteroperabilityIndex": ("互操作规范标识。", "R98、R03 或 THM"),
    "InteroperabilityVersion": ("互操作规范版本。", "4 位数字，例如 0100"),
    "RelatedImageWidth": ("关联图像宽度。", "整数"),
    "RelatedImageLength": ("关联图像高度。", "整数"),
    "ExifIFDPointer": ("EXIF 子目录指针，由写入器自动维护，通常不要手动修改。", "只读指针"),
    "GPSInfoIFDPointer": ("GPS 子目录指针，由写入器自动维护，通常不要手动修改。", "只读指针"),
    "InteroperabilityIFDPointer": ("互操作子目录指针，由写入器自动维护，通常不要手动修改。", "只读指针"),
    "MakerNote": ("厂商私有数据，结构随品牌和机型变化，编辑器只读保留。", "只读"),
}

ENUM_CHOICES: dict[str, tuple[tuple[str, str], ...]] = {
    "Orientation": (
        ("1", "正常"), ("2", "水平镜像"), ("3", "旋转 180°"),
        ("4", "垂直镜像"), ("5", "水平镜像 + 顺时针 270°"),
        ("6", "顺时针旋转 90°"), ("7", "水平镜像 + 顺时针 90°"),
        ("8", "逆时针旋转 90°")),
    "ResolutionUnit": (("1", "无单位"), ("2", "英寸"), ("3", "厘米")),
    "YCbCrPositioning": (("1", "居中"), ("2", "与采样点一致")),
    "Compression": (("1", "未压缩"), ("6", "旧式 JPEG"), ("7", "JPEG")),
    "PhotometricInterpretation": (
        ("0", "白为零"), ("1", "黑为零"), ("2", "RGB"), ("3", "调色板"),
        ("5", "CMYK"), ("6", "YCbCr"), ("8", "CIELab")),
    "ExposureProgram": (
        ("0", "未定义"), ("1", "手动"), ("2", "正常程序"), ("3", "光圈优先"),
        ("4", "快门优先"), ("5", "创意程序"), ("6", "运动程序"),
        ("7", "人像"), ("8", "风景")),
    "MeteringMode": (
        ("0", "未知"), ("1", "平均"), ("2", "中央重点平均"), ("3", "点测光"),
        ("4", "多点测光"), ("5", "矩阵/图案"), ("6", "局部测光"), ("255", "其他")),
    "LightSource": (
        ("0", "未知"), ("1", "日光"), ("2", "荧光灯"), ("3", "钨丝灯"),
        ("4", "闪光灯"), ("9", "晴天"), ("10", "阴天"), ("11", "阴影"),
        ("12", "日光荧光灯"), ("13", "日光白荧光灯"), ("14", "冷白荧光灯"),
        ("15", "白色荧光灯"), ("17", "标准 A"), ("18", "标准 B"),
        ("19", "标准 C"), ("20", "D55"), ("21", "D65"), ("22", "D75"),
        ("23", "D50"), ("24", "ISO 影棚钨丝灯"), ("255", "其他")),
    "ColorSpace": (
        ("1", "sRGB"), ("2", "Adobe RGB"), ("65533", "广色域 RGB"),
        ("65534", "ICC 配置文件"), ("65535", "未校准")),
    "SensingMethod": (
        ("1", "未定义"), ("2", "单芯片彩色区域"), ("3", "双芯片彩色区域"),
        ("4", "三芯片彩色区域"), ("5", "彩色顺序区域"),
        ("7", "三线性"), ("8", "彩色顺序线性")),
    "CustomRendered": (("0", "正常"), ("1", "自定义处理")),
    "ExposureMode": (("0", "自动"), ("1", "手动"), ("2", "自动包围")),
    "WhiteBalance": (("0", "自动"), ("1", "手动")),
    "SceneCaptureType": (("0", "标准"), ("1", "风景"), ("2", "人像"), ("3", "夜景")),
    "GainControl": (
        ("0", "无"), ("1", "低增益提升"), ("2", "高增益提升"),
        ("3", "低增益降低"), ("4", "高增益降低")),
    "Contrast": (("0", "正常"), ("1", "柔和"), ("2", "强烈")),
    "Saturation": (("0", "正常"), ("1", "低"), ("2", "高")),
    "Sharpness": (("0", "正常"), ("1", "柔和"), ("2", "强烈")),
    "SubjectDistanceRange": (("0", "未知"), ("1", "微距"), ("2", "近景"), ("3", "远景")),
    "SensitivityType": (
        ("0", "未知"), ("1", "标准输出灵敏度"), ("2", "推荐曝光指数"),
        ("3", "ISO 速度"), ("4", "SOS"), ("5", "REI"),
        ("6", "ISO 速度"), ("7", "SOS + REI")),
    "FileSource": (("3", "数码相机")),
    "SceneType": (("1", "直接拍摄")),
    "GPSAltitudeRef": (("0", "海平面以上"), ("1", "海平面以下")),
    "GPSStatus": (("A", "测量中"), ("V", "测量中断")),
    "GPSMeasureMode": (("2", "二维"), ("3", "三维")),
    "GPSSpeedRef": (("K", "公里/小时"), ("M", "英里/小时"), ("N", "节")),
    "GPSDifferential": (("0", "无差分"), ("1", "差分校正")),
    "InteroperabilityIndex": (("R98", "标准 EXIF"), ("R03", "DCF 基本"), ("THM", "缩略图")),
}

_TYPE_DESC = {
    ASCII: "文本字段。",
    SHORT: "无符号 16 位整数。",
    LONG: "无符号 32 位整数。",
    RATIONAL: "有理数，以分子/分母保存。",
    SRATIONAL: "有符号有理数，以分子/分母保存。",
    BYTE: "字节序列。",
    UNDEFINED: "字节序列。",
    SSHORT: "有符号 16 位整数。",
    SLONG: "有符号 32 位整数。",
    FLOAT: "单精度小数。",
    DOUBLE: "双精度小数。",
}

_TYPE_FORMAT = {
    ASCII: "直接输入文本，例如 Canon EOS R5",
    SHORT: "整数；多个值用空格分隔，例如 8 8 8",
    LONG: "整数；多个值用空格分隔，例如 6000",
    RATIONAL: "分数或小数；多个值用空格分隔，例如 1/250 或 28/10",
    SRATIONAL: "可带负号的分数或小数；多个值用空格分隔，例如 -4196/2560",
    BYTE: "文本按 UTF-8 写入；0x 开头按十六进制，例如 0x0231",
    UNDEFINED: "文本按 UTF-8 写入；0x 开头按十六进制，例如 0x0231",
    SSHORT: "可带负号的整数；多个值用空格分隔",
    SLONG: "可带负号的整数；多个值用空格分隔",
    FLOAT: "小数；多个值用空格分隔",
    DOUBLE: "小数；多个值用空格分隔",
}

XMP_HELP: dict[str, tuple[str, str]] = {
    "dc:title": ("图像标题，多个语言版本在 XMP 面板中维护。", "文本，例如 海边日落"),
    "dc:description": ("图像说明或图注。", "文本，例如 傍晚在栈桥拍摄"),
    "dc:creator": ("作者或摄影师。", "文本，例如 Zhang San"),
    "dc:rights": ("版权声明。", "文本，例如 (c) 2026 Zhang San"),
    "dc:subject": ("关键词列表。", "文本，多个关键词由 XMP 面板维护"),
    "dc:format": ("文件 MIME 类型。", "例如 image/jpeg"),
    "xmp:CreatorTool": ("创建该文件的软件。", "文本，例如 Adobe Photoshop 25.0"),
    "xmp:CreateDate": ("创建时间。", "ISO 8601，例如 2026-01-02T15:30:00+08:00"),
    "xmp:ModifyDate": ("修改时间。", "ISO 8601，例如 2026-01-02T16:00:00+08:00"),
    "xmp:MetadataDate": ("元数据最后修改时间。", "ISO 8601 时间"),
    "xmp:Rating": ("星级评分。", "0 到 5 的整数"),
    "photoshop:DateCreated": ("Photoshop 记录的创建时间。", "ISO 8601 时间"),
    "photoshop:City": ("拍摄城市。", "文本，例如 上海"),
    "photoshop:Country": ("拍摄国家。", "文本，例如 China"),
    "exif:GPSLatitude": ("XMP 中的纬度，十进制度。", "例如 39,54.3123N 或 39.9087"),
    "exif:GPSLongitude": ("XMP 中的经度，十进制度。", "例如 116,23.51E 或 116.3975"),
}


def tag_help(name: str) -> dict[str, Any]:
    """Describe one tag for the editor dialog.

    The hint follows the tag currently typed into the dialog, so it stays
    relevant when the user edits the tag name as well as its value.
    """
    raw = str(name or "").strip()
    if not raw:
        return {"name": "", "ifd": "", "tag": "", "type": "",
                "desc": "填写标签名后，这里会显示该标签的含义和输入格式。",
                "format": "", "options": [], "readonly": False}
    if raw.upper().startswith("XMP."):
        key = raw[4:]
        desc, fmt = XMP_HELP.get(key, (
            "XMP 属性以纯文本写入，适合标题、作者、日期等扩展信息。",
            "纯文本或数值，例如 2026-01-02T15:30:00"))
        return {"name": raw, "ifd": "XMP", "tag": key, "type": "XMP",
                "desc": desc, "format": fmt, "options": [], "readonly": False}
    try:
        ifd, tag = resolve_name(raw)
    except Exception:
        return {"name": raw, "ifd": "", "tag": "", "type": "",
                "desc": "这个标签名没有收录，保存时会按原始类型尝试写入。",
                "format": "建议使用 IFD0.Model、EXIF.FNumber 或 0x0110 形式",
                "options": [], "readonly": False}
    info = tag_info(ifd, tag)
    desc, fmt = TAG_HELP.get(info.name, ("", ""))
    if not desc:
        desc = _TYPE_DESC.get(info.type or ASCII, "")
    if not fmt:
        fmt = _TYPE_FORMAT.get(info.type or ASCII, "")
    options = ENUM_CHOICES.get(info.name, ())
    known = info.name != ("0x%04X" % tag)
    return {
        "name": info.name if known else raw,
        "ifd": ifd,
        "tag": "0x%04X" % tag,
        "type": TYPE_NAMES.get(info.type, "") if info.type else "",
        "desc": desc,
        "format": fmt,
        "options": [{"value": v, "label": label} for v, label in options],
        "readonly": info.name in ("MakerNote", "ExifIFDPointer",
                                  "GPSInfoIFDPointer", "InteroperabilityIFDPointer"),
    }

