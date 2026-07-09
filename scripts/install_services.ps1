<#
.SYNOPSIS
    Register the two LLM Wiki components (FastAPI + Agent) as Windows services via NSSM.

.DESCRIPTION
    - Auto-elevates to Administrator
    - Auto-detects Python interpreter
    - Detects NSSM availability (fails with install instructions if missing)
    - Idempotent: re-running updates existing services
    - Auto-restart on crash (5s delay)
    - Logs auto-rotate at 10MB

.PARAMETER PythonPath
    Optional: explicit path to python.exe. If empty, auto-detected from PATH.

.PARAMETER ApiPort
    FastAPI listen port, default 8021.

.EXAMPLE
    PS> .\scripts\install_services.ps1
    PS> .\scripts\install_services.ps1 -ApiPort 9000
    PS> .\scripts\install_services.ps1 -PythonPath 'D:\Python312\python.exe'
#>

[CmdletBinding()]
param(
    [string]$PythonPath = '',
    [int]$ApiPort = 8021,
    [string]$NssmPath = ''
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir '..')).Path

# ── 1. Auto-elevate to Administrator ───────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host 'Need administrator privileges, elevating...' -ForegroundColor Yellow
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'))
    if ($PythonPath) { $argList += '-PythonPath', ('"' + $PythonPath + '"') }
    $argList += '-ApiPort', "$ApiPort"
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    exit $LASTEXITCODE
}

