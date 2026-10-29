# Hourly at home (scheduled task "TavernAdvisor Model Sync"): copy the network the office
# promoted (data/models/best.pt there, advisor.promote) into this repo's data/models when it
# changed. The live advisor reloads the file by itself; a file copy is harmless while playing.
# Log: %LOCALAPPDATA%\TavernAdvisor\sync.log. Remove the task:
#   Unregister-ScheduledTask -TaskName "TavernAdvisor Model Sync" -Confirm:$false
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$models = Join-Path $repo "data\models"
$logDir = Join-Path $env:LOCALAPPDATA "TavernAdvisor"
New-Item -ItemType Directory -Force $models, $logDir | Out-Null
$log = Join-Path $logDir "sync.log"
function Log($m) { Add-Content $log ("{0:s} {1}" -f (Get-Date), $m) -Encoding utf8 }

$tmp = Join-Path $models "best.pt.download"
try {
    & scp -q -o BatchMode=yes -o ConnectTimeout=20 "office:autotavern/data/models/best.pt" $tmp
    if ($LASTEXITCODE -ne 0) { Log "office unreachable or no promoted network (scp exit $LASTEXITCODE)"; exit 0 }
    & scp -q -o BatchMode=yes -o ConnectTimeout=20 "office:autotavern/data/models/promotions.jsonl" (Join-Path $models "promotions.jsonl")
    $best = Join-Path $models "best.pt"
    $new = (Get-FileHash $tmp -Algorithm SHA256).Hash
    $old = if (Test-Path $best) { (Get-FileHash $best -Algorithm SHA256).Hash } else { "" }
    if ($new -eq $old) {
        Remove-Item $tmp -Force
        Log "up to date"
    } else {
        if (Test-Path $best) {
            $archive = Join-Path $models "archive"
            New-Item -ItemType Directory -Force $archive | Out-Null
            Copy-Item $best (Join-Path $archive ("best_{0:yyyyMMdd_HHmmss}.pt" -f (Get-Date)))
        }
        Move-Item $tmp $best -Force
        Log "updated best.pt from the office ($new)"
    }
} catch {
    Log "failed: $($_.Exception.Message)"
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
}
