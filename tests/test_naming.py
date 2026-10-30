import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host.download import QUALITIES
from host.naming import (
    UserError,
    auto_filename,
    detect_network,
    format_time,
    load_catalog,
    output_extension,
    parse_request,
    parse_time,
    sanitize_filename,
    youtube_start,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests" / "cases.json").read_text(encoding="utf-8"))


class NamingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_urls(self):
        for case in CASES["urls"]:
            found = detect_network(case["url"], self.catalog)
            found_id = None if found is None else found["id"]
            self.assertEqual(found_id, case["id"], case["url"])
            if case.get("label"):
                self.assertEqual(found["label"], case["label"], case["url"])

    def test_filenames(self):
        for case in CASES["filenames"]:
            moment = datetime(*case["parts"])
            self.assertEqual(auto_filename(case["id"], moment), case["expected"])

    def test_sanitize_and_extension(self):
        for case in CASES["sanitize"]:
            self.assertEqual(sanitize_filename(case["value"]), case["expected"], case["value"])
        for case in CASES["extensions"]:
            self.assertEqual(
                output_extension(case["quality"], case["compress"]),
                case["expected"],
            )

    def test_quality_ids_follow_the_catalog(self):
        self.assertEqual([item["id"] for item in self.catalog["qualities"]], list(QUALITIES))

    def test_parse_request_fills_the_name_and_rejects_a_bad_link(self):
        moment = datetime(2026, 10, 30, 21, 5, 9)
        request = parse_request(
            {"url": "https://www.youtube.com/watch?v=abc", "quality": "720", "compress": True},
            self.catalog,
            moment,
        )
        self.assertEqual(request.filename, "youtube_2026-10-30_21-05-09")
        self.assertTrue(request.compress)
        self.assertEqual(request.network_id, "youtube")
        with self.assertRaises(Exception):
            parse_request({"url": "notaurl", "quality": "best"}, self.catalog)
        ranged = parse_request(
            {
                "url": "https://youtu.be/abc",
                "quality": "best",
                "compress": False,
                "start_time": "1:30",
                "end_time": 95,
            },
            self.catalog,
            moment,
        )
        self.assertEqual(ranged.start_time, 90)
        self.assertEqual(ranged.end_time, 95)
        self.assertIsNone(request.start_time)
        self.assertIsNone(request.end_time)
        with self.assertRaises(UserError) as caught:
            parse_request(
                {"url": "https://youtu.be/abc", "start_time": 10, "end_time": "0:10"},
                self.catalog,
            )
        self.assertIn("fim", str(caught.exception))

    def test_times_match_the_shared_cases(self):
        for case in CASES["times"]:
            label = repr(case["value"])
            if case.get("error"):
                with self.assertRaises(UserError) as caught:
                    parse_time(case["value"])
                self.assertEqual(str(caught.exception), case["error"], label)
            else:
                self.assertEqual(parse_time(case["value"]), case["seconds"], label)
        for case in CASES["clocks"]:
            self.assertEqual(format_time(case["seconds"]), case["text"])
            self.assertEqual(parse_time(case["text"]), case["seconds"])
        for case in CASES["youtubeStarts"]:
            self.assertEqual(youtube_start(case["url"]), case["seconds"], case["url"])


if __name__ == "__main__":
    unittest.main()
