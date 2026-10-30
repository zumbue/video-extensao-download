import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host.download import BusyError, DownloadManager, format_selector, media_facts, unique_destination
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
        if last and last["state"] not in {"queued", "running"}:
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

        blocked = DownloadManager(Path("."), runner=lambda url, opts: None, ffmpeg_ok=lambda: False)
        with self.assertRaises(UserError):
            blocked.start(request())

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
