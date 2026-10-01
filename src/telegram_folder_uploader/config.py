from __future__ import annotations

import os
import stat
from pathlib import Path

from .constants import CONFIG_DIR, ENV_FILENAME


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
    env_path = source_root / ENV_FILENAME
    dotenv = load_dotenv(env_path)
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

    if not env_path.exists():
        try:
            env_path.write_text(
                "# Telegram API credentials - keep this file private\n"
                f"TELEGRAM_API_ID={api_id}\n"
                f"TELEGRAM_API_HASH={api_hash}\n",
                encoding="utf-8",
            )
            _chmod_private(env_path, stat.S_IRUSR | stat.S_IWUSR)
            print(f"Saved API credentials to {env_path}")
        except OSError as exc:
            print(f"Warning: could not save .env: {exc}")

    return api_id, api_hash
