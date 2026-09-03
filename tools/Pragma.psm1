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
# WHAT THIS IS. `pragma` opens a menu and stays there: an action runs and
# returns to it, and quitting the menu leaves the program, the way a terminal
# harness behaves. The window keeps the project's environment afterwards, so
# `pragma -Chat` and the rest still work at the prompt.
#
# This reverses the first design, which set the window up and got out of the
# way. The argument for that shape was that a loop would be unusable to a
# developer and impossible in batch; only the second half held. Batch never
# reaches the menu - a project named by -Project or PRAGMA_PROJECT skips it,
# and a redirected stdin refuses it - so the loop costs the batch path
# nothing.
#
# NOTE: keep this file pure ASCII. PowerShell 5.1 reads BOM-less files as ANSI,
# and one fancy dash or quote silently corrupts the script.

# No Set-StrictMode here. It is dynamically scoped and the session script is
# dot-sourced into this module's session state, so the functions it defines
# inherit it - and pragma -Sampling, written years before, reads absent
# properties on purpose to mean "not sent". Under strict mode those throw,
# and the table printed 0.0 for values that were never sent at all.

$script:PragmaHome     = Join-Path $env:USERPROFILE ".pragma"
$script:RegistryPath   = Join-Path $script:PragmaHome "registry.json"
$script:ProjectsRoot   = Join-Path $script:PragmaHome "projects"
$script:RepoRoot       = Split-Path -Parent $PSScriptRoot
$script:SessionScript  = Join-Path $PSScriptRoot "pragma-session.ps1"
$script:BriefScript    = Join-Path $PSScriptRoot "pragma_brief.py"
$script:EndpointScript = Join-Path $PSScriptRoot "pragma_endpoint.py"
$script:Python         = Join-Path $script:RepoRoot "venv\Scripts\python.exe"

# When this file was read. PowerShell loads a module once per session and keeps
# it, so editing the file - or pulling a new one - changes nothing in a window
# that is already open. That is correct behaviour and a genuinely confusing one:
# the fix looks like a missing feature, twice over. Comparing this against the
# file's timestamp turns "it is not there" into a line that says why.
$script:LoadedAt = try { (Get-Item $PSCommandPath).LastWriteTimeUtc } catch { $null }

function script:Test-Stale {
    if (-not $script:LoadedAt) { return $false }
    try { return ((Get-Item $PSCommandPath).LastWriteTimeUtc -gt $script:LoadedAt) }
    catch { return $false }
}

