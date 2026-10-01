from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import questionary
from rich.console import Console
from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.sessions import StringSession
from telethon.utils import get_peer_id

from .config import (
    ensure_config_dir,
    load_credentials,
    save_encrypted_vault,
)
from .constants import VAULT_PATH
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


async def _prompt_login_code() -> str:
    code = await questionary.text(
        "Enter the login code sent to your Telegram app:",
        validate=lambda val: bool(val.strip()) or "Login code cannot be empty",
    ).ask_async()
    if not code:
        raise KeyboardInterrupt
    return code.strip()


async def _prompt_2fa_password() -> str:
    pwd = await questionary.password(
        "Enter your Telegram Two-Step Verification (2FA) password:",
    ).ask_async()
    if pwd is None:
        raise KeyboardInterrupt
    return pwd


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
    auth = await load_credentials(source_root)

    # Use in-memory StringSession (loaded from decrypted vault if available)
    session = StringSession(auth.session_string) if auth.session_string else StringSession()

    console.print("\n[cyan]Connecting to Telegram...[/cyan]")
    client = TelegramClient(session, auth.api_id, auth.api_hash)

    try:
        await client.start(
            phone=lambda: auth.phone,
            code_callback=_prompt_login_code,
            password=_prompt_2fa_password,
        )

        me = await client.get_me()
        username = getattr(me, "username", None)
        account_name = f"@{username}" if username else (getattr(me, "first_name", None) or str(me.id))
        actual_phone = f"+{me.phone}" if getattr(me, "phone", None) else auth.phone

        # Encrypt API ID, API Hash, Phone, and active StringSession into vault.enc
        if auth.save_for_future and auth.vault_password:
            session_str = client.session.save()
            save_encrypted_vault(
                api_id=auth.api_id,
                api_hash=auth.api_hash,
                phone=actual_phone,
                session_string=session_str,
                password=auth.vault_password,
                account_name=account_name,
            )
            console.print(f"[green]🔒 Credentials & session encrypted in {VAULT_PATH}[/green]")

        is_premium = bool(getattr(me, "premium", False))
        max_file_size = 4 * 1024**3 if is_premium else 2 * 1024**3
        tier_label = "Premium (4 GB limit)" if is_premium else "Standard (2 GB limit)"

        console.print(
            f"[green]✔ Logged in as:[/green] [bold]{account_name}[/bold] "
            f"({actual_phone}) [{tier_label}]\n"
        )

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