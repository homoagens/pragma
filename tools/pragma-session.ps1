# pragma-session.ps1 - the batch session commands, shared by every session.
#
# You do not run this file directly. `new-session.ps1` creates a small
# pragma.ps1 inside a session folder; that file sets $PragmaSession and then
# dot-sources this one:
#
#     . D:\my-notes\pragma.ps1
#
# WHY IT LIVES HERE AND NOT IN THE SESSION FILE. The logic is written once, in
# the repository, so improvements reach every session the next time it is
# entered. A generator that copied 300 lines into each session folder would
# leave every existing session frozen at the day it was created.
#
# Unknown or missing keys in $PragmaSession fall back to a default, so a
# session file written by an older version keeps working after an upgrade.
#
# NOTE: keep this file pure ASCII - PowerShell 5.1 reads BOM-less files as
# ANSI, and a fancy dash or quote silently corrupts the script.

$script:PragmaSessionVersion = "v1"

if (-not (Get-Variable -Name PragmaSession -Scope Global -ErrorAction SilentlyContinue) -and
    -not (Get-Variable -Name PragmaSession -Scope Script -ErrorAction SilentlyContinue) -and
    -not $PragmaSession) {
    Write-Host "pragma-session.ps1 is not meant to be dot-sourced directly." -ForegroundColor Red
    Write-Host "Create a session first:   .\new-session.ps1"
    Write-Host "Then enter it:            . <session folder>\pragma.ps1"
    return
}

function script:Cfg([string]$key, $default) {
    if ($PragmaSession.ContainsKey($key)) {
        $v = $PragmaSession[$key]
        if ($null -ne $v -and "$v" -ne "") { return $v }
    }
    return $default
}

$script:SName    = Cfg "Name"     (Split-Path (Cfg "Root" ".") -Leaf)
$script:SRoot    = Cfg "Root"     $null
$script:SRepo    = Cfg "Repo"     $null
$script:SSteps   = Cfg "MaxSteps" 50
$script:SProto   = Cfg "Protocol" "native"

if (-not $script:SRoot -or -not $script:SRepo) {
    Write-Host "This session file is incomplete: Root and Repo are required." -ForegroundColor Red
    return
}

$script:PragmaPy = Join-Path $script:SRepo "venv\Scripts\python.exe"
if (-not (Test-Path $script:PragmaPy)) {
    Write-Host "Python environment not found at $script:PragmaPy" -ForegroundColor Red
    Write-Host "Run install.bat in the Pragma repository first."
    return
}

# --- environment for this window ---------------------------------------------
# Set when a value is given, cleared when it is not, so an emptied field really
# hands control back to the repository default instead of leaving a stale value
# from an earlier session in the same window.
function script:Set-SessionEnv([string]$name, $value) {
    if ($null -ne $value -and "$value" -ne "") { Set-Item -Path "Env:$name" -Value "$value" }
    else { Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue }
}

$env:PRAGMA_WORKSPACE = Join-Path $script:SRoot "workspace"
$env:PRAGMA_DATA_DIR  = Join-Path $script:SRoot ".memoria"
Set-SessionEnv "PRAGMA_PROFILE"    (Cfg "Profile" "")
Set-SessionEnv "LLM_TOOL_PROTOCOL" $script:SProto
Set-SessionEnv "CONTEXT_WINDOW"    (Cfg "ContextWindow"  "")
Set-SessionEnv "MAX_TOKENS"        (Cfg "MaxTokens"      "")
Set-SessionEnv "CODING_MAX_TOKENS" (Cfg "MaxTokens"      "")
Set-SessionEnv "SKILL_MAX_TOKENS"  (Cfg "SkillMaxTokens" "")
Set-SessionEnv "LLM_TIMEOUT"       (Cfg "Timeout"        "")
# Real time, real forgetting: a session store is never accelerated implicitly.
# `pragma -Time` is the only way to move it, and it asks first.
Remove-Item Env:EPISODE_DECAY_HALF_LIFE_DAYS -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force $env:PRAGMA_WORKSPACE | Out-Null
New-Item -ItemType Directory -Force $env:PRAGMA_DATA_DIR  | Out-Null
$script:Journal = Join-Path $env:PRAGMA_WORKSPACE "journal.md"

# --- helpers ------------------------------------------------------------------

