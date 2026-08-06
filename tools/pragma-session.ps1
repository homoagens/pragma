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

# Bump on every change to this file. The banner and -Info print it, so a
# window that dot-sourced an older copy shows a stale number and the mismatch
# is visible at a glance instead of surfacing as a missing command.
$script:PragmaSessionVersion = "v6 (live session, sampling)"

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
# The memory faculties, separately. Empty follows SkillMaxTokens, as it always
# did; set it when the model reasons its way through a three-line verdict and
# you would rather it did not do so at the agent's budget.
Set-SessionEnv "MEMORY_MAX_TOKENS" (Cfg "MemoryMaxTokens" "")
# "" | select | all. Asks the chat template to skip the thinking phase on
# memory calls only - the agent keeps thinking either way. "select" silences
# the faculties that CHOOSE (curator, segmenter); "all" also silences those
# that WRITE, whose mistakes end up in the store instead of expiring with the
# turn. Off unless set: this changes the judgement, not only the speed.
Set-SessionEnv "MEMORY_NO_THINK"   (Cfg "MemoryNoThink"   "")
Set-SessionEnv "LLM_TIMEOUT"       (Cfg "Timeout"        "")
# Sampling. Temperature is always sent by Pragma, so leaving it empty falls
# back to the repository default (0.0) and NOT to the server's. The other three
# are only sent when set here: empty really does mean "the server decides",
# which is where a model's recommended preset usually already lives.
Set-SessionEnv "DEFAULT_TEMPERATURE" (Cfg "Temperature" "")
Set-SessionEnv "TOP_K"               (Cfg "TopK"        "")
Set-SessionEnv "TOP_P"               (Cfg "TopP"        "")
Set-SessionEnv "MIN_P"               (Cfg "MinP"        "")
# Real time, real forgetting: a session store is never accelerated implicitly.
# `pragma -Time` is the only way to move it, and it asks first.
Remove-Item Env:EPISODE_DECAY_HALF_LIFE_DAYS -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force $env:PRAGMA_WORKSPACE | Out-Null
New-Item -ItemType Directory -Force $env:PRAGMA_DATA_DIR  | Out-Null
$script:Journal  = Join-Path $env:PRAGMA_WORKSPACE "journal.md"
$script:Contract = Join-Path $env:PRAGMA_WORKSPACE "PRAGMA.md"

# Standing instructions are injected before every task, so it matters whether
# any are actually in force. HTML comments do not count - the shipped template
# is entirely commented out, and reporting it as active would be a lie.
function script:Get-ContractLine {
    if (-not (Test-Path $script:Contract)) { return "none (no PRAGMA.md)" }
    try {
        $raw = Get-Content $script:Contract -Raw -ErrorAction Stop
    } catch { return "unreadable" }
    $body = [regex]::Replace("$raw", '(?s)<!--.*?-->', '').Trim()
    if (-not $body) { return "empty - edit PRAGMA.md to add standing rules" }
    $n = @($body -split "`n" | Where-Object { $_.Trim() }).Count
    "$n line(s) in force"
}

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

