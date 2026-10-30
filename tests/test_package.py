import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.package_extension import PREFIX, build_zip

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".md", ".html", ".sh", ".json", ".css", ".desktop", ".bat", ".ps1", ".in", ".txt", ".socket"}


class PackageTests(unittest.TestCase):
    def test_manifest_points_at_files_that_exist(self):
        extension = ROOT / "extension"
        manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["name"], "Video Extensão Download")
        names = set(manifest["icons"].values())
        names.add(manifest["action"]["default_popup"])
        names.add(manifest["background"]["service_worker"])
        for name in names:
            self.assertTrue((extension / name).is_file(), name)

    def test_release_zip_is_installable_and_has_no_personal_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "video-extensao-download.zip"
            build_zip(destination)
            with zipfile.ZipFile(destination) as archive:
                names = set(archive.namelist())
                self.assertIn(f"{PREFIX}/extension/manifest.json", names)
                self.assertIn(f"{PREFIX}/Instalar.desktop", names)
                self.assertIn(f"{PREFIX}/Instalar.bat", names)
                self.assertIn(f"{PREFIX}/scripts/install-click.sh", names)
                self.assertIn(f"{PREFIX}/scripts/install-windows.ps1", names)
                self.assertIn(f"{PREFIX}/systemd/user/video-extensao-download.service.in", names)
                self.assertIn(f"{PREFIX}/systemd/user/video-extensao-download.socket", names)
                self.assertNotIn(f"{PREFIX}/systemd/user/media-downloader-ext.service.in", names)
                self.assertIn(f"{PREFIX}/.gitignore", names)
                self.assertFalse(any(".venv/" in name or name.endswith(".pyc") or "/tests/" in name for name in names))
                self.assertFalse(any("/.git/" in f"/{name}" for name in names))

                desktop = archive.getinfo(f"{PREFIX}/Instalar.desktop")
                click = archive.getinfo(f"{PREFIX}/scripts/install-click.sh")
                self.assertTrue((desktop.external_attr >> 16) & 0o111)
                self.assertTrue((click.external_attr >> 16) & 0o111)

                blob = []
                for info in archive.infolist():
                    if Path(info.filename).suffix in TEXT_SUFFIXES:
                        blob.append(archive.read(info).decode("utf-8"))
                text = "\n".join(blob)
        self.assertIsNone(re.search(r"/home/\w+", text))
        self.assertIsNone(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text))
        self.assertNotIn("Collaborators", text)
        self.assertNotIn("privado", text.lower())
        self.assertIn("@ROOT@", text)
        self.assertIn("Video Extensão Download", text)
        self.assertIn("MDE_IDLE_EXIT=1", text)
        self.assertNotIn("WantedBy=default.target", text)


if __name__ == "__main__":
    unittest.main()
