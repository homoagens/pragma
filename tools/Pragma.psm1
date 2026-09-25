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
# WHAT THIS IS. `pragma` opens a home prompt (/open, /new, /configure, /exit)
# and stays there: an action runs and returns to it, and /exit leaves the
# program, the way a terminal harness behaves. The window keeps the project's environment afterwards, so
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


# --- colour ---------------------------------------------------------------
# Write-Host has sixteen names and none of them is a purple worth looking at:
# the nearest, Magenta, is the DOS one. A terminal that understands virtual
# terminal sequences can do 24-bit colour, and this one asks before using them
# so a console that cannot is left with the named colours it does understand.
#
# PRAGMA_ACCENT overrides the hue as "R;G;B" - "255;140;0" for orange, say -
# because a colour someone has to like is not a thing to hardcode and argue
# about.

$script:UseVT = $false
try {
    $script:UseVT = ($Host.UI.SupportsVirtualTerminal -and -not [Console]::IsOutputRedirected)
} catch { }

$script:Accent = "178;132;255"
if ($env:PRAGMA_ACCENT -match '^\d{1,3};\d{1,3};\d{1,3}$') {
    $script:Accent = $env:PRAGMA_ACCENT
}

function script:Paint([string]$text, [string]$role) {
    # Returns the text ready to print: wrapped in escapes where they work,
    # untouched where they do not, so every caller is one line either way.
    if (-not $script:UseVT) { return $text }
    $e = [char]27
    switch ($role) {
        'accent'   { return "$e[38;2;$($script:Accent)m$text$e[0m" }
        'selected' { return "$e[48;2;76;40;130m$e[38;2;255;255;255m$text$e[0m" }
        'dim'      { return "$e[38;2;128;128;128m$text$e[0m" }
        default    { return $text }
    }
}

function script:Write-Accent([string]$text) {
    # The fallback is Magenta rather than nothing: on a console without VT the
    # headings should still be the colour they mean, even if it is a coarser
    # one.
    if ($script:UseVT) { Write-Host (Paint $text 'accent') }
    else { Write-Host $text -ForegroundColor Magenta }
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
        # --since only when there is one. PowerShell drops an empty string
        # when it builds a native command line, so `--since ""` reached
        # argparse as a bare `--since` and the whole briefing failed with a
        # usage error - on a project that had never been opened, which is
        # exactly the first one anyone sees. It looked like a memory with
        # nothing in it.
        if ($since) {
            $json = & $script:Python $script:BriefScript $store --since $since 2>$null
        } else {
            $json = & $script:Python $script:BriefScript $store 2>$null
        }
        if (-not $json) { return $null }
        return ($json | ConvertFrom-Json)
    } catch { return $null }
}

function script:New-Page {
    # Each view replaces the last rather than scrolling under it. Guarded
    # because a host without a console cannot clear one, and a briefing is
    # never worth failing over.
    try { Clear-Host } catch { }
    # Clear-Host empties the visible screen and leaves the scrollback, so the
    # page just replaced is still a wheel-turn above - which is not what
    # replacing it promised. ESC[3J drops the scrollback as well, on hosts that
    # understand it; asking first keeps the escape from being printed as text
    # on one that does not.
    try {
        if ($Host.UI.SupportsVirtualTerminal -and -not [Console]::IsOutputRedirected) {
            [Console]::Write([string][char]27 + "[3J")
        }
    } catch { }
}

function script:Show-Logo([switch]$Compact) {
    # The mark from interface-web/logo.png, at eight rows against the word's
    # four. Twelve rows made a picture with a caption under it rather than a
    # logotype; at this ratio the mark reads as the letter the word starts
    # with, which is what it is.
    #
    # Beside rather than flowing out of the tail, which was the nicer idea:
    # at this size the bowl's lower sweep is as wide as the whole mark, so a
    # word tucked under it gets eaten. That trick needs a mark three times
    # this tall, and a mark three times this tall is the problem it was
    # meant to solve.
    #
    # Binarised at full resolution and then area-averaged: sampling one
    # point per cell of an antialiased image put a bleed line along the top
    # bar and split the dot across two rows. F is a full cell, T an upper
    # half, B a lower half - letters, so this file stays pure ASCII while
    # the output is not, and so the fallback for a console that cannot draw
    # blocks is one map rather than a second copy of the art.
    if ($Compact) {
        if ($script:UseVT) { Write-Host (Paint '  Pragma' 'accent') -NoNewline }
        else { Write-Host '  Pragma' -ForegroundColor Magenta -NoNewline }
        return
    }
    $glyph = if ($script:UseVT) {
        @{ 'F' = [char]0x2588; 'T' = [char]0x2580; 'B' = [char]0x2584 }
    } else {
        @{ 'F' = '#'; 'T' = '#'; 'B' = '#' }
    }
    $art = @(
        ' BFFFFFFFFFBB',
        ' TTTTTTTTTTFFF',
        '       BB   FFF',
        '    B  TT   FFF',
        '  BFFBBBBBBFFF   _ _ __ _ __ _ _ __  __ _',
        ' FFFFFFFFFFTT   | ''_/ _` / _` | ''  \/ _` |',
        ' FFFT           |_| \__,_\__, |_|_|_\__,_|',
        ' FT                       |___/'
    )
    foreach ($row in $art) {
        $out = ''
        foreach ($ch in $row.ToCharArray()) {
            $k = [string]$ch
            $out += if ($glyph.ContainsKey($k)) { $glyph[$k] } else { $ch }
        }
        if ($script:UseVT) { Write-Host (Paint $out 'accent') }
        else { Write-Host $out -ForegroundColor Magenta }
    }
}


