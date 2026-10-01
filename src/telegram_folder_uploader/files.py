from __future__ import annotations

from pathlib import Path
from .constants import CONFIG_DIR, EXCLUDED_NAMES


def is_excluded(relative_path: Path) -> bool:
    for part in relative_path.parts:
        if (
            part in EXCLUDED_NAMES
            or part.endswith(".session")
            or part.endswith(".session-journal")
        ):
            return True
    return False


def collect_files(source_root: Path) -> list[Path]:
    files: list[Path] = []
    resolved_config = CONFIG_DIR.expanduser().resolve()

    for path in source_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue

        # Never collect anything inside ~/.telegram-folder-uploader
        try:
            path.resolve().relative_to(resolved_config)
            continue
        except ValueError:
            pass

        relative = path.relative_to(source_root)
        if is_excluded(relative):
            continue

        files.append(path)

    return sorted(files, key=lambda p: p.relative_to(source_root).as_posix().lower())


def file_key(
    chat_id: int | str,
    source_root: Path,
    path: Path,
    size: int | None = None,
    mtime_ns: int | None = None,
) -> str:
    relative = path.relative_to(source_root).as_posix()
    if size is None or mtime_ns is None:
        stat_result = path.stat()
        size = stat_result.st_size
        mtime_ns = stat_result.st_mtime_ns
    return f"{chat_id}|{source_root.as_posix()}|{relative}|{size}|{mtime_ns}"


def folder_size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def human_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value:.1f} B"