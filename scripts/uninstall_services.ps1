<#
.SYNOPSIS
    Unregister LlmWikiApi and LlmWikiAgent Windows services.

.DESCRIPTION
    - Auto-elevates to Administrator
    - Gracefully stops then removes both services
    - Does not delete logs or .env (preserves troubleshooting artifacts)
    - Idempotent: missing services are silently skipped

.EXAMPLE
    PS> .\scripts\uninstall_services.ps1
#>

[CmdletBinding()]
param(
    [string]$NssmPath = ''
)

$ErrorActionPreference = 'Stop'

# ── Elevate ───────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host 'Need administrator privileges, elevating...' -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"')
    ) -Wait
    exit $LASTEXITCODE
}

# ── Detect NSSM ───────────────────────────────────────────
# Same path-detection logic as install_services.ps1
function Find-Nssm {
    param([string]$Hint = '')
    if ($Hint) {
        if (Test-Path $Hint) { return (Resolve-Path $Hint).Path }
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
    Write-Host '[FAIL] NSSM not found. Cannot uninstall via NSSM.' -ForegroundColor Red
    Write-Host 'Try: .\uninstall_services.ps1 -NssmPath ''C:\Tools\nssm-win64-Release\nssm.exe'''
    Write-Host 'Or: open services.msc and manually delete LlmWikiApi / LlmWikiAgent'
    exit 1
}

# ── Remove both services ──────────────────────────────────
# Stop Agent first (it queries API state)
$services = @('LlmWikiAgent', 'LlmWikiApi')

foreach ($name in $services) {
    Write-Host ('--- Removing: ' + $name + ' ---') -ForegroundColor Cyan
    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host '  Not installed, skipping' -ForegroundColor Gray
        continue
    }
    & nssm stop $name 2>$null | Out-Null
    Start-Sleep -Seconds 2
    & nssm remove $name confirm 2>$null | Out-Null
    Write-Host '  Removed' -ForegroundColor Green
    Write-Host ''
}

Write-Host '=====================================' -ForegroundColor Green
Write-Host 'Uninstall complete' -ForegroundColor Green
Write-Host '====================================='
Write-Host 'Logs and data remain in the project logs/ directory.'
