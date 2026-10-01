# Telegram Folder Uploader

A cross-platform terminal application for uploading files from any local folder to a Telegram group or channel.

It uses [Telethon](https://github.com/LonamiWebs/Telethon) for Telegram communication and [uv](https://docs.astral.sh/uv/) for Python project and dependency management.

> **Unofficial project:** This project is not affiliated with Telegram.

---

## ✨ Features

- 📁 Upload files from any local folder
- 📂 Recursively upload files from subdirectories
- 📋 Interactive terminal file selector
- ✅ Select/deselect individual files
- ✅ Select all / deselect all
- 🔄 Invert selection
- 🚀 Upload files as Telegram documents
- 📊 Per-file and overall progress bars
- ⏭️ Automatically skip previously uploaded files
- 🔁 `--force` to re-upload files
- 🧪 `--dry-run` preview mode
- ⏳ Handles Telegram `FloodWait` rate limits
- 🔄 Refreshes Telegram peer information when necessary
- 👥 Select an existing Telegram group/channel
- 🔗 Public Telegram links
- 🔐 Private invite links
- ➕ Create a new private Telegram supergroup
- 🔒 Encrypted local credential vault
- 🔑 Telegram 2-Step Verification support
- 📝 Upload logging
- 💾 Persistent upload state for resumable workflows
- 🐧 Linux support
- 🪟 Windows support

---

# 📁 Project Structure

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
```

### What each module does

| File | Purpose |
|---|---|
| `cli.py` | Command-line interface and application entry point |
| `config.py` | Telegram credentials, encrypted vault, authentication setup |
| `constants.py` | Application paths and file exclusions |
| `files.py` | File discovery, size calculation, and upload-state keys |
| `logger.py` | Upload logging |
| `state.py` | Persistent upload state |
| `telegram.py` | Telegram destination resolution and peer handling |
| `uploader.py` | File selection, upload, progress, retries, and summaries |
| `run.sh` | Convenience launcher for Linux |

---

# 🔄 How the Project Works

The application's workflow is:

```text
Local Folder
     │
     ▼
Scan Files
     │
     ▼
Login to Telegram
     │
     ▼
Choose Destination
     │
     ├── Existing Group / Channel
     ├── Public Link
     ├── Private Invite Link
     └── Create New Private Group
     │
     ▼
Select Files
     │
     ▼
Check Upload State
     │
     ├── Already uploaded → Skip
     └── New/changed file  → Upload
     │
     ▼
Upload to Telegram
     │
     ├── FloodWait → Wait and retry
     └── Peer problem → Refresh peer and retry
     │
     ▼
Save Upload State
     │
     ▼
Show Summary
```

---

# 🧠 How It Works Internally

## 1. File discovery

The application starts from the selected source directory and recursively searches for files.

For example:

```text
My Backup/
├── Documents/
│   ├── resume.pdf
│   └── marks.xlsx
├── Photos/
│   ├── photo1.jpg
│   └── photo2.jpg
└── archive.zip
```

All supported files are discovered recursively.

Common development/configuration data such as `.git`, `.venv`, `.env`, application state, and other protected files are excluded.

---

## 2. Telegram authentication

The application communicates with Telegram using your own Telegram API credentials.

You provide:

```text
api_id
api_hash
phone number
```

Telegram may then request:

```text
login code
2FA password
```

The application does not require Telegram Desktop to be running.

---

## 3. Encrypted credential storage

The project can store Telegram credentials and the active Telethon session in an encrypted vault.

The vault is stored outside the project:

```text
~/.telegram-folder-uploader/
├── vault.enc
├── upload_state.json
└── logs/
```

Your vault password is required to decrypt the saved credentials.

The following information can be protected by the vault:

```text
Telegram API ID
Telegram API Hash
Phone number
Telegram StringSession
```

Keep the vault private.

---

## 4. Destination resolution

The application can resolve several destination types:

### Existing Telegram chats

Select:

```text
📋 Choose from my Telegram Groups / Channels
```

The application retrieves your dialogs and uses Telegram's input-peer information to communicate with the selected chat.

### Public links

Examples:

```text
https://t.me/examplegroup
https://telegram.me/examplegroup
@examplegroup
```

### Private invite links

Examples:

```text
https://t.me/+xxxxxxxx
https://t.me/joinchat/xxxxxxxx
```

When necessary, the application asks before joining the group.

### New private group

The application can create a new private Telegram supergroup using your account.

---

# 🧾 Requirements

## All platforms

You need:

- Python
- `uv`
- A Telegram account
- Telegram API credentials
- Internet access

Telegram Desktop is optional.

---

# 🐍 Python Version

The supported Python range is defined in:

```text
pyproject.toml
```

Use the Python version required by the current project metadata rather than manually installing packages with `pip`.

---

# ⚡ Install `uv`

## Linux

Official installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal or reload your shell configuration.

Verify:

```bash
uv --version
```

Official uv documentation:

https://docs.astral.sh/uv/

---

## Windows PowerShell

Install `uv` using the official Windows installer instructions:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then restart PowerShell and verify:

```powershell
uv --version
```

---

# 📦 Install the Project

Clone the repository:

```bash
git clone https://github.com/rdChandrahaS/telegram-file-uploader.git
cd telegram-file-uploader
```

Then synchronize the project environment:

```bash
uv sync
```

This creates/manages the project's `.venv` and installs the dependencies from `pyproject.toml` and `uv.lock`.

You do not need to run:

```text
pip install -r requirements.txt
```

The project is managed through uv.

---

# ♻️ Force Reinstall / Repair the Environment

If the environment is broken or packages need to be reinstalled:

```bash
uv sync --reinstall
```

You can also force a reinstall when running the application:

```bash
uv run --reinstall telegram-folder-uploader
```

See the official uv CLI documentation:

https://docs.astral.sh/uv/reference/cli/

---

# 🔐 Telegram API Credentials

Go to:

https://my.telegram.org

Open:

```text
API development tools
```

Create an application and obtain:

```text
api_id
api_hash
```

Do **not** publish your real API hash.

For an initial credential setup, the project can accept credentials interactively.

If you use environment variables, a template is provided as:

```text
.env.example
```

Example:

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
```

Never commit your real `.env` file.

---

# ▶️ Running the Application

## Option 1 — Run from the project directory

Linux:

```bash
uv run telegram-folder-uploader
```

Windows PowerShell:

```powershell
uv run telegram-folder-uploader
```

This uses the current directory as the source folder.

---

# 🌍 Run It From Any Folder

This is the recommended workflow for uploading arbitrary folders.

Suppose the project is installed at:

```text
Linux:
~/Desktop/telegram-folder-uploader

Windows:
C:\Users\YourName\Desktop\telegram-folder-uploader
```

And you want to upload:

```text
Linux:
~/Documents/My Backup

Windows:
C:\Users\YourName\Documents\My Backup
```

## Linux

```bash
cd "/home/rdchandrahas/Documents/My Backup"

uv run --project "/home/rdchandrahas/Desktop/telegram-folder-uploader" telegram-folder-uploader
```

## Windows PowerShell

```powershell
cd "C:\Users\YourName\Documents\My Backup"

uv run --project "C:\Users\YourName\Desktop\telegram-folder-uploader" telegram-folder-uploader
```

The current folder becomes the upload source.

---

# ⭐ Install as a Global Command

You can also install the project as a uv-managed command-line tool.

From the project directory:

```bash
uv tool install .
```

After installation, the command should be available as:

```bash
telegram-folder-uploader
```

You can then change to any folder and run:

```bash
cd /path/to/folder
telegram-folder-uploader
```

On Windows PowerShell:

```powershell
cd "C:\path\to\folder"
telegram-folder-uploader
```

If the command is not found after `uv tool install`, run:

```bash
uv tool update-shell
```

Then restart your terminal.

uv's tool installation uses an isolated environment and exposes installed command-line executables separately from normal project environments. citeturn223862search0turn223862search1

---

# 🐧 Linux Convenience Launcher

Linux users also have:

```text
run.sh
```

Make it executable once:

```bash
chmod +x /path/to/telegram-folder-uploader/run.sh
```

Then from any upload folder:

```bash
/path/to/telegram-folder-uploader/run.sh
```

The launcher invokes the project through uv.

---

# 🪟 Windows

Windows does not use `run.sh`.

Use:

```powershell
uv run telegram-folder-uploader
```

from the project directory, or install it globally:

```powershell
uv tool install .
```

After installation:

```powershell
telegram-folder-uploader
```

from any folder.

---

# 🛠️ Command-Line Options

Show help:

```bash
telegram-folder-uploader --help
```

Available options include:

```text
--folder PATH
--group DESTINATION
--all
--force
--dry-run
```

---

## `--folder`

Specify the source folder explicitly.

```bash
telegram-folder-uploader --folder "/path/to/files"
```

Windows:

```powershell
telegram-folder-uploader --folder "C:\Users\YourName\Documents\Files"
```

---

## `--group`

Specify a Telegram destination directly.

```bash
telegram-folder-uploader --group "@examplegroup"
```

or:

```bash
telegram-folder-uploader --group "https://t.me/examplegroup"
```

---

## `--all`

Select every discovered file without opening the interactive file selector.

```bash
telegram-folder-uploader --all
```

---

## `--force`

Re-upload files that are already recorded as uploaded.

```bash
telegram-folder-uploader --force
```

Combine with `--all`:

```bash
telegram-folder-uploader --all --force
```

---

## `--dry-run`

Preview what would be uploaded without sending files:

```bash
telegram-folder-uploader --dry-run
```

This is useful for checking a folder before a real upload.

---

# 🧪 Example Workflows

## Interactive upload

```bash
cd "/home/user/Documents/Backup"

telegram-folder-uploader
```

Then:

```text
1. Unlock/login to Telegram
2. Choose Telegram destination
3. Select files
4. Press Enter
5. Upload starts
6. Summary is displayed
```

---

## Upload everything

```bash
cd "/home/user/Documents/Backup"

telegram-folder-uploader --all
```

---

## Upload a specific folder to a specific group

```bash
telegram-folder-uploader \
  --folder "/home/user/Documents/Backup" \
  --group "@mybackupgroup" \
  --all
```

Windows:

```powershell
telegram-folder-uploader `
  --folder "C:\Users\User\Documents\Backup" `
  --group "@mybackupgroup" `
  --all
```

---

## Preview first

```bash
telegram-folder-uploader \
  --folder "/home/user/Documents/Backup" \
  --dry-run
```

Then perform the real upload:

```bash
telegram-folder-uploader \
  --folder "/home/user/Documents/Backup"
```

---

# 📊 Progress and Upload Status

The application displays both file-level and overall progress.

Example:

```text
[1/10] document.pdf
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

Overall (10 files)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62%
```

After the upload, a summary is shown:

```text
Uploaded
Skipped
Failed
Log File
```

---

# 💾 Resume / Skip System

Completed files are stored in:

```text
~/.telegram-folder-uploader/upload_state.json
```

A file is identified using information including:

```text
destination
source folder
relative path
file size
modification time
```

Therefore, when you run the uploader again:

```text
Already uploaded and unchanged → Skip
New file                    → Upload
Changed file                → Upload
Renamed file                → Upload
```

This allows interrupted or repeated upload sessions to continue without intentionally uploading the same unchanged files again.

Use:

```bash
telegram-folder-uploader --force
```

when you explicitly want to upload them again.

---

# 🛑 Telegram Rate Limits

Telegram can temporarily rate-limit API requests.

When Telethon reports a `FloodWaitError`, the application waits for the requested time and retries the affected operation instead of repeatedly sending requests.

Example:

```text
⏳ Rate limit hit on file.zip.
Waiting 120s...
```

---

# 🔄 Peer Refresh

Some existing Telegram groups can occasionally have peer information that is not immediately usable by the API session.

The application attempts to refresh the selected destination through Telegram's dialog/entity information before uploading.

If Telegram rejects a peer during an upload, the application can refresh the destination and retry the file.

This is intended to handle cases where an older or previously unused group has stale peer information in the local session.

---

# 🔒 Security

Never commit or share:

```text
.env
vault.enc
Telegram session data
Telegram API hash
Telegram login codes
Telegram 2FA password
upload_state.json
```

The repository should contain only safe templates and source code.

The `.gitignore` file is intended to prevent sensitive/local files from being committed.

Before pushing to GitHub, check:

```bash
git status --ignored
```

and:

```bash
git ls-files .env
```

The second command should produce no output when `.env` is not tracked.

---

# 📝 Logs

The normal log file is:

```text
upload-telegram.log
```

inside the source folder.

If the source directory cannot be written, the application can fall back to the application's private log directory:

```text
~/.telegram-folder-uploader/logs/
```

Logs contain upload events, skips, failures, rate-limit messages, and destination-resolution errors.

---

# 🧹 What the Program Skips

The application intentionally avoids common development and sensitive paths such as:

```text
.git
.venv
venv
env
__pycache__
.idea
.vscode
.env
.env.local
.telegram-folder-uploader
upload_state.json
vault.enc
```

Symbolic links are also not followed during recursive file discovery.

---

# 🧰 Development

Install the repository for development:

```bash
uv sync
```

Run the application without installing it globally:

```bash
uv run telegram-folder-uploader
```

Run Python through the project environment:

```bash
uv run python
```

Check the project environment:

```bash
uv sync
```

Compile the source to catch syntax/import compilation problems:

```bash
uv run python -m compileall src
```

Inspect dependency information:

```bash
uv tree
```

---

# ➕ Adding Dependencies

Use uv rather than manually editing dependency lists:

```bash
uv add package-name
```

For example:

```bash
uv add some-package
```

After dependency changes, commit both:

```text
pyproject.toml
uv.lock
```

Do not manually edit `uv.lock`.

---

# 🧪 Before Opening a Pull Request

Run:

```bash
uv sync
uv run python -m compileall src
uv run telegram-folder-uploader --help
```

Also check:

```bash
git status
```

and ensure sensitive files are not staged.

---

# 🤝 Contributing

Contributions are welcome.

You can help by:

- fixing bugs
- improving Telegram peer handling
- improving Windows/Linux compatibility
- improving the TUI
- adding tests
- improving error handling
- improving documentation
- optimizing large-file uploads
- improving state/resume behavior
- suggesting features

## Contribution workflow

1. Fork the repository.
2. Create a branch.

```bash
git checkout -b feature/my-change
```

3. Make your changes.
4. Run the project checks.

```bash
uv sync
uv run python -m compileall src
uv run telegram-folder-uploader --help
```

5. Commit your changes.

```bash
git add .
git commit -m "Describe the change"
```

6. Push your branch.
7. Open a Pull Request.

Please keep pull requests focused and explain what changed and why.

---

# 🐛 Bug Reports

When reporting a bug, include:

```text
Operating system
Python version
uv version
Project version
Command used
Relevant error message
Relevant log output
```

Do **not** post:

```text
API hash
Telegram login code
2FA password
vault password
session data
```

---

# 💡 Feature Requests

Feature ideas are welcome.

Useful future improvements could include:

```text
pause/resume controls
download verification
upload speed configuration
better private /c/ link handling
more destination types
file filters
ignore patterns
unit tests
parallel upload controls
```

---

# ⚠️ Important Usage Notes

This project uses your own Telegram account through Telegram's API.

You are responsible for:

- securing your account credentials
- securing your Telegram session
- having permission to upload the selected files
- having permission to post to the destination
- complying with Telegram's rules and applicable laws

The project does not bypass Telegram permissions.

Being an administrator is not inherently required to upload a file; your Telegram account must simply have whatever permissions Telegram requires for the chosen destination and action.

---

# 📜 License

This repository is intended to be open-source.

Choose and add a license file before publishing the project for general reuse.

A common choice for a small permissively licensed project is the **MIT License**.

If the repository contains a `LICENSE` file, that file is the authoritative license for the project.

Example:

```text
MIT License

Copyright (c) 2026 Rajdeep Debnath

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files, to deal in the Software
without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

Replace the example license with the license actually committed to the repository.

---

# 🙌 Thanks

If you use this project and find it useful, consider:

- ⭐ starring the repository
- 🐛 reporting bugs
- 💡 suggesting improvements
- 🔧 contributing code
- 📖 improving documentation

Every contribution helps make the project better.

---

# 🔗 Project Links

**GitHub:**

https://github.com/rdChandrahaS/telegram-file-uploader

**uv:**

https://docs.astral.sh/uv/

**Telethon:**

https://docs.telethon.dev/

**Telegram API:**

https://my.telegram.org/