@echo off
REM Double-click this file to start the bot.
REM It finds Python for you even if Python is not on your PATH.

cd /d "%~dp0"
title Gacha bot

REM Ask each candidate where its real python.exe lives, so paths with spaces work.
set "PY="
for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY for %%v in (313 312 311 310) do (
    if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
)

if not defined PY (
    echo.
    echo Could not find Python on this computer.
    echo Install it from https://www.python.org/downloads/
    echo and tick "Add Python to PATH" on the first screen.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PY%
echo.

REM Install discord.py the first time only.
"%PY%" -c "import discord" >nul 2>&1
if errorlevel 1 (
    echo First run - installing what the bot needs. This takes a minute...
    echo.
    "%PY%" -m pip install -r requirements.txt
    echo.
)

"%PY%" bot.py

echo.
echo The bot has stopped. Close this window, or run this file again to restart.
pause
