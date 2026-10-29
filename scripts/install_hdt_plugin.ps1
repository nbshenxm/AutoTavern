# Build the Tavern Advisor HDT plugin and install it into HDT's plugin folder.
# HDT must be closed (it locks loaded plugin DLLs). An existing taverngym.plugin.json (your
# settings) is kept; delete it to get the defaults again. Enable the plugin once in HDT:
# Options > Plugins > Tavern Advisor (Battlegrounds).
param([string]$HdtDir = "$env:LOCALAPPDATA\HearthstoneDeckTracker\app-1.59.6")

$ErrorActionPreference = "Stop"
if (Get-Process HearthstoneDeckTracker -ErrorAction SilentlyContinue) {
    Write-Error "HDT is running: close it first (it locks the plugin DLL)."
}
$project = Join-Path $PSScriptRoot "..\plugin\TavernAdvisor.HdtPlugin"
dotnet build $project -c Release -p:HdtDir="$HdtDir" | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Error "build failed" }

$out = Join-Path $project "bin\Release\net472"
$dest = Join-Path $env:APPDATA "HearthstoneDeckTracker\Plugins\TavernAdvisor"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $out "TavernAdvisor.HdtPlugin.dll") $dest -Force
$settings = Join-Path $dest "taverngym.plugin.json"
if (-not (Test-Path $settings)) {
    Copy-Item (Join-Path $out "taverngym.plugin.json") $dest
}
Write-Host "Installed to $dest"
