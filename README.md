# Telegram Folder Uploader

An interactive Terminal UI (TUI) project that uploads files from any local folder to a Telegram group or channel using Telethon.

## Project Structure

```text
telegram-folder-uploader/
├── pyproject.toml
├── uv.lock
├── README.md
├── .env.example
├── .gitignore
├── run.sh
└── src/
    └── telegram_folder_uploader/
        ├── __init__.py
        ├── cli.py
        ├── config.py
        ├── constants.py
        ├── files.py
        ├── logger.py
        ├── state.py
        ├── telegram.py
        └── uploader.py

## Linux + uv setup

Install `uv` first if it is not already installed.

From the project directory:

```bash
uv sync
```

This creates and manages the project's `.venv` automatically.

## Telegram API credentials

Create a Telegram API application at:

https://my.telegram.org

Open **API development tools** and obtain your `api_id` and `api_hash`.

You can create a `.env` in the folder you are uploading from:

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
```

The program also prompts for missing values and can save them to `.env`.

Keep `.env` and the Telegram session private.

## Run it from any folder

After setup, the simplest project-local command is:

```bash
cd /path/to/the/folder/you/want/to/upload
uv run --project /path/to/telegram-folder-uploader telegram-folder-uploader
```

That command uses the **current directory** as the upload source.

You can also specify the folder explicitly:

```bash
uv run --project /path/to/telegram-folder-uploader telegram-folder-uploader --folder /path/to/files
```

Or specify a Telegram destination directly:

```bash
uv run --project /path/to/telegram-folder-uploader telegram-folder-uploader --group https://t.me/examplegroup
```

### Optional Linux launcher

The included `run.sh` can also be used:

```bash
chmod +x /path/to/telegram-folder-uploader/run.sh
cd /path/to/the/folder/you/want/to/upload
/path/to/telegram-folder-uploader/run.sh
```

`run.sh` uses `uv` and keeps your current directory as the source folder.

## First run

On the first run, Telegram may ask for your phone number, login code, and two-step verification password.

The Telegram session is stored outside the source folder:

```text
~/.telegram-folder-uploader/telegram.session
```

Do not publish or share it.

## Destination selection

Paste one of these:

```text
https://t.me/public_group
@public_group
```

For a private invite link:

```text
https://t.me/+xxxxxxxxxxxx
```

The program will ask before joining a private invite when you are not already a member.

Press Enter at the destination prompt to choose a group/channel from your existing Telegram chats.

## Resume behavior

Completed uploads are recorded at:

```text
~/.telegram-folder-uploader/upload_state.json
```

A file is considered already uploaded when its relative path, size, and modification time match the stored state. Changing or renaming a file causes it to be treated as a new upload.

## Dry run

Preview what would be uploaded without sending anything:

```bash
uv run --project /path/to/telegram-folder-uploader telegram-folder-uploader --dry-run
```

## Notes

Files are uploaded as Telegram documents. The uploader works recursively through subdirectories, skips common development/configuration directories, shows per-file progress, and waits when Telegram returns a FloodWait rate-limit response.
