@echo off
rem start.bat - the terminal harness, for a window that has not got `pragma`.
rem
rem After install.ps1 there is a better way in: `pragma` exists in every
rem PowerShell window and needs no path. This is the one that works before
rem that line reaches a profile, and from a double-click.
rem
rem The browser interface has moved to pragma-gui.bat.
cd /d "%~dp0"
powershell -NoExit -ExecutionPolicy Bypass -Command ^
  "Import-Module '%~dp0tools\Pragma.psd1'; pragma"
