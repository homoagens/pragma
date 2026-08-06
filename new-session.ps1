<#
.SYNOPSIS
  Create a new Pragma batch session: its own memory, its own workspace.

.DESCRIPTION
  `start.bat` opens the normal interface. This is the batch counterpart: it
  sets up a folder that holds one persistent memory and gives you a `pragma`
  command to work with it from PowerShell.

  Each session is independent. A session for your notes and a session for a
  project remember different things and never mix.

  The folder it creates:

      <path>\
          pragma.ps1     enter the session:  . <path>\pragma.ps1
          workspace\     the files the agent reads and writes
          .memoria\      episodes and beliefs
          backups\       created by `pragma -Backup`

  Only pragma.ps1 is generated: the commands themselves live in the repository
  (tools\pragma-session.ps1), so a session picks up improvements the next time
  you enter it.

  Run with no arguments for the guided version; pass the parameters to skip
  the questions.

.EXAMPLE
  .\new-session.ps1

.EXAMPLE
  .\new-session.ps1 -Path D:\pragma-notes -Name notes -Profile 27b
#>

[CmdletBinding()]
param(
    # Where the session lives. Anywhere outside the Pragma repository.
    [string]$Path,

    # Short name, used in the banner and to confirm a wipe. Defaults to the
    # folder name.
    [string]$Name,

    # A profile from examples_memory\models.json. Empty = the model in .env.
    [string]$Profile,

    # Step budget for one task.
    [int]$MaxSteps = 50,

    # native = the model calls tools and the server constrains the arguments
    # with a grammar (recommended). text = the older channel, kept so earlier
    # results can be reproduced.
    [ValidateSet('native', 'text')]
    [string]$Protocol = 'native',

    # Overwrite an existing pragma.ps1 in that folder.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot

function Ask([string]$question, [string]$default) {
    $suffix = if ($default) { " [$default]" } else { "" }
    $reply = Read-Host "  $question$suffix"
    if ([string]::IsNullOrWhiteSpace($reply)) { return $default }
    return $reply.Trim()
}

Write-Host ""
Write-Host "New Pragma batch session" -ForegroundColor Cyan
Write-Host "  repository : $Repo"

# --- the Python environment has to exist before anything else ----------------
$py = Join-Path $Repo "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host ""
    Write-Host "Python environment not found at $py" -ForegroundColor Red
    Write-Host "Run install.bat first, then come back."
    exit 1
}

# --- questions ----------------------------------------------------------------
Write-Host ""
if (-not $Path) {
    $Path = Ask "Where should this session live?" (Join-Path $HOME "pragma-notes")
}
$Path = [System.IO.Path]::GetFullPath($Path)

# A session inside the repository would put the agent's workspace in Pragma's
# own source tree, which agent.batch refuses outright - catch it here, with an
# explanation, instead of at the first task.
#
# Compared as paths, not as text. A bare StartsWith made "pragma-notes" look
# like a child of "pragma" - they are siblings that happen to share a prefix -
# and the script rejected its own suggested default, so it could not be used
# at all. The separator is what turns a prefix into containment.
$sep     = [System.IO.Path]::DirectorySeparatorChar
$pathKey = $Path.TrimEnd($sep).ToLower()
$repoKey = $Repo.TrimEnd($sep).ToLower()
if ($pathKey -eq $repoKey -or $pathKey.StartsWith($repoKey + $sep)) {
    Write-Host ""
    Write-Host "That path is inside the Pragma repository." -ForegroundColor Red
    Write-Host "A session must live elsewhere: Pragma refuses to work inside its own"
    Write-Host "source tree, and keeping your data out of it also keeps it out of git."
    exit 1
}

