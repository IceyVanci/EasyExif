"""Launch the local web UI and a window shell."""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import secrets
import sys

from .api import Api
from .paths import data_dir
from .server import WebUIServer
from .session import Session
from . import shell


def _message(title: str, text: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        if sys.stderr:
            print(text, file=sys.stderr)


def _ensure_temp(root) -> None:
    """Give Python and WebView2 a writable temp directory even if TEMP is broken."""
    try:
        tmp = root / "temp"
        tmp.mkdir(parents=True, exist_ok=True)
        probe = tmp / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        os.environ["TEMP"] = str(tmp)
        os.environ["TMP"] = str(tmp)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--dialog-helper":
        from .dialog_helper import main as helper_main
        return helper_main(argv[1:])
    parser = argparse.ArgumentParser(prog="easyexif-webui")
    parser.add_argument("file", nargs="?")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        root = data_dir()
    except Exception as exc:
        _message("EasyExif", "无法创建数据目录：\n%s" % exc)
        return 1
    _ensure_temp(root)
    try:
        logging.basicConfig(
            filename=str(root / "easyexif.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("easyexif.webui")
    log.info("starting webui, frozen=%s", getattr(sys, "frozen", False))

    session = Session(root)
    if args.file:
        session.open(args.file)
    if session.meta is not None:
        try:
            session.preview(480)
        except Exception:
            log.exception("preview warmup failed")
    server = WebUIServer(Api(session), secrets.token_urlsafe(24), port=args.port)
    server.start()
    url = server.url + "/?token=" + server.token
    log.info("listening on %s", url)

    if args.no_browser:
        if sys.stdout:
            print(url, flush=True)
        else:
            log.info("no-browser mode: %s", url)
        try:
            server.wait()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
        return 0

    try:
        code = shell.launch(url, root, server, session=session)
        return int(code or 0)
    except Exception as exc:
        log.exception("shell failed")
        _message("EasyExif", "无法启动界面：\n%s" % exc)
        return 1
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
