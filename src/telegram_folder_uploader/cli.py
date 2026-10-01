from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.utils import get_peer_id

from .config import ensure_config_dir, load_credentials, protect_session
from .constants import SESSION_PATH
from .files import collect_files
from .logger import setup_folder_logger
from .telegram import prompt_destination
from .uploader import interactive_select_files, upload_files

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upload-telegram",
        description="Interactive Terminal GUI to select and upload files from a folder to Telegram.",
    )
    parser.add_argument(
        "--folder",
        default=".",
        help="Source folder (default: current working directory).",
    )
    parser.add_argument(
        "--group",
        help="Telegram group/channel link (public or private invite) or @username.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Select all files in the folder without opening the interactive file selector.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload selected files even if they are already recorded in upload_state.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview which files would be uploaded without sending them.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    source_root = Path(args.folder).expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        console.print(f"[bold red]Error:[/bold red] Not a valid directory: {source_root}")
        return 2

    all_files = collect_files(source_root)
    if not all_files:
        console.print(f"[yellow]No uploadable files found in {source_root}[/yellow]")
        return 0

    ensure_config_dir()
    logger, log_path = setup_folder_logger(source_root)
    api_id, api_hash = load_credentials(source_root)

    console.print("\n[cyan]Connecting to Telegram...[/cyan]")
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)

    try:
        await client.start()
        protect_session(SESSION_PATH)

        me = await client.get_me()
        account_name = getattr(me, "username", None) or getattr(me, "first_name", None) or str(me.id)
        is_premium = bool(getattr(me, "premium", False))
        max_file_size = 4 * 1024**3 if is_premium else 2 * 1024**3

        tier_label = "Premium (4 GB limit)" if is_premium else "Standard (2 GB limit)"
        console.print(f"[green]✔ Logged in as:[/green] [bold]{account_name}[/bold] [{tier_label}]\n")

        # Step 1: Ask for destination group link (or pick from user's groups)
        try:
            entity = await prompt_destination(client, args.group)
        except (ValueError, RPCError) as exc:
            console.print(f"[bold red]Could not resolve destination:[/bold red] {exc}")
            logger.error("Destination resolution failed: %s", exc)
            return 3

        # Step 2: Open Terminal GUI file selector (Space, 'a' select all, 'i' invert, Enter to start)
        chat_id = get_peer_id(entity)
        if args.all:
            selected_files = all_files
        else:
            selected_files = await interactive_select_files(
                source_root, all_files, chat_id, force=args.force
            )

        if not selected_files:
            console.print("[yellow]No files selected. Nothing uploaded.[/yellow]")
            return 0

        # Step 3: Pressing Enter in the selector immediately starts the upload
        failed = await upload_files(
            client=client,
            entity=entity,
            source_root=source_root,
            files=selected_files,
            logger=logger,
            log_path=log_path,
            max_file_size=max_file_size,
            dry_run=args.dry_run,
            force=args.force,
        )
        return 1 if failed else 0
    finally:
        await client.disconnect()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print(
            "\n[yellow]⚠ Upload cancelled by user. Completed files are saved in state.[/yellow]"
        )
        return 130
    except Exception as exc:  # noqa: BLE001
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())