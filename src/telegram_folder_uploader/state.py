from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from rich.console import Console

from .constants import CONFIG_DIR, STATE_PATH

console = Console()


def _private(path: Path) -> None:
    if os.name != "posix" or not path.exists():
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        corrupt_backup = STATE_PATH.with_suffix(".corrupt.json")
        try:
            STATE_PATH.replace(corrupt_backup)
            _private(corrupt_backup)
        except OSError:
            pass
        console.print(
            f"[bold yellow]⚠ Warning:[/bold yellow] State file was corrupted and backed up to {corrupt_backup}."
        )
        return {}
    except OSError:
        return {}


def save_state(state: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STATE_PATH)
    _private(STATE_PATH)