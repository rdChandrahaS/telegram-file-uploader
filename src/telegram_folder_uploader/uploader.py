from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.utils import get_peer_id

from .files import file_key, folder_size, human_bytes
from .state import load_state, save_state
from .telegram import display_destination

console = Console()


async def interactive_select_files(
    source_root: Path,
    all_files: list[Path],
    chat_id: int | str,
    force: bool = False,
) -> list[Path]:
    """Opens an interactive terminal checkbox UI supporting 'a' (all), 'i' (invert), and Enter."""
    state = load_state()
    choices: list[questionary.Choice] = []

    for path in all_files:
        rel = path.relative_to(source_root).as_posix()
        try:
            stat_res = path.stat()
            size_str = human_bytes(stat_res.st_size)
            key = file_key(chat_id, source_root, path, stat_res.st_size, stat_res.st_mtime_ns)
            already_done = state.get(key, {}).get("status") == "uploaded"
        except OSError:
            size_str = "? B"
            already_done = False

        status_tag = " [already uploaded]" if already_done else ""
        label = f"{rel} ({size_str}){status_tag}"
        choices.append(
            questionary.Choice(
                title=label,
                value=path,
                checked=(True if force else not already_done),
            )
        )

    console.print(
        Panel(
            "[bold cyan]Interactive File Selector[/bold cyan]\n"
            "• [bold]↑ / ↓[/bold] : Move cursor\n"
            "• [bold]Space[/bold] : Toggle file selection\n"
            "• [bold]a[/bold]     : Select All / Deselect All\n"
            "• [bold]i[/bold]     : Invert Selection\n"
            "• [bold]Enter[/bold] : Confirm & Start Uploading",
            border_style="cyan",
        )
    )

    selected_files = await questionary.checkbox(
        f"Select files to upload from '{source_root.name}':",
        choices=choices,
    ).ask_async()

    if selected_files is None:
        raise KeyboardInterrupt

    return selected_files


def _mark_uploaded(
    state: dict[str, Any],
    key: str,
    chat_id: int | str,
    source_root: Path,
    relative: str,
    size: int,
    mtime_ns: int,
) -> None:
    state[key] = {
        "status": "uploaded",
        "chat_id": str(chat_id),
        "source_root": source_root.as_posix(),
        "relative_path": relative,
        "size": size,
        "mtime_ns": mtime_ns,
    }
    save_state(state)


