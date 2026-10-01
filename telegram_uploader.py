#!/usr/bin/env python3
"""Upload all files from the current folder to a Telegram chat using Telethon.

The script is intentionally local-first:
- Telegram session is stored outside the source folder.
- API credentials live in a local .env file (or are requested interactively).
- The uploader skips its own project/config/state files.
- Upload state is persisted so an interrupted run can resume.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl import functions, types

APP_NAME = "telegram-folder-uploader"
CONFIG_DIR = Path.home() / f".{APP_NAME}"
SESSION_PATH = CONFIG_DIR / "telegram.session"
STATE_PATH = CONFIG_DIR / "upload_state.json"
DEFAULT_ENV_PATH = Path.cwd() / ".env"

EXCLUDED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".idea",
    ".vscode",
    ".DS_Store",
    ".env",
    ".env.local",
    "telegram_uploader.py",
}


def parse_dotenv(path: Path) -> dict[str, str]:
    """Read a tiny .env subset without requiring python-dotenv."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def set_private_permissions(path: Path) -> None:
    """Best-effort chmod 600 for credential/state files on POSIX systems."""
    if os.name == "posix" and path.exists():
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def set_private_dir_permissions(path: Path) -> None:
    """Best-effort chmod 700 for the directory containing private session data."""
    if os.name == "posix" and path.exists():
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    set_private_dir_permissions(CONFIG_DIR)


def load_config() -> tuple[int, str]:
    dotenv = parse_dotenv(DEFAULT_ENV_PATH)
    api_id_raw = os.environ.get("TELEGRAM_API_ID") or dotenv.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH") or dotenv.get("TELEGRAM_API_HASH")

    if not api_id_raw:
        print("\nTelegram API ID is not configured.")
        print("Create one at https://my.telegram.org -> API development tools.\n")
        api_id_raw = input("API ID: ").strip()

    if not api_hash:
        api_hash = input("API hash: ").strip()

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise ValueError("TELEGRAM_API_ID must be an integer.") from exc

    if not api_hash:
        raise ValueError("TELEGRAM_API_HASH cannot be empty.")

    # If .env does not exist, offer to save the values locally for future runs.
    if not DEFAULT_ENV_PATH.exists():
        try:
            DEFAULT_ENV_PATH.write_text(
                "# Telegram API credentials - keep this file private\n"
                f"TELEGRAM_API_ID={api_id}\n"
                f"TELEGRAM_API_HASH={api_hash}\n",
                encoding="utf-8",
            )
            set_private_permissions(DEFAULT_ENV_PATH)
            print(f"Saved API credentials to {DEFAULT_ENV_PATH}")
        except OSError as exc:
            print(f"Warning: could not save .env: {exc}")

    return api_id, api_hash


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    ensure_config_dir()
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_PATH)
    set_private_permissions(STATE_PATH)


def file_key(source_root: Path, path: Path) -> str:
    rel = path.relative_to(source_root).as_posix()
    st = path.stat()
    return f"{rel}|{st.st_size}|{st.st_mtime_ns}"


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_NAMES for part in path.parts)


def collect_files(source_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        if is_excluded(path.relative_to(source_root)):
            continue
        # Avoid symlink surprises.
        if path.is_symlink():
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(source_root).as_posix().lower())


def human_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value:.1f} B"


def progress_callback(label: str):
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


def clean_group_input(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^tg://openmessage\?user_id=", "", value)
    return value


async def resolve_chat(client: TelegramClient, raw: str):
    raw = clean_group_input(raw)
    if not raw:
        raise ValueError("No Telegram group was supplied.")

    # Direct usernames are convenient.
    if raw.startswith("@"):
        return await client.get_entity(raw)

    # Handle public t.me links and ordinary Telegram usernames.
    match = re.fullmatch(r"https?://t\.me/([A-Za-z0-9_]+)(?:\?.*)?", raw)
    if match:
        username = match.group(1)
        return await client.get_entity(username)

    # Private invite links. We do not join automatically; the user must opt in.
    invite_match = re.search(r"(?:https?://)?t\.me/(?:\+|joinchat/)([^/?#]+)", raw)
    if invite_match:
        invite_hash = invite_match.group(1)
        try:
            checked = await client(functions.messages.CheckChatInviteRequest(hash=invite_hash))
        except RPCError as exc:
            raise ValueError(f"Telegram could not inspect that invite link: {exc}") from exc

        if isinstance(checked, types.messages.ChatInviteAlready):
            return await client.get_entity(checked.chat)

        title = getattr(checked, "title", "this chat")
        print(f"Invite link refers to: {title}")
        answer = input("You are not currently in this chat. Join it now? [y/N]: ").strip().lower()
        if answer != "y":
            raise ValueError("Not joining the invite chat. Join it in Telegram first, then run again.")

        joined = await client(functions.messages.ImportChatInviteRequest(hash=invite_hash))
        if getattr(joined, "chats", None):
            return joined.chats[0]
        raise ValueError("Telegram did not return the joined chat.")

    # Also allow a numeric chat/channel id if the entity is cached.
    try:
        return await client.get_entity(int(raw))
    except ValueError:
        pass
    return await client.get_entity(raw)


async def choose_from_dialogs(client: TelegramClient):
    print("\nLoading your groups/channels...")
    choices = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (types.Chat, types.Channel)):
            # Broadcast channels are included because they are also valid upload destinations.
            choices.append(dialog)
        if len(choices) >= 100:
            break

    if not choices:
        raise ValueError("No groups/channels were found in your Telegram account.")

    for idx, dialog in enumerate(choices, 1):
        kind = "channel" if isinstance(dialog.entity, types.Channel) and getattr(dialog.entity, "broadcast", False) else "group"
        print(f"  {idx:3d}. [{kind}] {dialog.name}")

    while True:
        raw = input(f"\nSelect destination [1-{len(choices)}]: ").strip()
        try:
            selected = int(raw)
            if 1 <= selected <= len(choices):
                return choices[selected - 1].entity
        except ValueError:
            pass
        print("Please enter one of the displayed numbers.")


