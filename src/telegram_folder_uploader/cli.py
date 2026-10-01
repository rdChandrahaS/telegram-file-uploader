from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import RPCError

from .config import ensure_config_dir, load_credentials
from .constants import SESSION_PATH
from .files import collect_files
from .telegram import choose_from_dialogs, display_destination, resolve_chat
from .uploader import upload_files


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
        help="Telegram group/channel link or @username. If omitted, choose from your chats.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would be uploaded without sending anything.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    source_root = Path(args.folder).expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        print(f"Error: not a directory: {source_root}", file=sys.stderr)
        return 2

    ensure_config_dir()
    api_id, api_hash = load_credentials(source_root)

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
            entity = (
                await choose_from_dialogs(client)
                if not group_input
                else await resolve_chat(client, group_input)
            )
        except (ValueError, RPCError) as exc:
            print(f"Could not resolve destination: {exc}", file=sys.stderr)
            return 3

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

        failed = await upload_files(client, entity, source_root, files)
        return 1 if failed else 0
    finally:
        await client.disconnect()


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