function script:Invoke-MemTool([string[]]$toolArgs) {
    Push-Location $script:SRepo
    if ($toolArgs -and $toolArgs[0]) {
        & $script:PragmaPy examples_memory\mem_map.py @toolArgs
    } else {
        & $script:PragmaPy examples_memory\mem_map.py
    }
    Pop-Location
}

function script:Invoke-Session([string]$task, [bool]$useMemory = $true) {
    Push-Location $script:SRepo
    if ($useMemory) {
        & $script:PragmaPy -m agent.batch --memory --max-steps $script:SSteps --task "$task"
    } else {
        & $script:PragmaPy -m agent.batch --max-steps $script:SSteps --task "$task"
    }
    Pop-Location
}

# Reads the environment, not the config, because what took effect is the truth.
function script:Get-BudgetLine {
    $d = "repo"
    $ctx = if ($env:CONTEXT_WINDOW)   { $env:CONTEXT_WINDOW }   else { $d }
    $mt  = if ($env:MAX_TOKENS)       { $env:MAX_TOKENS }       else { $d }
    $sk  = if ($env:SKILL_MAX_TOKENS) { $env:SKILL_MAX_TOKENS } else { $d }
    # "120s" when set, plain "repo" when not - never "repos".
    $to  = if ($env:LLM_TIMEOUT) { "$($env:LLM_TIMEOUT)s" } else { $d }
    "ctx $ctx / out $mt / skills $sk / timeout $to"
}

# Time machine: a BOUNDED jump. It never changes the half-life. At the end of
# the wait the jump is banked by shifting every episode's timestamps back by
# <months> * half_life days (convention: 1 half-life = 1 month), which bakes
# exactly that much extra decay into the stored state, permanently. Then the
# real dormancy sweep runs. After the command, physical time and story time run
# at the same pace again.
#
# On a store you actually care about this falsifies when things happened, and
# there is no undo - hence the typed confirmation and the reminder to back up.
function script:Invoke-TimeMachine([double]$Minutes, [double]$Months) {
    if ($Minutes -lt 0 -or $Months -le 0) {
        Write-Host "Usage: pragma -Time <minutes> <months>"
        Write-Host "  e.g. pragma -Time 1 12   -> 12 months pass over 1 real minute"
        Write-Host "       pragma -Time 0 12   -> 12 months pass instantly"
        return
    }

    Write-Host ""
    Write-Host "TIME MACHINE on session '$script:SName'" -ForegroundColor Yellow
    Write-Host ("  every episode will be aged by {0} month(s)." -f $Months)
    Write-Host "  This rewrites their timestamps permanently. There is no undo."
    Write-Host "  Anything that falls below the threshold becomes dormant."
    Write-Host "  Run 'pragma -Backup' first if you want to come back from this."
    $answer = Read-Host "Type 'age' to confirm"
    if ($answer -ne "age") {
        Write-Host "aborted - nothing touched" -ForegroundColor Green
        return
    }

    if ($Minutes -gt 0) {
        $totalSeconds = [Math]::Round($Minutes * 60)
        $width = 38
        $start = Get-Date
        while ($true) {
            $elapsed = ((Get-Date) - $start).TotalSeconds
            if ($elapsed -ge $totalSeconds) { break }
            $filled = [Math]::Floor($width * ($elapsed / $totalSeconds))
            $bar = ("#" * $filled) + ("-" * ($width - $filled))
            $remaining = [Math]::Max(0, $totalSeconds - $elapsed)
            $mm = [Math]::Floor($remaining / 60)
            $ss = [Math]::Floor($remaining % 60)
            Write-Host -NoNewline ("`r  time machine [{0}] {1:00}:{2:00} " -f $bar, $mm, $ss)
            Start-Sleep -Milliseconds 500
        }
        Write-Host ("`r  time machine [{0}] done.{1}" -f ("#" * $width), (" " * 14))
        Write-Host ""
    }

    Invoke-MemTool @("--jump", "$Months")
    Write-Host ""
    Write-Host "Check with pragma -Map / pragma -Oblio." -ForegroundColor Cyan
}

