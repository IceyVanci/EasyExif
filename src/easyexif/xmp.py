"""A small, dependency free XMP packet reader / writer.

The editor deliberately performs targeted string edits instead of rebuilding
the RDF graph, so unknown properties, custom namespaces and the original
xpacket wrapper survive a round trip.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "exif": "http://ns.adobe.com/exif/1.0/",
    "exifEX": "http://cipa.jp/exif/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "xmpMM": "http://ns.adobe.com/xap/1.0/mm/",
    "xmpRights": "http://ns.adobe.com/xap/1.0/rights/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "aux": "http://ns.adobe.com/exif/1.0/aux/",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
    "iptc": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/",
    "iptcExt": "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
    "pdf": "http://ns.adobe.com/pdf/1.3/",
    "plus": "http://ns.useplus.org/ldf/xmp/1.0/",
    "GPano": "http://ns.google.com/photos/1.0/panorama/",
    "drone-dji": "http://www.dji.com/drone-dji/1.0/",
    "easyexif": "https://github.com/IceyVanci/EasyExif/ns/1.0/",
}

DEFAULT_NS_ATTRS = "".join(
    ' xmlns:%s="%s"' % (p, u) for p, u in NS.items())

LIST_PROPS = {
    "dc:subject", "dc:creator", "dc:title", "dc:description", "dc:rights",
    "dc:publisher", "dc:contributor", "dc:type", "dc:format", "dc:identifier",
    "dc:language", "dc:relation", "dc:coverage", "dc:source",
    "photoshop:AuthorsPosition", "iptc:Keywords",
}


class XmpError(ValueError):
    pass


class Xmp:
    def __init__(self, raw: bytes | str | None = None):
        if isinstance(raw, bytes):
            self.text = raw.decode("utf-8", "replace")
        elif isinstance(raw, str):
            self.text = raw
        else:
            self.text = ""
        self._prefixes: dict[str, str] = {}
        self.props: dict[str, Any] = {}
        self.changed = False
        self._parse()

    # -- inspection --------------------------------------------------------
    @property
    def exists(self) -> bool:
        return bool(self.text.strip())

    def _parse(self) -> None:
        self._prefixes = {}
        for m in re.finditer(r'xmlns:([A-Za-z_][\w.-]*)\s*=\s*"([^"]+)"', self.text):
            self._prefixes[m.group(1)] = m.group(2)
        self.props = {}
        desc_re = re.compile(
            r"<rdf:Description\b([^>]*?)(?:/>|>(.*?)</rdf:Description>)", re.S)
        for desc in desc_re.finditer(self.text):
            attrs = desc.group(1) or ""
            for m in re.finditer(r'([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)\s*=\s*"([^"]*)"', attrs):
                name = "%s:%s" % (m.group(1), m.group(2))
                if name.startswith("xmlns:") or name == "rdf:about":
                    continue
                self.props[name] = html.unescape(m.group(3))
            inner = desc.group(2) or ""
            for m in re.finditer(
                    r"<([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)(?:\s[^>]*)?>(.*?)</\1:\2>",
                    inner, re.S):
                prefix = m.group(1)
                if prefix == "rdf":
                    continue
                name = "%s:%s" % (prefix, m.group(2))
                body = m.group(3)
                lis = re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", body, re.S)
                if lis:
                    self.props[name] = [_plain(x) for x in lis]
                elif "<rdf:" in body:
                    self.props[name] = body.strip()
                else:
                    self.props[name] = _plain(body)

    def get(self, name: str, default: Any = None) -> Any:
        return self.props.get(name, default)

    def keys(self) -> list[str]:
        return sorted(self.props)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.props)

    def find(self, suffix: str) -> list[tuple[str, Any]]:
        low = suffix.lower()
        return [(k, v) for k, v in self.props.items() if k.lower().endswith(low)]

    # -- editing -----------------------------------------------------------
    def set(self, name: str, value: Any) -> None:
        prefix, _, local = name.partition(":")
        if not local:
            raise XmpError("property name must be prefix:local, got %r" % name)
        if prefix not in self._prefixes and prefix not in NS:
            raise XmpError("unknown namespace prefix %r" % prefix)
        if not self.exists:
            self._create()
        text_value = _to_text(value)
        pattern = re.compile(
            r"(<(%s:%s)(\s[^>]*)?>)(.*?)(</\2>)" % (re.escape(prefix), re.escape(local)),
            re.S)
        m = pattern.search(self.text)
        if m:
            open_tag = m.group(1)
            close_tag = m.group(5)
            if isinstance(value, (list, tuple)):
                inner = _xml_list(value, name)
            else:
                inner = _escape(text_value)
            self.text = self.text[:m.start()] + open_tag + inner + close_tag + self.text[m.end():]
        else:
            attr = re.compile(r'(%s:%s\s*=\s*")([^"]*)(")' % (re.escape(prefix), re.escape(local)))
            if attr.search(self.text):
                self.text = attr.sub(lambda mm: mm.group(1) + _escape(text_value) + mm.group(3), self.text, count=1)
            else:
                self._append_property(name, value)
        self.changed = True
        self._parse()

    def delete(self, name: str) -> bool:
        prefix, _, local = name.partition(":")
        if not local:
            return False
        before = self.text
        pattern = re.compile(r"\s*<%s:%s(\s[^>]*)?>.*?</%s:%s>" % (
            re.escape(prefix), re.escape(local), re.escape(prefix), re.escape(local)), re.S)
        self.text = pattern.sub("", self.text)
        attr = re.compile(r'\s+%s:%s\s*=\s*"[^"]*"' % (re.escape(prefix), re.escape(local)))
        self.text = attr.sub("", self.text)
        self.changed = self.text != before
        self._parse()
        return self.changed

    def _append_property(self, name: str, value: Any) -> None:
        prefix, _, local = name.partition(":")
        if isinstance(value, (list, tuple)):
            inner = _xml_list(value, name)
        else:
            inner = _escape(_to_text(value))
        element = "<%s>%s</%s>" % (name, inner, name)
        ns_attr = ""
        if prefix not in self._prefixes:
            ns_attr = ' xmlns:%s="%s"' % (prefix, NS[prefix])
            self._prefixes[prefix] = NS[prefix]
        desc = re.search(r"<rdf:Description\b([^>]*?)(/?)>", self.text, re.S)
        if not desc:
            # no RDF yet: add a minimal description before </rdf:RDF>
            block = ('<rdf:Description rdf:about=""%s>%s</rdf:Description>' % (ns_attr, element))
            if "</rdf:RDF>" in self.text:
                self.text = self.text.replace("</rdf:RDF>", block + "</rdf:RDF>", 1)
            else:
                self.text = _new_packet(element, ns_attr)
            return
        start, end = desc.span()
        tag = desc.group(0)
        if desc.group(2) == "/":
            new_tag = tag[:-2].rstrip() + ns_attr + ">" + element + "</rdf:Description>"
            self.text = self.text[:start] + new_tag + self.text[end:]
        else:
            if ns_attr and ("xmlns:%s=" % prefix) not in tag:
                new_tag = re.sub(r"\s*>$", ns_attr + ">", tag, count=1)
                self.text = self.text[:start] + new_tag + self.text[end:]
                end = start + len(new_tag)
            self.text = self.text[:end] + element + self.text[end:]

    def _create(self) -> None:
        self.text = _new_packet("", "")

    def to_bytes(self) -> bytes:
        return self.text.encode("utf-8")

    def __repr__(self) -> str:
        return "<Xmp %d properties>" % len(self.props)


def _new_packet(body: str, ns_attr: str) -> str:
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="EasyExif 0.1.1">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""%s%s>%s</rdf:Description>\n'
        ' </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>' % (DEFAULT_NS_ATTRS, ns_attr, body))


def _xml_list(values, name: str) -> str:
    tag = "rdf:Bag" if name in ("dc:subject", "dc:creator", "dc:publisher") else "rdf:Seq"
    items = "".join("<rdf:li>%s</rdf:li>" % _escape(_to_text(v)) for v in values)
    return "<%s>%s</%s>" % (tag, items, tag)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _plain(inner: str) -> str:
    text = re.sub(r"<[^>]+>", "", inner)
    return html.unescape(text).strip()


def _to_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)