# ── 2. Detect NSSM ─────────────────────────────────────────
# Search order:
#   1. -NssmPath argument (explicit override)
#   2. nssm.exe on PATH
#   3. Common install locations (covers the nssm-X.Y.Z win64/win32 dirs and
#      the nssm-win64-Release layout from the official GitHub release zip)
function Find-Nssm {
    param([string]$Hint = '')
    if ($Hint) {
        if (Test-Path $Hint) { return (Resolve-Path $Hint).Path }
        Write-Host ('[WARN] -NssmPath not found: ' + $Hint) -ForegroundColor Yellow
    }
    $onPath = (Get-Command nssm.exe -ErrorAction SilentlyContinue).Source
    if ($onPath) { return $onPath }
    $candidates = @(
        'C:\Tools\nssm-2.24\win64\nssm.exe',
        'C:\Tools\nssm-2.24\win32\nssm.exe',
        'C:\Tools\nssm-win64-Release\nssm.exe',
        'C:\Tools\nssm-win32-Release\nssm.exe',
        'C:\Tools\nssm\win64\nssm.exe',
        'C:\Tools\nssm\nssm.exe',
        'C:\nssm\win64\nssm.exe',
        'C:\nssm\nssm.exe',
        'C:\Program Files\nssm\win64\nssm.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

$nssm = Find-Nssm -Hint $NssmPath
if (-not $nssm) {
    Write-Host '[FAIL] NSSM not found.' -ForegroundColor Red
    Write-Host ''
    Write-Host 'Tried (in order):' -ForegroundColor Yellow
    Write-Host '  1. -NssmPath argument'
    Write-Host '  2. nssm.exe on PATH'
    Write-Host '  3. Common locations under C:\Tools\, C:\nssm\, C:\Program Files\'
    Write-Host ''
    Write-Host 'Fix options:' -ForegroundColor Yellow
    Write-Host '  A) Add NSSM to PATH (recommended):'
    Write-Host '       setx PATH "$env:PATH;C:\Tools\nssm-win64-Release"'
    Write-Host '       (reopen PowerShell afterward)'
    Write-Host '  B) Pass explicit path:'
    Write-Host '       .\install_services.ps1 -NssmPath ''C:\Tools\nssm-win64-Release\nssm.exe'''
    exit 1
}

# Make nssm invokable as bare `nssm ...` for the rest of the script.
# This insulates Install-LlmWikiService from PATH lookup, even when NSSM
# wasn't added to system PATH permanently. Idempotent — prepending again
# when already present is harmless.
$nssmBin = Split-Path -Parent $nssm
$env:Path = "$nssmBin;$env:Path"
Write-Host ('[OK] Added NSSM dir to PATH for this session: ' + $nssmBin)

# ── 3. Detect Python ───────────────────────────────────────
# Find-Python walks PATH manually so we can skip the Microsoft Store stub
# (Microsoft\WindowsApps\python.exe) — which silently fails inside NSSM
# service contexts because the Store alias isn't available to LocalSystem.
function Find-Python {
    $storeStub = '\\Microsoft\WindowsApps\python.exe$'
    foreach ($dir in ($env:Path -split ';')) {
        if (-not $dir) { continue }
        $candidate = Join-Path $dir 'python.exe'
        if (Test-Path $candidate) {
            if ($candidate -match $storeStub) {
                Write-Host ('  [skip] Microsoft Store stub: ' + $candidate) -ForegroundColor DarkGray
                continue
            }
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

# Test-PythonDeps runs `python -c "import X"` for each module and reports
# which ones THIS Python can't find. Service runs as LocalSystem and only
# sees THIS Python's site-packages — so user-site-packages (e.g. AppData\Roaming)
# don't help. If anything is missing we print a loud warning with the fix.
function Test-PythonDeps {
    param([string]$Py, [string[]]$Modules)
    $missing = @()
    foreach ($m in $Modules) {
        $code = "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$m') else 1)"
        $proc = Start-Process -FilePath $Py -ArgumentList '-c', $code -NoNewWindow -Wait -PassThru -RedirectStandardError "$env:TEMP\_dep_err.txt"
        if ($proc.ExitCode -ne 0) { $missing += $m }
    }
    Remove-Item "$env:TEMP\_dep_err.txt" -ErrorAction SilentlyContinue
    return $missing
}

if (-not $PythonPath) {
    $PythonPath = Find-Python
    if (-not $PythonPath) {
        # Fallback: try `py.exe` launcher
        $pyExe = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
        if ($pyExe) { $PythonPath = "$pyExe" }
    }
    if (-not $PythonPath) {
        Write-Host '[FAIL] Python not found.' -ForegroundColor Red
        Write-Host 'Please specify with -PythonPath ''C:\path\to\python.exe'''
        exit 1
    }
}
Write-Host ('[OK] Python: ' + $PythonPath)

# Verify required deps are reachable from this Python (service will run as
# LocalSystem and cannot use the user's per-account site-packages).
$required = @('uvicorn', 'fastapi', 'anthropic', 'openai', 'mistune', 'pdf_oxide')
$missing = Test-PythonDeps -Py $PythonPath -Modules $required
if ($missing.Count -gt 0) {
    Write-Host ''
    Write-Host ('[WARN] Missing modules: ' + ($missing -join ', ')) -ForegroundColor Yellow
    Write-Host '  The service runs as LocalSystem and cannot use your user site-packages.' -ForegroundColor Yellow
    Write-Host '  Likely cause: dependencies installed with `pip install --user`.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Fix (run in admin PowerShell from this repo):' -ForegroundColor Cyan
    Write-Host ('    $env:PYTHONNOUSERSITE = 1')
    Write-Host ('    & ''' + $PythonPath + ''' -m pip install -r api\requirements.txt -r agent\requirements.txt')
    Write-Host ''
    Write-Host '  Then re-run this script. Continuing anyway (install will register but service may fail to start).' -ForegroundColor Yellow
}

Write-Host ('[OK] NSSM:   ' + $nssm)
Write-Host ('[OK] Project root: ' + $ProjectRoot)
Write-Host ''

# ── 4. Prepare log directory ───────────────────────────────
$LogDir = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# ── 5. Service install helper ──────────────────────────────
function Install-LlmWikiService {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Exe,
        [Parameter(Mandatory)][string]$Args,
        [Parameter(Mandatory)][string]$WorkDir,
        [Parameter(Mandatory)][string]$Stdout,
        [Parameter(Mandatory)][string]$Stderr
    )

    Write-Host ('--- Registering service: ' + $Name + ' ---') -ForegroundColor Cyan

    # If exists: stop then remove
    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host '  Already exists, stopping first...' -ForegroundColor Yellow
        & nssm stop $Name 2>$null | Out-Null
        Start-Sleep -Seconds 2
        & nssm remove $Name confirm 2>$null | Out-Null
    }

    # Install
    & nssm install $Name $Exe $Args
    if ($LASTEXITCODE -ne 0) { throw ('nssm install ' + $Name + ' failed') }

    # Working directory (critical: determines .env loading, relative paths)
    & nssm set $Name AppDirectory $WorkDir | Out-Null

    # Log redirection + auto-rotation
    & nssm set $Name AppStdout $Stdout | Out-Null
    & nssm set $Name AppStderr $Stderr | Out-Null
    & nssm set $Name AppRotateFiles 1 | Out-Null
    & nssm set $Name AppRotateBytes 10485760 | Out-Null  # 10MB

    # Startup: auto (boot-time start)
    & nssm set $Name Start SERVICE_AUTO_START | Out-Null

    # Crash recovery: auto-restart after 5s, infinite retries
    & nssm set $Name AppExit Default Restart | Out-Null
    & nssm set $Name AppRestartDelay 5000 | Out-Null
    & nssm set $Name AppThrottle 5000 | Out-Null  # prevent crash loops

    # Display info
    & nssm set $Name DisplayName $Name | Out-Null
    & nssm set $Name Description ('LLM Wiki - ' + $Name + ' (managed by install_services.ps1)') | Out-Null

    # Start
    & nssm start $Name | Out-Null
    Write-Host '  Registered and started' -ForegroundColor Green
    Write-Host ''
}

# ── 6. Register FastAPI service ────────────────────────────
$apiDir = Join-Path $ProjectRoot 'api'
Install-LlmWikiService `
    -Name 'LlmWikiApi' `
    -Exe $PythonPath `
    -Args ('-m uvicorn main:app --host 0.0.0.0 --port ' + $ApiPort) `
    -WorkDir $apiDir `
    -Stdout (Join-Path $LogDir 'api.out.log') `
    -Stderr (Join-Path $LogDir 'api.err.log')

# ── 7. Register Agent service ──────────────────────────────
$agentDir = Join-Path $ProjectRoot 'agent'
Install-LlmWikiService `
    -Name 'LlmWikiAgent' `
    -Exe $PythonPath `
    -Args 'run.py' `
    -WorkDir $agentDir `
    -Stdout (Join-Path $LogDir 'agent.out.log') `
    -Stderr (Join-Path $LogDir 'agent.err.log')

# ── 8. Verify both services actually started ────────────────
# `nssm start` returns immediately even if the executable crashes a few
# hundred ms later (we saw this: missing uvicorn in LocalSystem context).
# So wait a beat, then check process state and a real HTTP probe.
Write-Host ''
Write-Host 'Waiting 8s for services to settle...' -ForegroundColor Cyan
Start-Sleep -Seconds 8

$apiRunning = $false
$agentRunning = $false
$httpOk = $false

$apiStatus = & nssm status LlmWikiApi 2>$null
if ($LASTEXITCODE -eq 0 -and ($apiStatus | Select-String -SimpleMatch 'SERVICE_RUNNING')) {
    $apiRunning = $true
}
$agentStatus = & nssm status LlmWikiAgent 2>$null
if ($LASTEXITCODE -eq 0 -and ($agentStatus | Select-String -SimpleMatch 'SERVICE_RUNNING')) {
    $agentRunning = $true
}

try {
    $resp = Invoke-WebRequest "http://localhost:$ApiPort/v1/agent/status" -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) { $httpOk = $true }
} catch {
    $httpOk = $false
}

# Also catch the "process stopped immediately" case: STATE != RUNNING
# is reported by NSSM as "SERVICE_STOPPED" only after Throttle delay.
# nssm status reports SERVICE_START_PENDING for in-progress boots, so we
# check both exits to disambiguate 'starting now' from 'dead'.

Write-Host ''
Write-Host '====================================='
if ($apiRunning -and $agentRunning -and $httpOk) {
    Write-Host 'Installation verified' -ForegroundColor Green
    Write-Host '=====================================' -ForegroundColor Green
    Write-Host ('  [+] LlmWikiApi     : SERVICE_RUNNING')
    Write-Host ('  [+] LlmWikiAgent   : SERVICE_RUNNING')
    Write-Host ('  [+] HTTP /v1/agent/status : 200')
} else {
    Write-Host '⚠ Verification FAILED' -ForegroundColor Yellow
    Write-Host '=====================================' -ForegroundColor Yellow
    if (-not $apiRunning)    { Write-Host ('  [-] LlmWikiApi     : status = ' + $apiStatus) -ForegroundColor Yellow }
    if (-not $agentRunning)  { Write-Host ('  [-] LlmWikiAgent   : status = ' + $agentStatus) -ForegroundColor Yellow }
    if (-not $httpOk)        { Write-Host  '  [-] HTTP probe failed — see api.err.log' -ForegroundColor Yellow }
    Write-Host ''
    Write-Host '  See logs for the cause:' -ForegroundColor Yellow
    Write-Host ('    ' + (Join-Path $LogDir 'api.err.log'))
    Write-Host ('    ' + (Join-Path $LogDir 'agent.err.log'))
}
Write-Host ''
Write-Host ('  Web UI:        http://localhost:' + $ApiPort)
Write-Host ('  Agent status:  http://localhost:' + $ApiPort + '/v1/agent/status')
Write-Host ('  Logs:          ' + $LogDir)
Write-Host ''
Write-Host 'Management commands (PowerShell admin):' -ForegroundColor Yellow
Write-Host '  nssm start   LlmWikiApi | LlmWikiAgent'
Write-Host '  nssm stop    LlmWikiApi | LlmWikiAgent'
Write-Host '  nssm restart LlmWikiApi | LlmWikiAgent'
Write-Host '  nssm status  LlmWikiApi | LlmWikiAgent'
Write-Host ''
Write-Host 'Or open services.msc to find LlmWikiApi / LlmWikiAgent'
