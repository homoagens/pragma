# monitor.ps1 - open the endpoint dashboard.
#
#     .\tools\monitor.ps1
#
# Shows, for each endpoint you add: whether it answers, which model it really
# has loaded, its context size, the sampling it applies to whatever a request
# omits, and what the last request actually used. Read-only - four GETs, nothing
# to click that starts or stops anything.
#
# Type a bare port (8100) or host:port. Over an SSH tunnel every remote server
# arrives on a local port, so the address stops identifying the machine: the
# model name in the panel is what tells you where you really are.
#
# NOTE: keep this file pure ASCII - PowerShell 5.1 reads BOM-less files as ANSI,
# and a fancy dash or quote silently corrupts the script.

$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $repo "venv\Scripts\python.exe" }
if (-not (Test-Path $py)) {
    Write-Host "Python environment not found in $repo" -ForegroundColor Red
    Write-Host "Run .\install.ps1 in the Pragma repository first."
    exit 1
}

# pythonw when available, so the dashboard does not keep a console window
# tethered to it and closing the terminal does not close the monitor.
Start-Process -FilePath $py `
    -ArgumentList (Join-Path $PSScriptRoot "endpoint_monitor.py") `
    -WorkingDirectory $repo