function script:Show-Brief($entry, $brief) {
    # A BRIEFING ANSWERS TWO QUESTIONS: can I start, and what changed while I
    # was away. It used to answer eight - window, tau, roles, sampling - and a
    # page that says everything says nothing, because the one line that needed
    # reading sat in the middle of seven that did not. What is configured is
    # /status now, a page asked for rather than one walked past every day.
    #
    # Colour carries meaning here and nowhere else: grey labels, green for a
    # server that answers, yellow for what wants you, red for what is broken.
    Write-Host ""
    Show-Logo
    Write-Host ""
    Write-Host ("   " + (Get-Date -Format "dddd d MMMM, HH:mm")) -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  project   " -ForegroundColor DarkGray -NoNewline
    Write-Host $entry.name
    if ($brief -and $brief.ok) {
        $mem = "{0} episodes active, {1} dormant, {2} beliefs" -f `
               $brief.episodes_active, $brief.episodes_dormant, $brief.beliefs
        if ($null -ne $brief.away_days) {
            $away = if ($brief.away_days -lt 1) { "today" }
                    elseif ($brief.away_days -lt 2) { "1 day" }
                    else { "{0:N0} days" -f $brief.away_days }
            $mem = $mem + ("   last here " + $away)
        }
        Write-Host "  memory    " -ForegroundColor DarkGray -NoNewline
        Write-Host $mem

        # Whether there is anything to talk to is the one thing worth finding
        # without reading. Keyed on the backend state rather than on the model
        # name: a server that answers without reporting a model is up.
        $isUp = ($brief.backend -eq "up")
        Write-Host "  serving   " -ForegroundColor DarkGray -NoNewline
        if ($isUp) {
            $what = if ($brief.serving) { $brief.serving } else { "up (model not reported)" }
            Write-Host $what -ForegroundColor Green
        } else {
            Write-Host "backend down" -ForegroundColor Red
            $why = "$($brief.backend)" -replace '^down - ', ''
            if ($why -and $why -ne "up") {
                Write-Host ("            " + $why) -ForegroundColor DarkGray
            }
            Write-Host "            /configure to point it elsewhere" -ForegroundColor DarkGray
        }

        # WHAT WANTS YOU. Nothing here on an ordinary day; one line each when
        # there is something, and every line says what to type about it.
        $attention = @()
        if ($brief.PSObject.Properties.Name -contains 'working' -and [int]$brief.working -gt 0) {
            $what = if ($brief.working_note) { $brief.working_note } else { "a session" }
            $attention += ("the memory is writing " + $what + " - the counts above will move")
        }
        if ($brief.PSObject.Properties.Name -contains 'jobs_failed' -and [int]$brief.jobs_failed -gt 0) {
            # Never silent. The turns are still in the job file, so this is
            # recoverable - but only if it is said.
            $attention += ("{0} consolidation(s) did not finish - /jobs" -f $brief.jobs_failed)
        }
        # THE WINDOW IN FORCE, when the server disagrees with it. Every
        # compaction threshold is derived from that number, so a wrong one does
        # not degrade gracefully: Pragma talks on until the server refuses the
        # request, having compacted for a window it never had. When the two
        # agree there is nothing to say, and the number lives in /status.
        if ($brief.PSObject.Properties.Name -contains 'context_window' -and
            [int]$brief.context_window -gt 0 -and $brief.context_source -ne 'endpoint') {
            $srvCtx = 0
            if ($brief.PSObject.Properties.Name -contains 'n_ctx') { $srvCtx = [int]$brief.n_ctx }
            $mine = [int]$brief.context_window
            if ($srvCtx -gt 0 -and $srvCtx -lt $mine) {
                $attention += ("context {0} tokens, but the server has {1} - requests will be refused" -f $mine, $srvCtx)
                $attention += ("clear it with pragma -Set ContextWindow `"`" to follow the server")
            } elseif ($srvCtx -gt $mine) {
                $attention += ("context {0} tokens of the server's {1} - /status" -f $mine, $srvCtx)
            }
        }
        # A role on an endpoint that does not answer: the conversation may work
        # and the memory still fail, which is the confusing kind of broken.
        if ($brief.PSObject.Properties.Name -contains 'roles' -and $brief.roles) {
            foreach ($r in @($brief.roles)) {
                if (-not $r.up) { $attention += ("{0} endpoint {1} - {2} - /configure" -f $r.role, $r.name, $r.status) }
            }
        }
        foreach ($line in $attention) {
            Write-Host "            " -NoNewline
            Write-Host $line -ForegroundColor Yellow
        }

        # SINCE YOU LEFT. The memory's own news, which is the other half of
        # what a briefing is for.
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
        Write-Host $brief.error -ForegroundColor Yellow
    }
    Write-Host ""
}


# --- the menu -----------------------------------------------------------------
# Arrow keys with a highlighted row, redrawn in place. The accelerator letters
# stay because a menu is good for discovery and bad for repetition, and this is
# opened daily: enter does the frequent thing and typing a task skips the menu
# entirely.

