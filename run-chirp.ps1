<#
.SYNOPSIS
    Launches the CHIRP GUI from this source checkout, creating a virtual
    environment and installing dependencies on first run.

.DESCRIPTION
    On first run this creates a .venv (using Python 3.11 by default, since
    the pinned wxPython 4.2.0 has prebuilt wheels for 3.11 but not 3.14),
    installs requirements.txt, then launches chirpwx.py. Subsequent runs
    skip setup and just launch.

    Any extra arguments are passed through to CHIRP.

.PARAMETER Cli
    Launch the command-line tool (chirpc) instead of the GUI.

.PARAMETER Reinstall
    Delete the existing .venv and rebuild it from scratch.

.EXAMPLE
    .\run-chirp.ps1

.EXAMPLE
    .\run-chirp.ps1 -Cli --help
#>
[CmdletBinding()]
param(
    [switch]$Cli,
    [switch]$Reinstall,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Passthru
)

$ErrorActionPreference = 'Stop'

# Always operate relative to this script's location.
$RepoRoot = $PSScriptRoot
$VenvDir  = Join-Path $RepoRoot '.venv'
$VenvPy   = Join-Path $VenvDir 'Scripts\python.exe'
$PyVersion = '3.11'   # wxPython 4.2.0 has Windows wheels for this

function Find-BasePython {
    # Prefer the version that has wxPython wheels via the py launcher.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $versions = (& py -0p) -join "`n"
        if ($versions -match [regex]::Escape("-V:$PyVersion")) {
            return @('py', "-$PyVersion")
        }
        Write-Warning "Python $PyVersion not found; falling back to the default 'py' interpreter. wxPython may fail to build."
        return @('py')
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Warning "'py' launcher not found; using 'python' on PATH. wxPython may fail to build if this isn't $PyVersion."
        return @('python')
    }
    throw "No Python interpreter found. Install Python $PyVersion from https://www.python.org/downloads/"
}

if ($Reinstall -and (Test-Path $VenvDir)) {
    Write-Host "Removing existing virtual environment..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $VenvDir
}

# Create the venv on first run.
if (-not (Test-Path $VenvPy)) {
    $base = Find-BasePython
    Write-Host "Creating virtual environment in .venv (using: $($base -join ' '))..." -ForegroundColor Cyan
    & $base[0] $base[1..($base.Count - 1)] -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment." }

    Write-Host "Installing dependencies (this may take a few minutes)..." -ForegroundColor Cyan
    & $VenvPy -m pip install --upgrade pip

    # Install everything from requirements.txt EXCEPT wxPython. The file pins
    # wxPython==4.2.0 on Windows, which has no wheel for Python 3.11+, so pip
    # would fall back to compiling the 71 MB source tarball (and fail). We
    # install wxPython separately below, wheel-only, letting pip pick a version
    # that actually ships a wheel for this interpreter.
    $reqFile = Join-Path $RepoRoot 'requirements.txt'
    $filtered = Get-Content $reqFile | Where-Object { $_ -notmatch '^\s*wxPython' }
    $tmpReq = Join-Path $env:TEMP "chirp-req-$PID.txt"
    Set-Content -Path $tmpReq -Value $filtered
    try {
        & $VenvPy -m pip install -r $tmpReq
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. See errors above." }

        # wheel-only so it never tries to compile; >=4.2.1 has cp311/cp312 wheels.
        & $VenvPy -m pip install --only-binary=:all: "wxPython>=4.2.1"
        if ($LASTEXITCODE -ne 0) { throw "wxPython installation failed. See errors above." }
    }
    finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tmpReq
    }
}

# Launch CHIRP.
if ($Cli) {
    Write-Host "Starting CHIRP CLI..." -ForegroundColor Green
    & $VenvPy -m chirp.cli.main @Passthru
} else {
    Write-Host "Starting CHIRP..." -ForegroundColor Green
    & $VenvPy (Join-Path $RepoRoot 'chirpwx.py') @Passthru
}

exit $LASTEXITCODE
