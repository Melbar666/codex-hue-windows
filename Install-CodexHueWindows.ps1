[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "CodexHueWindows")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Native {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$ArgumentList
    )

    & $Command @ArgumentList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $Command $($ArgumentList -join ' ')"
    }
}

$RepositoryRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $InstallRoot "venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Exe = Join-Path $Venv "Scripts\codex-hue.exe"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' is not installed or not in PATH."
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (-not (Test-Path -LiteralPath $Python)) {
    Invoke-Native -Command "py" -ArgumentList @(
        "-3", "-m", "venv", $Venv
    )
}

Invoke-Native -Command $Python -ArgumentList @(
    "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"
)
Invoke-Native -Command $Python -ArgumentList @(
    "-m", "pip", "install",
    "--no-deps",
    "--no-build-isolation",
    "--force-reinstall",
    $RepositoryRoot
)
Invoke-Native -Command $Exe -ArgumentList @("--help")

Write-Host ""
Write-Host "Installed codex-hue-windows in $InstallRoot"
Write-Host "Next commands:"
Write-Host "  & `"$Exe`" setup"
Write-Host "  & `"$Exe`" test"
Write-Host "  & `"$Exe`" install-hooks"
