@echo off
rem install.bat - the double-click way in.
rem
rem Thin wrapper: install.ps1, in the repository root, is the implementation,
rem so the two entry points cannot drift. It sets up the Python environment
rem AND puts `pragma` in every PowerShell window.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\install.ps1" %*
