@echo off
REM ===========================================================================
REM build.bat - builds dist\pragma.exe from the current Pragma source.
REM
REM Run this every time you change Pragma and want a fresh executable.
REM It cleans previous artifacts, ensures PyInstaller is installed, and
REM rebuilds using pragma.spec.
REM
REM IMPORTANT: this must run in a Python environment that has ALL of Pragma's
REM dependencies installed (PyInstaller analyzes them). The script auto-uses
REM the repo venv if present.
REM ===========================================================================

setlocal
cd /d "%~dp0"

REM --- pick the interpreter: prefer the repo venv -----------------------------
set "PY=python"
if exist "venv\Scripts\python.exe"  set "PY=venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
echo [pragma-build] using interpreter: %PY%

REM --- clean previous build ---------------------------------------------------
echo [pragma-build] cleaning build\ and dist\ ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

REM --- ensure PyInstaller is available ----------------------------------------
echo [pragma-build] checking PyInstaller ...
"%PY%" -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 (
    echo [pragma-build] ERROR: could not install PyInstaller
    exit /b 1
)

REM --- build ------------------------------------------------------------------
echo [pragma-build] running PyInstaller ...
"%PY%" -m PyInstaller --noconfirm --clean pragma.spec
if errorlevel 1 (
    echo [pragma-build] ERROR: PyInstaller build failed
    exit /b 1
)

echo.
echo [pragma-build] DONE  -^>  dist\pragma.exe
echo [pragma-build] test it with:  dist\pragma.exe --port 8006
endlocal
