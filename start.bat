@echo off
cd /d "%~dp0"
start "" /b cmd /c "timeout /t 2 /nobreak > nul && start http://localhost:8006"
venv\Scripts\python.exe -m agent.run