# Checked before the remaining questions: being asked for a name and a profile
# only to be told the session already existed is a waste of the user's time.
$sessionFile = Join-Path $Path "pragma.ps1"
if ((Test-Path $sessionFile) -and -not $Force) {
    Write-Host ""
    Write-Host "A session already exists at $sessionFile" -ForegroundColor Yellow
    Write-Host "Enter it with:   . $sessionFile"
    Write-Host "Re-create it with -Force (your memory is NOT touched)."
    exit 1
}

if (-not $Name) {
    $Name = Ask "A short name for it?" (Split-Path $Path -Leaf)
}
if (-not $PSBoundParameters.ContainsKey('Profile')) {
    $Profile = Ask "Model profile (empty = the model from .env)?" ""
}

# --- sampling ---------------------------------------------------------------
# Asked AFTER the profile, because the profile is what selects the endpoint: a
# question about a server's defaults has to be aimed at the server the session
# will actually talk to.
#
# The numbers are read from that server rather than guessed. They matter because
# of an asymmetry that is easy to get wrong: Pragma always sends `temperature`,
# so the server's own value never reaches it, while top_k / top_p / min_p are
# only sent when set, so there the server decides. Showing both sides is the
# only way the choice is an informed one.
$Temperature = ''
$TopK = ''
$TopP = ''
$MinP = ''

$probe = @'
import json, sys
sys.path.insert(0, "core")
import llm_client
url, _k = llm_client._resolved_endpoint(None, None)
out = {"base_url": url}
root = url[:-3] if url.endswith("/v1") else url
try:
    import requests
    p = requests.get(root.rstrip("/") + "/props", timeout=5).json()
    # llama.cpp nests the samplers two levels down, in
    # default_generation_settings.params; n_ctx sits one level up. Looking only
    # at the outer object found nothing and reported blanks, which reads exactly
    # like a server with no defaults.
    dgs = p.get("default_generation_settings") or {}
    params = dgs.get("params") or {}

    def pick(k):
        for d in (params, dgs, p):
            if isinstance(d, dict) and d.get(k) is not None:
                v = d[k]
                # 0.6 arrives as 0.6000000238418579: float32 through JSON.
                return round(v, 4) if isinstance(v, float) else v
        return None

    out["server"] = {k: pick(k) for k in ("temperature", "top_k", "top_p", "min_p")}
except Exception as e:
    out["error"] = str(e)[:100]
print(json.dumps(out))
'@
$probeFile = Join-Path $env:TEMP "pragma_newsession_probe.py"
$probe | Out-File -FilePath $probeFile -Encoding ascii
$srv = $null
$endpoint = ''
try {
    if ($Profile) { $env:PRAGMA_PROFILE = $Profile }
    Push-Location $Repo
    $raw = & (Join-Path $Repo "venv\Scripts\python.exe") $probeFile 2>$null
    Pop-Location
    $info = ($raw | Out-String).Trim() | ConvertFrom-Json
    $endpoint = $info.base_url
    if (-not $info.error) { $srv = $info.server }
} catch { }
Remove-Item $probeFile -ErrorAction SilentlyContinue