function script:Show-Menu([object[]]$items, [string]$hint, [int]$start = 0) {
    # Drawn once, then redrawn over itself. The first attempt recorded the
    # cursor BEFORE drawing and returned to it, which a console that scrolls
    # invalidates: every keypress appended a fresh copy of the menu instead of
    # replacing it. Deriving the top from where the drawing actually ENDED
    # survives scrolling, because the end moves with the content.
    #
    # [Console] rather than $Host.UI.RawUI: the .NET API drives the console
    # directly and does not depend on virtual-terminal sequences being enabled,
    # which on a classic PowerShell 5.1 window they may not be.
    # $start is where the cursor begins. A list of projects opens on the one
    # you are most likely to want - the folder you are standing in, or the last
    # one you had open - so the common case is still a single Enter even though
    # nothing is entered for you.
    $sel   = [Math]::Max(0, [Math]::Min($start, $items.Count - 1))
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
                if ($script:UseVT) { Write-Host (Paint $row 'selected') }
                else { Write-Host $row -ForegroundColor Black -BackgroundColor Magenta }
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
        # Ctrl+D goes back here as it does everywhere else in Pragma: in the
        # conversation, in /configure, at the home prompt. Esc and q still work.
        if (Test-CtrlD $key) { return $null }
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
    # Pragma's own source tree. Not caught by the home/Desktop guard, and it
    # registers happily - then the conversation refuses to open, because
    # self_modify_guard blocks every write inside the source tree. A terminal
    # that starts in the repository is not a rare accident: it is what an
    # editor's terminal does right after the clone.
    #
    # Refused rather than made impossible: developing Pragma with Pragma is a
    # real case, and PRAGMA_ALLOW_SELF_MODIFY is the switch that already
    # governs it in config.py. Naming it here means the refusal points at the
    # one thing that lifts it, instead of looking like a wall.
    $repoN = $script:RepoRoot.TrimEnd([char]92, [char]47)
    if ($n -ieq $repoN -or
        $n.StartsWith($repoN + [IO.Path]::DirectorySeparatorChar,
                      [StringComparison]::OrdinalIgnoreCase)) {
        if ("$env:PRAGMA_ALLOW_SELF_MODIFY" -match '^(1|true|yes)$') {
            Write-Host "pragma: inside Pragma's own source tree, allowed by" -ForegroundColor Yellow
            Write-Host "        PRAGMA_ALLOW_SELF_MODIFY." -ForegroundColor Yellow
            return $true
        }
        Write-Host "pragma: that is inside Pragma's own source tree." -ForegroundColor Red
        Write-Host "        The agent refuses to write there, and your memory has no" -ForegroundColor DarkGray
        Write-Host "        business in a folder you will git pull over." -ForegroundColor DarkGray
        Write-Host "        To develop Pragma with Pragma, set PRAGMA_ALLOW_SELF_MODIFY=true" -ForegroundColor DarkGray
        Write-Host "        first - it is the same switch config.py already reads." -ForegroundColor DarkGray
        Show-WhatAWorkspaceIs $env:USERPROFILE
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
    # A FOLDER THAT IS NOT THERE YET is the normal way to start a project, not
    # a mistake: you name where the work will go before there is any of it. So
    # it is offered, not refused - and offered rather than made silently,
    # because a typed path with a typo would otherwise become a folder nobody
    # meant to create. The Python launcher asks the same question.
    $full = $workspace
    try { $full = [System.IO.Path]::GetFullPath(
            [System.IO.Path]::Combine((Get-Location).Path, $workspace)) } catch { }
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        Write-Host "pragma: that is a file, not a folder: $full" -ForegroundColor Red
        return $null
    }
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        Write-Host ""
        Write-Host "  $full does not exist." -ForegroundColor DarkGray
        $ans = Show-Menu @(
            [pscustomobject]@{ key = 'n'; label = "no, go back";   action = '' }
            [pscustomobject]@{ key = 'y'; label = "yes, create it"; action = 'make' }
        ) "enter select . ctrl+D back"
        Write-Host ""
        if (-not $ans -or -not $ans.action) { return $null }
        try {
            $null = New-Item -ItemType Directory -Path $full -Force -ErrorAction Stop
        } catch {
            Write-Host "pragma: cannot create it: $($_.Exception.Message)" -ForegroundColor Red
            return $null
        }
    }
    try {
        $ws = (Resolve-Path -LiteralPath $full -ErrorAction Stop).Path
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
        # Nothing about the model here. What it is, whether it reasons and
        # how it samples are the endpoint's, and a project inherits them.
        settings    = [pscustomobject]@{ }
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
    Write-Accent "  settings for '$($entry.name)'"
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
    Write-Accent "  endpoint"
    if (-not $ep) {
        Write-Host "    could not be read" -ForegroundColor Yellow
        Write-Host ""
        return
    }
    Write-Host ("    url       {0}" -f $ep.endpoint)
    # With an endpoint catalogue this page is the agent's endpoint; the roles
    # say where the other two are, and /configure is where they change.
    if ($ep.PSObject.Properties.Name -contains 'roles' -and $ep.roles) {
        $parts = @()
        foreach ($role in @('agent', 'recall', 'memory')) { $parts += ("{0} {1}" -f $role, $ep.roles.$role) }
        Write-Host ("    roles     {0}" -f ($parts -join ' . ')) -ForegroundColor DarkGray
        Write-Host "              this page shows the agent's endpoint; /configure changes the roles" -ForegroundColor DarkGray
    }
    if ($ep.PSObject.Properties.Name -contains 'catalogue_error' -and $ep.catalogue_error) {
        Write-Host ("    catalogue {0}" -f $ep.catalogue_error) -ForegroundColor Red
    }
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
            Write-Host "              pragma -Set Endpoint <url>, or /configure to fix DEFAULT_MODEL" -ForegroundColor DarkGray
        }
        if ($ep.PSObject.Properties.Name -contains 'build' -and $ep.build) {
            Write-Host ("    build     {0}" -f $ep.build) -ForegroundColor DarkGray
        }
        # THE WINDOW, IN THREE NUMBERS. They are asked for together because
        # they are only meaningful together: how many requests the server
        # works on at once, how much window each of those gets, and which
        # figure Pragma is actually compacting against. On llama.cpp the
        # first two are one setting seen from two sides - -c is shared out
        # among the slots - so a window that halved without anyone touching
        # it is a -np that changed.
        $slots = 0
        if ($ep.PSObject.Properties.Name -contains 'slots') { $slots = [int]$ep.slots }
        if ($slots -gt 0) {
            Write-Host ("    slots     {0}   (llama-server -np {0}: {1} at a time)" -f `
                        $slots, $(if ($slots -eq 1) { "one request" } else { "$slots requests" })) -ForegroundColor DarkGray
        }
        if ($ep.PSObject.Properties.Name -contains 'n_ctx' -and $ep.n_ctx) {
            $per = [int]$ep.n_ctx
            Write-Host ("    context   {0} tokens per slot - what one call may use" -f $per) -ForegroundColor DarkGray
            if ($slots -gt 1) {
                Write-Host ("              {0} slots x {1} = {2} of KV cache, unless the" -f `
                            $slots, $per, ($slots * $per)) -ForegroundColor DarkGray
                Write-Host "              server shares one cache between them" -ForegroundColor DarkGray
            }
            $mine = 0
            if ($ep.PSObject.Properties.Name -contains 'context_window') { $mine = [int]$ep.context_window }
            if ($mine -gt 0 -and $mine -ne $per) {
                Write-Host ("    in force  {0} - " -f $mine) -NoNewline -ForegroundColor Red
                if ($mine -gt $per) {
                    Write-Host "more than a call gets: requests will be refused" -ForegroundColor Red
                } else {
                    Write-Host "less than a call gets: window wasted" -ForegroundColor Yellow
                }
                Write-Host "              pragma -Set ContextWindow `"`" follows the server" -ForegroundColor DarkGray
            } elseif ($mine -gt 0) {
                $how = if ($ep.context_source -eq 'endpoint') { "from the server" }
                       elseif ($ep.context_source -eq 'declared') { "declared, and it agrees" }
                       else { "the built-in default" }
                Write-Host ("    in force  {0}   ({1})" -f $mine, $how) -ForegroundColor DarkGray
            }
        } elseif ($ep.PSObject.Properties.Name -contains 'context_window') {
            Write-Host ("    in force  {0}   (the server did not say)" -f $ep.context_window) -ForegroundColor DarkGray
        }
    } else {
        Write-Host "    serving   " -NoNewline
        Write-Host "backend down" -ForegroundColor Red
        if ($ep.detail) {
            Write-Host ("              {0}" -f $ep.detail) -ForegroundColor DarkGray
        }
        Write-Host "              to point it elsewhere, type /configure" -ForegroundColor DarkGray
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


function script:Get-ProjectValue($entry, [string]$key) {
    if ($entry.settings -and ($entry.settings.PSObject.Properties.Name -contains $key)) {
        return "$($entry.settings.$key)"
    }
    return ""
}

function script:Invoke-ProjectChoices($entry) {
    # The decisions that change how a project feels, asked one at a time with
    # the options spelled out, so nobody has to know a setting's name or its
    # values. Enter keeps what is in brackets - going through without typing
    # changes nothing - and ctrl+D stops, keeping what was already answered.
    Write-Host ""
    Write-Accent "  choices for '$($entry.name)'"
    Write-Host "  enter keeps the value in brackets . ctrl+D stops" -ForegroundColor DarkGray

    # What the model IS, and how it samples, are the endpoint's: one server,
    # one model, one answer for every project that talks to it. /configure.
    Write-Host ""
    Write-Host "  Whether anything reasons, and how it samples, belong to the" -ForegroundColor DarkGray
    Write-Host "  endpoint - /configure, once, for every project. There it is" -ForegroundColor DarkGray
    Write-Host "  said role by role: the steps, the recall, the memory." -ForegroundColor DarkGray

    # 2. How far one turn may go before the agent has to answer.
    $cur = Get-ProjectValue $entry 'MaxSteps'
    $shown = if ($cur) { $cur } else { '50' }
    Write-Host ""
    Write-Host "  steps per turn - how many actions the agent may take before it must answer"
    Write-Host "    50 suits a conversation; long tasks on files may need more" -ForegroundColor DarkGray
    while ($true) {
        $v = Read-Line "  steps per turn [$shown]: "
        if ($null -eq $v) { return }
        $v = $v.Trim()
        if (-not $v -or $v -eq $shown) { break }
        $n = 0
        if ([int]::TryParse($v, [ref]$n) -and $n -ge 1 -and $n -le 1000) {
            Set-ProjectSetting $entry 'MaxSteps' "$n" | Out-Null
            break
        }
        Write-Host "    a number from 1 to 1000" -ForegroundColor Yellow
    }
    Write-Host ""
}

function script:Invoke-SettingsMenu($entry) {
    # NO MENU HERE. The three sampling rows asked, in a second idiom, exactly
    # what the choices page asks in words - and a page that can be walked with
    # arrows next to a page that is typed at is most of what made this feel
    # like two programs. What is set, then the questions, then back.
    New-Page
    Show-Settings $entry
    Show-Endpoint (Get-Endpoint)
    Invoke-ProjectChoices $entry
    $fresh = Get-EntryByName $entry.name
    if ($fresh) { Enable-Project $fresh | Out-Null; $entry = $fresh }
    Wait-Key
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

# --- backups ------------------------------------------------------------------
# pragma -Backup only ever snapshotted the store, which is how a day ended with
# the memory safe and the workspace overwritten. The two halves are separate by
# design - the store is Pragma's, the workspace is yours - and that is exactly
# why a backup has to be able to take either, or both.
#
# Every archive carries a manifest naming what is inside and where each part
# came from, so a restore does not have to guess. Archives written before this
# existed have none, and are read by inspecting their contents instead.

function script:Get-BackupRoot($entry) {
    Join-Path (Join-Path $script:PragmaHome "backups") $entry.name
}

function script:New-Snapshot($entry, [string]$what, [string]$tag = "") {
    $root = Get-BackupRoot $entry
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
    $name = if ($tag) { "$tag-$what" + "_$stamp" } else { $what + "_$stamp" }
    $zip = Join-Path $root ($name + ".zip")

    $stage = Join-Path ([IO.Path]::GetTempPath()) ("pragma-snap-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    try {
        $eps = 0
        if ($what -ne "workspace" -and (Test-Path $entry.memory)) {
            Copy-Item -Recurse -Force -Path $entry.memory -Destination (Join-Path $stage "memory")
            try {
                $eps = @(Get-ChildItem -Recurse -Path (Join-Path $stage "memory") -Filter "ep_*.json" -ErrorAction SilentlyContinue).Count
            } catch { }
        }
        if ($what -ne "memory" -and (Test-Path $entry.workspace)) {
            Copy-Item -Recurse -Force -Path $entry.workspace -Destination (Join-Path $stage "workspace")
        }
        $manifest = [pscustomobject]@{
            pragma_backup = 1
            project       = $entry.name
            kind          = $what
            created       = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            memory_from   = $entry.memory
            workspace_from = $entry.workspace
            episodes      = $eps
        }
        ($manifest | ConvertTo-Json) |
            Set-Content -Encoding UTF8 (Join-Path $stage "pragma-backup.json")
        Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
    } finally {
        Remove-Item -Recurse -Force -Path $stage -ErrorAction SilentlyContinue
    }
    return (Get-Item $zip)
}

function script:Read-SnapshotInfo([string]$zipPath) {
    # The manifest when there is one, otherwise inferred from the entry names -
    # the archives this replaced still have to be restorable.
    $info = [ordered]@{ kind = "?"; created = ""; episodes = $null; legacy = $true }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $z = [IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            $m = $z.Entries | Where-Object { $_.FullName -eq "pragma-backup.json" }
            if ($m) {
                $r = New-Object IO.StreamReader($m.Open())
                $j = $r.ReadToEnd() | ConvertFrom-Json
                $r.Dispose()
                $info.kind = "$($j.kind)"
                $info.created = "$($j.created)"
                $info.episodes = $j.episodes
                $info.legacy = $false
            } else {
                # Separators are normalised first: Compress-Archive on
                # PowerShell 5.1 writes backslashes into the entry names, so
                # matching on "/" alone read a store full of episodes as a
                # workspace - and this is the shape every archive written
                # before the manifest existed has.
                # [char]92 rather than a literal backslash, and .Replace
                # rather than -replace: a lone backslash is an invalid
                # regex, and writing one into this file is a trap that
                # has already been walked into once.
                $names = $z.Entries | ForEach-Object {
                    $_.FullName.Replace([char]92, [char]47) }
                $hasMem = @($names | Where-Object { $_ -match '^(memory/)?episodes/' }).Count -gt 0
                $hasWs  = @($names | Where-Object { $_ -match '^workspace/' }).Count -gt 0
                if ($hasMem -and $hasWs) { $info.kind = "both" }
                elseif ($hasMem) { $info.kind = "memory" }
                elseif ($hasWs) { $info.kind = "workspace" }
                else { $info.kind = "workspace" }
                $info.episodes = @($names | Where-Object { $_ -match 'ep_.*\.json$' }).Count
            }
        } finally { $z.Dispose() }
    } catch { }
    return $info
}

function script:Invoke-Restore($entry) {
    New-Page
    Write-Host ""
    Write-Accent "  Restore a snapshot"
    Write-Host ""
    $root = Get-BackupRoot $entry
    $files = @()
    if (Test-Path $root) {
        $files = @(Get-ChildItem -Path $root -Filter "*.zip" | Sort-Object LastWriteTime -Descending)
    }
    if ($files.Count -eq 0) {
        Write-Host "  No snapshots for '$($entry.name)' yet." -ForegroundColor DarkGray
        Write-Host "  $root" -ForegroundColor DarkGray
        Write-Host ""
        Wait-Key
        return
    }

    $picks = @()
    foreach ($f in $files) {
        $i = Read-SnapshotInfo $f.FullName
        $ep = if ($null -ne $i.episodes) { "$($i.episodes) ep" } else { "" }
        $picks += [pscustomobject]@{
            key = ''
            label = ("{0,-11} {1:yyyy-MM-dd HH:mm}  {2,8:N0} KB  {3}" -f `
                     $i.kind, $f.LastWriteTime, ($f.Length / 1KB), $ep)
            file = $f; info = $i }
    }
    $picks += [pscustomobject]@{ key = 'q'; label = "back"; file = $null }
    $p = Show-Menu $picks "enter select . ctrl+D back"
    Write-Host ""
    if (-not $p -or -not $p.file) { return }

    New-Page
    Write-Host ""
    Write-Host "  Restore into '$($entry.name)'" -ForegroundColor Red
    Write-Host ""
    Write-Host "    from   $($p.file.Name)"
    Write-Host "    holds  $($p.info.kind)"
    Write-Host ""
    if ($p.info.kind -ne "workspace") {
        Write-Host "  The memory is REPLACED - what is there now goes:" -ForegroundColor DarkGray
        Write-Host "    $($entry.memory)"
    }
    if ($p.info.kind -ne "memory") {
        # Merge, not replace: a workspace holds files Pragma never made, and a
        # restore has no business deleting what it cannot have created.
        Write-Host "  The workspace is OVERWRITTEN FILE BY FILE - anything added" -ForegroundColor DarkGray
        Write-Host "  since the snapshot stays where it is:" -ForegroundColor DarkGray
        Write-Host "    $($entry.workspace)"
    }
    Write-Host ""
    Write-Host "  A snapshot of the current state is taken first, so this is" -ForegroundColor DarkGray
    Write-Host "  undoable." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  ctrl+D goes back" -ForegroundColor DarkGray
    $typed = Read-Line "  Type the project name to confirm: "
    if ($typed -ne $entry.name) {
        Write-Host ""
        Write-Host "  nothing restored" -ForegroundColor Green
        Wait-Key
        return
    }

    Write-Host ""
    try {
        $safety = New-Snapshot $entry $p.info.kind "BEFORE-RESTORE"
        Write-Host "  current state saved as $($safety.Name)" -ForegroundColor Green
    } catch {
        Write-Host "  could not take the safety snapshot: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  nothing restored." -ForegroundColor Red
        Wait-Key
        return
    }

    $stage = Join-Path ([IO.Path]::GetTempPath()) ("pragma-rest-" + [guid]::NewGuid().ToString("N"))
    try {
        Expand-Archive -Path $p.file.FullName -DestinationPath $stage -Force
        # Legacy archives put the store at the root; the manifest-era ones put
        # it under memory/.
        $srcMem = Join-Path $stage "memory"
        if (-not (Test-Path $srcMem)) {
            if (Test-Path (Join-Path $stage "episodes")) { $srcMem = $stage } else { $srcMem = $null }
        }
        $srcWs = Join-Path $stage "workspace"
        if (-not (Test-Path $srcWs)) { $srcWs = $null }

        if ($srcMem -and $p.info.kind -ne "workspace") {
            Remove-Item -Recurse -Force -Path $entry.memory -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force -Path $entry.memory | Out-Null
            Copy-Item -Recurse -Force -Path (Join-Path $srcMem "*") -Destination $entry.memory
            Write-Host "  memory restored" -ForegroundColor Green
        }
        if ($srcWs -and $p.info.kind -ne "memory") {
            New-Item -ItemType Directory -Force -Path $entry.workspace | Out-Null
            Copy-Item -Recurse -Force -Path (Join-Path $srcWs "*") -Destination $entry.workspace
            Write-Host "  workspace restored" -ForegroundColor Green
        }
    } catch {
        Write-Host "  restore failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  the safety snapshot above still holds the previous state." -ForegroundColor DarkGray
    } finally {
        Remove-Item -Recurse -Force -Path $stage -ErrorAction SilentlyContinue
    }
    Write-Host ""
    Wait-Key
}

