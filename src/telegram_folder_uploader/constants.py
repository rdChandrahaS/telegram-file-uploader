from pathlib import Path

APP_NAME = "telegram-folder-uploader"
CONFIG_DIR = Path.home() / f".{APP_NAME}"
SESSION_PATH = CONFIG_DIR / "telegram.session"
STATE_PATH = CONFIG_DIR / "upload_state.json"
GLOBAL_ENV_PATH = CONFIG_DIR / ".env"
ENV_FILENAME = ".env"
LOG_FILENAME = "upload-telegram.log"

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
    "Thumbs.db",
    ".env",
    ".env.local",
    "telegram_uploader.py",
    "telegram-folder-uploader",
    LOG_FILENAME,
}