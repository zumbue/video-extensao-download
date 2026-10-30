"""Serviço HTTP em 127.0.0.1 para a extensão."""

import json
import os
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .download import BusyError, DownloadManager, js_runtimes, probe_media, ytdlp_version
from .naming import UserError, detect_network, load_catalog, parse_request

CLIENT_HEADER = "video-extensao-download"
MAX_BODY = 32_768
HOST = "127.0.0.1"
EXTENSION_ROOT = Path(__file__).resolve().parents[1] / "extension"
STATIC_FILES = {
    "/": "popup.html",
    "/popup.html": "popup.html",
    "/popup.css": "popup.css",
    "/popup.js": "popup.js",
    "/detect.js": "detect.js",
    "/networks.json": "networks.json",
    "/icons/icon.svg": "icons/icon.svg",
    "/icons/icon16.png": "icons/icon16.png",
    "/icons/icon32.png": "icons/icon32.png",
    "/icons/icon48.png": "icons/icon48.png",
    "/icons/icon128.png": "icons/icon128.png",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def health_payload() -> dict:
    runtime = next(iter(js_runtimes()), None)
    return {
        "ok": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "js_runtime": runtime,
        "ytdlp": ytdlp_version(),
        "version": __version__,
    }


class App:
    def __init__(self, manager: DownloadManager, catalog: dict, probe=None):
        self.manager = manager
        self.catalog = catalog
        self.probe = probe or probe_media


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            path = urlparse(self.path).path
            if path == "/health" or path.startswith("/jobs/"):
                return
            if self.command == "GET":
                return
            print(f"[ved] {self.address_string()} {fmt % args}")

        def do_OPTIONS(self) -> None:
            self._send(204, b"")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._send_json(200, health_payload())
                return
            if path.startswith("/jobs/"):
                job_id = path.removeprefix("/jobs/").strip("/")
                job = app.manager.get(job_id)
                if job is None:
                    self._send_json(404, {"error": "Download não encontrado."})
                    return
                self._send_json(200, job)
                return
            relative = STATIC_FILES.get(path)
            if relative is not None:
                self._send_static(relative)
                return
            self._send_json(404, {"error": "Caminho não encontrado."})

        def do_POST(self) -> None:
            if not self._post_allowed():
                self._send_json(403, {"error": "Origem recusada."})
                return
            path = urlparse(self.path).path
            if path == "/download":
                self._download()
                return
            if path == "/probe":
                self._probe()
                return
            if path.startswith("/jobs/") and path.endswith("/cancel"):
                job_id = path.removeprefix("/jobs/").removesuffix("/cancel").strip("/")
                if not app.manager.cancel(job_id):
                    self._send_json(404, {"error": "Download não encontrado."})
                    return
                job = app.manager.get(job_id)
                self._send_json(200, job)
                return
            self._send_json(404, {"error": "Caminho não encontrado."})

        def _local_origin(self) -> str:
            return f"http://127.0.0.1:{self.server.server_address[1]}"

        def _post_allowed(self) -> bool:
            origin = self.headers.get("Origin", "")
            if origin == "null":
                return False
            if origin.startswith(("http://", "https://")) and origin != self._local_origin():
                return False
            return self.headers.get("X-Mde-Client", "") == CLIENT_HEADER

        def _send_static(self, relative: str) -> None:
            path = EXTENSION_ROOT / relative
            if not path.is_file():
                self._send_json(404, {"error": "Caminho não encontrado."})
                return
            content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
            self._send(200, path.read_bytes(), content_type)

        def _read_payload(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                self._send_json(400, {"error": "Pedido inválido."})
                return None
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "Pedido inválido."})
                return None
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Pedido inválido."})
                return None
            return payload

        def _download(self) -> None:
            payload = self._read_payload()
            if payload is None:
                return
            try:
                request = parse_request(payload, app.catalog)
            except UserError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            try:
                job = app.manager.start(request)
            except UserError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except BusyError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(202, job)

        def _probe(self) -> None:
            payload = self._read_payload()
            if payload is None:
                return
            url = payload.get("url")
            if not isinstance(url, str):
                self._send_json(400, {"error": "Informe o link."})
                return
            url = url.strip()
            if detect_network(url, app.catalog) is None:
                self._send_json(400, {"error": "Use um link http ou https."})
                return
            try:
                facts = app.probe(url)
            except Exception as exc:
                print(f"[ved] duração indisponível: {exc.__class__.__name__}: {str(exc)[:200]}")
                self._send_json(200, {"duration": None, "title": None})
                return
            if not isinstance(facts, dict):
                facts = {}
            duration = facts.get("duration")
            title = facts.get("title")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
                duration = None
            else:
                duration = round(float(duration), 3)
            self._send_json(200, {
                "duration": duration,
                "title": title if isinstance(title, str) else None,
            })

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin", "")
            local = f"http://127.0.0.1:{self.server.server_address[1]}"
            if origin.startswith(("chrome-extension://", "moz-extension://")) or origin == local:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Mde-Client")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve(app: App, port: int) -> ThreadingHTTPServer:
    return ReuseServer((HOST, port), make_handler(app))


def main() -> None:
    port = int(os.environ.get("MDE_PORT", "8734"))
    downloads = Path(os.environ.get(
        "MDE_DOWNLOADS",
        Path.home() / "Downloads" / "Video Extensao Download",
    ))
    app = App(DownloadManager(downloads), load_catalog())
    try:
        server = serve(app, port)
    except OSError as exc:
        raise SystemExit(f"Não foi possível abrir a porta {port}: {exc}") from exc
    print(f"Video Extensão Download em http://{HOST}:{port}")
    print(f"Arquivos em {downloads}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServiço encerrado.")
    finally:
        server.server_close()