function script:Invoke-BackupMenu($entry) {
    while ($true) {
        New-Page
        Write-Host ""
        Write-Accent "  Backups"
        Write-Host ""
        $root = Get-BackupRoot $entry
        $n = 0
        if (Test-Path $root) { $n = @(Get-ChildItem -Path $root -Filter "*.zip").Count }
        Write-Host "    memory     $($entry.memory)" -ForegroundColor DarkGray
        Write-Host "    workspace  $($entry.workspace)" -ForegroundColor DarkGray
        Write-Host "    snapshots  $n in $root" -ForegroundColor DarkGray
        Write-Host ""
        $items = @(
            [pscustomobject]@{ key = 'b'; label = "snapshot both        the memory and the workspace"; action = 'both' }
            [pscustomobject]@{ key = 'm'; label = "snapshot memory      episodes and beliefs only";    action = 'memory' }
            [pscustomobject]@{ key = 'w'; label = "snapshot workspace   your files only";             action = 'workspace' }
            [pscustomobject]@{ key = 'r'; label = "restore a snapshot";                                action = 'restore' }
            [pscustomobject]@{ key = 'q'; label = "back";                                              action = '' }
        )
        $c = Show-Menu $items "enter select . ctrl+D back"
        Write-Host ""
        if (-not $c -or -not $c.action) { return }
        if ($c.action -eq 'restore') { Invoke-Restore $entry; continue }
        try {
            $z = New-Snapshot $entry $c.action
            Write-Host ("  saved {0}  ({1:N1} KB)" -f $z.Name, ($z.Length / 1KB)) -ForegroundColor Green
        } catch {
            Write-Host "  could not write the snapshot: $($_.Exception.Message)" -ForegroundColor Red
        }
        Write-Host ""
        Wait-Key
    }
}


