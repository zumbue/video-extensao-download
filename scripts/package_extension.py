#!/usr/bin/env python3
"""Gera dist/video-extensao-download.zip pronto para extrair e instalar."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "dist" / "video-extensao-download.zip"
PREFIX = "video-extensao-download"
INCLUDE_DIRS = ("extension", "host", "scripts", "systemd")
INCLUDE_FILES = (
    "LICENSE",
    "README.md",
    ".gitignore",
    "run.sh",
    "run.bat",
    "Instalar.desktop",
    "Instalar.bat",
)
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv", ".git", "dist"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def build_zip(destination: Path = DEST) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in _files():
            _write(archive, ROOT / relative, f"{PREFIX}/{relative.as_posix()}")
    return destination


def _files() -> list[Path]:
    chosen: list[Path] = []
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.is_file():
            chosen.append(Path(name))
    for directory in INCLUDE_DIRS:
        base = ROOT / directory
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.parts) or path.suffix in SKIP_SUFFIXES:
                continue
            chosen.append(path.relative_to(ROOT))
    return chosen


def _write(archive: zipfile.ZipFile, path: Path, arcname: str) -> None:
    info = zipfile.ZipInfo.from_file(path, arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, path.read_bytes())


def main() -> None:
    print(build_zip())


if __name__ == "__main__":
    main()