function script:Show-StaleNotice {
    if (-not (Test-Stale)) { return }
    Write-Host ""
    Write-Host "  This window is running an older copy of Pragma." -ForegroundColor Yellow
    Write-Host "  The file changed after it was loaded, and PowerShell keeps a" -ForegroundColor DarkGray
    Write-Host "  module for the life of the session." -ForegroundColor DarkGray
    Write-Host "    Import-Module `"$(Join-Path $PSScriptRoot 'Pragma.psd1')`" -Force" -ForegroundColor DarkGray
    Write-Host "  or open a new terminal." -ForegroundColor DarkGray
    Write-Host ""
}


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

function script:New-Page {
    # Each view replaces the last rather than scrolling under it. Guarded
    # because a host without a console cannot clear one, and a briefing is
    # never worth failing over.
    try { Clear-Host } catch { }
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
        # Same colours as the settings panel: whether there is anything to talk
        # to is the one thing worth finding without reading. Keyed on the
        # backend state rather than on the model name, because a server that
        # answers without reporting a model is up - and colouring that red said
        # the opposite of what had just been measured.
        $isUp = ($brief.backend -eq "up")
        Write-Host "  serving   " -ForegroundColor DarkGray -NoNewline
        if ($isUp) {
            $what = if ($brief.serving) { $brief.serving } else { "up (model not reported)" }
            Write-Host $what -ForegroundColor Green
        } else {
            # Two lines, as in the settings panel: the state belongs on the
            # serving line, the reason underneath. Inline it was truncated
            # mid-word and pushed the line past the width of the page.
            Write-Host "backend down" -ForegroundColor Red
            $why = "$($brief.backend)" -replace '^down - ', ''
            if ($why -and $why -ne "up") {
                Write-Host ("            " + $why) -ForegroundColor DarkGray
            }
        }
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
    # Drawn once, then redrawn over itself. The first attempt recorded the
    # cursor BEFORE drawing and returned to it, which a console that scrolls
    # invalidates: every keypress appended a fresh copy of the menu instead of
    # replacing it. Deriving the top from where the drawing actually ENDED
    # survives scrolling, because the end moves with the content.
    #
    # [Console] rather than $Host.UI.RawUI: the .NET API drives the console
    # directly and does not depend on virtual-terminal sequences being enabled,
    # which on a classic PowerShell 5.1 window they may not be.
    $sel   = 0
    $lines = $items.Count + 2          # the rows, a blank, the hint
    # Never the last column: writing into it wraps, which silently adds a row
    # and puts the count the redraw depends on permanently out of step.
    $width = 78
    try { $width = [Math]::Max(24, [Math]::Min(78, [Console]::BufferWidth - 1)) } catch { }
    $first = $true

    while ($true) {
        if (-not $first) {
            $y = [Math]::Max(0, [Console]::CursorTop - $lines)
            try { [Console]::SetCursorPosition(0, $y) } catch { }
        }
        for ($i = 0; $i -lt $items.Count; $i++) {
            $row = ("  " + $(if ($i -eq $sel) { ">" } else { " " }) + " " + $items[$i].label)
            if ($row.Length -gt $width) { $row = $row.Substring(0, $width) }
            $row = $row.PadRight($width)
            if ($i -eq $sel) {
                Write-Host $row -ForegroundColor Black -BackgroundColor Cyan
            } else {
                Write-Host $row
            }
        }
        Write-Host ("".PadRight($width))
        $tip = "  " + $hint
        if ($tip.Length -gt $width) { $tip = $tip.Substring(0, $width) }
        Write-Host $tip.PadRight($width) -ForegroundColor DarkGray
        $first = $false

        $key = [Console]::ReadKey($true)
        switch ($key.Key) {
            'UpArrow'   { $sel = ($sel - 1 + $items.Count) % $items.Count }
            'DownArrow' { $sel = ($sel + 1) % $items.Count }
            'Enter'     { return $items[$sel] }
            'Escape'    { return $null }
            default {
                $ch = "$($key.KeyChar)".ToLower()
                if ($ch -eq 'q') { return $null }
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
        try {
            New-Item -ItemType Directory -Force -ErrorAction Stop `
                     -Path $entry.memory | Out-Null
        } catch {
            Write-Host "pragma: the store of '$($entry.name)' cannot be opened" -ForegroundColor Red
            Write-Host "        $($entry.memory)" -ForegroundColor DarkGray
            Write-Host "        $($_.Exception.Message)" -ForegroundColor DarkGray
            return $false
        }
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
            Workspace = $entry.workspace; Memory = $entry.memory
            Backups = (Join-Path $script:PragmaHome (Join-Path "backups" $entry.name)) }
    foreach ($k in $settings.Keys) { $s[$k] = $settings[$k] }
    $global:PragmaSession = $s
    # Names the project this window is on. -Set reads it, and it is the same
    # variable the batch contract uses to skip the menu.
    $env:PRAGMA_PROJECT = $entry.name

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

function script:Test-ProjectName([string]$name) {
    # The name becomes a directory under ~/.pragma/projects, so anything that
    # is really a path has to be refused here rather than producing something
    # like ...\projects\C:\Users\tu\test and failing four calls later.
    # The message names the parameter that WAS wanted: passing a folder to
    # -Name is the obvious mistake, because "register this folder" reads like
    # it should take the folder.
    if (-not $name -or -not $name.Trim()) {
        Write-Host "pragma: a project needs a name" -ForegroundColor Red
        return $false
    }
    $bad = [IO.Path]::GetInvalidFileNameChars()
    if ($name.IndexOfAny($bad) -ge 0 -or $name -match '[\\/:]') {
        Write-Host "pragma: '$name' is not a name, it looks like a path" -ForegroundColor Red
        Write-Host "        pragma -Register -Name <short-name> [-Workspace <folder>]" -ForegroundColor DarkGray
        Write-Host "        the folder defaults to the one you are in." -ForegroundColor DarkGray
        return $false
    }
    if ($name -in @('.', '..')) {
        Write-Host "pragma: '$name' is not a usable name" -ForegroundColor Red
        return $false
    }
    return $true
}