function script:Invoke-ProjectsPage($suggested) {
    # Everything that is done TO a project: four words, and the list of
    # projects under the first of them. The page listed the projects itself
    # at first, which put two questions on one screen - which project, and
    # what to do with it - and made a menu long enough that Show-Menu's
    # redraw fell off the bottom of a short console.
    #
    # Returns the project to open, or $null to stay at home.
    while ($true) {
        New-Page
        Write-Host ""
        Write-Accent "  Projects"
        Write-Host ""
        $items = @(
            [pscustomobject]@{ key = 'o'; label = "open       open a project and start talking";    action = 'open' }
            [pscustomobject]@{ key = 'n'; label = "new        start a project";                     action = 'new' }
            [pscustomobject]@{ key = 'b'; label = "backups    snapshot a memory, or put one back";  action = 'backups' }
            [pscustomobject]@{ key = 'd'; label = "delete     remove a project, and its memory";    action = 'delete' }
            [pscustomobject]@{ key = 'q'; label = "back";                                           action = '' }
        )
        $c = Show-Menu $items "enter select . ctrl+D back"
        Write-Host ""
        if (-not $c -or -not $c.action) { return $null }
        if ($c.action -eq 'open') {
            $chosen = Invoke-OpenProject $suggested
            if ($chosen) { return $chosen }
        } elseif ($c.action -eq 'new') {
            $made = Invoke-NewProject
            if ($made) { return $made }
        } elseif ($c.action -eq 'delete') {
            Invoke-DeleteProject $null | Out-Null
        } elseif ($c.action -eq 'backups') {
            $which = Invoke-OpenProject $null
            if ($which) { Invoke-BackupMenu $which }
        }
    }
}

