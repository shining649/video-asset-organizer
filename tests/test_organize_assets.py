"""Standard-library tests; no real media files or exiftool required."""

import datetime as dt
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.organize_assets import AssetOrganizer, parse_args


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "incoming"
        self.source.mkdir()
        self.output = self.root / "sorted"
        self.backup = self.root / "backup"
        # Isolate logging from the process root logger and close handlers on Windows.
        def configure(**kwargs):
            for handler in kwargs["handlers"]:
                handler.close()
        self.logging_patch = patch("src.organize_assets.logging.basicConfig", side_effect=configure)
        self.logging_patch.start()
        self.addCleanup(self.logging_patch.stop)
        self.organizer = AssetOrganizer(self.source, self.output, True, "copy",
                                        self.root / "logs" / "test.log", self.backup)
        self.timestamp = dt.datetime(2024, 2, 29, 12, 30).timestamp()
        self.date_dir = self.output / "2024" / "02" / "29"

    def asset(self, name="clip.mp4", content=b"original"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (self.timestamp, self.timestamp))
        return path

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def run_organizer(self):
        with patch("src.organize_assets.subprocess.run", side_effect=FileNotFoundError):
            self.organizer.run()

    def test_parse_dates(self):
        for value in ("2024:02:29 12:30:00", "2024-02-29 12:30:00", "2024-02-29T12:30:00",
                      "2024:02:29 12:30:00+0900", "2024-02-29T12:30:00+09:00",
                      "2024-02-29T12:30:00Z"):
            with self.subTest(value=value):
                parsed = self.organizer._parse_datetime(value)
                self.assertEqual(parsed.date(), dt.date(2024, 2, 29))
                self.assertEqual(parsed.hour, 12)
        for value in (None, 123, "", "2023:02:29 12:30:00", "not a date"):
            with self.subTest(value=value):
                self.assertIsNone(self.organizer._parse_datetime(value))

    def test_metadata_priority_and_invalid_field_fallback(self):
        asset = self.asset()
        cases = [
            ({"DateTimeOriginal": "2020:01:02 03:04:05", "CreateDate": "2021:03:04 05:06:07",
              "MediaCreateDate": "2022:05:06 07:08:09"}, dt.date(2020, 1, 2)),
            ({"DateTimeOriginal": "bad", "CreateDate": "2021:03:04 05:06:07",
              "MediaCreateDate": "2022:05:06 07:08:09"}, dt.date(2021, 3, 4)),
            ({"MediaCreateDate": "2022:05:06 07:08:09"}, dt.date(2022, 5, 6)),
        ]
        for metadata, expected in cases:
            with self.subTest(metadata=metadata), patch("src.organize_assets.subprocess.run") as run:
                run.return_value.stdout = json.dumps([metadata])
                self.assertEqual(self.organizer._resolve_date(asset).date(), expected)

    def test_mtime_fallback(self):
        asset = self.asset()
        for payload in ("[]", "[{}]", '[{"DateTimeOriginal":"bad"}]', "invalid json"):
            with self.subTest(payload=payload), patch("src.organize_assets.subprocess.run") as run:
                run.return_value.stdout = payload
                self.assertEqual(self.organizer._resolve_date(asset), dt.datetime.fromtimestamp(self.timestamp))
        for error in (FileNotFoundError(), subprocess.CalledProcessError(1, "exiftool")):
            with self.subTest(error=error), patch("src.organize_assets.subprocess.run", side_effect=error):
                self.assertEqual(self.organizer._resolve_date(asset), dt.datetime.fromtimestamp(self.timestamp))

    def test_exclusions(self):
        for name in ("clip.tmp", "clip.part", "clip.crdownload", "notes.txt", "thumb001.JPG",
                     "Thumbnail.png", "~$clip.mov", ".hidden.wav"):
            with self.subTest(name=name):
                self.assertTrue(self.organizer._should_skip(Path(name)))
        for name in ("clip.MP4", "clip.mov", "photo.png", "photo.JPG", "sound.wav"):
            with self.subTest(name=name):
                self.assertFalse(self.organizer._should_skip(Path(name)))

    def test_copy_and_recursive_scan_skip_excluded_files(self):
        original = self.asset("nested/clip.MP4")
        excluded = self.asset("nested/thumb.jpg")
        self.organizer.dry_run = False
        self.run_organizer()
        target = self.date_dir / original.name
        self.assertEqual(target.read_bytes(), original.read_bytes())
        self.assertEqual(target.stat().st_mtime, original.stat().st_mtime)
        self.assertTrue(excluded.exists())
        self.assertEqual(list(self.date_dir.iterdir()), [target])
        self.assertFalse(self.backup.exists())

    def test_move_with_and_without_backup(self):
        for use_backup in (True, False):
            with self.subTest(backup=use_backup):
                original = self.asset(f"nested/clip{use_backup}.mov")
                backup_path = self.backup / original.relative_to(self.source)
                self.organizer.dry_run = False
                self.organizer.mode = "move"
                self.organizer.backup_dir = self.backup if use_backup else None
                self.run_organizer()
                self.assertFalse(original.exists())
                self.assertEqual((self.date_dir / original.name).read_bytes(), b"original")
                self.assertEqual(backup_path.exists(), use_backup)
                if use_backup:
                    self.assertEqual(backup_path.read_bytes(), b"original")

    def test_dry_run_preserves_files_and_creates_no_asset_directories(self):
        self.asset()
        before = self.snapshot()
        for mode in ("copy", "move"):
            with self.subTest(mode=mode):
                self.organizer.mode = mode
                self.run_organizer()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.backup.exists())

    def test_collision_plans_match_execution_and_do_not_overwrite(self):
        self.asset("a/clip.mp4", b"a")
        self.asset("b/clip.mp4", b"b")
        self.date_dir.mkdir(parents=True)
        (self.date_dir / "clip.mp4").write_bytes(b"existing")
        (self.date_dir / "clip_001.mp4").write_bytes(b"existing 001")
        before = self.snapshot()
        def plans():
            with self.assertLogs(self.organizer.logger, logging.INFO) as captured:
                self.run_organizer()
            return [record.getMessage() for record in captured.records if record.msg.startswith("plan:")]
        preview = plans()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(preview, plans())  # Reservations reset for each run.
        self.assertTrue(preview[0].endswith("clip_002.mp4"))
        self.assertTrue(preview[1].endswith("clip_003.mp4"))
        self.organizer.dry_run = False
        self.assertEqual(preview, plans())
        for name, content in (("clip.mp4", b"existing"), ("clip_001.mp4", b"existing 001"),
                              ("clip_002.mp4", b"a"), ("clip_003.mp4", b"b")):
            self.assertEqual((self.date_dir / name).read_bytes(), content)

    def test_no_supported_files_creates_no_output_even_in_execute(self):
        self.asset("thumb.png")
        self.organizer.dry_run = False
        self.run_organizer()
        self.assertFalse(self.output.exists())

    def test_cli_defaults_and_execute_option(self):
        argv = ["organize_assets.py", "--source", str(self.source), "--output", str(self.output)]
        with patch.object(sys, "argv", argv):
            args = parse_args()
        self.assertFalse(args.execute)
        self.assertEqual(args.mode, "copy")
        with patch.object(sys, "argv", argv + ["--execute", "--mode", "move"]):
            args = parse_args()
        self.assertTrue(args.execute)
        self.assertEqual(args.mode, "move")

    def test_cli_default_dry_run_writes_only_log(self):
        self.asset()
        script = Path(__file__).resolve().parents[1] / "src" / "organize_assets.py"
        result = subprocess.run([sys.executable, str(script), "--source", str(self.source),
                                 "--output", str(self.output), "--mode", "move",
                                 "--backup-dir", str(self.backup)],
                                cwd=self.root, capture_output=True, text=True,
                                env={**os.environ, "PATH": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.backup.exists())
        self.assertEqual((self.source / "clip.mp4").read_bytes(), b"original")
        log = (self.root / "logs" / "organizer.log").read_text(encoding="utf-8")
        self.assertIn("plan:", log)
        self.assertIn("dry_run=True", log)


if __name__ == "__main__":
    unittest.main()
