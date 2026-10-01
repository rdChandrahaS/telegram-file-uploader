@echo off
setlocal
set "PROJECT_DIR=%~dp0"
REM Remove trailing backslash so it doesn't escape the closing quote
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

uv run --project "%PROJECT_DIR%" telegram-folder-uploader %*