<#
.SYNOPSIS
  Downloads Oracle SQLcl and extracts it into ./vendor/sqlcl/.

.DESCRIPTION
  Idempotent. Skips download when ./vendor/sqlcl/bin/sql.exe already exists.
  Use -Force to reinstall. Prints the absolute SQLCL_PATH at the end so you
  can paste it into .env.

  Requires a Java runtime (JRE 17+). The script does NOT install Java; it
  warns if `java -version` is missing.

.PARAMETER Force
  Wipe ./vendor/sqlcl/ and reinstall.

.PARAMETER Version
  SQLcl version to fetch ("latest" or e.g. "23.4.0.023.2321"). Defaults to
  "latest" which pulls https://download.oracle.com/.../sqlcl-latest.zip.

.EXAMPLE
  pwsh ./scripts/install-sqlcl.ps1
  pwsh ./scripts/install-sqlcl.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"

# Resolve repo root (script lives in scripts/, so parent of $PSScriptRoot is the root).
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$VendorDir  = Join-Path $RepoRoot "vendor"
$SqlclDir   = Join-Path $VendorDir "sqlcl"
$SqlExe     = Join-Path $SqlclDir "bin\sql.exe"
$TempZip    = Join-Path $env:TEMP "sqlcl-$([guid]::NewGuid().ToString('N')).zip"
$TempExtract= Join-Path $env:TEMP "sqlcl-extract-$([guid]::NewGuid().ToString('N'))"

if ($Version -eq "latest") {
    $Url = "https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip"
} else {
    $Url = "https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-$Version.zip"
}

Write-Host "==> nl2sql-agent: SQLcl bootstrap" -ForegroundColor Cyan
Write-Host "    Repo root : $RepoRoot"
Write-Host "    Target    : $SqlclDir"
Write-Host "    Source    : $Url"

if (-not $Force -and (Test-Path $SqlExe)) {
    Write-Host "==> SQLcl already installed at $SqlExe (use -Force to reinstall)." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next: set this in your .env"
    Write-Host "    SQLCL_PATH=vendor/sqlcl/bin/sql.exe" -ForegroundColor Yellow
    exit 0
}

# Java sanity check.
$javaCmd = Get-Command java -ErrorAction SilentlyContinue
if ($null -eq $javaCmd) {
    Write-Warning "Java is not on PATH. SQLcl needs JRE 17+ to run."
    Write-Warning "Install Adoptium / Oracle JDK and re-run this script."
} else {
    try {
        $javaVer = (& java -version 2>&1) -join " "
        Write-Host "    Java      : $javaVer"
    } catch {
        Write-Warning "Could not query java -version. Continuing anyway."
    }
}

if ($Force -and (Test-Path $SqlclDir)) {
    Write-Host "==> -Force: removing existing $SqlclDir" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $SqlclDir
}

if (-not (Test-Path $VendorDir)) {
    New-Item -ItemType Directory -Path $VendorDir | Out-Null
}

try {
    Write-Host "==> Downloading SQLcl ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $Url -OutFile $TempZip -UseBasicParsing
    $sizeMB = [math]::Round((Get-Item $TempZip).Length / 1MB, 1)
    Write-Host "    Downloaded $sizeMB MB to $TempZip"

    Write-Host "==> Extracting ..." -ForegroundColor Cyan
    Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

    # Oracle's zip always nests a single 'sqlcl' folder at the top level.
    $InnerDir = Join-Path $TempExtract "sqlcl"
    if (-not (Test-Path $InnerDir)) {
        throw "Unexpected zip layout: '$InnerDir' not found. Inspect $TempExtract."
    }

    # Copy the inner folder's contents directly into vendor/sqlcl so
    # SQLCL_PATH=vendor/sqlcl/bin/sql.exe is correct.
    Copy-Item -Path $InnerDir -Destination $VendorDir -Recurse -Force

    if (-not (Test-Path $SqlExe)) {
        throw "Install completed but $SqlExe is missing. Inspect $SqlclDir."
    }

    Write-Host ""
    Write-Host "==> SQLcl installed." -ForegroundColor Green
    Write-Host "    Binary    : $SqlExe"
    Write-Host ""
    Write-Host "Next: set these in your .env" -ForegroundColor Cyan
    Write-Host "    SQLCL_PATH=vendor/sqlcl/bin/sql.exe" -ForegroundColor Yellow
    Write-Host "    SQLCL_USER_DIR=.sqlcl" -ForegroundColor Yellow
    Write-Host "    SQLCL_CONNECTIONS=[name,user/password@host:port/service]" -ForegroundColor Yellow
}
finally {
    if (Test-Path $TempZip)     { Remove-Item -Force $TempZip }
    if (Test-Path $TempExtract) { Remove-Item -Recurse -Force $TempExtract }
}
