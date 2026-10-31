# Hourly at home (scheduled task "TavernAdvisor Model Sync"): copy the network the office
# promoted (data/models/best.pt there, advisor.promote) into this repo's data/models when it
# changed. The live advisor reloads the file by itself; a file copy is harmless while playing.
# Then the progress page: the office's training logs and running jobs into data/progress, and
# data/report.html remade (advisor.report).
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

try {
    $progress = Join-Path $repo "data\progress"
    New-Item -ItemType Directory -Force $progress | Out-Null
    $running = & ssh -o BatchMode=yes -o ConnectTimeout=20 office 'bash autotavern/scripts/office/progress.sh'
    if ($LASTEXITCODE -eq 0) {
        Set-Content (Join-Path $progress "running.txt") ($running -join "`n") -Encoding utf8
        $tgz = Join-Path $progress "bgprogress.tgz"
        & scp -q -o BatchMode=yes -o ConnectTimeout=20 "office:/tmp/bgprogress.tgz" $tgz
        $unpack = Join-Path $progress "unpack"
        if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
        New-Item -ItemType Directory -Force $unpack | Out-Null
        & (Join-Path $env:SystemRoot "System32\tar.exe") -xzf $tgz -C $unpack
        $train = Join-Path $progress "train"
        if (Test-Path $train) { Remove-Item $train -Recurse -Force }
        Move-Item (Join-Path $unpack "data\train") $train
        Remove-Item $unpack, $tgz -Recurse -Force
    } else { Log "progress: office unreachable (ssh exit $LASTEXITCODE)" }
    Set-Location $repo
    & (Join-Path $env:USERPROFILE "anaconda3\envs\taverngym\python.exe") -X utf8 -m advisor.report | Out-Null
    Log "progress page remade"
} catch {
    Log "progress failed: $($_.Exception.Message)"
}

# The library seats' real warbands and the round starts (advisor.library): rebuilt from the logs when a game was
# played since, never while Hearthstone runs (it parses every log), and sent to the office's
# training runs when they changed (they pick the new file up by themselves).
try {
    if (-not (Get-Process -Name Hearthstone -ErrorAction SilentlyContinue)) {
        Set-Location $repo
        $py = Join-Path $env:USERPROFILE "anaconda3\envs\taverngym\python.exe"
        $said = & $py -X utf8 -m advisor.library --refresh 2>&1 | Select-Object -Last 2
        $boards = Join-Path $repo "data\library\boards.json"
        $starts = Join-Path $repo "data\library\starts.jsonl"
        $sent = Join-Path $repo "data\library\sent.sha256"
        $hash = (Get-FileHash $boards -Algorithm SHA256).Hash + (Get-FileHash $starts -Algorithm SHA256).Hash
        $last = if (Test-Path $sent) { Get-Content $sent } else { "" }
        if ($hash -ne $last) {
            & scp -q -o BatchMode=yes -o ConnectTimeout=20 $boards "office:autotavern/data/library/boards.json.tmp"
            & scp -q -o BatchMode=yes -o ConnectTimeout=20 $starts "office:autotavern/data/library/starts.jsonl.tmp"
            & ssh -o BatchMode=yes -o ConnectTimeout=20 office 'cd autotavern/data/library && mv boards.json.tmp boards.json && mv starts.jsonl.tmp starts.jsonl'
            if ($LASTEXITCODE -eq 0) {
                Set-Content $sent $hash
                Log "library sent to the office: $($said -join ' ')"
                # The player's own choices (advisor.human_data), rebuilt from the same logs
                & $py -X utf8 -m advisor.human_data 2>&1 | Out-Null
                foreach ($dir in @("human", "human_eval")) {
                    $shards = Get-ChildItem (Join-Path $repo "data\search\$dir") -Filter "shard_*.npz" -ErrorAction SilentlyContinue
                    if ($shards) {
                        & ssh -o BatchMode=yes -o ConnectTimeout=20 office "mkdir -p autotavern/data/search/$dir.new"
                        foreach ($f in $shards) { & scp -q -o BatchMode=yes -o ConnectTimeout=20 $f.FullName "office:autotavern/data/search/$dir.new/" }
                        & ssh -o BatchMode=yes -o ConnectTimeout=20 office "cd autotavern/data/search && rm -rf $dir.old && mv $dir $dir.old && mv $dir.new $dir && rm -rf $dir.old"
                    }
                }
                Log "the player's choices sent to the office"
                # docs/ROBUSTNESS.md: every advice of the new game re-checked (advisor.review,
                # data/review), and the simulator against all logs vs its baseline
                # (advisor.fidelity, data/replay/fidelity_last.json); both pause while you play
                & $py -X utf8 -m advisor.review 2>&1 | Select-Object -Last 12 | ForEach-Object { Log "review: $_" }
                if ($LASTEXITCODE -ne 0) { Log "review FAILED (exit $LASTEXITCODE)" }
                & $py -X utf8 -m advisor.fidelity 2>&1 | Select-Object -Last 8 | ForEach-Object { Log "fidelity: $_" }
                # (a check that fails says so: fidelity crashed unnoticed from Oct 30 to 31)
                if ($LASTEXITCODE -ne 0) { Log "fidelity FAILED (exit $LASTEXITCODE)" }
                # (and how often you followed the advice, per game: advisor.usefulness)
                & $py -X utf8 -m advisor.usefulness 2>&1 | Select-Object -Last 3 | ForEach-Object { Log "usefulness: $_" }
            } else { Log "library: office unreachable (exit $LASTEXITCODE)" }
        }
    }
} catch {
    Log "library failed: $($_.Exception.Message)"
}

# The progress page's strength curve (advisor.study --curve: 16 games of the overlay's network,
# a few minutes of CPU): remade when the network is newer than it, never while Hearthstone runs.
try {
    $best = Join-Path $repo "data\models\best.pt"
    $curve = Join-Path $repo "data\progress\curve.json"
    $stale = (Test-Path $best) -and (-not (Test-Path $curve) -or (Get-Item $curve).LastWriteTime -lt (Get-Item $best).LastWriteTime)
    if ($stale -and -not (Get-Process -Name Hearthstone -ErrorAction SilentlyContinue)) {
        Set-Location $repo
        $py = Join-Path $env:USERPROFILE "anaconda3\envs\taverngym\python.exe"
        & $py -X utf8 -m advisor.study $best --games 16 --curve $curve 2>&1 | Out-Null
        # The genre scorecard (advisor.genres: ~30 minutes, pauses while Hearthstone runs); the
        # office's comp starts are weighted by it (advisor.train.comp_curriculum)
        $genres = Join-Path $repo "data\progress\genres.json"
        & $py -X utf8 -m advisor.genres $best --rounds 8 --ahead 2 --trials 1 --json $genres 2>&1 | Out-Null
        if (Test-Path $genres) {
            & scp -q -o BatchMode=yes -o ConnectTimeout=20 $genres "office:autotavern/data/library/genres.json"
        }
        # Your mid/late turns against the network's (advisor.compare_play): the bottom line's habits
        & $py -X utf8 -m advisor.compare_play $best --json (Join-Path $repo "data\progress\compare_play.json") 2>&1 | Out-Null
        # The pattern checks (advisor.patterns: Beatboxer, late turns), one line per network
        & $py -X utf8 -m advisor.patterns $best 2>$null | Add-Content (Join-Path $repo "data\progress\patterns.jsonl") -Encoding utf8
        & $py -X utf8 -m advisor.report | Out-Null
        Log "strength curve remade"
    }
} catch {
    Log "curve failed: $($_.Exception.Message)"
}