# A live session: many turns in one conversation, consolidated on exit.
# Experimental - `pragma "task"` remains the settled one-shot path.
function script:Invoke-Chat([bool]$showThoughts = $false) {
    Push-Location $script:SRepo
    # The model's per-step note is hidden by default: in a conversation the
    # reply belongs in the closing message, and showing both made the agent
    # answer twice. -Verbose brings it back when what you want to see is what
    # the model told itself.
    if ($showThoughts) {
        & $script:PragmaPy -m agent.chat --memory --max-steps $script:SSteps --show-thoughts
    } else {
        & $script:PragmaPy -m agent.chat --memory --max-steps $script:SSteps
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
    # Stated separately from "skills" now that it can differ. A session that
    # waits a long time before its first step is usually waiting on the
    # curator, and this is the number that explains it.
    $mem = if ($env:MEMORY_MAX_TOKENS) { $env:MEMORY_MAX_TOKENS } else { "as skills" }
    # Stated because it changes what the faculties DO, not only how fast, and
    # WHICH of them, because silencing the writers is the consequential half.
    if ($env:MEMORY_NO_THINK) { $mem = "$mem no-think:$($env:MEMORY_NO_THINK)" }
    # "120s" when set, plain "repo" when not - never "repos".
    $to  = if ($env:LLM_TIMEOUT) { "$($env:LLM_TIMEOUT)s" } else { $d }
    "ctx $ctx / out $mt / skills $sk / memory $mem / timeout $to"
}

# What this window will actually SEND. Printed on entry because a sampling
# setting is invisible once you are talking to the agent, and an experiment run
# under the wrong preset looks exactly like an experiment run under the right
# one. The distinction that matters is stated: temperature is always sent, so
# empty means Pragma's 0.0; the rest are omitted when empty, so the server's
# launch-time defaults apply.
function script:Get-SamplingLine {
    $t = if ($env:DEFAULT_TEMPERATURE) { $env:DEFAULT_TEMPERATURE } else { "0.0 (repo)" }
    $line = "temp $t"
    $extra = @()
    if ($env:TOP_K) { $extra += "top_k $($env:TOP_K)" }
    if ($env:TOP_P) { $extra += "top_p $($env:TOP_P)" }
    if ($env:MIN_P) { $extra += "min_p $($env:MIN_P)" }
    if ($extra.Count -gt 0) { $line += " / " + ($extra -join " / ") }
    else { $line += " / top_k,top_p,min_p from the server" }
    if ($env:DEFAULT_TEMPERATURE -eq "0" -or $env:DEFAULT_TEMPERATURE -eq "0.0" -or
        -not $env:DEFAULT_TEMPERATURE) {
        $line += "  [greedy: the others have no effect]"
    }
    return $line
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
    Write-Host "  pragma -Chat            live session: many turns, one conversation" -ForegroundColor DarkGray
    Write-Host "  pragma -Chat -Verbose   the same, showing the model's per-step notes" -ForegroundColor DarkGray
    Write-Host "  pragma -Map             what is in memory now"
    Write-Host "  pragma -Beliefs         what it has concluded"
    Write-Host "  pragma -Diff            meanings it has revised, before/after"
    Write-Host "  pragma -Oblio           what has faded"
    Write-Host "  pragma -Last            the newest episode, in full"
    Write-Host "  pragma -Sizes           how wordy the store is vs what recall shows"
    Write-Host "  pragma -Sampling        what is sent, what the server adds, what applies"
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
    Write-Host "  sampling  : $(Get-SamplingLine)"
    Write-Host "  rules     : $(Get-ContractLine)"
    Write-Host "  half-life : 30 days (real time)"
}

function pragma {
    param(
        [Parameter(Position = 0)]$A,
        [Parameter(Position = 1)]$B,
        [switch]$NoMem,
        [switch]$Note, [switch]$Ask, [switch]$Time, [switch]$Chat,
        [switch]$Map, [switch]$Beliefs, [switch]$Diff, [switch]$Oblio,
        [switch]$Last, [switch]$Mem, [switch]$Sizes, [switch]$Sampling,
        [switch]$Backup, [switch]$Reset, [switch]$Off, [switch]$Info
    )

    if ($Info)    { Show-PragmaInfo;            return }
    # -Verbose is NOT declared above: an attribute like [Parameter(Position=0)]
    # already makes this an advanced function, so PowerShell supplies -Verbose
    # itself and declaring it again is a duplicate-parameter error. Reading the
    # common one gives the same spelling without fighting the shell.
    if ($Chat)    { Invoke-Chat ($PSBoundParameters.ContainsKey('Verbose')); return }
    if ($Map)     { Invoke-MemTool "";          return }
    if ($Beliefs) { Invoke-MemTool "--beliefs"; return }
    if ($Diff)    { Invoke-MemTool "--diff";    return }
    if ($Oblio)   { Invoke-MemTool "--oblio";   return }
    if ($Last)    { Invoke-MemTool "--last";    return }
    if ($Sizes)   { Invoke-MemTool "--sizes";   return }
    if ($Sampling) { Show-Sampling;            return }

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
        Remove-Item Env:SKILL_MAX_TOKENS, Env:MEMORY_MAX_TOKENS, Env:MEMORY_NO_THINK, Env:LLM_TIMEOUT -ErrorAction SilentlyContinue
        Write-Host "off - defaults restored for this window"
        return
    }

    if (-not $A) { Show-PragmaInfo; return }
    Invoke-Session "$A" (-not $NoMem)
}

