# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.
#
# Pragma.psm1 - one command, many projects.
#
# Import this once from your PowerShell profile and `pragma` exists in every
# window, with no paths to type:
#
#     Import-Module <repo>\tools\Pragma.psd1
#
# WHAT THIS IS AND IS NOT. It chooses a project, sets this window's environment
# for it, and gets out of the way: you are left at your own prompt, where
# `pragma -Chat`, git and python coexist. It is deliberately not a shell of its
# own - that would be tidier and would make the tool useless to a developer and
# unusable in batch.
#
# NOTE: keep this file pure ASCII. PowerShell 5.1 reads BOM-less files as ANSI,
# and one fancy dash or quote silently corrupts the script.

Set-StrictMode -Version 2.0

$script:PragmaHome     = Join-Path $env:USERPROFILE ".pragma"
$script:RegistryPath   = Join-Path $script:PragmaHome "registry.json"
$script:ProjectsRoot   = Join-Path $script:PragmaHome "projects"
$script:RepoRoot       = Split-Path -Parent $PSScriptRoot
$script:SessionScript  = Join-Path $PSScriptRoot "pragma-session.ps1"
$script:BriefScript    = Join-Path $PSScriptRoot "pragma_brief.py"
$script:Python         = Join-Path $script:RepoRoot "venv\Scripts\python.exe"


# --- the registry -------------------------------------------------------------
# One file, one entry per project. It holds what pragma.ps1 used to hold: a
# session file was never only an entry point, it carried the per-project model
# profile, budgets and sampling. Losing those in the move would leave a memory
# that behaves differently the day after, in ways that surface late.

function script:Read-Registry {
    # Callers wrap the result in @() as well: PowerShell unrolls a one-element
    # array on return, and under StrictMode the resulting scalar has no .Count.
    if (-not (Test-Path $script:RegistryPath)) { return @() }
    try {
        $raw = Get-Content -Raw -Encoding UTF8 $script:RegistryPath
        if (-not $raw -or -not $raw.Trim()) { return @() }
        $data = $raw | ConvertFrom-Json
        if ($null -eq $data) { return @() }
        return @($data)
    } catch {
        Write-Host "pragma: the registry is unreadable ($($_.Exception.Message))" -ForegroundColor Red
        Write-Host "        $script:RegistryPath"
        return @()
    }
}

function script:Write-Registry([object[]]$entries) {
    $dir = Split-Path -Parent $script:RegistryPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    # Always a JSON array, even with one entry: ConvertTo-Json would emit a
    # bare object for a single item, and a reader in another language would
    # then see a different shape depending on how many projects exist.
    $json = ConvertTo-Json -InputObject ([object[]]$entries) -Depth 6
    if ($entries.Count -eq 0) { $json = "[]" }
    # WriteAllText with an explicit BOM-less encoding: Set-Content -Encoding
    # UTF8 emits a BOM on PowerShell 5.1, and json.loads chokes on it.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($script:RegistryPath, $json, $utf8)
}

function script:Get-EntryByName([string]$name) {
    Read-Registry | Where-Object { $_.name -eq $name } | Select-Object -First 1
}

