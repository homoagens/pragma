# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.
#
# install.ps1 - the Python environment, then `pragma` in every window.
#
#     .\install.ps1              environment + profile line
#     .\install.ps1 -NoProfile   environment only, leave the profile alone
#     .\install.ps1 -Uninstall   remove the profile line (keeps venv and data)
#     .\install.ps1 -Python <exe>  build the venv with that interpreter
#
# The profile edit is written between markers and replaced in place on a
# re-run, so installing twice, or after moving the repository, updates the path
# instead of leaving a second stale import behind.
#
# NOTE: keep this file pure ASCII. PowerShell 5.1 reads BOM-less files as ANSI,
# and one fancy dash or quote silently corrupts the script.

[CmdletBinding()]
param(
    [switch]$NoProfile,
    [switch]$Uninstall,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$Root     = $PSScriptRoot
$Manifest = Join-Path $Root "tools\Pragma.psd1"
$Begin    = "# >>> pragma >>>"
$End      = "# <<< pragma <<<"

function Write-Step([string]$text) { Write-Host "  $text" }
function Write-Done([string]$text) { Write-Host "  $text" -ForegroundColor Green }
function Write-Warn([string]$text) { Write-Host "  $text" -ForegroundColor Yellow }


# --- the profile block --------------------------------------------------------
# CurrentUserAllHosts, not CurrentUserCurrentHost: the same `pragma` should
# exist in a plain console, in Windows Terminal and in an editor's terminal,
# and those are different hosts with different profile files.

function Get-ProfileCandidates {
    # AllHosts first because that is where it belongs: the same `pragma` should
    # exist in a plain console, in Windows Terminal and in an editor's terminal,
    # and those are different hosts with different profile files. CurrentHost is
    # searched too because that is where a hand-written line usually lands.
    @($PROFILE.CurrentUserAllHosts, $PROFILE.CurrentUserCurrentHost) |
        Where-Object { $_ } | Select-Object -Unique
}

function Find-ExistingInstall {
    # Returns @{ Path; Managed } for the first profile that mentions Pragma, so
    # a line the operator wrote by hand is adopted rather than duplicated - two
    # imports in two profiles both load, and the stale one wins nothing but
    # confusion the day the repository moves.
    foreach ($p in Get-ProfileCandidates) {
        if (-not (Test-Path $p)) { continue }
        $lines = @(Get-Content -Path $p)
        if ($lines | Where-Object { $_.TrimEnd() -eq $Begin }) {
            return @{ Path = $p; Managed = $true }
        }
        if ($lines | Where-Object { $_ -match 'Import-Module.*Pragma\.psd1' }) {
            return @{ Path = $p; Managed = $false }
        }
    }
    return $null
}

function Remove-Block([string[]]$lines) {
    $out  = @()
    $skip = $false
    foreach ($l in $lines) {
        if ($l.TrimEnd() -eq $Begin) { $skip = $true;  continue }
        if ($l.TrimEnd() -eq $End)   { $skip = $false; continue }
        if ($skip) { continue }
        # An unmanaged import of any Pragma manifest goes too: it is the line
        # this block replaces, and leaving it would import the module twice.
        if ($l -match 'Import-Module.*Pragma\.psd1') { continue }
        $out += $l
    }
    return $out
}

function Set-ProfileBlock([switch]$Remove) {
    $found = Find-ExistingInstall
    $path  = if ($found) { $found.Path } else { $PROFILE.CurrentUserAllHosts }
    $dir   = Split-Path -Parent $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

    $lines = @()
    if (Test-Path $path) { $lines = @(Get-Content -Path $path) }
    $kept = @(Remove-Block $lines)

    if ($Remove) {
        if (-not $found) { Write-Step "profile: nothing of Pragma's was there"; return }
        # Trailing blank lines left by the removal are noise in a file the user
        # also edits by hand.
        while ($kept.Count -gt 0 -and -not $kept[-1].Trim()) {
            $kept = $kept[0..($kept.Count - 2)]
        }
        Set-Content -Path $path -Value $kept -Encoding UTF8
        Write-Done "profile: Pragma removed from $path"
        return
    }

    $block = @($Begin,
               "Import-Module `"$Manifest`"",
               $End)
    if ($kept.Count -gt 0 -and $kept[-1].Trim()) { $kept += "" }
    Set-Content -Path $path -Value ($kept + $block) -Encoding UTF8

    if (-not $found)              { Write-Done "profile: added to $path" }
    elseif ($found.Managed)       { Write-Done "profile: updated in $path" }
    else { Write-Done "profile: adopted the line you had written in $path" }
}


# --- run ----------------------------------------------------------------------

Write-Host ""
Write-Host "  Pragma" -ForegroundColor Cyan
Write-Host "  $Root" -ForegroundColor DarkGray
Write-Host ""

if ($Uninstall) {
    Set-ProfileBlock -Remove
    Write-Host ""
    Write-Step "The virtual environment, the registry and every memory are untouched."
    Write-Step "Delete them by hand if that is what you want:"
    Write-Host "    $Root\venv" -ForegroundColor DarkGray
    Write-Host "    $env:USERPROFILE\.pragma" -ForegroundColor DarkGray
    Write-Host ""
    return
}

# 1. Python environment
#
# ErrorActionPreference is lowered around the native calls on purpose. Under
# 'Stop', PowerShell 5.1 turns anything an executable writes to stderr into a
# terminating error even when it exited 0 - and pip announces new versions of
# itself on stderr, so a successful install failed the script. The exit code is
# the truth about a native command, and it is what is checked.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $py = Join-Path $Root "venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        # Not simply `python`. Three things go wrong with that on a machine
        # nobody has prepared:
        #
        #   - on a shared one the first python on PATH can belong to another
        #     account, because the machine PATH is searched before the user's -
        #     so fixing your own PATH never puts yours in front - and the venv
        #     then inherits that installation's pip configuration too;
        #   - on a clean Windows 11 `python` exists but is a stub that opens the
        #     Microsoft Store, so it resolves and then does nothing useful;
        #   - an interpreter old enough to fail on this code builds a venv
        #     perfectly well, and the failure surfaces much later as something
        #     that looks unrelated.
        #
        # So candidates are PROBED rather than trusted: each is asked its own
        # version and path, and the first that is new enough wins.
        $minor = 10        # README says 3.10+; the annotations need it
        $candidates = @()
        if ($Python) {
            if (-not (Test-Path $Python)) { throw "no such interpreter: $Python" }
            $candidates += ,@($Python, @())
        } else {
            if (Get-Command py -ErrorAction SilentlyContinue) {
                $candidates += ,@("py", @("-3"))
            }
            if (Get-Command python -ErrorAction SilentlyContinue) {
                $candidates += ,@("python", @())
            }
        }

        $chosen = $null
        $seen   = @()
        foreach ($c in $candidates) {
            $exe, $pre = $c
            $probe = $null
            try {
                $probe = & $exe @pre -c "import sys;print('%d.%d|%s' % (sys.version_info[0], sys.version_info[1], sys.executable))" 2>$null
            } catch { }
            if (-not $probe) { continue }          # the Store stub answers nothing
            $ver, $path = "$probe".Trim() -split '\|', 2
            $mj, $mn = $ver -split '\.'
            $seen += "$ver at $path"
            if ([int]$mj -ge 3 -and [int]$mn -ge $minor) {
                $chosen = @{ Exe = $exe; Pre = $pre; Version = $ver; Path = $path }
                break
            }
        }

        if (-not $chosen) {
            Write-Host ""
            if ($seen.Count -gt 0) {
                Write-Warn "no Python 3.$minor or newer was found. Seen:"
                foreach ($s in $seen) { Write-Host "    $s" -ForegroundColor DarkGray }
            } else {
                Write-Warn "no usable Python was found on this machine."
            }
            Write-Host ""
            Write-Step "Install one for your account:"
            Write-Host "    winget install Python.Python.3.12 --scope user" -ForegroundColor DarkGray
            Write-Step "or point this at one you already have:"
            Write-Host "    .\install.ps1 -Python C:\path\to\python.exe" -ForegroundColor DarkGray
            Write-Host ""
            # A machine without Python is an expected state, not a crash: the
            # message above IS the outcome, and a PowerShell stack trace under
            # it only buries the two lines worth reading.
            $ErrorActionPreference = $prevEAP
            exit 1
        }

        # Say which one, always. This whole class of confusion is invisible
        # until someone prints the path.
        Write-Step "creating the virtual environment with Python $($chosen.Version):"
        Write-Host "    $($chosen.Path)" -ForegroundColor DarkGray
        & $chosen.Exe @($chosen.Pre) -m venv (Join-Path $Root "venv")
        if ($LASTEXITCODE -ne 0) {
            throw "creating the virtual environment failed. Pass -Python <path to python.exe>."
        }
    }
    Write-Step "installing dependencies..."
    & (Join-Path $Root "venv\Scripts\pip.exe") install -q --disable-pip-version-check `
        -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
} finally {
    $ErrorActionPreference = $prevEAP
}
Write-Done "environment ready"

# 2. A repository unzipped from a download carries the mark of the internet on
# every file, and PowerShell refuses to load a marked module. Cloning does not,
# so this usually finds nothing - and costs nothing when it does.
Get-ChildItem -Path (Join-Path $Root "tools") -Filter "Pragma.ps*1" |
    ForEach-Object { Unblock-File -Path $_.FullName -ErrorAction SilentlyContinue }

# 3. The profile
if ($NoProfile) {
    Write-Step "profile: left alone (-NoProfile). To do it by hand, add:"
    Write-Host "    Import-Module `"$Manifest`"" -ForegroundColor DarkGray
} else {
    Set-ProfileBlock
}

# 4. Say whether it will actually load
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -in @('Restricted', 'AllSigned')) {
    Write-Host ""
    Write-Warn "execution policy is '$policy', which will block the profile."
    Write-Warn "Allow local scripts for your user with:"
    Write-Host "    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" -ForegroundColor DarkGray
}

Write-Host ""
Write-Step "Open a NEW terminal, then:"
Write-Host "    pragma -Register -Name <short-name>   " -NoNewline
Write-Host "register the folder you are in" -ForegroundColor DarkGray
Write-Host "    pragma                                " -NoNewline
Write-Host "the menu" -ForegroundColor DarkGray
Write-Host ""
Write-Step "Not pointed at an LLM server yet? Type /configure once inside."
Write-Host ""
