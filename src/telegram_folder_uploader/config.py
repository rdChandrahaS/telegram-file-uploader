from __future__ import annotations

import base64
import dataclasses
import json
import os
import stat
from pathlib import Path

import questionary
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from rich.console import Console
from rich.panel import Panel

from .constants import (
    CONFIG_DIR,
    ENV_FILENAME,
    GLOBAL_ENV_PATH,
    SESSION_PATH,
    VAULT_PATH,
)

console = Console()
PBKDF2_ITERATIONS = 600_000
PROJECT_ROOT_ENV = Path(__file__).resolve().parents[2] / ENV_FILENAME


@dataclasses.dataclass
class AuthConfig:
    api_id: int
    api_hash: str
    phone: str
    save_for_future: bool
    vault_password: str | None = None
    session_string: str | None = None


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


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """Derives a 256-bit Fernet key from a password using 600,000 SHA-256 iterations."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _mask_phone(phone: str) -> str:
    clean = phone.strip()
    if len(clean) <= 5:
        return "***"
    return f"{clean[:3]}{'*' * (len(clean) - 5)}{clean[-2:]}"


def _mask_api_id(api_id: int) -> str:
    s = str(api_id)
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


def remove_legacy_plaintext_files() -> None:
    """Deletes any old unencrypted global .env or SQLite .session files."""
    for path in (
        GLOBAL_ENV_PATH,
        SESSION_PATH,
        SESSION_PATH.with_name(f"{SESSION_PATH.name}-journal"),
    ):
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def save_encrypted_vault(
    api_id: int,
    api_hash: str,
    phone: str,
    session_string: str,
    password: str,
    account_name: str | None = None,
) -> None:
    """Encrypts credentials + Telegram StringSession into ~/.telegram-folder-uploader/vault.enc."""
    ensure_config_dir()
    salt = os.urandom(16)
    key = _derive_fernet_key(password, salt)
    fernet = Fernet(key)

    secret_payload = json.dumps(
        {
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "session_string": session_string,
        }
    ).encode("utf-8")

    encrypted_token = fernet.encrypt(secret_payload)
    masked_phone = _mask_phone(phone)
    account_hint = f"{masked_phone} ({account_name})" if account_name else masked_phone

    vault_wrapper = {
        "version": 1,
        "account_hint": account_hint,
        "api_id_hint": _mask_api_id(api_id),
        "salt": base64.b64encode(salt).decode("ascii"),
        "ciphertext": encrypted_token.decode("ascii"),
    }

    temp_vault = VAULT_PATH.with_suffix(".tmp")
    temp_vault.write_text(json.dumps(vault_wrapper, indent=2), encoding="utf-8")
    temp_vault.replace(VAULT_PATH)
    _chmod_private(VAULT_PATH, stat.S_IRUSR | stat.S_IWUSR)

    # Remove any old plaintext global .env or .session files
    remove_legacy_plaintext_files()


def _read_vault_metadata() -> dict[str, str] | None:
    if not VAULT_PATH.exists():
        return None
    try:
        data = json.loads(VAULT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "salt" in data and "ciphertext" in data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


async def _unlock_saved_vault(vault_meta: dict[str, str]) -> AuthConfig | None:
    salt = base64.b64decode(vault_meta["salt"])
    ciphertext = vault_meta["ciphertext"].encode("ascii")

    for attempt in range(1, 4):
        password = await questionary.password(
            f"🔒 Enter Vault Password to unlock credentials (attempt {attempt}/3):"
        ).ask_async()
        if password is None:
            raise KeyboardInterrupt

        try:
            key = _derive_fernet_key(password, salt)
            decrypted = Fernet(key).decrypt(ciphertext)
            payload = json.loads(decrypted.decode("utf-8"))
            console.print("[green]✔ Vault unlocked successfully![/green]")
            return AuthConfig(
                api_id=int(payload["api_id"]),
                api_hash=str(payload["api_hash"]),
                phone=str(payload["phone"]),
                save_for_future=True,
                vault_password=password,
                session_string=payload.get("session_string"),
            )
        except (InvalidToken, KeyError, ValueError, json.JSONDecodeError):
            console.print("[bold red]✖ Incorrect vault password.[/bold red]")

    console.print("[yellow]Too many failed attempts. Switching to fresh credentials entry...[/yellow]")
    return None


async def _prompt_new_vault_password() -> str:
    while True:
        pwd1 = await questionary.password(
            "Create a Vault Password / PIN to encrypt your credentials:",
            validate=lambda v: len(v) >= 4 or "Password must be at least 4 characters",
        ).ask_async()
        if pwd1 is None:
            raise KeyboardInterrupt

        pwd2 = await questionary.password("Confirm Vault Password / PIN:").ask_async()
        if pwd2 is None:
            raise KeyboardInterrupt

        if pwd1 == pwd2:
            return pwd1
        console.print("[red]✖ Passwords do not match. Please try again.[/red]")


async def _prompt_fresh_credentials() -> AuthConfig:
    console.print(
        Panel(
            "Get your API credentials at [cyan underline]https://my.telegram.org[/cyan underline] -> [bold]API development tools[/bold]",
            title="🔑 Enter Telegram Credentials",
            border_style="cyan",
        )
    )

    api_id_raw = await questionary.text(
        "Enter your Telegram API ID (numbers only):",
        validate=lambda val: val.strip().isdigit() or "API ID must be a valid integer",
    ).ask_async()
    if not api_id_raw:
        raise KeyboardInterrupt

    api_hash = await questionary.password(
        "Enter your Telegram API Hash:",
        validate=lambda val: bool(val.strip()) or "API Hash cannot be empty",
    ).ask_async()
    if not api_hash:
        raise KeyboardInterrupt

    phone = await questionary.text(
        "Enter your Telegram Phone Number (with country code, e.g. +919876543210):",
        validate=lambda val: bool(val.strip()) or "Phone number cannot be empty",
    ).ask_async()
    if not phone:
        raise KeyboardInterrupt

    save_choice = await questionary.confirm(
        "Do you want to encrypt and save these credentials for future use?",
        default=True,
    ).ask_async()
    if save_choice is None:
        raise KeyboardInterrupt

    vault_password = None
    if save_choice:
        vault_password = await _prompt_new_vault_password()

    return AuthConfig(
        api_id=int(api_id_raw.strip()),
        api_hash=api_hash.strip(),
        phone=phone.strip(),
        save_for_future=save_choice,
        vault_password=vault_password,
        session_string=None,
    )


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


async def load_credentials(source_root: Path) -> AuthConfig:
    ensure_config_dir()

    # 1. Check if an Encrypted Vault exists
    vault_meta = _read_vault_metadata()
    if vault_meta:
        account_hint = vault_meta.get("account_hint", "Saved Account")
        api_id_hint = vault_meta.get("api_id_hint", "****")

        choice = await questionary.select(
            "Encrypted Telegram vault found. What would you like to do?",
            choices=[
                questionary.Choice(
                    f"🔒 Unlock saved credentials [Account: {account_hint} | API ID: {api_id_hint}]",
                    value="saved",
                ),
                questionary.Choice(
                    "🆕 Enter new / fresh credentials",
                    value="fresh",
                ),
            ],
        ).ask_async()

        if choice is None:
            raise KeyboardInterrupt

        if choice == "saved":
            unlocked = await _unlock_saved_vault(vault_meta)
            if unlocked is not None:
                return unlocked

        return await _prompt_fresh_credentials()

    # 2. Check if legacy plaintext .env credentials exist and offer one-click encryption migration
    local_dotenv = load_dotenv(source_root / ENV_FILENAME)
    project_dotenv = load_dotenv(PROJECT_ROOT_ENV)
    global_dotenv = load_dotenv(GLOBAL_ENV_PATH)

    api_id_raw = (
        os.environ.get("TELEGRAM_API_ID")
        or local_dotenv.get("TELEGRAM_API_ID")
        or global_dotenv.get("TELEGRAM_API_ID")
        or project_dotenv.get("TELEGRAM_API_ID")
    )
    api_hash = (
        os.environ.get("TELEGRAM_API_HASH")
        or local_dotenv.get("TELEGRAM_API_HASH")
        or global_dotenv.get("TELEGRAM_API_HASH")
        or project_dotenv.get("TELEGRAM_API_HASH")
    )
    saved_phone = (
        os.environ.get("TELEGRAM_PHONE")
        or local_dotenv.get("TELEGRAM_PHONE")
        or global_dotenv.get("TELEGRAM_PHONE")
        or project_dotenv.get("TELEGRAM_PHONE")
    )

    if api_id_raw and api_hash and api_id_raw.strip().isdigit():
        api_id = int(api_id_raw.strip())
        api_hash = api_hash.strip()
        phone_label = _mask_phone(saved_phone) if saved_phone else "Phone not saved yet"

        choice = await questionary.select(
            "Plaintext .env credentials detected. What would you like to do?",
            choices=[
                questionary.Choice(
                    f"🛡️ Use & upgrade to Encrypted Vault [Account: {phone_label} | API ID: {_mask_api_id(api_id)}]",
                    value="migrate",
                ),
                questionary.Choice(
                    "🆕 Enter new / fresh credentials",
                    value="fresh",
                ),
            ],
        ).ask_async()

        if choice is None:
            raise KeyboardInterrupt

        if choice == "fresh":
            return await _prompt_fresh_credentials()

        if not saved_phone:
            saved_phone = await questionary.text(
                "Enter your Telegram Phone Number (with country code, e.g. +91...):",
                validate=lambda val: bool(val.strip()) or "Phone number cannot be empty",
            ).ask_async()
            if not saved_phone:
                raise KeyboardInterrupt
            saved_phone = saved_phone.strip()

        save_encrypted = await questionary.confirm(
            "Encrypt and save these credentials in a password-protected vault for future use?",
            default=True,
        ).ask_async()
        if save_encrypted is None:
            raise KeyboardInterrupt

        vault_password = await _prompt_new_vault_password() if save_encrypted else None
        return AuthConfig(
            api_id=api_id,
            api_hash=api_hash,
            phone=saved_phone,
            save_for_future=save_encrypted,
            vault_password=vault_password,
            session_string=None,
        )

    # 3. No credentials anywhere -> Prompt fresh
    console.print("\n[bold yellow]No saved Telegram credentials found.[/bold yellow]")
    return await _prompt_fresh_credentials()