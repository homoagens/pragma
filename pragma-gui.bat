@echo off
rem pragma-gui.bat - the browser interface.
rem
rem Pragma's default is the terminal harness: `pragma` in any PowerShell
rem window, or start.bat if the module is not installed yet. This launches
rem the web UI instead, which is the older way in and still the one to use
rem when you want the thread list and the panes.
rem
rem agent.run opens the browser itself; no extra open here.
cd /d "%~dp0"
venv\Scripts\python.exe -m agent.run %*
