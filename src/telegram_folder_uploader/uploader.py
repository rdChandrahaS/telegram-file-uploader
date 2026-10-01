from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from .constants import STATE_PATH
from .files import file_key, folder_size
from .state import load_state, save_state
from .telegram import display_destination


def human_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value:.1f} B"


def progress_callback(label: str) -> Callable[[int, int], None]:
    last_printed = -1

    def callback(current: int, total: int) -> None:
        nonlocal last_printed
        if total <= 0:
            return
        percent = int(current * 100 / total)
        if percent == last_printed and percent != 100:
            return
        last_printed = percent
        width = 34
        filled = int(width * percent / 100)
        bar = "#" * filled + "." * (width - filled)
        print(
            f"\r  {label[:42]:42} [{bar}] {percent:3d}% "
            f"({human_bytes(current)}/{human_bytes(total)})",
            end="",
            flush=True,
        )
        if percent >= 100:
            print()

    return callback


def _mark_uploaded(state: dict[str, Any], source_root: Path, path: Path) -> None:
    state[file_key(source_root, path)] = {
        "status": "uploaded",
        "relative_path": path.relative_to(source_root).as_posix(),
        "size": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
    }
    save_state(state)


async def _send_one(client: TelegramClient, entity: Any, path: Path, relative: str) -> None:
    await client.send_file(
        entity,
        str(path),
        force_document=True,
        progress_callback=progress_callback(relative),
    )


async def upload_files(
    client: TelegramClient,
    entity: Any,
    source_root: Path,
    files: list[Path],
    dry_run: bool = False,
) -> int:
    state = load_state()
    uploaded = 0
    skipped = 0
    failed = 0

    print(f"\nSource:      {source_root}")
    print(f"Destination: {display_destination(entity)}")
    print(f"Files:       {len(files)} ({human_bytes(folder_size(files))})")

    if not files:
        print("No files to upload.")
        return 0

    for index, path in enumerate(files, 1):
        relative = path.relative_to(source_root).as_posix()
        try:
            key = file_key(source_root, path)
            size = path.stat().st_size
        except OSError as exc:
            print(f"[{index}/{len(files)}] SKIP {relative}: cannot stat file ({exc})")
            failed += 1
            continue

        if state.get(key, {}).get("status") == "uploaded":
            print(f"[{index}/{len(files)}] SKIP  {relative} (already uploaded)")
            skipped += 1
            continue

        if dry_run:
            print(f"[{index}/{len(files)}] WOULD UPLOAD {relative} ({human_bytes(size)})")
            continue

        print(f"[{index}/{len(files)}] UPLOAD {relative} ({human_bytes(size)})")
        try:
            await _send_one(client, entity, path, relative)
        except FloodWaitError as exc:
            print(f"\n  Telegram rate limit: waiting {exc.seconds} seconds...")
            await asyncio.sleep(exc.seconds)
            try:
                await _send_one(client, entity, path, relative)
            except Exception as retry_exc:  # noqa: BLE001
                print(f"  ✗ Retry failed: {retry_exc}")
                failed += 1
                continue
        except RPCError as exc:
            print(f"  ✗ Telegram error: {exc}")
            failed += 1
            continue
        except OSError as exc:
            print(f"  ✗ File error: {exc}")
            failed += 1
            continue

        try:
            _mark_uploaded(state, source_root, path)
        except OSError as exc:
            print(f"  ⚠ Uploaded, but state could not be saved: {exc}")
        uploaded += 1
        print(f"  ✓ Uploaded: {relative}")

    print("\nFinished.")
    print(f"  Uploaded: {uploaded}")
    print(f"  Skipped:  {skipped}")
    print(f"  Failed:   {failed}")
    print(f"  State:    {STATE_PATH}")
    return failed
