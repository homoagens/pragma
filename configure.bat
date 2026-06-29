@echo off
REM ===========================================================================
REM configure.bat - interactive setup of Pragma's .env (Windows).
REM
REM Pipeline: install -> configure -> start.
REM Thin wrapper: all logic lives in configure.py (robust, cross-platform).
REM Prefers the repo venv's Python so `requests` is available for the health
REM check.
REM ===========================================================================

setlocal
cd /d "%~dp0"

set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

"%PY%" configure.py
endlocal
