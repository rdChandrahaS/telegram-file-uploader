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
from telethon.errors import (
    ChannelInvalidError,
    ChatIdInvalidError,
    FloodWaitError,
    PeerIdInvalidError,
    RPCError,
)
from telethon.utils import get_peer_id

from .files import (
    file_key,
    folder_size,
    human_bytes,
)
from .state import load_state, save_state
from .telegram import (
    display_destination,
    get_valid_input_peer,
)

console = Console()


async def interactive_select_files(
    source_root: Path,
    all_files: list[Path],
    chat_id: int | str,
    force: bool = False,
) -> list[Path]:
    """
    Interactive checkbox selector.

    Files already recorded as uploaded are unchecked by default.
    --force checks everything.
    """
    state = load_state()

    choices: list[questionary.Choice] = []

    for path in all_files:
        rel = path.relative_to(
            source_root
        ).as_posix()

        try:
            stat_result = path.stat()
            size = stat_result.st_size
            mtime_ns = stat_result.st_mtime_ns
            size_str = human_bytes(size)
            key = file_key(
                chat_id,
                source_root,
                path,
                size,
                mtime_ns,
            )
            already_uploaded = (
                state.get(key, {}).get("status") == "uploaded"
            )
        except OSError:
            size_str = "? B"
            already_uploaded = False

        status = ( " [already uploaded]" if already_uploaded else "" )

        choices.append(
            questionary.Choice(
                title=(
                    f"{rel} "
                    f"({size_str})"
                    f"{status}"
                ),
                value=path,
                checked=(
                    True
                    if force
                    else not already_uploaded
                ),
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

    selected = await questionary.checkbox(
        f"Select files to upload from "
        f"'{source_root.name}':",
        choices=choices,
    ).ask_async()

    if selected is None:
        raise KeyboardInterrupt

    return selected


def _mark_uploaded(
    state: dict[str, Any],
    key: str,
    chat_id: int | str,
    source_root: Path,
    relative: str,
    size: int,
    mtime_ns: int,
) -> None:
    """Record a successfully uploaded file."""
    state[key] = {
        "status": "uploaded",
        "chat_id": str(chat_id),
        "source_root": source_root.as_posix(),
        "relative_path": relative,
        "size": size,
        "mtime_ns": mtime_ns,
    }

    save_state(state)

async def _refresh_destination_peer(
    client: TelegramClient,
    entity: Any,
    destination_name: str,
    logger: logging.Logger,
) -> Any:
    """
    Refresh the selected destination through Telegram dialogs.

    This is used when Telegram rejects an InputPeer during sending.
    """
    console.print(
        "[yellow]⚠ Telegram rejected the destination peer. "
        "Refreshing group information...[/yellow]"
    )

    logger.warning(
        "Refreshing destination peer: %s",
        destination_name,
    )

    try:
        refreshed_peer = await get_valid_input_peer(
            client,
            entity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Destination refresh failed: %s",
            exc,
        )

        raise RuntimeError(
            f"Could not refresh Telegram destination "
            f"'{destination_name}': {exc}"
        ) from exc

    console.print(
        "[green]✔ Destination peer refreshed successfully."
        "[/green]"
    )

    logger.info(
        "Destination peer refreshed successfully: %s",
        destination_name,
    )

    return refreshed_peer


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
    """
    Upload files to a Telegram destination.

    Returns:
        Number of failed files.
    """
    state = load_state()

    chat_id = get_peer_id(entity)

    destination_name = display_destination(
        entity
    )

    uploaded = 0
    skipped = 0
    failed = 0

    total_bytes = folder_size(files)

    console.print(
        Panel(
            f"[bold]Source Folder:[/bold] "
            f"{source_root}\n"
            f"[bold]Destination:[/bold]   "
            f"{destination_name}\n"
            f"[bold]Selected:[/bold]      "
            f"{len(files)} file(s) "
            f"({human_bytes(total_bytes)})\n"
            f"[bold]Size Limit:[/bold]    "
            f"{human_bytes(max_file_size)} per file\n"
            f"[bold]Log File:[/bold]      "
            f"{log_path}",
            title="🚀 Upload Session",
            border_style="green",
        )
    )

    logger.info(
        "=== Starting upload session | "
        "Folder: %s | Destination: %s (%s) | "
        "Files selected: %d ===",
        source_root,
        destination_name,
        chat_id,
        len(files),
    )

    if not files:
        console.print(
            "[yellow]No files selected. Exiting.[/yellow]"
        )

        logger.info(
            "No files selected by user."
        )

        return 0

    # ---------------------------------------------------------------
    # Resolve a fresh InputPeer BEFORE uploading anything.
    # ---------------------------------------------------------------
    input_peer: Any | None = None

    if not dry_run:
        try:
            console.print(
                "[cyan]Refreshing destination peer...[/cyan]"
            )

            input_peer = await get_valid_input_peer(
                client,
                entity,
            )

            console.print(
                "[green]✔ Destination peer ready.[/green]"
            )

            logger.info(
                "Destination InputPeer resolved successfully."
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Could not resolve destination '%s': %s",
                destination_name,
                exc,
            )

            raise RuntimeError(
                f"Could not resolve a valid Telegram "
                f"input peer for '{destination_name}': {exc}"
            ) from exc

    progress = Progress(
        SpinnerColumn(),
        TextColumn(
            "[bold blue]{task.description}"
        ),
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
            f"[bold green]Overall "
            f"({len(files)} files)",
            total=total_bytes,
        )

        for index, path in enumerate(
            files,
            start=1,
        ):
            relative = path.relative_to(
                source_root
            ).as_posix()

            # -------------------------------------------------------
            # Capture file metadata before uploading.
            # -------------------------------------------------------
            try:
                stat_result = path.stat()

                size = stat_result.st_size
                mtime_ns = stat_result.st_mtime_ns

            except OSError as exc:
                msg = (
                    f"[{index}/{len(files)}] "
                    f"Cannot stat {relative}: {exc}"
                )

                progress.console.print(
                    f"[red]✖ {msg}[/red]"
                )

                logger.error(msg)

                failed += 1
                continue

            key = file_key(
                chat_id,
                source_root,
                path,
                size,
                mtime_ns,
            )

            # -------------------------------------------------------
            # 1. Skip already uploaded.
            # -------------------------------------------------------
            if (
                not force
                and state.get(key, {}).get("status")
                == "uploaded"
            ):
                skipped += 1

                progress.update(
                    overall_task,
                    advance=size,
                )

                progress.console.print(
                    "[yellow]⏭ "
                    f"[{index}/{len(files)}] "
                    f"Skipped: {relative} "
                    "(already uploaded)[/yellow]"
                )

                logger.info(
                    "SKIPPED | %s (already uploaded)",
                    relative,
                )

                continue

            # -------------------------------------------------------
            # 2. Check per-file Telegram limit.
            # -------------------------------------------------------
            if size > max_file_size:
                failed += 1

                progress.update(
                    overall_task,
                    advance=size,
                )

                msg = (
                    f"[{index}/{len(files)}] "
                    f"{relative} "
                    f"({human_bytes(size)}) exceeds "
                    f"your Telegram limit of "
                    f"{human_bytes(max_file_size)}"
                )

                progress.console.print(
                    f"[red]✖ {msg}[/red]"
                )

                logger.error(
                    "TOO LARGE | %s | %d bytes",
                    relative,
                    size,
                )

                continue

            # -------------------------------------------------------
            # 3. Dry run.
            # -------------------------------------------------------
            if dry_run:
                msg = (
                    f"[{index}/{len(files)}] "
                    f"DRY-RUN would upload: "
                    f"{relative} "
                    f"({human_bytes(size)})"
                )

                progress.console.print(
                    f"[cyan]{msg}[/cyan]"
                )

                logger.info(msg)

                progress.update(
                    overall_task,
                    advance=size,
                )

                continue

            assert input_peer is not None

            # -------------------------------------------------------
            # 4. File progress bar.
            # -------------------------------------------------------
            file_task = progress.add_task(
                f"[{index}/{len(files)}] "
                f"{relative[:40]}",
                total=size,
            )

            def make_callback(
                task_id: int,
            ):
                def _callback(
                    current: int,
                    total: int,
                ) -> None:
                    progress.update(
                        task_id,
                        completed=current,
                    )

                return _callback

            peer_refresh_attempted = False

            try:
                while True:
                    try:
                        # ------------------------------------------------
                        # Send the file using the refreshed InputPeer.
                        # ------------------------------------------------
                        await client.send_file(
                            input_peer,
                            str(path),
                            caption=relative,
                            parse_mode=None,
                            force_document=True,
                            progress_callback=(
                                make_callback(
                                    file_task
                                )
                            ),
                        )

                        # ------------------------------------------------
                        # Confirm the local file did not change.
                        # ------------------------------------------------
                        current_stat = path.stat()

                        if (
                            current_stat.st_size != size
                            or current_stat.st_mtime_ns
                            != mtime_ns
                        ):
                            raise RuntimeError(
                                "File changed on disk while "
                                f"uploading: {relative}"
                            )

                        # ------------------------------------------------
                        # Only mark uploaded after send_file succeeds.
                        # ------------------------------------------------
                        _mark_uploaded(
                            state,
                            key,
                            chat_id,
                            source_root,
                            relative,
                            size,
                            mtime_ns,
                        )

                        progress.update(
                            overall_task,
                            advance=size,
                        )

                        uploaded += 1

                        progress.console.print(
                            f"[green]✔ "
                            f"[{index}/{len(files)}] "
                            f"Uploaded:[/green] "
                            f"{relative}"
                        )

                        logger.info(
                            "UPLOADED | %s (%d bytes)",
                            relative,
                            size,
                        )

                        break

                    # ---------------------------------------------------
                    # Telegram rate limit.
                    # ---------------------------------------------------
                    except FloodWaitError as exc:
                        wait_msg = (
                            f"Rate limit hit on "
                            f"{relative}. "
                            f"Waiting {exc.seconds}s..."
                        )

                        progress.console.print(
                            f"[yellow]⏳ "
                            f"{wait_msg}[/yellow]"
                        )

                        logger.warning(
                            wait_msg
                        )

                        await asyncio.sleep(
                            exc.seconds + 1
                        )

                        progress.reset(
                            file_task
                        )

                    # ---------------------------------------------------
                    # Peer problem.
                    #
                    # Refresh once and retry this file.
                    # ---------------------------------------------------
                    except (
                        PeerIdInvalidError,
                        ChannelInvalidError,
                        ChatIdInvalidError,
                    ) as exc:
                        if peer_refresh_attempted:
                            raise RuntimeError(
                                "Telegram rejected the "
                                "destination peer even after "
                                "refreshing it: "
                                f"{exc}"
                            ) from exc

                        peer_refresh_attempted = True

                        input_peer = (
                            await _refresh_destination_peer(
                                client,
                                entity,
                                destination_name,
                                logger,
                            )
                        )

                        progress.reset(
                            file_task
                        )

                    # ---------------------------------------------------
                    # Other upload failure.
                    # ---------------------------------------------------
                    except (
                        RPCError,
                        OSError,
                        RuntimeError,
                    ) as exc:
                        err_msg = (
                            f"Failed to upload "
                            f"{relative}: {exc}"
                        )

                        progress.console.print(
                            f"[red]✖ "
                            f"[{index}/{len(files)}] "
                            f"{err_msg}[/red]"
                        )

                        logger.error(
                            "FAILED | %s | Error: %s",
                            relative,
                            exc,
                        )

                        progress.update(
                            overall_task,
                            advance=size,
                        )

                        failed += 1

                        break

            finally:
                progress.remove_task(
                    file_task
                )

    # ---------------------------------------------------------------
    # Summary.
    # ---------------------------------------------------------------
    summary = Table(
        title="Upload Summary",
        show_header=True,
        header_style="bold magenta",
    )

    summary.add_column(
        "Metric",
        style="bold",
    )

    summary.add_column(
        "Count / Path"
    )

    summary.add_row(
        "Uploaded",
        f"[green]{uploaded}[/green]",
    )

    summary.add_row(
        "Skipped",
        f"[yellow]{skipped}[/yellow]",
    )

    summary.add_row(
        "Failed",
        f"[red]{failed}[/red]",
    )

    summary.add_row(
        "Log File",
        str(log_path),
    )

    console.print(summary)

    logger.info(
        "=== Session finished | "
        "Uploaded: %d | Skipped: %d | Failed: %d ===",
        uploaded,
        skipped,
        failed,
    )

    return failed