function script:Invoke-OpenProject($preferred) {
    # The project list, whether it was reached from the home screen or from
    # /switch inside a conversation. One function because they are the same
    # question, and two copies of it would have drifted the first time one grew
    # a column.
    $entries = @(Read-Registry)
    New-Page
    Write-Host ""
    Write-Accent "  Open a project"
    Write-Host ""
    if ($entries.Count -eq 0) {
        # An empty list rather than a different screen. The home menu offers
        # the same three things on a machine that has never run Pragma and on
        # one with ten projects, so there is one shape to learn.
        Write-Host "  Nothing registered yet." -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  A project is one folder the agent works in, plus a memory of" -ForegroundColor DarkGray
        Write-Host "  its own that Pragma keeps elsewhere. Go back and type" -ForegroundColor DarkGray
        Write-Host "  /new." -ForegroundColor DarkGray
        Write-Host ""
        Wait-Key
        return $null
    }
    $picks = @()
    $sel   = 0
    for ($i = 0; $i -lt $entries.Count; $i++) {
        $e = $entries[$i]
        $picks += [pscustomobject]@{ key = ''
                                     label = ("{0,-18} {1}" -f $e.name, $e.workspace)
                                     entry = $e }
        if ($preferred -and $preferred.name -and $e.name -eq $preferred.name) { $sel = $i }
    }
    $picks += [pscustomobject]@{ key = 'q'; label = "back"; entry = $null }
    $p = Show-Menu $picks "enter select . ctrl+D back" $sel
    Write-Host ""
    if (-not $p) { return $null }
    return $p.entry
}

