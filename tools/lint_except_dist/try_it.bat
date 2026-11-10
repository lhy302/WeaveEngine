@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set PYCMD=
py -3.12 --version >nul 2>&1 && set PYCMD=py -3.12
if not defined PYCMD (
    python --version >nul 2>&1 && set PYCMD=python
)
if not defined PYCMD (
    echo [ERROR] Python not found. Please install Python 3.8+ or add to PATH.
    echo.
    pause
    exit /b 1
)
%PYCMD% "%~dp0try_it.py"
echo.
pause