def display_destination(entity: Any) -> str:
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    if title and username:
        return f"{title} (@{username})"
    return title or (f"@{username}" if username else str(entity))


def folder_size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


async def upload_files(client: TelegramClient, entity: Any, source_root: Path, files: list[Path], dry_run: bool) -> int:
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
        except OSError as exc:
            print(f"[{index}/{len(files)}] SKIP {relative}: cannot stat file ({exc})")
            failed += 1
            continue

        if state.get(key, {}).get("status") == "uploaded":
            print(f"[{index}/{len(files)}] SKIP  {relative} (already uploaded)")
            skipped += 1
            continue

        if dry_run:
            print(f"[{index}/{len(files)}] WOULD UPLOAD {relative} ({human_bytes(path.stat().st_size)})")
            continue

        print(f"[{index}/{len(files)}] UPLOAD {relative} ({human_bytes(path.stat().st_size)})")

        try:
            await client.send_file(
                entity,
                str(path),
                force_document=True,
                progress_callback=progress_callback(relative),
            )
            state[key] = {
                "status": "uploaded",
                "relative_path": relative,
                "size": path.stat().st_size,
                "mtime_ns": path.stat().st_mtime_ns,
            }
            save_state(state)
            uploaded += 1
            print(f"  ✓ Uploaded: {relative}")

        except FloodWaitError as exc:
            print(f"\n  Telegram rate limit: waiting {exc.seconds} seconds...")
            await asyncio.sleep(exc.seconds)
            # Retry the same file once after the server-requested wait.
            try:
                await client.send_file(
                    entity,
                    str(path),
                    force_document=True,
                    progress_callback=progress_callback(relative),
                )
                state[key] = {
                    "status": "uploaded",
                    "relative_path": relative,
                    "size": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                }
                save_state(state)
                uploaded += 1
                print(f"  ✓ Uploaded after rate-limit wait: {relative}")
            except Exception as retry_exc:  # noqa: BLE001
                print(f"  ✗ Retry failed: {retry_exc}")
                failed += 1

        except (RPCError, OSError, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            print(f"  ✗ Failed: {exc}")
            failed += 1

    print("\nFinished.")
    print(f"  Uploaded: {uploaded}")
    print(f"  Skipped:  {skipped}")
    print(f"  Failed:   {failed}")
    print(f"  State:    {STATE_PATH}")
    return failed


async def async_main(args: argparse.Namespace) -> int:
    source_root = Path(args.folder).expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        print(f"Error: not a directory: {source_root}", file=sys.stderr)
        return 2

    ensure_config_dir()
    api_id, api_hash = load_config()

    print("\nConnecting to Telegram...")
    print("First run: Telegram may ask for your phone, login code, and 2FA password.")
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        await client.start()
        me = await client.get_me()
        account_name = getattr(me, "username", None) or getattr(me, "first_name", None) or str(me.id)
        print(f"Logged in as: {account_name}")

        group_input = args.group
        if not group_input:
            group_input = input(
                "\nTelegram group link / @username (press Enter to choose from your chats): "
            ).strip()

        try:
            entity = await choose_from_dialogs(client) if not group_input else await resolve_chat(client, group_input)
        except (ValueError, RPCError) as exc:
            print(f"Could not resolve destination: {exc}", file=sys.stderr)
            return 3

        # Collect before starting uploads so the preview is deterministic.
        files = collect_files(source_root)

        if args.dry_run:
            await upload_files(client, entity, source_root, files, dry_run=True)
            return 0

        answer = input(
            f"\nUpload {len(files)} file(s) to {display_destination(entity)}? [y/N]: "
        ).strip().lower()
        if answer != "y":
            print("Cancelled. No files were uploaded.")
            return 0

        failed = await upload_files(client, entity, source_root, files, dry_run=False)
        return 1 if failed else 0
    finally:
        await client.disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload all files from a folder to a Telegram group/channel."
    )
    parser.add_argument(
        "--folder",
        default=".",
        help="Source folder (default: current directory).",
    )
    parser.add_argument(
        "--group",
        help="Telegram group/channel link or @username. If omitted, you can choose from your chats.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would be uploaded without sending anything.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted. Progress already saved for completed files.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