function script:Invoke-NewProject {
    # A project IS a folder, so the folder is asked first and the name follows
    # from it. The first version asked for a name with no folder in sight, which
    # put the abstract half before the concrete one.
    New-Page
    Write-Host ""
    Write-Accent "  New project"
    Write-Host ""
    Write-Host "  A project is one folder the agent works in, plus a memory of" -ForegroundColor DarkGray
    Write-Host "  its own that Pragma keeps elsewhere." -ForegroundColor DarkGray
    Write-Host "  ctrl+D goes back" -ForegroundColor DarkGray
    Write-Host ""

    $here = (Get-Location).Path
    $ws = Read-Line "  folder  [$here]: "
    if ($null -eq $ws) { return $null }
    if (-not $ws) { $ws = $here }
    $ws = $ws.Trim('"').Trim()
    if (-not (Test-Path $ws)) {
        Write-Host ""
        $mk = Read-Line "  '$ws' does not exist. Create it? [y/N]: "
        if ($mk -notmatch '^[yYsS]') { Write-Host ""; return $null }
        try { New-Item -ItemType Directory -Force -Path $ws -ErrorAction Stop | Out-Null }
        catch {
            Write-Host "  could not create it: $($_.Exception.Message)" -ForegroundColor Red
            Wait-Key; return $null
        }
    }

    $leaf = Split-Path -Leaf ($ws.TrimEnd('\','/'))
    $name = Read-Line "  name    [$leaf]: "
    if ($null -eq $name) { return $null }
    if (-not $name) { $name = $leaf }

    Write-Host ""
    $entry = New-Project $name $ws
    if (-not $entry) { Wait-Key; return $null }
    # The same choices /settings offers, while the project is new: enter takes
    # the recommended one each time, so creating a project stays three Enters.
    Invoke-ProjectChoices $entry
    $fresh = Get-EntryByName $entry.name
    if ($fresh) { return $fresh }
    return $entry
}

function script:Invoke-DeleteProject($entry) {
    New-Page
    Write-Host ""
    Write-Accent "  Delete a project"
    Write-Host ""
    $entries = @(Read-Registry)
    $picks = @()
    foreach ($e in $entries) {
        $picks += [pscustomobject]@{ key = ''
                                     label = ("{0,-18} {1}" -f $e.name, $e.workspace)
                                     entry = $e }
    }
    $picks += [pscustomobject]@{ key = 'q'; label = "back"; entry = $null }
    $p = Show-Menu $picks "enter select . ctrl+D back"
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
    Write-Host "  ctrl+D goes back" -ForegroundColor DarkGray
    $typed = Read-Line "  Type the project name to confirm: "
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


function script:Invoke-MenuLoop($suggested) {
    # The briefing, then the conversation - and the conversation IS the
    # interface. A menu between the two was one screen of navigation standing
    # in front of the thing everyone came for, and every command it held is
    # reachable from inside the talk with a slash.
    #
    # settings, backups and the project lifecycle stay here because they are
    # about the window rather than the conversation, and because they are
    # written in PowerShell while the chat is Python. The chat asks for them
    # through a request file and steps out - consolidating its turns on the way
    # - this runs the page, and then puts the operator back in the chat.
    $active = $null
    $entry  = $null                    # nothing is open until it is chosen
    $notice = ""
    $req = Join-Path ([IO.Path]::GetTempPath()) ("pragma-request-" + $PID + ".json")
    $env:PRAGMA_REQUEST = $req

    while ($true) {
        if (-not $entry) {
            # THE SAME COMMANDS, ALWAYS, typed rather than picked. Opening
            # straight into the last project was convenient exactly once per
            # machine and wrong the rest of the time, so the launcher asks.
            #
            # A prompt instead of a menu, for two reasons. The system has things
            # to set up that belong to no project - the endpoints first of all -
            # and a menu grows a row for each of them. And the conversation
            # already speaks in slash commands, so the screen before it now
            # speaks the same language: /configure means the same thing here
            # and inside a chat.
            New-Page
            Write-Host ""
            Show-Logo
            Write-Host ""
            $n = @(Read-Registry).Count
            if ($n -eq 0) { Write-Host "  No projects yet." -ForegroundColor DarkGray }
            elseif ($n -eq 1) { Write-Host "  1 project" -ForegroundColor DarkGray }
            else { Write-Host ("  {0} projects" -f $n) -ForegroundColor DarkGray }
            Write-Host ""
            # What is done TO a project - open it, start one, back one up,
            # remove one - is one family, because from here that is the only
            # kind of thing there is to do. With nothing registered the family
            # would be four doors onto an empty room, so the page offers /new
            # and the endpoint you will need anyway. The Linux launcher builds
            # the same rows from pragma_home.rows(); keep the two in step.
            $rows = if ($n -eq 0) {
                @(@("/new",       "start your first project"),
                  @("/configure", "set up the endpoint"),
                  @("/help",      "what each command does"),
                  @("/exit",      "leave"))
            } else {
                @(@("/projects",  "open . new . backups . delete"),
                  @("/jobs",      "what the memory is writing"),
                  @("/configure", "set up the endpoint"),
                  @("/help",      "what each command does"),
                  @("/exit",      "leave"))
            }
            foreach ($row in $rows) {
                Write-Host ("  " + (Paint ("{0,-12}" -f $row[0]) 'accent') + (Paint $row[1] 'dim'))
            }
            Write-Host ""
            if ($notice) { Write-Host "  $notice" -ForegroundColor Yellow; Write-Host "" }
            $notice = ""

            # Called as a statement and read back from a variable, never as
            # `$choice = Read-HomeCommand`: assigning a function's result
            # captures everything it emits, including the stdout of the
            # Python it runs. The prompt then went into the variable instead of
            # onto the screen, and the page sat there looking like it waited.
            $script:HomeChoice = $null
            Read-HomeCommand
            $choice = $script:HomeChoice
            if (-not $choice) { continue }
            $cmd = $choice.action
            $arg = $choice.arg

            # An if-chain, not a switch: inside a PowerShell switch, continue
            # and break act on the switch, not on this loop.
            if (-not $cmd) { continue }
            if ($cmd -eq 'exit') { New-Page; return }
            if ($cmd -in @('open', 'o')) {
                if ($arg) {
                    $entry = Get-EntryByName $arg
                    if (-not $entry) { $notice = "No project named '$arg'." }
                } else {
                    $entry = Invoke-OpenProject $suggested
                }
            } elseif ($cmd -in @('new', 'n')) {
                $entry = Invoke-NewProject
            } elseif ($cmd -eq 'projects') {
                $entry = Invoke-ProjectsPage $suggested
            } elseif ($cmd -eq 'delete') {
                # From here there is no project open, so nothing to go back to:
                # the page lists them all and $null is what "none of them" means.
                Invoke-DeleteProject $null | Out-Null
            } elseif ($cmd -eq 'backups') {
                $which = if ($arg) { Get-EntryByName $arg } else { Invoke-OpenProject $null }
                if ($which) { Invoke-BackupMenu $which }
            } elseif ($cmd -eq 'configure') {
                Invoke-Configure
            } elseif ($cmd -eq 'clear') {
                # Nothing to do here: the loop draws the page again on a clean screen.
            } elseif ($cmd -notin @('help', '?')) {
                $notice = "'/$cmd' is not a command here. Try /projects, /configure or /exit."
            }
            continue
        }
        if (-not $active -or $active.name -ne $entry.name) {
            if (-not (Enable-Project $entry)) { return }
            $active = Get-EntryByName $entry.name
            $entry = $active
        }

        New-Page
        Show-Brief $entry (Get-Brief $entry)
        Remove-Item -LiteralPath $req -Force -ErrorAction SilentlyContinue

        # global: is not decoration. Inside this module `pragma` is the
        # launcher's own function, which has no -Chat; the session script's is
        # the one dot-sourced into the global scope.
        global:pragma -Chat

        $want = ""
        if (Test-Path $req) {
            try { $want = "$((Get-Content -Raw $req | ConvertFrom-Json).action)" } catch { }
            Remove-Item -LiteralPath $req -Force -ErrorAction SilentlyContinue
        }
        if (-not $want) {
            # /exit, or Ctrl+C: the conversation ended on its own terms. This
            # is the launcher's other exit, and the one people actually use:
            # it does not pass the home prompt, so the reminder lives here too.
            if (-not (Confirm-LeaveWhileWriting)) {
                $suggested = $entry
                $entry = $null
                $active = $null
                continue
            }
            New-Page
            Write-Host ""
            Write-Host "  the window stays on '$($entry.name)' - pragma to come back" -ForegroundColor DarkGray
            Write-Host ""
            return
        }

        if ($want -eq 'refresh') { continue }

        switch ($want) {
            'settings' { $entry = Invoke-SettingsMenu $entry }
            'backups'  { Invoke-BackupMenu $entry }
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
                $chosen = Invoke-OpenProject $entry
                if ($chosen) { $entry = $chosen }
            }
            'close' {
                # Back to the home prompt: /open, /new, /configure, /exit.
                # The project stays the suggestion in the /open list.
                $suggested = $entry
                $entry = $null
                $active = $null
            }
        }
    }
}


function script:Test-CtrlD($key) {
    # Ctrl+D as ReadKey reports it: the D key with Control held, or the raw
    # end-of-transmission character some hosts deliver instead.
    if ($null -eq $key) { return $false }
    if ($key.Key -eq [ConsoleKey]::D -and ($key.Modifiers -band [ConsoleModifiers]::Control)) { return $true }
    return ([int]$key.KeyChar -eq 4)
}

function script:Read-Line([string]$prompt) {
    # Read-Host, except that Ctrl+D (or Esc) goes back and returns $null.
    # Read-Host cannot: on Windows Ctrl+D is just one more character in the
    # line, so a question asked with it was the one place in Pragma where the
    # key that goes back everywhere else did nothing.
    Write-Host $prompt -NoNewline
    if ([Console]::IsInputRedirected) { return [Console]::ReadLine() }
    $buf = New-Object System.Text.StringBuilder
    while ($true) {
        $k = [Console]::ReadKey($true)
        if ((Test-CtrlD $k) -or $k.Key -eq [ConsoleKey]::Escape) { Write-Host ""; return $null }
        if ($k.Key -eq [ConsoleKey]::Enter) { Write-Host ""; return $buf.ToString() }
        if ($k.Key -eq [ConsoleKey]::Backspace) {
            if ($buf.Length -gt 0) {
                $buf.Length = $buf.Length - 1
                Write-Host "`b `b" -NoNewline
            }
            continue
        }
        if (-not [char]::IsControl($k.KeyChar)) {
            [void]$buf.Append($k.KeyChar)
            Write-Host $k.KeyChar -NoNewline
        }
    }
}

function script:Invoke-Configure {
    # The same tool /configure runs inside a conversation, reachable before any
    # project is open: which model Pragma talks to is a property of the machine,
    # not of a project. Nothing here has loaded .env yet, so the next chat
    # started from this window picks the change up.
    # No header drawn here: the page clears the screen and writes its own the
    # moment it starts, so one printed first is a flash and nothing more.
    New-Page
    $tool = Join-Path $PSScriptRoot "pragma_configure.py"
    if (-not (Test-Path $script:Python)) {
        Write-Host "  The Python environment is missing: $($script:Python)" -ForegroundColor Red
        Write-Host "  Run install.ps1 again." -ForegroundColor DarkGray
    } elseif (-not (Test-Path $tool)) {
        Write-Host "  This needs $tool, which is missing from this copy of Pragma." -ForegroundColor Red
    } else {
        # The page is its own loop and ends when you leave it, with ctrl+D or
        # /done, so there is nothing left to pause on afterwards.
        & $script:Python $tool
        return
    }
    Write-Host ""
    Wait-Key
}

function script:Get-MemoryBusy {
    # What the memory is still writing, in any project: asked of the same
    # Python that knows where each project keeps its jobs. Nothing at all if
    # it cannot be asked - a launcher that cannot check must not become a
    # launcher that cannot be left.
    $tool = Join-Path $PSScriptRoot "pragma_home.py"
    if (-not ((Test-Path $script:Python) -and (Test-Path $tool))) { return @() }
    try {
        $raw = & $script:Python $tool --jobs
        if (-not $raw) { return @() }
        $data = ($raw -join "") | ConvertFrom-Json
        if ($null -eq $data) { return @() }
        return @($data)
    } catch { return @() }
}

function script:Confirm-LeaveWhileWriting {
    # Leaving costs nothing - the consolidation is its own process and carries
    # on - but leaving without knowing the memory is mid-sentence is exactly
    # what makes a memory feel unreliable. So the last step out is held once.
    # Ctrl+D twice in a row goes anyway; anything else goes back.
    $busy = @(Get-MemoryBusy)
    if ($busy.Count -eq 0) { return $true }
    Write-Host ""
    foreach ($job in $busy) {
        Write-Host ("  the memory is still writing - " + $job.project) -ForegroundColor Yellow -NoNewline
        Write-Host ("   " + $job.step) -ForegroundColor DarkGray
    }
    Write-Host "  it finishes on its own. ctrl+D twice, quickly, to leave anyway;" -ForegroundColor DarkGray
    Write-Host "  any other key goes back to the home screen." -ForegroundColor DarkGray
    Write-Host ""
    if ([Console]::IsInputRedirected) { return $true }
    if (-not (Test-CtrlD ([Console]::ReadKey($true)))) { return $false }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $again = [Console]::ReadKey($true)
    return ((Test-CtrlD $again) -and ($watch.ElapsedMilliseconds -le 1500))
}

function script:Read-HomeCommand {
    # The line is read by pragma_home.py, which gives it what the chat prompt
    # has and PowerShell lacks: commands completed as they are typed, and a
    # grey hint on the empty line. /help and mistakes are handled there.
    # If Python cannot run, a plain line read keeps the launcher usable.
    $out = Join-Path ([IO.Path]::GetTempPath()) ("pragma-home-" + $PID + ".json")
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
    $tool = Join-Path $PSScriptRoot "pragma_home.py"
    if ((Test-Path $script:Python) -and (Test-Path $tool)) {
        & $script:Python $tool --out $out
        if (Test-Path $out) {
            try {
                $r = Get-Content -Raw $out | ConvertFrom-Json
                Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
                $script:HomeChoice = [pscustomobject]@{ action = "$($r.action)"; arg = "$($r.arg)" }
                return
            } catch { }
        }
    }
    Write-Host "  > " -NoNewline
    $line = [Console]::ReadLine()
    if ($null -eq $line) { $script:HomeChoice = [pscustomobject]@{ action = 'exit'; arg = '' }; return }
    $parts = @($line.Trim() -split '\s+', 2)
    $cmd = $parts[0].TrimStart('/').ToLowerInvariant()
    if ($cmd -in @('quit', 'q')) { $cmd = 'exit' }
    $arg = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "" }
    $script:HomeChoice = [pscustomobject]@{ action = $cmd; arg = $arg }
}

function script:Wait-Key {
    Write-Host "  any key to go back" -ForegroundColor DarkGray
    [Console]::ReadKey($true) | Out-Null
    Write-Host ""
}

# The memory menu that used to be here is gone: map, beliefs, diff, oblivion
# and last are /memory <view> in the conversation, where looking at the store
# does not mean leaving what you were doing. Nothing called this.


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
