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

# ── 3. Detect Python ───────────────────────────────────────
if (-not $PythonPath) {
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if (-not $py) {
        $py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $py) {
        Write-Host '[FAIL] Python not found.' -ForegroundColor Red
        Write-Host 'Please specify with -PythonPath'
        exit 1
    }
    $PythonPath = $py
}
Write-Host ('[OK] Python: ' + $PythonPath)
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

# ── 8. Done ────────────────────────────────────────────────
Write-Host '=====================================' -ForegroundColor Green
Write-Host 'Installation complete' -ForegroundColor Green
Write-Host '====================================='
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
