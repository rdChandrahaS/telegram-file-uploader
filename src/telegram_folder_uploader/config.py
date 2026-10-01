from __future__ import annotations

import os
import stat
from pathlib import Path
import questionary
from rich.console import Console

from .constants import CONFIG_DIR, ENV_FILENAME, GLOBAL_ENV_PATH

console = Console()


def _chmod_private(path: Path, mode: int) -> None:
    if os.name != "posix" or not path.exists():
        return
    try:
        path.chmod(mode)
    except OSError:
        pass


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _chmod_private(CONFIG_DIR, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def protect_session(session_path: Path) -> None:
    """Locks Down Telethon session files to chmod 600 on POSIX systems."""
    _chmod_private(session_path, stat.S_IRUSR | stat.S_IWUSR)
    journal = session_path.with_name(f"{session_path.name}-journal")
    _chmod_private(journal, stat.S_IRUSR | stat.S_IWUSR)


def load_dotenv(path: Path) -> dict[str, str]:
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


def load_credentials(source_root: Path) -> tuple[int, str]:
    ensure_config_dir()
    local_dotenv = load_dotenv(source_root / ENV_FILENAME)
    global_dotenv = load_dotenv(GLOBAL_ENV_PATH)

    api_id_raw = (
        os.environ.get("TELEGRAM_API_ID")
        or local_dotenv.get("TELEGRAM_API_ID")
        or global_dotenv.get("TELEGRAM_API_ID")
    )
    api_hash = (
        os.environ.get("TELEGRAM_API_HASH")
        or local_dotenv.get("TELEGRAM_API_HASH")
        or global_dotenv.get("TELEGRAM_API_HASH")
    )

    if not api_id_raw or not api_hash:
        console.print(
            "\n[bold yellow]Telegram API credentials not found.[/bold yellow]\n"
            "Get yours at [cyan underline]https://my.telegram.org[/cyan underline] -> API development tools.\n"
        )
        if not api_id_raw:
            api_id_raw = questionary.text(
                "Enter your Telegram API ID:",
                validate=lambda val: val.strip().isdigit() or "API ID must be an integer",
            ).ask()
        if not api_hash:
            api_hash = questionary.password("Enter your Telegram API Hash:").ask()

    if not api_id_raw or not api_hash:
        raise ValueError("Telegram API credentials are required.")

    api_id = int(api_id_raw.strip())
    api_hash = api_hash.strip()

    if not GLOBAL_ENV_PATH.exists():
        try:
            GLOBAL_ENV_PATH.write_text(
                "# Telegram API credentials - keep this file private\n"
                f"TELEGRAM_API_ID={api_id}\n"
                f"TELEGRAM_API_HASH={api_hash}\n",
                encoding="utf-8",
            )
            _chmod_private(GLOBAL_ENV_PATH, stat.S_IRUSR | stat.S_IWUSR)
            console.print(f"[green]✔ Saved API credentials globally to {GLOBAL_ENV_PATH}[/green]")
        except OSError as exc:
            console.print(f"[yellow]Warning: could not save global .env: {exc}[/yellow]")

    return api_id, api_hash