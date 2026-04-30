<#
.SYNOPSIS
Downloads Oracle Instant Client (Basic Light) into .\third_party\.

.DESCRIPTION
Required for python-oracledb in THICK mode (ORACLE_CLIENT_MODE=thick).
Idempotent: skips if any third_party\instantclient_*\genezi.exe exists.
Pass -Force to reinstall. Optional -Version + -FolderSlug override the
default 23.6 build.

Always Windows x64. For macOS / Linux use install-instantclient.sh instead.
Requires PowerShell 5.1+ (uses Invoke-WebRequest + Expand-Archive).

.EXAMPLE
pwsh ./scripts/install-instantclient.ps1

.EXAMPLE
pwsh ./scripts/install-instantclient.ps1 -Force

.EXAMPLE
pwsh ./scripts/install-instantclient.ps1 -Version '23.6.0.24.10' -FolderSlug '2360000'
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string]$Version    = '23.6.0.24.10',
    [string]$FolderSlug = '2360000'
)

$ErrorActionPreference = 'Stop'

# Resolve repo root (script lives in scripts/).
$ScriptDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot      = (Resolve-Path (Join-Path $ScriptDir '..')).Path
$ThirdPartyDir = Join-Path $RepoRoot 'third_party'

# Always Windows x64 from PowerShell.
$PlatformDir  = 'nt'
$PlatformName = 'windows.x64'
$Url = "https://download.oracle.com/otn_software/$PlatformDir/instantclient/$FolderSlug/instantclient-basiclite-$PlatformName-$Version.zip"

Write-Host '==> nl2sql-agent: Oracle Instant Client (Basic Light) bootstrap'
Write-Host "    Repo root : $RepoRoot"
Write-Host "    Target    : $ThirdPartyDir"
Write-Host "    Source    : $Url"

# Idempotency: bail if any instantclient_* with genezi.exe already exists.
if (-not $Force -and (Test-Path $ThirdPartyDir)) {
    $existing = Get-ChildItem -Path $ThirdPartyDir -Directory -Filter 'instantclient_*' -ErrorAction SilentlyContinue
    foreach ($d in $existing) {
        $genezi = Join-Path $d.FullName 'genezi.exe'
        if (Test-Path $genezi) {
            Write-Host "==> Instant Client already installed at $($d.FullName) (use -Force to reinstall)."
            Write-Host '    Set in your .env:'
            Write-Host '      ORACLE_CLIENT_MODE=thick'
            Write-Host "      ORACLE_CLIENT_LIB_DIR=$($d.FullName)"
            exit 0
        }
    }
}

if (-not (Test-Path $ThirdPartyDir)) {
    New-Item -Path $ThirdPartyDir -ItemType Directory -Force | Out-Null
}

$TmpDir  = New-Item -Path ([System.IO.Path]::GetTempPath()) -Name "ic-$([guid]::NewGuid().ToString('N'))" -ItemType Directory
$ZipFile = Join-Path $TmpDir.FullName 'instantclient.zip'
try {
    Write-Host '==> Downloading…'
    Invoke-WebRequest -Uri $Url -OutFile $ZipFile -UseBasicParsing

    if ($Force) {
        Write-Host '==> -Force: removing existing instantclient_* folders'
        Get-ChildItem -Path $ThirdPartyDir -Directory -Filter 'instantclient_*' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
    }

    Write-Host "==> Extracting into $ThirdPartyDir…"
    Expand-Archive -Path $ZipFile -DestinationPath $ThirdPartyDir -Force

    $extracted = Get-ChildItem -Path $ThirdPartyDir -Directory -Filter 'instantclient_*' -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending |
                 Select-Object -First 1
    if (-not $extracted) {
        Write-Error 'Extraction did not produce an instantclient_* folder'
        exit 1
    }

    Write-Host '==> Done.'
    Write-Host '    Set in your .env:'
    Write-Host '      ORACLE_CLIENT_MODE=thick'
    Write-Host "      ORACLE_CLIENT_LIB_DIR=$($extracted.FullName)"
} finally {
    Remove-Item -Path $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