function script:Show-WhatAWorkspaceIs([string]$ws) {
    # The first refusal anyone meets, and the first version of it only said
    # what the folder was NOT. Someone registering their first project has no
    # reason to know the word "workspace" yet, so the refusal has to teach it -
    # and end with a line that can be typed.
    Write-Host "        A workspace is the one folder the agent reads and writes in:" -ForegroundColor DarkGray
    Write-Host "        a project, a notes folder. Not everything you own." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "        Make one and register it:" -ForegroundColor DarkGray
    $example = Join-Path $ws "notes"
    Write-Host "          mkdir `"$example`"" -ForegroundColor DarkGray
    Write-Host "          pragma -Register -Name notes -Workspace `"$example`"" -ForegroundColor DarkGray
}

function script:Test-Workspace([string]$ws) {
    # A workspace is a folder you work in, not the whole of your home or a
    # drive. Registering one of those points the agent at everything you own.
    $n = $ws.TrimEnd('\','/')
    $root = [IO.Path]::GetPathRoot($n).TrimEnd('\','/')
    if ($n -ieq $root) {
        Write-Host "pragma: '$ws' is a whole drive." -ForegroundColor Red
        Show-WhatAWorkspaceIs $n
        return $false
    }
    $guarded = @{}
    if ($env:USERPROFILE) { $guarded[$env:USERPROFILE] = "home" }
    $desk = [Environment]::GetFolderPath('Desktop')
    if ($desk) { $guarded[$desk] = "Desktop" }
    foreach ($p in $guarded.Keys) {
        if ($n -ieq $p.TrimEnd([char]92, [char]47)) {
            Write-Host "pragma: that is your $($guarded[$p]) folder." -ForegroundColor Red
            Show-WhatAWorkspaceIs $n
            return $false
        }
    }
    return $true
}

function script:New-Project([string]$name, [string]$workspace) {
    if (-not (Test-ProjectName $name)) { return $null }
    $entries = @(Read-Registry)
    if ($entries | Where-Object { $_.name -eq $name }) {
        Write-Host "pragma: a project named '$name' already exists" -ForegroundColor Red
        return $null
    }
    try {
        $ws = (Resolve-Path -LiteralPath $workspace -ErrorAction Stop).Path
    } catch {
        Write-Host "pragma: no such folder: $workspace" -ForegroundColor Red
        return $null
    }
    if (-not (Test-Workspace $ws)) { return $null }
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
    try {
        # -ErrorAction Stop, and the registry written only afterwards: this
        # failed once and the code carried on regardless, leaving an entry
        # pointing at a store that was never created.
        New-Item -ItemType Directory -Force -ErrorAction Stop `
                 -Path (Join-Path $memory "episodes") | Out-Null
    } catch {
        Write-Host "pragma: could not create the store at $memory" -ForegroundColor Red
        Write-Host "        $($_.Exception.Message)" -ForegroundColor DarkGray
        return $null
    }
    $entry = [pscustomobject]@{
        name        = $name
        workspace   = $ws
        memory      = $memory
        last_opened = $null
        # The endpoint decides unless told otherwise. The alternative default,
        # an empty set, is not neutral: it means the repository's 0.0, which is
        # greedy - a deliberate-looking choice nobody made.
        settings    = [pscustomobject]@{ Temperature = "server" }
    }
    Write-Registry ($entries + $entry)
    Write-Host "pragma: registered '$name'" -ForegroundColor Green
    Write-Host "        workspace  $ws" -ForegroundColor DarkGray
    Write-Host "        memory     $memory" -ForegroundColor DarkGray
    return $entry
}


# --- the entry point ----------------------------------------------------------

function script:Get-SettableKeys {
    # Read from pragma-session.ps1 rather than copied into a list here. A
    # second copy of the same set would drift the first time a key was added
    # there, and -Set would reject something that works.
    # Backups belongs here too: it is written by the launcher, and letting it
    # be set by hand would allow pointing snapshots of the whole memory back
    # into a workspace - the leak the launcher exists to prevent.
    $structural = @('Name', 'Root', 'Repo', 'Workspace', 'Memory', 'Backups')
    $keys = @()
    try {
        $text = Get-Content -Raw $script:SessionScript
        foreach ($m in [regex]::Matches($text, 'Cfg "([A-Za-z]+)"')) {
            $k = $m.Groups[1].Value
            if ($k -notin $structural -and $k -notin $keys) { $keys += $k }
        }
    } catch { }
    return ($keys | Sort-Object)
}

function script:Resolve-Project([string]$name) {
    if ($name) { return Get-EntryByName $name }
    if ($env:PRAGMA_PROJECT) {
        $e = Get-EntryByName $env:PRAGMA_PROJECT
        if ($e) { return $e }
    }
    $here = Get-EntryByPath (Get-Location).Path
    if ($here) { return $here }
    return Get-LastOpened
}

function script:Show-Settings($entry) {
    Write-Host ""
    Write-Host "  settings for '$($entry.name)'" -ForegroundColor Cyan
    $props = @()
    if ($entry.settings) { $props = @($entry.settings.PSObject.Properties) }
    if ($props.Count -eq 0) {
        Write-Host "    none - every value falls back to the repository default" -ForegroundColor DarkGray
    } else {
        foreach ($p in $props) {
            Write-Host ("    {0,-18} {1}" -f $p.Name, $p.Value)
        }
    }
    Write-Host ""
    Write-Host "  settable: $((Get-SettableKeys) -join ', ')" -ForegroundColor DarkGray
    Write-Host "  pragma -Set <key> <value>   ('' clears it)" -ForegroundColor DarkGray
    Write-Host ""
}

function script:Get-Endpoint {
    if (-not (Test-Path $script:Python)) { return $null }
    try {
        $json = & $script:Python $script:EndpointScript 2>$null
        if (-not $json) { return $null }
        return ($json | ConvertFrom-Json)
    } catch { return $null }
}

function script:Show-Endpoint($ep) {
    # A sampling value means nothing on its own: what applies is whichever side
    # supplies it. This is the page where that is chosen, so both sides are on
    # it - the server's own defaults and what this project sends over them.
    Write-Host "  endpoint" -ForegroundColor Cyan
    if (-not $ep) {
        Write-Host "    could not be read" -ForegroundColor DarkYellow
        Write-Host ""
        return
    }
    Write-Host ("    url       {0}" -f $ep.endpoint)
    if ($ep.up) {
        # The one line worth finding at a glance: whether there is anything to
        # talk to. Green for yes, red for no - the rest of the panel is detail.
        Write-Host "    serving   " -NoNewline
        Write-Host $ep.serving -ForegroundColor Green
        if ($ep.configured_model -and $ep.serving -and
            ($ep.configured_model -ne $ep.serving)) {
            # Worth showing, not worth alarming about: DEFAULT_MODEL is a label
            # sent in the request, and llama.cpp serves what is loaded whatever
            # it says. Provenance already records the served name, not this one.
            # Not a fault: DEFAULT_MODEL is a label sent in the request, and
            # llama.cpp serves what is loaded whatever it says. Said here only
            # because a stale label is confusing to read, with the one command
            # that ends the confusion.
            Write-Host ("    labelled  {0}  - stale .env label, harmless" -f $ep.configured_model) -ForegroundColor DarkGray
            Write-Host "              pragma -Set Endpoint <url>, or fix DEFAULT_MODEL in .env" -ForegroundColor DarkGray
        }
        if ($ep.PSObject.Properties.Name -contains 'build' -and $ep.build) {
            Write-Host ("    build     {0}" -f $ep.build) -ForegroundColor DarkGray
        }
        if ($ep.PSObject.Properties.Name -contains 'n_ctx' -and $ep.n_ctx) {
            Write-Host ("    context   {0} tokens" -f $ep.n_ctx) -ForegroundColor DarkGray
        }
    } else {
        Write-Host "    serving   " -NoNewline
        Write-Host "backend down" -ForegroundColor Red
        if ($ep.detail) {
            Write-Host ("              {0}" -f $ep.detail) -ForegroundColor DarkGray
        }
    }
    Write-Host ""

    $keys = @('temperature', 'top_k', 'top_p', 'min_p')
    Write-Host ("    {0,-14}{1,-14}{2,-14}{3}" -f "", "the server", "this project", "applies") -ForegroundColor DarkGray
    foreach ($k in $keys) {
        $srv = $null; $snd = $null
        if ($ep.server -and ($ep.server.PSObject.Properties.Name -contains $k)) {
            $srv = $ep.server.$k
        }
        if ($ep.sending -and ($ep.sending.PSObject.Properties.Name -contains $k)) {
            $snd = $ep.sending.$k
        }
        # Rounded: llama.cpp reports 0.949999988079071 for a top_p of 0.95, and
        # the full float overflows the column and reads as a different number.
        $srvT = if ($null -ne $srv) { "{0:g}" -f [math]::Round([double]$srv, 4) } elseif ($ep.server_readable) { "-" } else { "?" }
        $sndT = if ($null -ne $snd) { "{0:g}" -f [math]::Round([double]$snd, 4) } else { "not sent" }
        $eff  = if ($null -ne $snd) { $sndT } else { $srvT }
        Write-Host ("    {0,-14}{1,-14}{2,-14}{3}" -f $k, $srvT, $sndT, $eff)
    }
    # Greedy is a property of the pair, not of one number, and it silently
    # voids the other three.
    $tsent = $null
    if ($ep.sending -and ($ep.sending.PSObject.Properties.Name -contains 'temperature')) {
        $tsent = [double]$ep.sending.temperature
    }
    if ($null -ne $tsent -and $tsent -eq 0) {
        Write-Host "    at temperature 0 decoding is greedy - the other three do nothing" -ForegroundColor DarkGray
    }
    Write-Host ""
}


function script:Set-Sampling($entry, [string]$mode) {
    # Four parameters, but only three states worth being in, and the fourth
    # number is not independent of the others: at temperature 0 the decoding is
    # greedy and top_k, top_p and min_p do nothing whatever they say. Offering
    # them as a set stops a project sitting in a combination that reads as
    # deliberate and is inert.
    switch ($mode) {
        'server' {
            # Omitted, all four: an absent field is what hands the choice over.
            Set-ProjectSetting $entry 'Temperature' 'server' | Out-Null
            foreach ($k in 'TopK', 'TopP', 'MinP') {
                Set-ProjectSetting $entry $k '' | Out-Null
            }
            Write-Host "  sampling: the endpoint decides all four" -ForegroundColor Green
        }
        'greedy' {
            Set-ProjectSetting $entry 'Temperature' '0.0' | Out-Null
            foreach ($k in 'TopK', 'TopP', 'MinP') {
                Set-ProjectSetting $entry $k '' | Out-Null
            }
            Write-Host "  sampling: greedy - the most likely token, every time" -ForegroundColor Green
        }
        'manual' {
            Write-Host ""
            Write-Host "  Blank leaves that one to the server." -ForegroundColor DarkGray
            foreach ($k in 'Temperature', 'TopK', 'TopP', 'MinP') {
                $cur = ""
                if ($entry.settings -and
                    ($entry.settings.PSObject.Properties.Name -contains $k)) {
                    $cur = $entry.settings.$k
                }
                $shown = if ($cur -ne "") { " [$cur]" } else { " [server]" }
                $v = Read-Host ("  " + $k.PadRight(12) + $shown)
                # Enter keeps what is there; "-" is how you clear one, since an
                # empty answer cannot mean both "keep" and "clear".
                if ($v -eq '-') { Set-ProjectSetting $entry $k '' | Out-Null }
                elseif ($v -ne '') { Set-ProjectSetting $entry $k $v | Out-Null }
            }
        }
    }
}

function script:Invoke-SettingsMenu($entry) {
    New-Page
    Show-Settings $entry
    Show-Endpoint (Get-Endpoint)
    $items = @(
        [pscustomobject]@{ key = 's'; label = "sampling: the server's      all four omitted, the endpoint decides"; action = 'server' }
        [pscustomobject]@{ key = 'm'; label = "sampling: by hand           enter the four yourself";                action = 'manual' }
        [pscustomobject]@{ key = 'g'; label = "sampling: greedy            temperature 0, deterministic";           action = 'greedy' }
        [pscustomobject]@{ key = 'q'; label = "back";                                                               action = '' }
    )
    $c = Show-Menu $items "enter select . esc back"
    Write-Host ""
    if (-not $c -or -not $c.action) { return $entry }
    Set-Sampling $entry $c.action
    $fresh = Get-EntryByName $entry.name
    if ($fresh) { Enable-Project $fresh | Out-Null; return $fresh }
    return $entry
}

function script:Set-ProjectSetting($entry, [string]$key, [string]$value) {
    $keys = Get-SettableKeys
    $match = $keys | Where-Object { $_ -ieq $key } | Select-Object -First 1
    if (-not $match) {
        Write-Host "pragma: '$key' is not a setting" -ForegroundColor Red
        Write-Host "        settable: $($keys -join ', ')" -ForegroundColor DarkGray
        return $false
    }
    $entries = @(Read-Registry)
    foreach ($e in $entries) {
        if ($e.name -ne $entry.name) { continue }
        if (-not $e.settings) {
            $e | Add-Member -NotePropertyName settings -NotePropertyValue ([pscustomobject]@{}) -Force
        }
        if ($value -eq "") {
            # Clearing is not the same as setting the empty string: an absent
            # key means "the repository default", which is what the operator
            # asked for when they cleared it.
            $e.settings.PSObject.Properties.Remove($match)
            Write-Host "pragma: $match cleared - back to the repository default" -ForegroundColor Green
        } else {
            $e.settings | Add-Member -NotePropertyName $match -NotePropertyValue $value -Force
            Write-Host "pragma: $match = $value" -ForegroundColor Green
        }
        Write-Registry $entries
        return $true
    }
    Write-Host "pragma: '$($entry.name)' is not in the registry any more" -ForegroundColor Red
    return $false
}


function Start-Pragma {
    [CmdletBinding()]
    param(
        [string]$Project,
        [switch]$List,
        [switch]$Register,
        [string]$Name,
        [string]$Workspace,
        [string[]]$Set,
        [switch]$Settings
    )

    if ($null -ne $Set -or $Settings) {
        $entry = Resolve-Project $Project
        if (-not $entry) {
            Write-Host "pragma: no project to configure. Open one first, or pass -Project." -ForegroundColor Red
            return
        }
        # A bare -Set cannot list: PowerShell demands an argument for a
        # [string[]] parameter, so listing has its own switch.
        if ($Settings -or $null -eq $Set -or $Set.Count -eq 0) {
            Show-Settings $entry; return
        }
        # Both spellings, because both are what people type.
        if ($Set.Count -eq 1 -and $Set[0] -match '^([A-Za-z]+)=(.*)$') {
            $k = $Matches[1]; $v = $Matches[2]
        } elseif ($Set.Count -ge 2) {
            $k = $Set[0]; $v = ($Set[1..($Set.Count - 1)] -join ' ')
        } else {
            Write-Host "pragma: -Set <key> <value>   or   -Set <key>=<value>" -ForegroundColor Red
            return
        }
        if (Set-ProjectSetting $entry $k $v) {
            # Re-activated on the spot: a setting that needed a new window to
            # take effect is exactly the kind of silent mismatch this exists to
            # remove, and the banner shows what changed.
            $fresh = Get-EntryByName $entry.name
            if ($fresh) { Enable-Project $fresh | Out-Null }
        }
        return
    }

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
        $ws = if ($Workspace) { $Workspace } else { (Get-Location).Path }
        $n  = if ($Name) { $Name } else { Split-Path -Leaf $ws }
        $entry = New-Project $n $ws
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

    if (Test-Stale) {
        Show-StaleNotice
        Write-Host "  any key to continue" -ForegroundColor DarkGray
        [Console]::ReadKey($true) | Out-Null
    }
    Invoke-MenuLoop $current
}


# --- the loop -----------------------------------------------------------------
# The menu is the program: an action runs, and when it finishes you are back
# here rather than at the shell. Quitting leaves. This is the opposite of what
# the first version did, and the reason is use rather than principle - the
# batch path never sees the menu anyway, so the loop costs nothing there.
#
# One thing the loop gives away for free: the briefing is recomputed on every
# pass, so after a chat you SEE what it consolidated - the episode count moves
# under you.

function script:Invoke-NewProject {
    # A project IS a folder, so the folder is asked first and the name follows
    # from it. The first version asked for a name with no folder in sight, which
    # put the abstract half before the concrete one.
    New-Page
    Write-Host ""
    Write-Host "  New project" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  A project is one folder the agent works in, plus a memory of" -ForegroundColor DarkGray
    Write-Host "  its own that Pragma keeps elsewhere." -ForegroundColor DarkGray
    Write-Host ""

    $here = (Get-Location).Path
    $ws = Read-Host "  folder  [$here]"
    if (-not $ws) { $ws = $here }
    $ws = $ws.Trim('"').Trim()
    if (-not (Test-Path $ws)) {
        Write-Host ""
        $mk = Read-Host "  '$ws' does not exist. Create it? [y/N]"
        if ($mk -notmatch '^[yYsS]') { Write-Host ""; return $null }
        try { New-Item -ItemType Directory -Force -Path $ws -ErrorAction Stop | Out-Null }
        catch {
            Write-Host "  could not create it: $($_.Exception.Message)" -ForegroundColor Red
            Wait-Key; return $null
        }
    }

    $leaf = Split-Path -Leaf ($ws.TrimEnd('\','/'))
    $name = Read-Host "  name    [$leaf]"
    if (-not $name) { $name = $leaf }

    Write-Host ""
    $entry = New-Project $name $ws
    if (-not $entry) { Wait-Key }
    return $entry
}

function script:Invoke-DeleteProject($entry) {
    New-Page
    Write-Host ""
    Write-Host "  Delete a project" -ForegroundColor Cyan
    Write-Host ""
    $entries = @(Read-Registry)
    $picks = @()
    foreach ($e in $entries) {
        $picks += [pscustomobject]@{ key = ''
                                     label = ("{0,-18} {1}" -f $e.name, $e.workspace)
                                     entry = $e }
    }
    $picks += [pscustomobject]@{ key = 'q'; label = "back"; entry = $null }
    $p = Show-Menu $picks "enter select . esc back"
    Write-Host ""
    if (-not $p -or -not $p.entry) { return $entry }
    $doomed = $p.entry

    $store = $doomed.memory
    $n = 0
    try { $n = @(Get-ChildItem -Path (Join-Path $store "episodes") -Filter "ep_*.json" -Recurse -ErrorAction SilentlyContinue).Count } catch { }

    New-Page
    Write-Host ""
    Write-Host "  Delete '$($doomed.name)'" -ForegroundColor Red
    Write-Host ""
    Write-Host "  This removes, for good:" -ForegroundColor DarkGray
    Write-Host "    the memory        $store"
    Write-Host "                      $n episode(s), and every belief drawn from them"
    Write-Host "    the registry entry"
    Write-Host ""
    # The workspace is the operator's own folder - often a git repository, often
    # the only copy of something. Pragma removes what Pragma made; deleting
    # someone's documents is not a menu item.
    Write-Host "  This does NOT touch:" -ForegroundColor DarkGray
    Write-Host "    the workspace     $($doomed.workspace)"
    $bk = Join-Path (Join-Path $script:PragmaHome "backups") $doomed.name
    if (Test-Path $bk) {
        Write-Host "    the snapshots     $bk"
    }
    Write-Host ""
    Write-Host "  There is no undo." -ForegroundColor Red
    Write-Host ""
    $typed = Read-Host "  Type the project name to confirm"
    if ($typed -ne $doomed.name) {
        Write-Host ""
        Write-Host "  not deleted" -ForegroundColor Green
        Wait-Key
        return $entry
    }

    try {
        if (Test-Path $store) { Remove-Item -Recurse -Force -Path $store -ErrorAction Stop }
    } catch {
        Write-Host "  could not remove the store: $($_.Exception.Message)" -ForegroundColor Red
        Wait-Key
        return $entry
    }
    Write-Registry @($entries | Where-Object { $_.name -ne $doomed.name })
    Write-Host ""
    Write-Host "  '$($doomed.name)' deleted. The workspace is still there." -ForegroundColor Green
    Wait-Key

    # If the window was on the project just deleted, it is on nothing now.
    if ($entry -and $entry.name -eq $doomed.name) { return $null }
    return $entry
}


function script:Invoke-MenuLoop($entry) {
    $active = $null
    while ($true) {
        # No project is a state to offer something from, not a reason to print
        # instructions and leave. Landing here used to be a dead end: the one
        # thing to do next was described rather than offered.
        if (-not $entry) {
            New-Page
            Write-Host ""
            Write-Host "  Pragma" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  No projects yet." -ForegroundColor DarkGray
            Write-Host ""
            $first = @(
                [pscustomobject]@{ key = 'n'; label = "new project"; action = 'new' }
                [pscustomobject]@{ key = 'q'; label = "quit";        action = 'quit' }
            )
            $c = Show-Menu $first "enter select . esc quit"
            Write-Host ""
            if (-not $c -or $c.action -eq 'quit') { return }
            $entry = Invoke-NewProject
            continue
        }
        if (-not $active -or $active.name -ne $entry.name) {
            if (-not (Enable-Project $entry)) { return }
            $active = Get-EntryByName $entry.name
            $entry = $active
        }

        New-Page
        $brief = Get-Brief $entry
        Show-Brief $entry $brief

        $items = @(
            [pscustomobject]@{ key = 'c'; label = "chat            many turns, one conversation"; action = 'chat' }
            [pscustomobject]@{ key = 't'; label = "task            one task, then back here";     action = 'task' }
            [pscustomobject]@{ key = 'a'; label = "ask             a question, no file changes";  action = 'ask' }
            [pscustomobject]@{ key = 'm'; label = "memory          map, beliefs, oblivion, last"; action = 'memory' }
            [pscustomobject]@{ key = 's'; label = "settings        what this project overrides";  action = 'settings' }
            [pscustomobject]@{ key = 'p'; label = "switch project";                               action = 'switch' }
            [pscustomobject]@{ key = 'n'; label = "new project";                                  action = 'new' }
            [pscustomobject]@{ key = 'd'; label = "delete project";                               action = 'delete' }
            [pscustomobject]@{ key = 'q'; label = "quit";                                         action = 'quit' }
        )
        $choice = Show-Menu $items "enter select . up/down move . esc quit"
        Write-Host ""
        if (-not $choice -or $choice.action -eq 'quit') {
            New-Page
            Write-Host ""
            Write-Host "  the window stays on '$($entry.name)' - pragma -Info for the commands" -ForegroundColor DarkGray
            Write-Host ""
            return
        }

        switch ($choice.action) {
            'chat' {
                # global: is not decoration. Inside this module `pragma` resolves
                # to the module's own function, which has no -Chat; the session
                # script's is the one dot-sourced into the global scope, and only
                # the qualifier reaches it.
                New-Page
                global:pragma -Chat
                Wait-Key
            }
            'task' {
                $task = Read-Host "  task"
                if ($task) { New-Page; global:pragma $task; Wait-Key }
            }
            'ask' {
                $q = Read-Host "  ask memory"
                if ($q) { New-Page; global:pragma -Ask $q; Wait-Key }
            }
            'memory'   { Invoke-MemoryMenu }
            'settings' { $entry = Invoke-SettingsMenu $entry }
            'new' {
                $fresh = Invoke-NewProject
                if ($fresh) { $entry = $fresh; $active = $null }
            }
            'delete' {
                $after = Invoke-DeleteProject $entry
                if (-not $after -or ($entry -and $after.name -ne $entry.name)) {
                    $entry = $after; $active = $null
                }
            }
            'switch' {
                $picks = @()
                foreach ($e in @(Read-Registry)) {
                    $picks += [pscustomobject]@{ key = ''
                                                 label = ("{0,-18} {1}" -f $e.name, $e.workspace)
                                                 entry = $e }
                }
                New-Page
                Write-Host ""
                Write-Host "  Which project" -ForegroundColor DarkGray
                $p = Show-Menu $picks "enter select . esc cancel"
                Write-Host ""
                if ($p) { $entry = $p.entry }
            }
        }
    }
}

function script:Wait-Key {
    Write-Host "  any key to go back" -ForegroundColor DarkGray
    [Console]::ReadKey($true) | Out-Null
    Write-Host ""
}

function script:Invoke-MemoryMenu {
    New-Page
    Write-Host ""
    Write-Host "  Memory" -ForegroundColor Cyan
    Write-Host ""
    $items = @(
        [pscustomobject]@{ key = 'm'; label = "map         what is in memory now";        action = 'Map' }
        [pscustomobject]@{ key = 'b'; label = "beliefs     what it has concluded";        action = 'Beliefs' }
        [pscustomobject]@{ key = 'd'; label = "diff        meanings it has revised";      action = 'Diff' }
        [pscustomobject]@{ key = 'o'; label = "oblivion    what has faded";               action = 'Oblio' }
        [pscustomobject]@{ key = 'l'; label = "last        the newest episode, in full";  action = 'Last' }
        [pscustomobject]@{ key = 'q'; label = "back";                                     action = '' }
    )
    $c = Show-Menu $items "enter select . esc back"
    Write-Host ""
    if (-not $c -or -not $c.action) { return }
    # Splatting needs a variable, not an inline hashtable: the session command
    # takes these as separate switches, not as a value.
    New-Page
    $splat = @{ $c.action = $true }
    global:pragma @splat
    Wait-Key
}


# `pragma` is a FUNCTION and deliberately not an alias. PowerShell resolves an
# alias BEFORE a function of the same name, so an alias here would keep
# shadowing the session command that Enable-Project dot-sources into the global
# scope, and `pragma -Chat` at the prompt would fail with "a parameter cannot
# be found". A function is simply replaced in the global function table by the
# session's `function global:pragma`, which is exactly the handover wanted:
# before a project is open `pragma` gets you one, after it is the full command
# surface. Start-Pragma is never shadowed and always reopens the menu.
#
# No [CmdletBinding()]: it would add the common parameters, and -Info would
# then be ambiguous against -InformationAction.
function pragma {
    param(
        [string]$Project,
        [switch]$List,
        [switch]$Register,
        [string]$Name,
        [string]$Workspace,
        [string[]]$Set,
        [switch]$Settings
    )
    Start-Pragma @PSBoundParameters
}

Export-ModuleMember -Function Start-Pragma, pragma
