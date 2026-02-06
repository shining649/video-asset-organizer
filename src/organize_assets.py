#!/usr/bin/env python3
"""指定フォルダ内の素材を日付フォルダへ自動整理するMVPスクリプト。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".png", ".jpg", ".wav"}
EXCLUDED_EXTENSIONS = {".tmp", ".part", ".crdownload"}
EXCLUDED_PREFIXES = ("thumb", "thumbnail", "~$", ".")


class AssetOrganizer:
    def __init__(
        self,
        source_dir: Path,
        output_dir: Path,
        dry_run: bool,
        mode: str,
        log_file: Path,
        backup_dir: Optional[Path],
    ) -> None:
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.dry_run = dry_run
        self.mode = mode
        self.backup_dir = backup_dir

        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def run(self) -> None:
        files = sorted([p for p in self.source_dir.rglob("*") if p.is_file()])
        self.logger.info("scan started: source=%s files=%s dry_run=%s", self.source_dir, len(files), self.dry_run)

        moved = 0
        skipped = 0

        for file_path in files:
            if self._should_skip(file_path):
                skipped += 1
                continue

            file_date = self._resolve_date(file_path)
            target_dir = self.output_dir / f"{file_date:%Y}" / f"{file_date:%m}" / f"{file_date:%d}"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = self._build_unique_path(target_dir / file_path.name)

            self.logger.info("plan: %s -> %s", file_path, target_path)

            if self.dry_run:
                continue

            if self.mode == "move" and self.backup_dir:
                backup_path = self.backup_dir / file_path.relative_to(self.source_dir)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, backup_path)
                self.logger.info("backup: %s", backup_path)

            if self.mode == "copy":
                shutil.copy2(file_path, target_path)
            else:
                shutil.move(str(file_path), str(target_path))

            moved += 1
            self.logger.info("done: %s", target_path)

        self.logger.info("scan finished: processed=%s skipped=%s dry_run=%s", moved, skipped, self.dry_run)

    def _should_skip(self, file_path: Path) -> bool:
        if file_path.suffix.lower() in EXCLUDED_EXTENSIONS:
            self.logger.debug("skip by excluded extension: %s", file_path)
            return True

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            self.logger.debug("skip by unsupported extension: %s", file_path)
            return True

        lowered_name = file_path.name.lower()
        if any(lowered_name.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            self.logger.debug("skip by excluded prefix: %s", file_path)
            return True

        return False

    def _resolve_date(self, file_path: Path) -> dt.datetime:
        metadata_date = self._read_date_from_exiftool(file_path)
        if metadata_date:
            return metadata_date
        return dt.datetime.fromtimestamp(file_path.stat().st_mtime)

    def _read_date_from_exiftool(self, file_path: Path) -> Optional[dt.datetime]:
        fields = ["-DateTimeOriginal", "-CreateDate", "-MediaCreateDate"]
        command = ["exiftool", "-j", "-n", *fields, str(file_path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            payload = json.loads(result.stdout)
            if not payload:
                return None
            item = payload[0]
            for key in ("DateTimeOriginal", "CreateDate", "MediaCreateDate"):
                raw_value = item.get(key)
                parsed = self._parse_datetime(raw_value)
                if parsed:
                    return parsed
        except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError):
            return None
        return None

    def _parse_datetime(self, raw_value: object) -> Optional[dt.datetime]:
        if not isinstance(raw_value, str):
            return None

        candidates = [
            "%Y:%m:%d %H:%M:%S",
            "%Y:%m:%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
        ]
        cleaned = raw_value.replace("Z", "+0000")
        for fmt in candidates:
            try:
                return dt.datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        return None

    def _build_unique_path(self, target_path: Path) -> Path:
        if not target_path.exists():
            return target_path

        stem = target_path.stem
        suffix = target_path.suffix
        parent = target_path.parent
        counter = 1

        while True:
            candidate = parent / f"{stem}_{counter:03d}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="動画/画像/音声素材を日付フォルダに整理する")
    parser.add_argument("--source", required=True, type=Path, help="入力フォルダ")
    parser.add_argument("--output", required=True, type=Path, help="出力フォルダ")
    parser.add_argument("--execute", action="store_true", help="実際にコピー/移動を実行する（指定がない場合はdry-run）")
    parser.add_argument("--mode", choices=["copy", "move"], default="copy", help="ファイル操作モード")
    parser.add_argument("--log-file", type=Path, default=Path("logs/organizer.log"), help="ログ出力先")
    parser.add_argument("--backup-dir", type=Path, default=None, help="move時に退避コピーを保存するフォルダ")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    organizer = AssetOrganizer(
        source_dir=args.source,
        output_dir=args.output,
        dry_run=not args.execute,
        mode=args.mode,
        log_file=args.log_file,
        backup_dir=args.backup_dir,
    )
    organizer.run()


if __name__ == "__main__":
    main()
