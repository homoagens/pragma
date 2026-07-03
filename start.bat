@echo off
cd /d "%~dp0"
REM agent.run opens the browser itself (works for the exe too); no extra open here.
venv\Scripts\python.exe -m agent.run
