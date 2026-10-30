import base64
import hashlib
import io
import json
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ved_host import MAX_MESSAGE, NATIVE_NAME, read_message, start_server, write_message

ROOT = Path(__file__).resolve().parents[1]


def chrome_extension_id(key_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(key_b64)).digest()
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[byte >> 4] + alphabet[byte & 0xF] for byte in digest[:16])


class OneByteStream:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        piece = self.data[self.offset:self.offset + 1]
        self.offset += len(piece)
        return piece


class NativeHostTests(unittest.TestCase):
    def test_message_roundtrip_survives_short_reads(self):
        buffer = io.BytesIO()
        write_message(buffer, {"ok": True, "started": False})
        self.assertEqual(read_message(OneByteStream(buffer.getvalue())), {"ok": True, "started": False})

    def test_empty_or_oversized_message_is_ignored(self):
        self.assertEqual(read_message(io.BytesIO()), {})
        self.assertEqual(read_message(io.BytesIO(struct.pack("<I", MAX_MESSAGE + 1))), {})
        self.assertEqual(read_message(io.BytesIO(struct.pack("<I", 2) + b"{")), {})

    def test_extension_id_matches_the_windows_allowlist(self):
        manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        extension_id = chrome_extension_id(manifest["key"])
        self.assertEqual(len(extension_id), 32)
        self.assertRegex(extension_id, r"^[a-p]{32}$")
        installer = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
        popup = (ROOT / "extension" / "popup.js").read_text(encoding="utf-8")
        self.assertIn(extension_id, installer)
        self.assertIn(f"chrome-extension://${{ExtensionId}}/", installer)
        self.assertIn(NATIVE_NAME, installer)
        self.assertIn(NATIVE_NAME, popup)
        self.assertIn("nativeMessaging", manifest["permissions"])
        self.assertNotIn("CreateShortcut", installer)
        self.assertIn("Video Extensao Download.lnk", installer)

    def test_launcher_is_crlf_and_points_at_the_host(self):
        cmd = (ROOT / "scripts" / "ved-host.cmd").read_bytes()
        self.assertTrue(cmd.startswith(b"@echo off\r\n"))
        self.assertNotIn(b"\n", cmd.replace(b"\r\n", b""))
        self.assertIn(b"ved_host.py", cmd)

    def test_start_server_does_not_spawn_when_the_port_is_open(self):
        with mock.patch("scripts.ved_host.port_open", return_value=True), mock.patch("scripts.ved_host._spawn") as spawn:
            self.assertFalse(start_server(8734))
        spawn.assert_not_called()

    def test_start_server_marks_idle_exit(self):
        with mock.patch("scripts.ved_host.port_open", return_value=False), mock.patch("scripts.ved_host._spawn") as spawn:
            self.assertTrue(start_server(8734))
        command, env = spawn.call_args.args
        self.assertEqual(command[-2:], ["-m", "host"])
        self.assertEqual(env["MDE_IDLE_EXIT"], "1")
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")


if __name__ == "__main__":
    unittest.main()