async def upload_files(
    client: TelegramClient,
    entity: Any,
    source_root: Path,
    files: list[Path],
    logger: logging.Logger,
    log_path: Path,
    max_file_size: int = 2 * 1024**3,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    state = load_state()
    chat_id = get_peer_id(entity)
    dest_name = display_destination(entity)

    uploaded = 0
    skipped = 0
    failed = 0

    total_bytes = folder_size(files)
    console.print(
        Panel(
            f"[bold]Source Folder:[/bold] {source_root}\n"
            f"[bold]Destination:[/bold]   {dest_name}\n"
            f"[bold]Selected:[/bold]      {len(files)} file(s) ({human_bytes(total_bytes)})\n"
            f"[bold]Size Limit:[/bold]    {human_bytes(max_file_size)} per file\n"
            f"[bold]Log File:[/bold]      {log_path}",
            title="🚀 Upload Session",
            border_style="green",
        )
    )

    logger.info(
        "=== Starting upload session | Folder: %s | Destination: %s (%s) | Files selected: %d ===",
        source_root,
        dest_name,
        chat_id,
        len(files),
    )

    if not files:
        console.print("[yellow]No files selected. Exiting.[/yellow]")
        logger.info("No files selected by user.")
        return 0

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=36),
        "[progress.percentage]{task.percentage:>3.0f}%",
        "•",
        DownloadColumn(),
        "•",
        TransferSpeedColumn(),
        "•",
        TimeRemainingColumn(),
        console=console,
    )

    with progress:
        overall_task = progress.add_task(
            f"[bold green]Overall ({len(files)} files)", total=total_bytes
        )

        for index, path in enumerate(files, 1):
            relative = path.relative_to(source_root).as_posix()
            try:
                stat_result = path.stat()
                size = stat_result.st_size
                mtime_ns = stat_result.st_mtime_ns
            except OSError as exc:
                msg = f"[{index}/{len(files)}] Cannot stat {relative}: {exc}"
                progress.console.print(f"[red]✖ {msg}[/red]")
                logger.error(msg)
                failed += 1
                continue

            key = file_key(chat_id, source_root, path, size, mtime_ns)

            # 1. Skip if already uploaded (unless --force was passed)
            if not force and state.get(key, {}).get("status") == "uploaded":
                skipped += 1
                progress.update(overall_task, advance=size)
                msg = f"[{index}/{len(files)}] Skipped: {relative} (already uploaded)"
                progress.console.print(f"[yellow]⏭ {msg}[/yellow]")
                logger.info("SKIPPED  | %s (already uploaded)", relative)
                continue

            # 2. Check Telegram account file-size limit (2 GiB standard / 4 GiB Premium)
            if size > max_file_size:
                failed += 1
                progress.update(overall_task, advance=size)
                msg = (
                    f"[{index}/{len(files)}] {relative} ({human_bytes(size)}) exceeds "
                    f"your Telegram limit of {human_bytes(max_file_size)}"
                )
                progress.console.print(f"[red]✖ {msg}[/red]")
                logger.error("TOO LARGE | %s | %d bytes", relative, size)
                continue

            # 3. Dry-run preview
            if dry_run:
                msg = f"[{index}/{len(files)}] DRY-RUN would upload: {relative} ({human_bytes(size)})"
                progress.console.print(f"[cyan]{msg}[/cyan]")
                logger.info(msg)
                progress.update(overall_task, advance=size)
                continue

            file_task = progress.add_task(
                f"[{index}/{len(files)}] {relative[:40]}", total=size
            )

            def make_callback(t_id: int):
                def _cb(current: int, total: int) -> None:
                    progress.update(t_id, completed=current)

                return _cb

            while True:
                try:
                    await client.send_file(
                        entity,
                        str(path),
                        caption=relative,
                        parse_mode=None,
                        force_document=True,
                        progress_callback=make_callback(file_task),
                    )

                    # Verify file did not change on disk during upload
                    current_stat = path.stat()
                    if current_stat.st_size != size or current_stat.st_mtime_ns != mtime_ns:
                        raise RuntimeError(f"File changed on disk while uploading: {relative}")

                    _mark_uploaded(state, key, chat_id, source_root, relative, size, mtime_ns)
                    progress.update(overall_task, advance=size)
                    uploaded += 1
                    progress.console.print(
                        f"[green]✔ [{index}/{len(files)}] Uploaded:[/green] {relative}"
                    )
                    logger.info("UPLOADED | %s (%d bytes)", relative, size)
                    break

                except FloodWaitError as exc:
                    wait_msg = f"Rate limit hit on {relative}. Waiting {exc.seconds}s..."
                    progress.console.print(f"[yellow]⏳ {wait_msg}[/yellow]")
                    logger.warning(wait_msg)
                    await asyncio.sleep(exc.seconds + 1)
                    progress.reset(file_task)

                except (RPCError, OSError, RuntimeError) as exc:
                    err_msg = f"Failed to upload {relative}: {exc}"
                    progress.console.print(
                        f"[red]✖ [{index}/{len(files)}] {err_msg}[/red]"
                    )
                    logger.error("FAILED   | %s | Error: %s", relative, exc)
                    progress.update(overall_task, advance=size)
                    failed += 1
                    break

            progress.remove_task(file_task)

    summary = Table(title="Upload Summary", show_header=True, header_style="bold magenta")
    summary.add_column("Metric", style="bold")
    summary.add_column("Count / Path")
    summary.add_row("Uploaded", f"[green]{uploaded}[/green]")
    summary.add_row("Skipped", f"[yellow]{skipped}[/yellow]")
    summary.add_row("Failed", f"[red]{failed}[/red]")
    summary.add_row("Log File", str(log_path))
    console.print(summary)

    logger.info(
        "=== Session finished | Uploaded: %d | Skipped: %d | Failed: %d ===",
        uploaded,
        skipped,
        failed,
    )
    return failed