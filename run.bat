@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Discord Audio Bot

echo ========================================================
echo               Discord Audio Bot Launcher
echo ========================================================
echo.

:: 1. Check if virtual environment Python already exists
if exist ".venv\Scripts\python.exe" goto :RUN_BOT

:: 2. If virtual environment does not exist, find Python to create it
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=python"
    goto :CREATE_VENV
)

where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=py"
    goto :CREATE_VENV
)

echo [ERROR] Python was not found in your system PATH.
echo Please install Python 3.10 or higher from https://www.python.org/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:CREATE_VENV
echo [*] Creating virtual environment...
%PY_CMD% -m venv .venv
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [*] Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:RUN_BOT
:: Ensure .env exists
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Creating .env from .env.example...
        copy .env.example .env >nul
    )
)

echo [*] Starting Audio Bot...
echo ========================================================
.venv\Scripts\python.exe main.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [!] Bot process terminated with error code %ERRORLEVEL%.
)

echo.
pause
