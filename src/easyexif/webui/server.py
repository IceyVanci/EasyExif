"""Local HTTP server for the web UI."""
from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from .api import Api, Response
from .paths import static_dir

LOG = logging.getLogger("easyexif.webui")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "EasyExif/" + __version__

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        try:
            if path == "/" or path == "/index.html":
                self._send_file(static_dir() / "index.html", "text/html; charset=utf-8")
                return
            if path.startswith("/api/"):
                if not self._authorized(query):
                    # Consume/close so a rejected body cannot desynchronize keep-alive.
                    self.close_connection = True
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                # Always consume a POST body before routing, including heartbeat.
                body = self._read_json() if method == "POST" else {}
                if path == "/api/heartbeat" and method in ("GET", "POST"):
                    self.server.touch()
                    self._send_json({"ok": True})
                    return
                response = self.server.api.dispatch(method, path, query, body)
                self._send_response(response)
                return
            if path == "/favicon.ico":
                self._send_bytes(b"", "image/x-icon", 204)
                return
            self._serve_static(path)
        except BrokenPipeError:
            pass
        except Exception as exc:
            LOG.exception("request failed: %s", exc)
            self.close_connection = True
            self._send_json({"ok": False, "error": str(exc)}, 500)

    def _authorized(self, query: dict) -> bool:
        token = self.headers.get("X-EasyExif-Token") or query.get("token")
        return bool(token) and token == self.server.token

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 32 * 1024 * 1024:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _serve_static(self, path: str) -> None:
        rel = unquote(path).lstrip("/")
        root = static_dir().resolve()
        candidate = (root / rel).resolve()
        if candidate != root and root not in candidate.parents:
            self._send_json({"ok": False, "error": "forbidden"}, 403)
            return
        if not candidate.is_file():
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self._send_file(candidate, ctype)

    def _send_file(self, path: Path, ctype: str) -> None:
        if not path.is_file():
            self._send_json({"ok": False, "error": "missing static file"}, 404)
            return
        data = path.read_bytes()
        self._send_bytes(data, ctype)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def _send_response(self, response: Response) -> None:
        self._send_bytes(response.body, response.content_type, response.status)

    def _send_bytes(self, data: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'",
            )
        self.end_headers()
        if data:
            self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        LOG.debug("%s - %s", self.address_string(), fmt % args)


class WebUIServer:
    def __init__(self, api: Api, token: str, port: int = 0):
        self.api = api
        self.token = token
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.api = api
        self.httpd.token = token
        self.httpd.touch = self.touch
        self.httpd.heartbeat_age = self.heartbeat_age
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self.last_heartbeat: float | None = None

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.port

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="easyexif-http", daemon=True)
        self._thread.start()

    def touch(self) -> None:
        self.last_heartbeat = time.monotonic()

    def heartbeat_age(self) -> float:
        if self.last_heartbeat is None:
            return 10 ** 9
        return time.monotonic() - self.last_heartbeat

    def wait(self) -> None:
        try:
            self._stopped.wait()
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        self._stopped.set()
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        self.httpd.server_close()
