# Every 10 minutes (task "TavernAdvisor Progress Page"): the logs of the jobs in
# data/progress/jobs.json copied from where they run (the office, the cluster's
# HearthstoneAdvisor_BG folder), then the progress page remade, at low priority. Light: small
# files and a page render. Log: %LOCALAPPDATA%\TavernAdvisor\progress_refresh.log
$ErrorActionPreference = "Continue"
$repo = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $env:LOCALAPPDATA "TavernAdvisor"
$log = Join-Path $logDir "progress_refresh.log"
function Log($m) { Add-Content $log ("{0:s} {1}" -f (Get-Date), $m) -Encoding utf8 }
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = "BelowNormal"
$cluster = "/fs1/projects/benchmarking_PIDS/HearthstoneAdvisor_BG/repo"
try {
    $jobs = (Get-Content (Join-Path $repo "data\progress\jobs.json") -Raw | ConvertFrom-Json).jobs
    foreach ($j in $jobs) {
        # A cluster job's results file (one line per finished case), copied as it is
        if ($j.results -and $j.where -like "cluster*") {
            $rd = Join-Path $repo ($j.results -replace "/", "\")
            & scp -q "star:$cluster/$($j.results)" "$rd.part" 2>$null
            if ($LASTEXITCODE -eq 0) { Move-Item -Force "$rd.part" $rd }
        }
        if (-not $j.log) { continue }
        # data/progress/train/RUN/log.jsonl <- data/train/RUN/log.jsonl where the run is
        $run = Split-Path (Split-Path $j.log -Parent) -Leaf
        $dest = Join-Path $repo ($j.log -replace "/", "\")
        New-Item -ItemType Directory -Force (Split-Path $dest -Parent) | Out-Null
        if ($j.where -like "office*") { $src = "office:autotavern/data/train/$run/log.jsonl" }
        elseif ($j.where -like "cluster*") { $src = "star:$cluster/data/train/$run/log.jsonl" }
        else { continue }
        & scp -q $src "$dest.part" 2>$null
        if ($LASTEXITCODE -eq 0) { Move-Item -Force "$dest.part" $dest } else { Log "no log for $run from $src" }
    }
    $py = Join-Path $env:USERPROFILE "anaconda3\envs\taverngym\python.exe"
    Set-Location $repo
    & $py -X utf8 -m advisor.report 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Log "report FAILED (exit $LASTEXITCODE)" }
} catch { Log "error: $_" }
