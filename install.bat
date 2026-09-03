@echo off
rem Thin wrapper: install.ps1 is the implementation, so the two entry
rem points cannot drift. It sets up the Python environment AND puts
rem `pragma` in every PowerShell window.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