function script:Show-PragmaInfo {
    Write-Host ""
    Write-Host "pragma session '$script:SName'   [$script:PragmaSessionVersion]" -ForegroundColor Cyan
    Write-Host '  pragma "task"           run a session, memory on'
    Write-Host '  pragma "task" -NoMem    run a session with NO memory (stateless)'
    Write-Host '  pragma -Note "..."      record an experience (journal + episode)'
    Write-Host '  pragma -Ask "..."       ask memory something, no file changes'
    Write-Host "  pragma -Map             what is in memory now"
    Write-Host "  pragma -Beliefs         what it has concluded"
    Write-Host "  pragma -Diff            meanings it has revised, before/after"
    Write-Host "  pragma -Oblio           what has faded"
    Write-Host "  pragma -Last            the newest episode, in full"
    Write-Host "  pragma -Sizes           how wordy the store is vs what recall shows"
    Write-Host "  pragma -Mem             raw learnings.json"
    Write-Host "  pragma -Backup          snapshot the store (do this often)"
    Write-Host "  pragma -Time <min> <mo> age the memory by <mo> months (asks first)" -ForegroundColor DarkGray
    Write-Host "  pragma -Info            this list"
    Write-Host "  pragma -Off             unset everything for this window"
    Write-Host "  pragma -Reset           WIPE this memory (typed confirmation)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  session   : $script:SName"
    Write-Host "  memory    : $env:PRAGMA_DATA_DIR"
    Write-Host "  workspace : $env:PRAGMA_WORKSPACE"
    Write-Host "  profile   : $(if ($env:PRAGMA_PROFILE) { $env:PRAGMA_PROFILE } else { '(default .env model)' })"
    Write-Host "  max steps : $script:SSteps per session"
    Write-Host "  protocol  : $(if ($env:LLM_TOOL_PROTOCOL) { $env:LLM_TOOL_PROTOCOL } else { 'text (repo default)' })"
    Write-Host "  budgets   : $(Get-BudgetLine)"
    Write-Host "  half-life : 30 days (real time)"
}

function pragma {
    param(
        [Parameter(Position = 0)]$A,
        [Parameter(Position = 1)]$B,
        [switch]$NoMem,
        [switch]$Note, [switch]$Ask, [switch]$Time,
        [switch]$Map, [switch]$Beliefs, [switch]$Diff, [switch]$Oblio,
        [switch]$Last, [switch]$Mem, [switch]$Sizes,
        [switch]$Backup, [switch]$Reset, [switch]$Off, [switch]$Info
    )

    if ($Info)    { Show-PragmaInfo;            return }
    if ($Map)     { Invoke-MemTool "";          return }
    if ($Beliefs) { Invoke-MemTool "--beliefs"; return }
    if ($Diff)    { Invoke-MemTool "--diff";    return }
    if ($Oblio)   { Invoke-MemTool "--oblio";   return }
    if ($Last)    { Invoke-MemTool "--last";    return }
    if ($Sizes)   { Invoke-MemTool "--sizes";   return }

    if ($Mem) {
        $p = Join-Path $env:PRAGMA_DATA_DIR "learnings.json"
        if (Test-Path $p) { Get-Content $p } else { Write-Host "(nothing learned yet)" }
        return
    }

    if ($Backup) {
        $stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
        $dir   = Join-Path $script:SRoot "backups"
        New-Item -ItemType Directory -Force $dir | Out-Null
        # Never overwrite an existing snapshot: a backup that silently replaces
        # a backup is not a backup. Two in the same second get a suffix.
        $dest = Join-Path $dir "memory_$stamp.zip"
        $i = 2
        while (Test-Path $dest) {
            $dest = Join-Path $dir "memory_${stamp}_$i.zip"
            $i++
        }
        Compress-Archive -Path (Join-Path $env:PRAGMA_DATA_DIR "*") -DestinationPath $dest -CompressionLevel Optimal
        $kb = [Math]::Round((Get-Item $dest).Length / 1KB, 1)
        Write-Host "backup: $dest  ($kb KB)" -ForegroundColor Green
        Write-Host "  $(@(Get-ChildItem $dir -Filter 'memory_*.zip').Count) snapshot(s) in $dir"
        return
    }

    if ($Note) {
        if (-not $A) { Write-Host 'Usage: pragma -Note "what happened"'; return }
        $today = Get-Date -Format "yyyy-MM-dd"
        $task  = "Append this entry to journal.md under a '## $today' heading " +
                 "(create the file or the heading if missing, keep earlier " +
                 "entries intact), then tell me in one or two sentences what " +
                 "it means in the light of what you already remember. " +
                 "The entry: $A"
        Invoke-Session $task
        return
    }

    if ($Ask) {
        if (-not $A) { Write-Host 'Usage: pragma -Ask "your question"'; return }
        Invoke-Session ("Answer from memory only. Do not read, write or " +
                        "modify any file. If you are unsure, say so. " +
                        "Question: $A")
        return
    }

    if ($Time) {
        Invoke-TimeMachine ([double]$A) ([double]$B)
        return
    }

    if ($Reset) {
        Write-Host "This deletes the whole memory of session '$script:SName'" -ForegroundColor Red
        Write-Host "at $env:PRAGMA_DATA_DIR" -ForegroundColor Red
        Write-Host "Episodes, beliefs, every revision. There is no undo." -ForegroundColor Red
        Write-Host "Run 'pragma -Backup' first if you are not certain."
        $answer = Read-Host "Type the session name ($script:SName) to confirm"
        if ($answer -ceq $script:SName) {
            Remove-Item -Recurse -Force $env:PRAGMA_DATA_DIR -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force $env:PRAGMA_DATA_DIR | Out-Null
            Write-Host "memory wiped - starting from nothing"
        } else {
            Write-Host "aborted - nothing touched" -ForegroundColor Green
        }
        return
    }

    if ($Off) {
        Remove-Item Env:PRAGMA_WORKSPACE, Env:PRAGMA_DATA_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:PRAGMA_PROFILE, Env:LLM_TOOL_PROTOCOL -ErrorAction SilentlyContinue
        Remove-Item Env:CONTEXT_WINDOW, Env:MAX_TOKENS, Env:CODING_MAX_TOKENS -ErrorAction SilentlyContinue
        Remove-Item Env:SKILL_MAX_TOKENS, Env:LLM_TIMEOUT -ErrorAction SilentlyContinue
        Write-Host "off - defaults restored for this window"
        return
    }

    if (-not $A) { Show-PragmaInfo; return }
    Invoke-Session "$A" (-not $NoMem)
}