function script:Get-EntryByPath([string]$path) {
    # One folder, one project: walking up means `pragma` inside a subdirectory
    # of a registered workspace still knows which memory it means, and never
    # has to ask.
    try { $p = (Resolve-Path -LiteralPath $path -ErrorAction Stop).Path } catch { return $null }
    $entries = @(Read-Registry)
    while ($p) {
        foreach ($e in $entries) {
            if ($e.workspace -and ($e.workspace.TrimEnd('\','/') -ieq $p.TrimEnd('\','/'))) { return $e }
        }
        $parent = Split-Path -Parent $p
        if ($parent -eq $p) { break }
        $p = $parent
    }
    return $null
}

function script:Get-LastOpened {
    Read-Registry | Where-Object { $_.last_opened } |
        Sort-Object { [datetime]$_.last_opened } -Descending | Select-Object -First 1
}


# --- the briefing -------------------------------------------------------------

function script:Get-Brief($entry) {
    if (-not (Test-Path $script:Python)) { return $null }
    $store = Join-Path $entry.memory "episodes"
    $since = ""
    if ($entry.PSObject.Properties.Name -contains 'last_opened' -and $entry.last_opened) {
        $since = $entry.last_opened
    }
    try {
        $json = & $script:Python $script:BriefScript $store --since $since 2>$null
        if (-not $json) { return $null }
        return ($json | ConvertFrom-Json)
    } catch { return $null }
}

function script:Show-Brief($entry, $brief) {
    Write-Host ""
    Write-Host "  Pragma" -ForegroundColor Cyan -NoNewline
    Write-Host ("  ." + (Get-Date -Format "  dddd d MMMM, HH:mm")) -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  project   " -ForegroundColor DarkGray -NoNewline
    Write-Host $entry.name -ForegroundColor White
    if ($brief -and $brief.ok) {
        $mem = "{0} episodes active, {1} dormant, {2} beliefs" -f `
               $brief.episodes_active, $brief.episodes_dormant, $brief.beliefs
        Write-Host "  memory    " -ForegroundColor DarkGray -NoNewline
        Write-Host $mem
        if ($null -ne $brief.away_days) {
            $away = if ($brief.away_days -lt 1) { "today" }
                    elseif ($brief.away_days -lt 2) { "1 day" }
                    else { "{0:N0} days" -f $brief.away_days }
            Write-Host "  away for  " -ForegroundColor DarkGray -NoNewline
            Write-Host $away -NoNewline
            Write-Host ("    tau {0}" -f $brief.tau) -ForegroundColor DarkGray
        }
        $lines = @()
        if ($brief.went_dormant_n -gt 0) {
            $lines += "{0} episode(s) went dormant" -f $brief.went_dormant_n
        }
        if ($brief.revised_n -gt 0) {
            foreach ($r in $brief.revised) { $lines += "belief revised - `"$r`"" }
        }
        if ($brief.fading -gt 0) {
            $lines += "{0} episode(s) close to fading" -f $brief.fading
        }
        if ($brief.last_goal) { $lines += "last time you were on: " + $brief.last_goal }
        if ($lines.Count) {
            Write-Host ""
            Write-Host "  Since you left" -ForegroundColor DarkGray
            foreach ($l in $lines) { Write-Host "    $l" }
        }
    } elseif ($brief -and -not $brief.ok) {
        Write-Host "  memory    " -ForegroundColor DarkGray -NoNewline
        Write-Host $brief.error -ForegroundColor DarkYellow
    }
    Write-Host ""
}


# --- the menu -----------------------------------------------------------------
# Arrow keys with a highlighted row, redrawn in place. The accelerator letters
# stay because a menu is good for discovery and bad for repetition, and this is
# opened daily: enter does the frequent thing and typing a task skips the menu
# entirely.

function script:Show-Menu([object[]]$items, [string]$hint) {
    $sel = 0
    $top = $null
    while ($true) {
        if ($null -eq $top) {
            $top = $Host.UI.RawUI.CursorPosition
            # Reserve the rows now so a menu drawn at the bottom of the window
            # does not scroll away from the position just recorded.
            for ($i = 0; $i -lt $items.Count + 2; $i++) { Write-Host "" }
            $Host.UI.RawUI.CursorPosition = $top
        }
        $Host.UI.RawUI.CursorPosition = $top
        for ($i = 0; $i -lt $items.Count; $i++) {
            $it = $items[$i]
            $pad = (" " * 68)
            if ($i -eq $sel) {
                Write-Host ("  > " + $it.label + $pad).Substring(0, 70) -ForegroundColor Black -BackgroundColor Cyan
            } else {
                Write-Host ("    " + $it.label + $pad).Substring(0, 70) -NoNewline
                Write-Host ""
            }
        }
        Write-Host ""
        Write-Host ("  " + $hint + (" " * 60)).Substring(0, 70) -ForegroundColor DarkGray

        $key = [Console]::ReadKey($true)
        switch ($key.Key) {
            'UpArrow'   { $sel = ($sel - 1 + $items.Count) % $items.Count }
            'DownArrow' { $sel = ($sel + 1) % $items.Count }
            'Enter'     { return $items[$sel] }
            'Escape'    { return $null }
            'Q'         { return $null }
            default {
                $ch = "$($key.KeyChar)".ToLower()
                foreach ($it in $items) {
                    if ($it.key -and $it.key -eq $ch) { return $it }
                }
            }
        }
    }
}


# --- activation ---------------------------------------------------------------

function script:Enable-Project($entry) {
    if (-not (Test-Path $entry.workspace)) {
        Write-Host "pragma: the workspace of '$($entry.name)' is gone: $($entry.workspace)" -ForegroundColor Red
        return $false
    }
    if (-not (Test-Path $entry.memory)) {
        New-Item -ItemType Directory -Force -Path $entry.memory | Out-Null
    }

    $settings = @{}
    if ($entry.PSObject.Properties.Name -contains 'settings' -and $entry.settings) {
        foreach ($p in $entry.settings.PSObject.Properties) { $settings[$p.Name] = $p.Value }
    }
    # The session script is the whole existing command surface. Handing it a
    # synthesised $PragmaSession reuses it instead of growing a second copy of
    # the same logic, and Workspace/Memory travel explicitly because in this
    # model they are no longer two subfolders of one session root.
    $s = @{ Name = $entry.name; Repo = $script:RepoRoot
            Root = $entry.workspace
            Workspace = $entry.workspace; Memory = $entry.memory }
    foreach ($k in $settings.Keys) { $s[$k] = $settings[$k] }
    $global:PragmaSession = $s

    . $script:SessionScript

    $entries = @(Read-Registry)
    foreach ($e in $entries) {
        if ($e.name -eq $entry.name) {
            $e.last_opened = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
    }
    Write-Registry $entries
    return $true
}


# --- registration -------------------------------------------------------------

function script:New-Project([string]$name, [string]$workspace) {
    $entries = @(Read-Registry)
    if ($entries | Where-Object { $_.name -eq $name }) {
        Write-Host "pragma: a project named '$name' already exists" -ForegroundColor Red
        return $null
    }
    $ws = (Resolve-Path -LiteralPath $workspace).Path
    # One folder, one project - and nesting counts. An exact-match test alone
    # let a subdirectory of a registered workspace become a second project,
    # after which walking up from a deeper path finds whichever is nearer:
    # exactly the ambiguity this rule exists to remove.
    $wsN = $ws.TrimEnd('\','/')
    foreach ($e in $entries) {
        if (-not $e.workspace) { continue }
        $other = $e.workspace.TrimEnd('\','/')
        $sep = [IO.Path]::DirectorySeparatorChar
        $oc = [StringComparison]::OrdinalIgnoreCase
        if ($other -ieq $wsN) {
            Write-Host "pragma: that folder is already project '$($e.name)'" -ForegroundColor Red
            return $null
        }
        if ($wsN.StartsWith($other + $sep, $oc)) {
            Write-Host "pragma: that folder is inside project '$($e.name)'" -ForegroundColor Red
            Write-Host "        $other" -ForegroundColor DarkGray
            return $null
        }
        if ($other.StartsWith($wsN + $sep, $oc)) {
            Write-Host "pragma: project '$($e.name)' lives inside that folder" -ForegroundColor Red
            Write-Host "        $other" -ForegroundColor DarkGray
            return $null
        }
    }
    # The store never lives inside the workspace: a workspace is a folder you
    # already own and often a git repository, and a memory directory inside it
    # is one forgotten .gitignore away from publishing personal episodes.
    $memory = Join-Path $script:ProjectsRoot $name
    New-Item -ItemType Directory -Force -Path (Join-Path $memory "episodes") | Out-Null
    $entry = [pscustomobject]@{
        name        = $name
        workspace   = $ws
        memory      = $memory
        last_opened = $null
        settings    = [pscustomobject]@{}
    }
    Write-Registry ($entries + $entry)
    Write-Host "pragma: registered '$name'" -ForegroundColor Green
    Write-Host "        workspace  $ws" -ForegroundColor DarkGray
    Write-Host "        memory     $memory" -ForegroundColor DarkGray
    return $entry
}


# --- the entry point ----------------------------------------------------------

function Start-Pragma {
    [CmdletBinding()]
    param(
        [string]$Project,
        [switch]$List,
        [switch]$Register,
        [string]$Name
    )

    if ($List) {
        $entries = @(Read-Registry)
        if (-not $entries -or $entries.Count -eq 0) {
            Write-Host "pragma: no projects registered yet. Use  pragma -Register -Name <name>"
            return
        }
        foreach ($e in $entries) {
            $when = if ($e.last_opened) { $e.last_opened } else { "never opened" }
            Write-Host ("  {0,-18} {1}" -f $e.name, $e.workspace)
            Write-Host ("  {0,-18} {1}" -f "", $when) -ForegroundColor DarkGray
        }
        return
    }

    if ($Register) {
        $n = if ($Name) { $Name } else { Split-Path -Leaf (Get-Location).Path }
        $entry = New-Project $n (Get-Location).Path
        if ($entry) { Enable-Project $entry | Out-Null }
        return
    }

    if ($Project) {
        $entry = Get-EntryByName $Project
        if (-not $entry) {
            Write-Host "pragma: no project named '$Project'" -ForegroundColor Red
            return
        }
        Enable-Project $entry | Out-Null
        return
    }

    # Never prompt a machine. A batch script that hits an invisible menu waits
    # forever, and the error it should have got is one line away.
    if ([Console]::IsInputRedirected) {
        Write-Host "pragma: no project selected and no terminal to ask." -ForegroundColor Red
        Write-Host "        Pass -Project <name> or set PRAGMA_PROJECT."
        return
    }

    $entries = @(Read-Registry)
    $here = Get-EntryByPath (Get-Location).Path
    $current = if ($here) { $here } else { Get-LastOpened }

    if (-not $current -and $entries.Count -eq 0) {
        Write-Host ""
        Write-Host "  Pragma" -ForegroundColor Cyan
        Write-Host "  No projects yet." -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  Register the folder you are in:" -ForegroundColor DarkGray
        Write-Host "    pragma -Register -Name <name>"
        Write-Host ""
        return
    }

    $brief = if ($current) { Get-Brief $current } else { $null }
    if ($current) { Show-Brief $current $brief }

    $items = @()
    if ($current) {
        $items += [pscustomobject]@{ key = ''; label = "continue here"; action = 'continue' }
        $items += [pscustomobject]@{ key = 'c'; label = "continue, straight into chat"; action = 'chat' }
    }
    $items += [pscustomobject]@{ key = 'n'; label = "new project"; action = 'new' }
    if ($entries.Count -gt 0) {
        $items += [pscustomobject]@{ key = 'p'; label = "switch project"; action = 'switch' }
    }

    $choice = Show-Menu $items "enter select . up/down move . esc quit"
    Write-Host ""
    if (-not $choice) { return }

    switch ($choice.action) {
        'continue' { Enable-Project $current | Out-Null }
        'chat'     { if (Enable-Project $current) { pragma -Chat } }
        'new' {
            $n = Read-Host "  name for this project"
            if (-not $n) { return }
            $w = Read-Host "  workspace folder (blank = $((Get-Location).Path))"
            if (-not $w) { $w = (Get-Location).Path }
            $entry = New-Project $n $w
            if ($entry) { Enable-Project $entry | Out-Null }
        }
        'switch' {
            $picks = @()
            foreach ($e in $entries) {
                $picks += [pscustomobject]@{ key = ''; label = ("{0,-18} {1}" -f $e.name, $e.workspace); entry = $e }
            }
            Write-Host "  Which project" -ForegroundColor DarkGray
            $p = Show-Menu $picks "enter select . esc cancel"
            Write-Host ""
            if ($p) { Enable-Project $p.entry | Out-Null }
        }
    }
}

Set-Alias -Name pragma -Value Start-Pragma
Export-ModuleMember -Function Start-Pragma -Alias pragma