# The full sampling picture, which no single source can give.
#
# WHY THIS COMMAND EXISTS. The banner and -Info read this window's environment:
# they say what Pragma WILL SEND, which is only half the story. The three
# samplers Pragma omits are decided by the server, and a line that says "from
# the server" without naming the values tells you what is missing rather than
# what will happen. Worse, the environment is a snapshot taken at dot-source:
# edit the session file without re-entering it and -Info reports the old values
# with no hint that it is doing so.
#
# So this asks. Three columns: what the session sends, what the server would
# supply, and what therefore applies. Plus, when the server has served at least
# one request, what it ACTUALLY used - the only line here that is a measurement
# rather than a deduction.
function script:Show-Sampling {
    $probe = @'
import json, sys
sys.path.insert(0, "core")
import config, llm_client
url, _k = llm_client._resolved_endpoint(None, None)
out = {"base_url": url,
       "summary_temperature": getattr(config, "SUMMARY_TEMPERATURE", None),
       "sent": dict({"temperature": config.DEFAULT_TEMPERATURE},
                    **config.sampling_extras())}
root = url[:-3] if url.endswith("/v1") else url
keys = ("temperature", "top_k", "top_p", "min_p")


def pick(src, k):
    for d in src:
        if isinstance(d, dict) and d.get(k) is not None:
            v = d[k]
            return round(v, 4) if isinstance(v, float) else v
    return None


try:
    import requests
    p = requests.get(root.rstrip("/") + "/props", timeout=5).json()
    dgs = p.get("default_generation_settings") or {}
    out["server"] = {k: pick((dgs.get("params") or {}, dgs, p), k) for k in keys}
except Exception as e:
    out["server_error"] = str(e)[:100]
try:
    s = requests.get(root.rstrip("/") + "/slots", timeout=5).json()
    slot = s[0] if isinstance(s, list) and s else s
    out["last"] = {k: pick((slot.get("params") or {}, slot), k) for k in keys}
except Exception:
    pass
print(json.dumps(out))
'@
    $probeFile = Join-Path $env:TEMP "pragma_sampling_probe.py"
    $probe | Out-File -FilePath $probeFile -Encoding ascii
    Push-Location $script:SRepo
    $raw = & $script:PragmaPy $probeFile 2>$null
    Pop-Location
    Remove-Item $probeFile -ErrorAction SilentlyContinue

    $info = $null
    try { $info = ("$raw" | Out-String).Trim() | ConvertFrom-Json } catch { }
    if (-not $info) {
        Write-Host ""
        Write-Host "Could not read the sampling state (is the venv intact?)." -ForegroundColor Red
        return
    }

    Write-Host ""
    Write-Host "sampling for session '$script:SName'" -ForegroundColor Cyan
    Write-Host "  endpoint : $($info.base_url)"
    if ($info.server_error) {
        Write-Host "  server   : unreachable - $($info.server_error)" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  parameter     this session   the server        applies"
    Write-Host "  -----------------------------------------------------------"

    $sentT = $info.sent.temperature
    foreach ($k in @('temperature', 'top_k', 'top_p', 'min_p')) {
        $sent = $info.sent.$k
        $srv  = if ($info.server) { $info.server.$k } else { $null }
        # Pragma always sends temperature, so for that row the server never
        # applies. For the rest, an omitted field is what hands over control.
        if ($k -eq 'temperature') {
            $eff = $sent
            $srvShown = if ($null -ne $srv) { "$srv (unused)" } else { '?' }
        } elseif ($null -ne $sent) {
            $eff = $sent
            $srvShown = if ($null -ne $srv) { "$srv (overridden)" } else { '?' }
        } else {
            $eff = $srv
            $srvShown = if ($null -ne $srv) { "$srv" } else { '?' }
        }
        $sentShown = if ($null -ne $sent) { "$sent" } else { 'not sent' }
        $effShown  = if ($null -ne $eff)  { "$eff" }  else { 'unknown' }
        Write-Host ("  {0,-13} {1,-14} {2,-17} {3}" -f $k, $sentShown, $srvShown, $effShown)
    }

    if ($info.last) {
        Write-Host ""
        $l = $info.last
        Write-Host ("  last request actually served: temp {0} / top_k {1} / top_p {2} / min_p {3}" -f `
            $l.temperature, $l.top_k, $l.top_p, $l.min_p) -ForegroundColor DarkGray
        Write-Host "  (a measurement, not a deduction - blank until the first call)" -ForegroundColor DarkGray
    }

    if ($null -ne $sentT -and [double]$sentT -eq 0) {
        Write-Host ""
        Write-Host "  At temperature 0 decoding is greedy: top_k, top_p and min_p" -ForegroundColor Yellow
        Write-Host "  have no effect whatever the table above says." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  Other calls in a run, which this session does NOT control:" -ForegroundColor DarkGray
    Write-Host "    memory faculties  temp 0   curator, segmenter, consolidator," -ForegroundColor DarkGray
    Write-Host "                               reconsolidator - the store stays" -ForegroundColor DarkGray
    Write-Host "                               deterministic whatever you send here" -ForegroundColor DarkGray
    $st = if ($null -ne $info.summary_temperature) { $info.summary_temperature } else { "?" }
    Write-Host "    history summary   temp $st   SUMMARY_TEMPERATURE; the one call" -ForegroundColor DarkGray
    Write-Host "                               that samples, so a $st in the line above" -ForegroundColor DarkGray
    Write-Host "                               means something compressed its context" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Read from the environment of THIS window. If you edited" -ForegroundColor DarkGray
    Write-Host "  pragma.ps1, dot-source it again or these are the old values." -ForegroundColor DarkGray
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
Write-Host "  sampling  : $(Get-SamplingLine)"
Write-Host "  rules     : $(Get-ContractLine)"

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
