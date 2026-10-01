from __future__ import annotations

from pathlib import Path

from .constants import EXCLUDED_NAMES


def is_excluded(relative_path: Path) -> bool:
    return any(part in EXCLUDED_NAMES for part in relative_path.parts)


def collect_files(source_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source_root)
        if is_excluded(relative):
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(source_root).as_posix().lower())


def file_key(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root).as_posix()
    stat_result = path.stat()
    return f"{relative}|{stat_result.st_size}|{stat_result.st_mtime_ns}"


def folder_size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total
