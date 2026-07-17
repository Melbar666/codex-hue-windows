[CmdletBinding()]
param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "CodexHueWindows"))
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Exe = Join-Path $InstallRoot "venv\Scripts\codex-hue.exe"
if (Test-Path -LiteralPath $Exe) {
    & $Exe uninstall-hooks
    if ($LASTEXITCODE -ne 0) { throw "Could not remove Codex hooks. Installation was left in place." }
}
if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force }
Write-Host "Removed codex-hue-windows application files."
Write-Host "Hue configuration and logs remain under $env:USERPROFILE\.codex\hue-indicator"
