"""Vendor maker note decoding and offset-aware re-encoding.

Only the Canon, Nikon, Sony, Olympus, Fujifilm, Pentax, Apple, Samsung,
Panasonic and DJI families are modelled here; other maker notes are kept as
opaque bytes.  Maker notes whose internal offsets are relative to the TIFF
header (Canon, Apple, Nikon type 1) are re-encoded when the EXIF block is
rebuilt so that previews and other pointed-to data keep working.  Notes whose
offsets are relative to the note itself are copied verbatim, which is safe
because the note keeps its internal coordinate system.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Callable

from .tags import BYTE, RATIONAL, SHORT, SRATIONAL, UNDEFINED, TYPE_SIZES

# ---------------------------------------------------------------------------
# Tag tables
# ---------------------------------------------------------------------------
CANON_TAGS = {
    0x0001: "CameraSettings", 0x0002: "FocalLength", 0x0003: "FlashInfo",
    0x0004: "ShotInfo", 0x0005: "Panorama", 0x0006: "ImageType",
    0x0007: "FirmwareVersion", 0x0008: "FileNumber", 0x0009: "OwnerName",
    0x000C: "SerialNumber", 0x000D: "CameraInfo", 0x000E: "FileLength",
    0x000F: "CustomFunctions", 0x0010: "ModelID", 0x0012: "PictureInfo",
    0x0013: "ThumbnailImageValidArea", 0x0015: "SerialNumberFormat",
    0x001A: "Supermacro", 0x001C: "DateStampMode", 0x001D: "MyColors",
    0x001E: "FirmwareRevision", 0x0024: "AFInfo", 0x0095: "LensModel",
    0x0096: "InternalSerialNumber", 0x0097: "DustRemovalData",
    0x0098: "CropInfo", 0x0099: "CustomFunctions2", 0x009A: "AspectInfo",
    0x00A0: "ProcessingInfo", 0x00A1: "ToneCurveTable",
    0x00A2: "SharpnessTable", 0x00A3: "SharpnessFreqTable",
    0x00A4: "WhiteBalanceTable", 0x00A9: "ColorBalance",
    0x00B4: "ColorSpace", 0x00D0: "VRDOffset", 0x00E0: "SensorInfo",
    0x4001: "ColorData", 0x4002: "CRWParam", 0x4005: "Flavor",
    0x4013: "AFMicroAdj", 0x4018: "VignettingCorr", 0x4019: "VignettingCorr2",
    0x4020: "LightingOpt", 0x4024: "AmbienceInfo", 0x4025: "MultiExp",
    0x403F: "FilterInfo", 0x4040: "HDRInfo",
}

NIKON_TAGS = {
    0x0001: "Version", 0x0002: "ISO", 0x0003: "ColorMode", 0x0004: "Quality",
    0x0005: "WhiteBalance", 0x0006: "Sharpness", 0x0007: "FocusMode",
    0x0008: "FlashSetting", 0x0009: "FlashType", 0x000B: "WhiteBalanceBias",
    0x000D: "ProgramShift", 0x000E: "ExposureDifference", 0x0011: "PreviewIFD",
    0x0012: "FlashComp", 0x0013: "ISOSetting", 0x0016: "ImageBoundary",
    0x0018: "FlashExposureComp", 0x0019: "FlashBracketComp",
    0x001A: "ExposureBracketComp", 0x001B: "CropHiSpeed",
    0x001C: "ExposureTuning", 0x001D: "SerialNumber", 0x001E: "ColorSpace",
    0x0022: "ActiveDLighting", 0x0023: "PictureControl", 0x0024: "WorldTime",
    0x0025: "ISOInfo", 0x002A: "VignetteControl", 0x0080: "ImageAdjustment",
    0x0081: "ToneComp", 0x0082: "AuxiliaryLens", 0x0083: "LensType",
    0x0084: "Lens", 0x0085: "FocusDistance", 0x0086: "DigitalZoom",
    0x0087: "FlashMode", 0x0088: "AFInfo", 0x0089: "ShootingMode",
    0x008B: "LensFStops", 0x008C: "ContrastCurve", 0x008D: "ColorHue",
    0x008F: "SceneMode", 0x0090: "LightSource", 0x0091: "ShotInfo",
    0x0092: "HueAdjustment", 0x0093: "NEFCompression", 0x0094: "Saturation",
    0x0095: "NoiseReduction", 0x0096: "NEFLinearization",
    0x0097: "ColorBalance", 0x0098: "LensData", 0x0099: "RawImageCenter",
    0x009A: "SensorPixelSize", 0x009C: "SceneAssist", 0x009E: "RetouchHistory",
    0x00A0: "SerialNumber2", 0x00A2: "ImageDataSize", 0x00A5: "ImageCount",
    0x00A6: "DeletedImageCount", 0x00A7: "ShutterCount", 0x00A8: "FlashInfo",
    0x00A9: "ImageOptimization", 0x00AA: "Saturation2", 0x00AB: "VariProgram",
    0x00AC: "ImageStabilization", 0x00AD: "AFResponse", 0x00B0: "MultiExposure",
    0x00B1: "HighISONoiseReduction", 0x00B3: "ToningEffect", 0x00B7: "AFInfo2",
    0x00B8: "FileInfo", 0x00B9: "AFTune", 0x00BB: "RetouchInfo",
    0x00BD: "PictureControl2", 0x00C0: "SerialNumber3",
}

SONY_TAGS = {
    0x0102: "Quality", 0x0104: "FlashExposureComp", 0x0105: "Teleconverter",
    0x0112: "WhiteBalanceFineTune", 0x0114: "CameraSettings",
    0x0115: "WhiteBalance", 0x0116: "ExtraInfo", 0x2010: "PrintImageMatching",
    0x2020: "ColorMode", 0x2021: "ColorSpace", 0x2022: "DynamicRangeOptimizer",
    0x2023: "AutoHDR", 0x9400: "ImageSize", 0x9401: "LensID",
    0x9402: "LensSpec", 0x9403: "ShutterCount", 0x9404: "ImageNumber",
    0x9405: "SonyDateTime", 0x9406: "SonyDateTime2",
}

OLYMPUS_TAGS = {
    0x0100: "MakerNoteVersion", 0x0104: "BodyFirmwareVersion",
    0x0200: "SpecialMode", 0x0201: "JPEGQuality", 0x0202: "Macro",
    0x0203: "BWMode", 0x0204: "DigitalZoom", 0x0205: "FocalPlaneDiagonal",
    0x0206: "LensDistortionParams", 0x0207: "CameraType", 0x0208: "TextInfo",
    0x0209: "CameraID", 0x020B: "EpsonImageWidth", 0x020C: "EpsonImageHeight",
    0x020D: "EpsonSoftware", 0x2010: "Equipment", 0x2020: "CameraSettings",
    0x2030: "RawDevelopment", 0x2040: "ImageProcessing", 0x2050: "FocusInfo",
    0x3000: "RawInfo", 0x4000: "MainInfo",
}

FUJI_TAGS = {
    0x0000: "Version", 0x0010: "InternalSerialNumber", 0x1000: "Quality",
    0x1001: "Sharpness", 0x1002: "WhiteBalance", 0x1003: "Color",
    0x1004: "Tone", 0x1005: "ColorTemperature", 0x1006: "Contrast",
    0x100A: "WhiteBalanceFineTune", 0x1010: "FlashMode",
    0x1011: "FlashExposureComp", 0x1020: "Macro", 0x1021: "FocusMode",
    0x1022: "AFMode", 0x1023: "FocusPixel", 0x1030: "SlowSync",
    0x1031: "PictureMode", 0x1032: "ExposureCount", 0x1033: "EXRAuto",
    0x1034: "EXRMode", 0x1100: "AutoBracketing", 0x1101: "SequenceNumber",
    0x1210: "ColorMode", 0x1300: "BlurWarning", 0x1301: "FocusWarning",
    0x1302: "ExposureWarning", 0x1400: "DynamicRange", 0x1401: "FilmMode",
    0x1402: "DynamicRangeSetting", 0x1403: "DevelopmentDynamicRange",
    0x1404: "MinFocalLength", 0x1405: "MaxFocalLength",
    0x1406: "MaxApertureAtMinFocal", 0x1407: "MaxApertureAtMaxFocal",
    0x140B: "AutoDynamicRange", 0x4100: "FacesDetected",
    0x4103: "FacePositions", 0x8000: "FileSource", 0x8002: "OrderNumber",
    0x8003: "FrameNumber",
}

PENTAX_TAGS = {
    0x0000: "Version", 0x0001: "Mode", 0x0002: "PreviewResolution",
    0x0003: "PreviewLength", 0x0004: "PreviewOffset", 0x0005: "ModelID",
    0x0006: "Date", 0x0007: "Time", 0x0008: "Quality", 0x0009: "Size",
    0x000D: "FocusMode", 0x000E: "AFPoint", 0x000F: "AFPointInFocus",
    0x0012: "ExposureTime", 0x0013: "FNumber", 0x0014: "ISO",
    0x0015: "LightReading", 0x0016: "ExposureCompensation",
    0x0017: "MeteringMode", 0x0018: "AutoBracketing", 0x0019: "WhiteBalance",
    0x001A: "WhiteBalanceMode", 0x001B: "BlueBalance", 0x001C: "RedBalance",
    0x001D: "FocalLength", 0x001E: "DigitalZoom", 0x001F: "Saturation",
    0x0020: "Contrast", 0x0021: "Sharpness", 0x0022: "WorldTimeLocation",
    0x0023: "HometownCity", 0x0024: "DestinationCity",
    0x0025: "HometownDST", 0x0026: "DestinationDST", 0x0027: "DSPFirmwareVersion",
    0x0028: "CPUFirmwareVersion", 0x0029: "FrameNumber", 0x002D: "EffectiveLV",
    0x0032: "ImageEditing", 0x0037: "PictureMode", 0x0039: "DriveMode",
    0x003D: "ColorSpace", 0x003F: "LensType",
}

APPLE_TAGS = {
    0x0001: "MakerNoteVersion", 0x0003: "RunTime", 0x0004: "AEStable",
    0x0005: "AETarget", 0x0006: "AEAverage", 0x0007: "AFStable",
    0x0008: "AccelerationVector", 0x000A: "HDRImageType",
    0x000B: "BurstUUID", 0x000E: "FocusDistanceRange",
    0x0011: "ContentIdentifier", 0x0014: "ImageCaptureType",
    0x0015: "ImageUniqueID", 0x0017: "LivePhotoVideoIndex",
    0x0019: "ImageCaptureRequestID", 0x001A: "HDRHeadroom",
    0x001C: "QualityHint", 0x001D: "LuminanceNoiseAmplitude",
    0x001F: "PhotosAppFeatureFlags", 0x0020: "ImageCaptureRequest",
    0x0021: "PhotoIdentifier", 0x0023: "CameraType",
}

DJI_TAGS = {
    0x0001: "Make", 0x0003: "SpeedX", 0x0004: "SpeedY", 0x0005: "SpeedZ",
    0x0006: "Pitch", 0x0007: "Yaw", 0x0008: "Roll", 0x0009: "CameraPitch",
    0x000A: "CameraYaw", 0x000B: "CameraRoll", 0x000C: "GimbalPitch",
    0x000D: "GimbalYaw", 0x000E: "GimbalRoll", 0x000F: "FlightPitch",
    0x0010: "FlightYaw", 0x0011: "FlightRoll", 0x0012: "Altitude",
    0x0013: "GPSLatitude", 0x0014: "GPSLongitude",
}

SAMSUNG_TAGS = {
    0x0001: "MakerNoteVersion", 0x0002: "DeviceType", 0x0003: "ModelID",
    0x0021: "PictureWizard", 0x0030: "LocalLocationName",
    0x0031: "LocationName", 0x0035: "PreviewIFD", 0x0043: "CameraTemperature",
    0x0045: "FirmwareName", 0x0046: "LastSoftwareVersion",
}

PANASONIC_TAGS = {
    0x0001: "Version", 0x0002: "Quality", 0x0003: "FirmwareVersion",
    0x0007: "WhiteBalance", 0x000F: "AFMode", 0x001A: "ImageStabilization",
    0x001C: "MacroMode", 0x001F: "ShootingMode", 0x0020: "Audio",
    0x0023: "WhiteBalanceBias", 0x0024: "FlashBias", 0x0025: "InternalSerialNumber",
    0x0026: "ExifVersion", 0x0028: "ColorEffect", 0x0029: "TimeSincePowerOn",
    0x002A: "BurstMode", 0x002B: "SequenceNumber", 0x002C: "ContrastMode",
    0x002D: "NoiseReduction", 0x002E: "SelfTimer", 0x0030: "Rotation",
    0x0031: "AFAssistLamp", 0x0032: "ColorMode", 0x0033: "BabyAge",
    0x0034: "OpticalZoomMode", 0x0035: "ConversionLens", 0x0036: "TravelDay",
    0x0039: "Contrast", 0x003A: "WorldTimeLocation", 0x003B: "TextStamp",
    0x003C: "ProgramISO", 0x003D: "AdvancedSceneType", 0x003E: "TextStamp2",
    0x003F: "FacesDetected", 0x0040: "Saturation", 0x0041: "Sharpness",
    0x0042: "FilmMode", 0x0044: "ColorTempKelvin", 0x0045: "BracketSettings",
    0x0046: "WBShiftAB", 0x0047: "WBShiftGM", 0x0048: "FlashCurtain",
    0x0049: "LongShutterNoiseReduction", 0x004B: "PanasonicImageWidth",
    0x004C: "PanasonicImageHeight", 0x004D: "AFPointPosition",
    0x004E: "FaceDetectionInfo", 0x0051: "LensType", 0x0052: "LensSerialNumber",
    0x0053: "AccessoryType", 0x0054: "AccessorySerialNumber",
    0x0059: "Transform", 0x005D: "IntelligentExposure",
    0x0060: "LensFirmwareVersion", 0x0061: "FaceRecognitionInfo",
    0x0062: "SonyModelID", 0x0065: "Title", 0x0066: "BabyName",
    0x0067: "Location", 0x0069: "Country", 0x006B: "State",
    0x006D: "City", 0x006F: "Landmark", 0x0070: "IntelligentResolution",
    0x0077: "BurstGroupID", 0x0079: "PortraitSceneMode",
    0x007A: "ShutterType", 0x0081: "ColorEffect2", 0x0086: "ManometerReading",
    0x0089: "VideoBurstResolution", 0x008A: "MultiExposure",
    0x008B: "RedEyeRemoval", 0x008D: "VideoCaptureMode",
    0x0090: "ShootingMode2", 0x0091: "PanasonicImageWidth2",
}

MAKER_TAGS = {
    "Canon": CANON_TAGS, "Nikon": NIKON_TAGS, "Sony": SONY_TAGS,
    "Olympus": OLYMPUS_TAGS, "Fujifilm": FUJI_TAGS, "Pentax": PENTAX_TAGS,
    "Apple": APPLE_TAGS, "DJI": DJI_TAGS, "Samsung": SAMSUNG_TAGS,
    "Panasonic": PANASONIC_TAGS,
}

SIGNATURES = [
    ("Canon", b""), ("Nikon", b"Nikon"), ("Sony", b"SONY"),
    ("Olympus", b"OLYMP"), ("Fujifilm", b"FUJIFILM"), ("Pentax", b"AOC"),
    ("Pentax", b"PENTAX"), ("Apple", b"Apple"), ("DJI", b"DJI"),
    ("Samsung", b"SAMSUNG"), ("Panasonic", b"Panasonic"),
]

CANON_CAMERA_SETTINGS = {
    1: "MacroMode", 2: "SelfTimer", 3: "Quality", 4: "FlashMode",
    5: "ContinuousDrive", 7: "FocusMode", 9: "RecordMode", 10: "ImageSize",
    11: "EasyMode", 12: "DigitalZoom", 13: "Contrast", 14: "Saturation",
    15: "Sharpness", 16: "CameraISO", 17: "MeteringMode", 18: "FocusRange",
    19: "AFPoint", 20: "ExposureMode", 22: "LensType", 23: "LongFocal",
    24: "ShortFocal", 25: "FocalUnits", 26: "MaxAperture", 27: "MinAperture",
    28: "FlashActivity", 29: "FlashBits", 32: "FocusContinuous",
    33: "AESetting", 34: "ImageStabilization", 35: "DisplayAperture",
    36: "ZoomSourceWidth", 37: "ZoomTargetWidth", 39: "SpotMeteringMode",
    40: "PhotoEffect", 41: "ManualFlashOutput", 42: "ColorTone",
    46: "SRAWQuality",
}

CANON_ISO = {0: "n/a", 14: "Auto", 15: "50", 16: "100", 17: "200", 18: "400",
             19: "800", 20: "1600", 261: "3200"}

CANON_LENS = {
    1: "Canon EF 50mm f/1.8", 2: "Canon EF 28mm f/2.8", 3: "Canon EF 135mm f/2.8 Soft",
    4: "Canon EF 35-105mm f/3.5-4.5", 5: "Canon EF 35-70mm f/3.5-4.5",
    6: "Canon EF 28-70mm f/3.5-4.5", 7: "Canon EF 100-300mm f/5.6L",
    8: "Canon EF 100-300mm f/5.6", 9: "Canon EF 70-210mm f/4",
    10: "Canon EF 50mm f/2.5 Macro", 11: "Canon EF 35mm f/2",
    12: "Canon EF 28mm f/2.8", 13: "Canon EF 15mm f/2.8 Fisheye",
    14: "Canon EF 50-200mm f/3.5-4.5L", 15: "Canon EF 50-200mm f/3.5-4.5",
    16: "Canon EF 35-135mm f/3.5-4.5", 17: "Canon EF 35-70mm f/3.5-4.5A",
    18: "Canon EF 28-70mm f/3.5-4.5", 19: "Canon EF 100-300mm f/5.6L",
    20: "Canon EF 100-300mm f/5.6", 21: "Canon EF 70-210mm f/4",
    22: "Canon EF 50mm f/2.5 Macro", 26: "Canon EF 100mm f/2.8 Macro",
    28: "Canon EF 80-200mm f/2.8L", 29: "Canon EF 50mm f/1.8 II",
    30: "Canon EF 35-105mm f/4.5-5.6", 31: "Canon EF 75-300mm f/4-5.6",
    32: "Canon EF 300mm f/4L IS USM", 33: "Canon EF 28-135mm f/3.5-5.6 IS",
    39: "Canon EF 75-300mm f/4-5.6 IS USM", 40: "Canon EF 28-105mm f/3.5-4.5 USM",
    43: "Canon EF 100-400mm f/4.5-5.6L IS USM", 45: "Canon EF-S 18-55mm f/3.5-5.6",
    46: "Canon EF 50mm f/1.4 USM", 47: "Canon EF 85mm f/1.8 USM",
    48: "Canon EF 100mm f/2.8 Macro USM", 50: "Canon EF 100-300mm f/4.5-5.6 USM",
    51: "Canon EF 24-85mm f/3.5-4.5 USM", 52: "Canon EF 28-105mm f/4-5.6 USM",
    53: "Canon EF 70-200mm f/4L USM", 54: "Canon EF 35-350mm f/3.5-5.6L USM",
    55: "Canon EF 28-200mm f/3.5-5.6 USM", 56: "Canon EF 28-90mm f/4-5.6 USM",
    57: "Canon EF 90-300mm f/4.5-5.6", 58: "Canon EF-S 18-55mm f/3.5-5.6 USM",
    59: "Canon EF 70-300mm f/4.5-5.6 DO IS USM", 60: "Canon EF 28-300mm f/3.5-5.6L IS USM",
    61: "Canon EF-S 17-85mm f/4-5.6 IS USM", 63: "Canon EF-S 18-55mm f/3.5-5.6 II",
    64: "Canon EF 17-40mm f/4L USM", 65: "Canon EF-S 10-22mm f/3.5-4.5 USM",
    66: "Canon EF 24-70mm f/2.8L USM", 67: "Canon EF 70-200mm f/2.8L IS USM",
    68: "Canon EF 85mm f/1.2L USM", 69: "Canon EF 70-200mm f/4L IS USM",
    71: "Canon EF 24-105mm f/4L IS USM", 72: "Canon EF 70-300mm f/4-5.6 IS USM",
    73: "Canon EF 50mm f/1.2L USM", 74: "Canon EF 85mm f/1.2L II USM",
    75: "Canon EF-S 18-55mm f/3.5-5.6 IS", 76: "Canon EF 70-200mm f/2.8L IS II USM",
    77: "Canon EF 24-70mm f/2.8L II USM", 78: "Canon EF 16-35mm f/2.8L II USM",
    79: "Canon EF 14mm f/2.8L II USM", 80: "Canon EF 24mm f/1.4L II USM",
    81: "Canon EF 35mm f/1.4L USM", 82: "Canon EF 100mm f/2.8L Macro IS USM",
    83: "Canon EF 70-200mm f/4L IS II USM", 84: "Canon EF 24-105mm f/3.5-5.6 IS STM",
    85: "Canon EF 40mm f/2.8 STM", 86: "Canon EF-S 18-135mm f/3.5-5.6 IS STM",
    87: "Canon EF 28mm f/2.8 IS USM", 88: "Canon EF 24mm f/2.8 IS USM",
    89: "Canon EF 35mm f/2 IS USM", 90: "Canon EF 100-400mm f/4.5-5.6L IS II USM",
    91: "Canon EF 400mm f/4 DO IS II USM", 92: "Canon EF 11-24mm f/4L USM",
    93: "Canon EF 100-400mm f/4.5-5.6L IS II USM",
}


@dataclass
class MakerField:
    tag: int
    name: str
    type: int
    count: int
    value: Any
    raw: bytes

    def display(self) -> str:
        v = self.value
        from .tags import format_value
        return format_value("MakerNote", self.tag, v, self.type)


@dataclass
class MakerNote:
    maker: str
    raw: bytes
    endian: str
    header_len: int = 0
    offset_delta: int = 0
    tiff_relative: bool = False
    encodable: bool = False
    fields: list[MakerField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def get(self, name: str, default: Any = None) -> Any:
        low = name.lower()
        for f in self.fields:
            if f.name.lower() == low:
                return f.value
        return default

    def describe(self) -> list[dict[str, Any]]:
        return [{"tag": f.tag, "name": f.name, "type": f.type, "count": f.count,
                 "value": f.value, "display": f.display()} for f in self.fields]

    def encode(self, abs_offset: int) -> bytes:
        if not self.encodable or not self.fields:
            return self.raw
        # Rewrite offsets against the new absolute position only when the
        # original note addressed data relative to the TIFF header.
        delta = abs_offset if self.tiff_relative else 0
        return _encode_ifd(self.fields, self.header_len, self.endian, delta,
                           self.raw[:self.header_len])


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _u16(data: bytes, off: int, endian: str) -> int:
    return struct.unpack_from(endian + "H", data, off)[0]


def _u32(data: bytes, off: int, endian: str) -> int:
    return struct.unpack_from(endian + "I", data, off)[0]


def _read_ifd(data: bytes, ifd_off: int, endian: str, delta: int,
              table: dict[int, str], maker: str) -> list[MakerField]:
    if ifd_off + 2 > len(data):
        return []
    count = _u16(data, ifd_off, endian)
    if count == 0 or count > 300 or ifd_off + 2 + 12 * count > len(data):
        return []
    fields: list[MakerField] = []
    for i in range(count):
        base = ifd_off + 2 + 12 * i
        tag, typ, cnt = struct.unpack_from(endian + "HHI", data, base)
        size = TYPE_SIZES.get(typ, 0) * cnt
        if size == 0 or size > len(data):
            continue
        if size <= 4:
            raw = data[base + 8:base + 8 + size]
        else:
            voff = _u32(data, base + 8, endian) - delta
            if voff < 0 or voff + size > len(data):
                continue
            raw = data[voff:voff + size]
        fields.append(MakerField(tag, table.get(tag, "0x%04X" % tag), typ, cnt,
                                 _decode(raw, typ, cnt, endian), raw))
    return fields


def _decode(raw: bytes, typ: int, cnt: int, endian: str) -> Any:
    if typ == 2:  # ASCII
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    if typ == BYTE or typ == UNDEFINED:
        return raw
    if typ == SHORT:
        vals = struct.unpack(endian + "%dH" % cnt, raw[:2 * cnt])
        return vals[0] if cnt == 1 else vals
    if typ == 3:
        return struct.unpack(endian + "%dH" % cnt, raw[:2 * cnt])
    if typ == 4:
        vals = struct.unpack(endian + "%dI" % cnt, raw[:4 * cnt])
        return vals[0] if cnt == 1 else vals
    if typ == 5:
        vals = struct.unpack(endian + "%dI" % (2 * cnt), raw[:8 * cnt])
        pairs = tuple((vals[j], vals[j + 1]) for j in range(0, len(vals), 2))
        return pairs[0] if cnt == 1 else pairs
    if typ == 10:
        vals = struct.unpack(endian + "%di" % (2 * cnt), raw[:8 * cnt])
        pairs = tuple((vals[j], vals[j + 1]) for j in range(0, len(vals), 2))
        return pairs[0] if cnt == 1 else pairs
    if typ == 8:
        vals = struct.unpack(endian + "%dh" % cnt, raw[:2 * cnt])
        return vals[0] if cnt == 1 else vals
    if typ == 9:
        vals = struct.unpack(endian + "%di" % cnt, raw[:4 * cnt])
        return vals[0] if cnt == 1 else vals
    return raw


def _plausible(fields: list[MakerField]) -> bool:
    if not fields:
        return False
    return sum(1 for f in fields if f.tag != 0) >= max(1, len(fields) // 2)


def _detect(maker: str, raw: bytes) -> tuple[str, int, int, int]:
    """Return (family, header_len, ifd_off, offset_delta)."""
    if raw.startswith(b"Nikon\0"):
        if raw[6:7] == b"\x02":
            return "Nikon", 10, 10, 0
        return "Nikon", 8, 8, -1  # -1 replaced by caller with absolute offset
    if raw.startswith(b"SONY"):
        return "Sony", 12, 12, 0
    if raw.startswith(b"OLYMP"):
        return "Olympus", 12 if len(raw) > 8 and raw[6:8] in (b"II", b"MM") else 6, \
               12 if len(raw) > 8 and raw[6:8] in (b"II", b"MM") else 6, 0
    if raw.startswith(b"FUJIFILM") and len(raw) > 12:
        off = struct.unpack_from(">I", raw, 8)[0]
        return "Fujifilm", 8, 8 + off, 0
    if raw.startswith(b"AOC\0"):
        return "Pentax", 4, 4, 0
    if raw.startswith(b"PENTAX"):
        return "Pentax", 8, 8, 0
    if raw.startswith(b"Apple"):
        return "Apple", 14, 14, -1
    if raw.startswith(b"SAMSUNG"):
        return "Samsung", 8, 8, 0
    if raw.startswith(b"Panasonic"):
        return "Panasonic", 12, 12, 0
    if raw.startswith(b"DJI"):
        return "DJI", 4, 4, 0
    if maker in ("Canon", "Apple"):
        return maker, 0, 0, -1
    return maker, 0, 0, 0


def parse_makernote(make: str, raw: bytes, endian: str,
                    tiff_offset: int = 0) -> MakerNote | None:
    if not raw:
        return None
    family = _family_from_make(make)
    if family is None:
        for name, sig in SIGNATURES:
            if sig and raw.startswith(sig):
                family = name
                break
    if family is None:
        family = "Canon" if len(raw) > 16 and _looks_like_ifd(raw, 0, endian) else "Unknown"
    family, header_len, ifd_off, delta = _detect(family, raw)
    tiff_relative = delta == -1
    if tiff_relative:
        delta = tiff_offset
    table = MAKER_TAGS.get(family, {})
    fields = _read_ifd(raw, ifd_off, endian, delta, table, family)
    if not _plausible(fields):
        alt_delta = tiff_offset if family in ("Canon", "Apple", "Nikon") else 0
        alt = _read_ifd(raw, 0, endian, alt_delta, table, family)
        if _plausible(alt):
            fields, ifd_off, header_len = alt, 0, 0
            delta, tiff_relative = alt_delta, (alt_delta != 0 or family in ("Canon", "Apple"))
        elif not _plausible(fields):
            return MakerNote(family, raw, endian, header_len, delta, tiff_relative,
                             False, [], ["unparsed"])
    note = MakerNote(family, raw, endian, header_len, delta, tiff_relative, False, fields)
    note.encodable = tiff_relative
    _decorate(note)
    return note


def _looks_like_ifd(raw: bytes, off: int, endian: str) -> bool:
    if off + 2 > len(raw):
        return False
    n = _u16(raw, off, endian)
    return 1 <= n <= 64


def _family_from_make(make: str) -> str | None:
    m = (make or "").lower()
    for fam in ("canon", "nikon", "sony", "olympus", "fujifilm", "pentax",
                "apple", "dji", "samsung", "panasonic", "casio", "epson",
                "leica", "sigma", "ricoh", "kodak"):
        if fam in m:
            return {"casio": "Casio", "epson": "Epson", "leica": "Leica",
                    "sigma": "Sigma", "ricoh": "Ricoh", "kodak": "Kodak"}.get(fam, fam.title())
    return None


def _decorate(note: MakerNote) -> None:
    """Add derived, human friendly fields."""
    if note.maker == "Canon":
        cs = next((f for f in note.fields if f.tag == 0x0001), None)
        if cs and isinstance(cs.value, tuple) and len(cs.value) > 16:
            iso_code = cs.value[16]
            if iso_code in CANON_ISO:
                note.fields.append(MakerField(0x1000, "DerivedISO", 3, 1,
                                              CANON_ISO[iso_code], b""))
            lens = cs.value[22] if len(cs.value) > 22 else None
            if lens in CANON_LENS:
                note.fields.append(MakerField(0x1001, "DerivedLens", 2, 1,
                                              CANON_LENS[lens], b""))
    if note.maker == "Nikon":
        iso = note.get("ISO")
        if isinstance(iso, tuple) and len(iso) == 2 and iso[1]:
            note.fields.append(MakerField(0x1000, "DerivedISO", 3, 1, iso[1], b""))


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def _encode_ifd(fields: list[MakerField], ifd_off: int, endian: str,
                delta: int, prefix: bytes) -> bytes:
    entries = [f for f in fields if not f.name.startswith("Derived")]
    entries.sort(key=lambda f: f.tag)
    n = len(entries)
    table_end = ifd_off + 2 + 12 * n + 4
    data_off = table_end
    blobs: list[tuple[int, bytes]] = []
    plan: list[tuple[MakerField, int, bytes]] = []
    for f in entries:
        if f.raw and len(f.raw) == TYPE_SIZES.get(f.type, 1) * f.count:
            data = f.raw
        else:
            data = _encode_value(f.value, f.type, endian)
        count = _count_from_data(f.type, data)
        if len(data) > 4:
            if data_off % 2:
                data_off += 1
            plan.append((f, data_off, data, count))
            data_off += len(data)
        else:
            plan.append((f, -1, data, count))
    out = bytearray(data_off)
    out[:len(prefix)] = prefix
    struct.pack_into(endian + "H", out, ifd_off, n)
    for i, (f, off, data, count) in enumerate(plan):
        base = ifd_off + 2 + 12 * i
        struct.pack_into(endian + "HHI", out, base, f.tag, f.type, count)
        if off < 0:
            out[base + 8:base + 8 + len(data)] = data
        else:
            struct.pack_into(endian + "I", out, base + 8, off + delta)
            out[off:off + len(data)] = data
    struct.pack_into(endian + "I", out, ifd_off + 2 + 12 * n, 0)
    return bytes(out)


def _count_from_data(typ: int, data: bytes) -> int:
    size = TYPE_SIZES.get(typ, 1)
    if size <= 1:
        return len(data)
    return max(1, len(data) // size)


def _encode_value(value: Any, typ: int, endian: str) -> bytes:
    from .tiff import encode_value
    if typ in (BYTE, UNDEFINED):
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
        elif isinstance(value, str):
            data = value.encode("utf-8")
        elif isinstance(value, (list, tuple)):
            data = bytes(int(x) & 0xFF for x in value)
        else:
            data = bytes([int(value) & 0xFF])
        return data
    if typ == SHORT and isinstance(value, str):
        return value.encode("ascii")
    return encode_value(value, typ, 1, endian)