Write-Host ""
if ($endpoint) { Write-Host "  endpoint  : $endpoint" -ForegroundColor DarkGray }
if ($srv) {
    Write-Host ("  the server's own sampling: temp {0} / top_k {1} / top_p {2} / min_p {3}" -f `
        $srv.temperature, $srv.top_k, $srv.top_p, $srv.min_p) -ForegroundColor DarkGray
    Write-Host "  Pragma always sends temperature, so the server's is never used." -ForegroundColor DarkGray
    Write-Host "  The other three apply only where you leave this session empty." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Enter = Pragma's defaults: temperature 0 (deterministic)," -ForegroundColor DarkGray
    Write-Host "          the other three left to the server." -ForegroundColor DarkGray
    Write-Host "  m     = match the server: write its four values into this" -ForegroundColor DarkGray
    Write-Host "          session, so restarting it with other flags cannot" -ForegroundColor DarkGray
    Write-Host "          move this session without you noticing." -ForegroundColor DarkGray
    Write-Host "  s     = set them one by one." -ForegroundColor DarkGray
    $ans = "$(Read-Host "  Your choice (Enter, m or s)")".Trim()

    if ($ans -match '^(m|match|e)$') {
        # Copied, not inherited. Leaving the fields empty would also reproduce
        # the server's behaviour today, but it would mean "whatever the server
        # uses", and a later launch flag would move this session silently.
        # Written out, the values are the session's own and a divergence shows
        # up as a difference between the banner and /slots.
        $Temperature = "$($srv.temperature)"
        $TopK = "$($srv.top_k)"
        $TopP = "$($srv.top_p)"
        $MinP = "$($srv.min_p)"
    } elseif ($ans -match '^(s|set|y|yes|si)$') {
        Write-Host ""
        Write-Host "  At each one: Enter keeps what is in brackets." -ForegroundColor DarkGray
        $Temperature = Ask "  temperature   (0 = deterministic; above 0 the next three start working)" "$($srv.temperature)"
        $TopK = Ask "  top_k         (Enter = leave to the server, which uses $($srv.top_k))" ""
        $TopP = Ask "  top_p         (Enter = leave to the server, which uses $($srv.top_p))" ""
        $MinP = Ask "  min_p         (Enter = leave to the server, which uses $($srv.min_p))" ""
    }

    if ($Temperature -or $TopK -or $TopP -or $MinP) {
        Write-Host ""
        $shown = @("temp $(if ($Temperature) { $Temperature } else { '0.0' })")
        foreach ($p in @(@('top_k', $TopK, $srv.top_k), @('top_p', $TopP, $srv.top_p),
                         @('min_p', $MinP, $srv.min_p))) {
            if ($p[1]) { $shown += "$($p[0]) $($p[1])" }
            else { $shown += "$($p[0]) $($p[2]) (server)" }
        }
        Write-Host "  This session will run at: $($shown -join ' / ')" -ForegroundColor Cyan
        if ([double]("0" + $Temperature) -eq 0) {
            Write-Host "  Note: at temperature 0 the other three have no effect." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  backend not reachable - sampling left empty (edit pragma.ps1 later)." -ForegroundColor DarkGray
}

# --- create ---------------------------------------------------------------------
foreach ($d in @($Path, (Join-Path $Path "workspace"), (Join-Path $Path ".memoria"))) {
    New-Item -ItemType Directory -Force $d | Out-Null
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$lines = @(
    "# pragma.ps1 - Pragma batch session '$Name'",
    "# Generated by new-session.ps1 on $stamp. Safe to edit by hand.",
    "#",
    "# Enter this session:",
    "#     . $sessionFile",
    "#",
    "# Then:  pragma `"your task`"      |      pragma -Info  for every command",
    "#",
    "# NOTE: keep this file pure ASCII - PowerShell 5.1 reads BOM-less files as",
    "# ANSI, and a fancy dash or quote silently corrupts the script.",
    "",
    "`$PragmaSession = @{",
    "    Name     = `"$Name`"",
    "    Root     = `"$Path`"",
    "    Repo     = `"$Repo`"",
    "    Profile  = `"$Profile`"        # `"`" = the model from the repo .env",
    "    MaxSteps = $MaxSteps",
    "    Protocol = `"$Protocol`"    # native | text",
    "",
    "    # Output budgets. `"`" = whatever the repository defaults to, which is",
    "    # the right answer unless you know your server needs otherwise.",
    "    # ContextWindow MUST match the -c of your LLM server if you set it.",
    "    ContextWindow  = `"`"",
    "    MaxTokens      = `"`"",
    "    SkillMaxTokens = `"`"",
    "    # MemoryMaxTokens `"`" = the same as SkillMaxTokens. Set it lower when",
    "    # the model reasons at length: curator, segmenter and consolidator emit",
    "    # a short structured verdict, and on a slow endpoint a wide budget is",
    "    # minutes of waiting before the first step. Too low truncates the JSON",
    "    # on a thinking model, which looks like a faculty that found nothing.",
    "    MemoryMaxTokens = `"`"",
    "    Timeout        = `"`"",
    "",
    "    # Sampling. These two lines behave DIFFERENTLY when left empty:",
    "    #   Temperature      `"`" = Pragma's own 0.0. Pragma always sends this",
    "    #                    field, so the server's -temp never applies.",
    "    #   TopK/TopP/MinP   `"`" = not sent at all, so your LLM server's",
    "    #                    launch-time defaults decide. That is usually",
    "    #                    where a model's recommended preset already is.",
    "    # At temperature 0 decoding is greedy and the other three do nothing;",
    "    # set them only together with a temperature above zero.",
    "    # Qwen3 thinking preset, for reference: 0.6 / 20 / 0.95 / 0.0",
    "    Temperature = `"$Temperature`"",
    "    TopK        = `"$TopK`"",
    "    TopP        = `"$TopP`"",
    "    MinP        = `"$MinP`"",
    "}",
    "",
    ". (Join-Path `$PragmaSession.Repo `"tools\pragma-session.ps1`")"
)
# ASCII, no BOM: PowerShell 5.1 would otherwise read the file as ANSI and the
# first line would carry invisible bytes.
Set-Content -Path $sessionFile -Value $lines -Encoding ASCII

# PRAGMA.md - standing instructions, injected before EVERY task in this
# workspace. Shipped as comments only, so it stays inert until someone writes
# a real rule: the agent ignores HTML comments, and a file with nothing else
# in it is treated as absent.
$contractFile = Join-Path $Path "workspace\PRAGMA.md"
if (-not (Test-Path $contractFile)) {
    $contract = @(
        "<!--",
        "PRAGMA.md - standing instructions for this workspace.",
        "",
        "Anything you write OUTSIDE these comment markers is given to the agent",
        "before every task, on top of whatever it remembers. Use it for rules",
        "that always apply, not for one-off requests.",
        "",
        "The agent may read this file and can never write to it.",
        "",
        "Comments like this one are ignored, so this guidance costs you nothing.",
        "Write your rules below the closing marker, for example:",
        "",
        "    ## Environment",
        "    - Install every dependency in .\venv, never in system Python.",
        "    - Run Python through .\venv\Scripts\python.exe.",
        "",
        "    ## Conventions",
        "    - Tests live in tests\ and run with pytest.",
        "    - Never edit anything under generated\.",
        "",
        "    ## Standing authorizations",
        "    - Deleting files under tmp\ is pre-authorized.",
        "",
        "Memory is what the agent LEARNS; this file is what you DECIDE. A rule",
        "here is never weighed against other memories - it always applies.",
        "-->"
    )
    Set-Content -Path $contractFile -Value $contract -Encoding ASCII
}

Write-Host ""
Write-Host "Created $sessionFile" -ForegroundColor Green
Write-Host "  memory    : $(Join-Path $Path '.memoria')"
Write-Host "  workspace : $(Join-Path $Path 'workspace')"
Write-Host "  rules     : $contractFile" -ForegroundColor Cyan
Write-Host "              standing instructions, read before EVERY task."
Write-Host "              Empty for now - open it and write what must always hold."

# --- is the backend up? a warning here saves a confusing first task ------------
Push-Location $Repo
$served = & $py -c @"
import sys
sys.path.insert(0, 'core')
import llm_client
ok, d = llm_client.ping_models()
print(('OK|' if ok else 'DOWN|') + d)
"@ 2>&1
Pop-Location
if (("$served" -split '\|')[0] -eq "OK") {
    Write-Host "  backend   : OK" -ForegroundColor Green
} else {
    Write-Host "  backend   : DOWN - start your LLM server before the first task" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Enter the session with:" -ForegroundColor Cyan
Write-Host "    . $sessionFile"
Write-Host ""
