import json
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import socket

from host.download import DownloadManager
from host.idle import IdleWatch
from host.naming import load_catalog
from host.server import CLIENT_HEADER, App, inherited_socket, keep_alive, serve


def write_media(url, opts):
    home = Path(opts["paths"]["home"])
    target = home / "media.mp4"
    target.write_bytes(b"video-bytes")


def raw(port, method, path, payload=None, origin=None, client=CLIENT_HEADER):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {}
    if client is not None:
        headers["X-Mde-Client"] = client
    if origin is not None:
        headers["Origin"] = origin
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            return response.status, response.read(), response.headers
    except HTTPError as exc:
        try:
            return exc.code, exc.read(), exc.headers
        finally:
            exc.close()


def call(port, method, path, payload=None, origin=None, client=CLIENT_HEADER):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {}
    if client is not None:
        headers["X-Mde-Client"] = client
    if origin:
        headers["Origin"] = origin
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            body = response.read().decode()
            parsed = json.loads(body) if body else {}
            return response.status, parsed, response.headers
    except HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode())
            return exc.code, parsed, exc.headers
        finally:
            exc.close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        def probe(url):
            if "falha" in url:
                raise RuntimeError("rede")
            return {"duration": 19.042, "title": "zoo"}

        manager = DownloadManager(
            self.tmp.name,
            runner=write_media,
            ffmpeg_ok=lambda: True,
        )
        self.opened = []
        manager.opener = self.opened.append
        self.manager = manager
        self.server = serve(App(manager, load_catalog(), probe=probe), 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_health_and_rejected_origins(self):
        status, payload, _headers = call(self.port, "GET", "/health", client=None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("ffmpeg", payload)

        status, payload, _headers = call(
            self.port, "POST", "/download", {"url": "https://youtu.be/abc"}, client="",
        )
        self.assertEqual(status, 403)

        status, payload, headers = call(
            self.port,
            "POST",
            "/download",
            {"url": "https://youtu.be/abc"},
            origin="https://evil.example",
        )
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_download_zip_from_the_extension_origin(self):
        status, payload, headers = call(
            self.port,
            "POST",
            "/download",
            {
                "url": "https://www.instagram.com/reel/abc/",
                "quality": "1080",
                "filename": "instagram_2026-10-30_21-05-09",
                "compress": True,
            },
            origin="chrome-extension://abc",
        )
        self.assertEqual(status, 202)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "chrome-extension://abc")
        job_id = payload["id"]
        for _ in range(50):
            status, job, _headers = call(self.port, "GET", f"/jobs/{job_id}")
            if job["state"] not in {"queued", "running", "cancelling"}:
                break
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["name"], "instagram_2026-10-30_21-05-09.zip")
        with zipfile.ZipFile(job["path"]) as archive:
            self.assertEqual(archive.namelist(), ["instagram_2026-10-30_21-05-09.mp4"])

        status, missing, _headers = call(self.port, "GET", "/jobs/nao-existe")
        self.assertEqual(status, 404)
        status, bad, _headers = call(
            self.port,
            "POST",
            "/download",
            {"url": "notaurl", "quality": "best", "filename": "x", "compress": False},
            origin="chrome-extension://abc",
        )
        self.assertEqual(status, 400)
        self.assertIn("http", bad["error"])

    def test_probe_and_rejected_range(self):
        status, payload, headers = call(
            self.port,
            "POST",
            "/probe",
            {"url": "https://youtu.be/abc"},
            origin="chrome-extension://abc",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["duration"], 19.042)
        self.assertEqual(payload["title"], "zoo")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "chrome-extension://abc")

        status, denied, _headers = call(
            self.port,
            "POST",
            "/probe",
            {"url": "https://youtu.be/abc"},
            origin="https://evil.example",
        )
        self.assertEqual(status, 403)

        status, bad, _headers = call(
            self.port,
            "POST",
            "/probe",
            {"url": "notaurl"},
            origin="chrome-extension://abc",
        )
        self.assertEqual(status, 400)
        self.assertIn("http", bad["error"])

        status, failed, _headers = call(
            self.port,
            "POST",
            "/probe",
            {"url": "https://youtu.be/falha"},
            origin="chrome-extension://abc",
        )
        self.assertEqual(status, 200)
        self.assertIsNone(failed["duration"])
        self.assertIsNone(failed["title"])

        status, order, _headers = call(
            self.port,
            "POST",
            "/download",
            {
                "url": "https://youtu.be/abc",
                "quality": "best",
                "filename": "youtube_trecho",
                "compress": False,
                "start_time": "1:00",
                "end_time": "0:30",
            },
            origin="chrome-extension://abc",
        )
        self.assertEqual(status, 400)
        self.assertIn("fim", order["error"])

    def test_local_page_and_same_origin_download(self):
        status, body, headers = raw(self.port, "GET", "/", client=None)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("Video Extensão Download".encode(), body)

        status, css, headers = raw(self.port, "GET", "/popup.css", client=None)
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))
        self.assertIn(b"body.page", css)

        status, missing, _headers = raw(self.port, "GET", "/../host/server.py", client=None)
        self.assertEqual(status, 404)

        local = f"http://127.0.0.1:{self.port}"
        status, payload, headers = call(
            self.port,
            "POST",
            "/download",
            {
                "url": "https://youtu.be/abc",
                "quality": "best",
                "filename": "pagina",
                "compress": False,
            },
            origin=local,
        )
        self.assertEqual(status, 202)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), local)

        status, denied, headers = call(
            self.port,
            "POST",
            "/download",
            {"url": "https://youtu.be/abc", "quality": "best", "filename": "arquivo", "compress": False},
            origin="null",
        )
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_folder_opens_the_download_directory(self):
        folder = Path(self.tmp.name).resolve()
        video = folder / "video.mp4"
        video.write_bytes(b"video")
        local = f"http://127.0.0.1:{self.port}"

        status, payload, _headers = call(
            self.port,
            "POST",
            "/folder",
            {"name": "video.mp4"},
            origin=local,
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.opened, [video])

        status, denied, headers = call(
            self.port,
            "POST",
            "/folder",
            {"name": "video.mp4"},
            origin="https://evil.example",
        )
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(len(self.opened), 1)

        status, payload, _headers = call(self.port, "POST", "/folder", {}, origin=local)
        self.assertEqual(status, 200)
        self.assertEqual(self.opened[-1], folder)

    def test_health_reports_when_idle_exit_is_off(self):
        status, payload, _headers = call(self.port, "GET", "/health", client=None)
        self.assertEqual(status, 200)
        self.assertFalse(payload["idle_exit"])


