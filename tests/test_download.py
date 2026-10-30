import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host.download import (
    BusyError,
    DownloadManager,
    Job,
    format_selector,
    media_facts,
    partial_bytes,
    precise_cut,
    unique_destination,
)
from host.naming import DownloadRequest, UserError


def request(**overrides):
    data = {
        "url": "https://www.youtube.com/watch?v=abc",
        "quality": "720",
        "filename": "youtube_2026-10-30_21-05-09",
        "compress": False,
        "network_id": "youtube",
    }
    data.update(overrides)
    return DownloadRequest(**data)


def wait_until(manager, job_id):
    last = None
    for _ in range(100):
        last = manager.get(job_id)
        if last and last["state"] not in {"queued", "running", "cancelling"}:
            return last
        time.sleep(0.02)
    raise AssertionError(last)


def write_media(opts):
    home = Path(opts["paths"]["home"])
    home.mkdir(parents=True, exist_ok=True)
    target = home / "media.mp4"
    target.write_bytes(b"video-bytes")
    opts["progress_hooks"][0]({
        "status": "downloading",
        "downloaded_bytes": 5,
        "total_bytes": 10,
        "filename": str(target),
    })
    opts["progress_hooks"][0]({"status": "finished", "filename": str(target)})


class DownloadTests(unittest.TestCase):
    def test_format_heights(self):
        self.assertIn("height<=1080", format_selector("1080"))
        self.assertEqual(format_selector("audio"), "bestaudio/best")
        self.assertEqual(format_selector("best"), "bv*+ba/b")

    def test_unique_destination_adds_a_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = unique_destination(folder, "video", ".mp4")
            first.write_bytes(b"a")
            second = unique_destination(folder, "video", ".mp4")
            self.assertEqual(second.name, "video-2.mp4")

    def test_saves_mp4_and_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            plain = DownloadManager(folder, runner=lambda url, opts: write_media(opts), ffmpeg_ok=lambda: True)
            saved = wait_until(plain, plain.start(request())["id"])
            self.assertEqual(saved["state"], "done")
            self.assertEqual(saved["name"], "youtube_2026-10-30_21-05-09.mp4")
            self.assertEqual(Path(saved["path"]).read_bytes(), b"video-bytes")

            packed = DownloadManager(folder, runner=lambda url, opts: write_media(opts), ffmpeg_ok=lambda: True)
            zipped = wait_until(packed, packed.start(request(compress=True))["id"])
            self.assertEqual(zipped["name"], "youtube_2026-10-30_21-05-09.zip")
            with zipfile.ZipFile(zipped["path"]) as archive:
                self.assertEqual(archive.namelist(), ["youtube_2026-10-30_21-05-09.mp4"])
                self.assertEqual(archive.read("youtube_2026-10-30_21-05-09.mp4"), b"video-bytes")

    def test_tells_when_the_job_finishes(self):
        finished = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            manager = DownloadManager(
                directory,
                runner=lambda url, opts: write_media(opts),
                ffmpeg_ok=lambda: True,
                on_settled=finished.set,
            )
            manager.start(request())
            self.assertTrue(finished.wait(2))

    def test_cancel_and_busy_and_missing_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            entered = threading.Event()

            def runner(url, opts):
                entered.set()
                hook = opts["progress_hooks"][0]
                while True:
                    hook({
                        "status": "downloading",
                        "downloaded_bytes": 1,
                        "total_bytes": 10,
                        "filename": "x",
                    })
                    time.sleep(0.01)

            manager = DownloadManager(directory, runner=runner, ffmpeg_ok=lambda: True)
            job = manager.start(request())
            self.assertTrue(entered.wait(1))
            with self.assertRaises(BusyError):
                manager.start(request())
            self.assertTrue(manager.cancel(job["id"]))
            done = wait_until(manager, job["id"])
            self.assertEqual(done["state"], "cancelled")

        with tempfile.TemporaryDirectory() as directory:
            entered = threading.Event()
            release = threading.Event()

            def blocked(url, opts):
                entered.set()
                release.wait(2)
                opts["progress_hooks"][0]({
                    "status": "downloading",
                    "downloaded_bytes": 1,
                    "total_bytes": 2,
                })

            manager = DownloadManager(directory, runner=blocked, ffmpeg_ok=lambda: True)
            job = manager.start(request())
            self.assertTrue(entered.wait(1))
            self.assertTrue(manager.cancel(job["id"]))
            self.assertEqual(manager.get(job["id"])["state"], "cancelling")
            self.assertEqual(manager.get(job["id"])["message"], "Cancelando...")
            self.assertTrue(manager.busy())
            release.set()
            done = wait_until(manager, job["id"])
            self.assertEqual(done["state"], "cancelled")

        blocked = DownloadManager(Path("."), runner=lambda url, opts: None, ffmpeg_ok=lambda: False)
        with self.assertRaises(UserError):
            blocked.start(request())

    def test_reports_bytes_speed_and_finished_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "pronto.mp4").write_bytes(b"abc")
            (folder / "nota.txt").write_bytes(b"x")
            release = threading.Event()

            def runner(url, opts):
                opts["progress_hooks"][0]({
                    "status": "downloading",
                    "downloaded_bytes": 2048,
                    "total_bytes_estimate": 4096,
                    "speed": 1536,
                })
                release.wait(2)

            manager = DownloadManager(folder, runner=runner, ffmpeg_ok=lambda: True)
            job = manager.start(request())
            snap = None
            for _ in range(50):
                snap = manager.get(job["id"])
                if snap and snap["downloaded"] == 2048:
                    break
                time.sleep(0.02)
            self.assertEqual(snap["downloaded"], 2048)
            self.assertEqual(snap["total"], 4096)
            self.assertEqual(snap["speed"], 1536)
            self.assertEqual(snap["progress"], 50)
            library = manager.library()
            self.assertEqual(library["active"]["id"], job["id"])
            self.assertEqual([item["name"] for item in library["files"]], ["pronto.mp4"])
            self.assertEqual(library["files"][0]["size"], 3)
            release.set()
            done = wait_until(manager, job["id"])
            self.assertEqual(done["state"], "error")

    def test_error_message_drops_the_extractor_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            def runner(url, opts):
                raise RuntimeError("ERROR: [youtube] vídeo indisponível")

            manager = DownloadManager(directory, runner=runner, ffmpeg_ok=lambda: True)
            done = wait_until(manager, manager.start(request())["id"])
            self.assertEqual(done["state"], "error")
            self.assertEqual(done["error"], "[youtube] vídeo indisponível")

    def test_section_is_optional_and_asks_for_a_precise_cut(self):
        captured = {}

        def runner(url, opts):
            captured.clear()
            captured.update(opts)
            write_media(opts)

        def factory(start, end):
            return {"start": start, "end": end}

        with tempfile.TemporaryDirectory() as directory:
            manager = DownloadManager(
                directory,
                runner=runner,
                ffmpeg_ok=lambda: True,
                range_factory=factory,
            )
            wait_until(manager, manager.start(request())["id"])
            self.assertNotIn("download_ranges", captured)
            self.assertNotIn("force_keyframes_at_cuts", captured)

            wait_until(manager, manager.start(request(start_time=0, end_time=None))["id"])
            self.assertNotIn("download_ranges", captured)

            wait_until(manager, manager.start(request(start_time=12.5, end_time=40))["id"])
            self.assertEqual(captured["download_ranges"], {"start": 12.5, "end": 40})
            self.assertTrue(captured["force_keyframes_at_cuts"])

            wait_until(manager, manager.start(request(end_time=8))["id"])
            self.assertEqual(captured["download_ranges"], {"start": 0.0, "end": 8})
            self.assertTrue(captured["force_keyframes_at_cuts"])

            wait_until(manager, manager.start(request(start_time=6))["id"])
            self.assertEqual(captured["download_ranges"], {"start": 6, "end": None})
            self.assertNotIn("force_keyframes_at_cuts", captured)

            wait_until(manager, manager.start(request(start_time=1, end_time=400))["id"])
            self.assertEqual(captured["download_ranges"], {"start": 1, "end": 400})
            self.assertNotIn("force_keyframes_at_cuts", captured)

    def test_precise_cut_skips_an_open_or_long_range(self):
        self.assertFalse(precise_cut(6, None))
        self.assertFalse(precise_cut(1, 400))
        self.assertTrue(precise_cut(12.5, 40))
        self.assertTrue(precise_cut(None, 8))
        self.assertFalse(precise_cut(10, 10))

    def test_partial_file_reports_size_and_speed(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)

            def runner(url, opts):
                home = Path(opts["paths"]["home"])
                part = home / "media.mp4.part"
                part.write_bytes(b"x" * 3000)
                time.sleep(1.6)
                (home / "media.mp4").write_bytes(b"video-bytes")

            manager = DownloadManager(folder, runner=runner, ffmpeg_ok=lambda: True)
            job_id = manager.start(request())["id"]
            seen = None
            for _ in range(40):
                seen = manager.get(job_id)
                if seen and (seen.get("downloaded") or 0) >= 3000 and isinstance(seen.get("speed"), (int, float)):
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(seen["downloaded"], 3000)
            self.assertIsInstance(seen["speed"], (int, float))
            done = wait_until(manager, job_id)
            self.assertEqual(done["state"], "done")

    def test_cancel_kills_the_child_and_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_box = {}

            def runner(url, opts):
                proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
                pid_box["pid"] = proc.pid
                proc.wait()

            manager = DownloadManager(directory, runner=runner, ffmpeg_ok=lambda: True)
            job = manager.start(request())
            for _ in range(50):
                if pid_box.get("pid"):
                    break
                time.sleep(0.02)
            self.assertIn("pid", pid_box)
            self.assertTrue(manager.cancel(job["id"]))
            self.assertTrue(manager.busy())
            done = wait_until(manager, job["id"])
            self.assertEqual(done["state"], "cancelled")
            self.assertFalse(manager.busy())
            self.assertIsNone(manager.get(job["id"])["error"])
            try:
                os.kill(pid_box["pid"], 0)
                os.killpg(pid_box["pid"], signal.SIGKILL)
                self.fail("o processo filho continuou depois do cancelamento")
            except ProcessLookupError:
                pass

    def test_a_finished_job_ignores_later_progress(self):
        job = Job(id="abc")
        job.update(state="done", message="Arquivo salvo.")
        job.update(state="running", message="Baixando...", downloaded=9, speed=10)
        snap = job.snapshot()
        self.assertEqual(snap["state"], "done")
        self.assertIsNone(snap["downloaded"])

    def test_partial_bytes_counts_part_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "media.mp4.part").write_bytes(b"abc")
            (folder / "thumb.jpg").write_bytes(b"jpeg")
            self.assertEqual(partial_bytes(folder), 3)
            self.assertIsNone(partial_bytes(folder / "ausente"))

    def test_media_facts_keep_a_positive_duration(self):
        self.assertEqual(media_facts({"duration": 19.0412, "title": "zoo"}), {
            "duration": 19.041,
            "title": "zoo",
        })
        self.assertIsNone(media_facts({"duration": 0, "title": 3})["duration"])
        self.assertIsNone(media_facts({"duration": 0, "title": 3})["title"])
        self.assertEqual(
            media_facts({"_type": "playlist", "entries": [{"duration": 3, "title": "a"}]}),
            {"duration": 3, "title": "a"},
        )

    def test_reveal_stays_inside_the_download_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            video = folder / "video.mp4"
            video.write_bytes(b"video")
            outside = folder.parent / "segredo.txt"
            outside.write_text("x", encoding="utf-8")
            opened = []
            manager = DownloadManager(folder, ffmpeg_ok=lambda: True)
            manager.opener = opened.append

            self.assertEqual(manager.reveal("video.mp4"), video.resolve())
            self.assertEqual(opened, [video.resolve()])

            self.assertEqual(manager.reveal("../segredo.txt"), folder.resolve())
            self.assertEqual(manager.reveal("ausente.mp4"), folder.resolve())
            self.assertEqual(manager.reveal(None), folder.resolve())
            self.assertEqual(opened[1:], [folder.resolve(), folder.resolve(), folder.resolve()])
            outside.unlink()


if __name__ == "__main__":
    unittest.main()