# Start (or settle) the story clock, so -Map can report how long this store has
# been running.
Invoke-MemTool "--clock-set" | Out-Null

# --- banner and preflight -----------------------------------------------------
Write-Host ""
Write-Host "pragma session '$script:SName'   [$script:PragmaSessionVersion]" -ForegroundColor Cyan
Write-Host "  memory    : $env:PRAGMA_DATA_DIR"
Write-Host "  workspace : $env:PRAGMA_WORKSPACE"
Write-Host "  protocol  : $(if ($env:LLM_TOOL_PROTOCOL) { $env:LLM_TOOL_PROTOCOL } else { 'text (repo default)' })"
Write-Host "  budgets   : $(Get-BudgetLine)"

Push-Location $script:SRepo
$served = & $script:PragmaPy -c @"
import sys
sys.path.insert(0, 'core')
import llm_client, config
ok, d = llm_client.ping_models()
print(('OK|' if ok else 'DOWN|') + (getattr(config, 'SERVED_MODEL', '') or '') + '|' + d)
"@ 2>&1
Pop-Location

$parts = ("$served" -split '\|')
if ($parts[0] -eq "OK") {
    Write-Host "  serving   : $($parts[1])" -ForegroundColor Green
    # A profile that names a different model than the endpoint is serving means
    # memories would be written under the wrong attribution. Compare loosely -
    # llama.cpp reports the full GGUF name while a profile carries a short one -
    # and warn only when neither contains the other: a warning that cries wolf
    # is a warning you stop reading.
    $want = $null
    $prof = Cfg "Profile" ""
    if ($prof) {
        try {
            $mj = Get-Content (Join-Path $script:SRepo "examples_memory\models.json") -Raw | ConvertFrom-Json
            $want = $mj.$prof.model
        } catch { }
    }
    $norm = { param($s) ($s -replace '[^a-zA-Z0-9]', '').ToLower() }
    $nWant   = & $norm $want
    $nServed = & $norm $parts[1]
    if ($nWant -and $nServed -and
        -not ($nServed.Contains($nWant) -or $nWant.Contains($nServed))) {
        Write-Host "  WARNING: profile '$prof' says '$want'," -ForegroundColor Yellow
        Write-Host "           but the endpoint is serving '$($parts[1])'." -ForegroundColor Yellow
    }
} else {
    Write-Host "  serving   : backend DOWN - start your LLM server first" -ForegroundColor Yellow
}
Write-Host '  usage     : pragma "your task"   |   pragma -Info for all commands'