class IdleTests(unittest.TestCase):
    def test_health_checks_do_not_keep_the_process(self):
        self.assertEqual(keep_alive("/health", busy=False), "skip")
        self.assertEqual(keep_alive("/probe", busy=False), "touch")
        self.assertEqual(keep_alive("/health", busy=True), "pause")

    def test_inherited_socket_is_absent_without_systemd(self):
        self.assertIsNone(inherited_socket())

    def test_exits_after_the_download_settles(self):
        fired = threading.Event()
        watch = IdleWatch(fired.set, idle_seconds=30, settled_seconds=0.3)
        watch.note_settled()
        self.assertTrue(fired.wait(1.5))
        watch.stop()

    def test_stays_while_a_download_is_running(self):
        fired = threading.Event()
        watch = IdleWatch(fired.set, idle_seconds=0.3, settled_seconds=0.3, busy=lambda: True)
        watch.touch()
        time.sleep(0.8)
        self.assertFalse(fired.is_set())
        watch.stop()

    def test_exits_when_nobody_downloads(self):
        fired = threading.Event()
        watch = IdleWatch(fired.set, idle_seconds=0.3, settled_seconds=30)
        watch.touch()
        self.assertTrue(fired.wait(1.5))
        watch.stop()

    def test_serves_on_a_socket_opened_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen(8)
            sock.setblocking(False)
            manager = DownloadManager(directory, runner=lambda url, opts: None, ffmpeg_ok=lambda: True)
            server = serve(App(manager, load_catalog(), probe=lambda url: {}), 0, sock=sock)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                status, payload, _headers = call(port, "GET", "/health", client=None)
                self.assertEqual(status, 200)
                self.assertTrue(payload["ok"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
