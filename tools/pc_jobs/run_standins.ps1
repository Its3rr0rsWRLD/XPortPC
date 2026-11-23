# Runs each stand-in GDK sample (Microsoft's public Xbox-GDK-Samples, built for PC by
# tools/build_standin_samples.ps1) under x2w_launch with the built shims and collects the run logs.
# For the PC worker's script jobs (cards: pc-gpu-queue, "Script jobs"): -Build is out\build\dev of the
# job's worktree, -Out the job's results folder. Writes <Out>\<Sample>\run.log, stderr.txt (x2w lines only)
# and exit.txt, and <Out>\summary.tsv. Copies no sample files; each run is hidden and time-limited.
param(
    [Parameter(Mandatory = $true)][string]$Build,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Samples = "C:\Users\brady\Documents\GitHub\anyps5-agents\jobs\standin\bin",
    [int]$Timeout = 40
)
$ErrorActionPreference = "Continue"
$launcher = Join-Path $Build "x2w_launch.exe"
$shims = Join-Path $Build "shims"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$summary = @("sample`texit`tseconds`tlast-lines")
foreach ($dir in Get-ChildItem -Directory $Samples) {
    $exe = Get-ChildItem -File -Path $dir.FullName -Filter *.exe | Select-Object -First 1
    if (-not $exe) { continue }
    $target = Join-Path $Out $dir.Name
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    $log = Join-Path $target "run.log"
    $err = Join-Path $target "stderr-full.txt"
    $outFile = Join-Path $target "stdout.txt"
    $start = Get-Date
    $p = Start-Process -FilePath $launcher -WorkingDirectory $dir.FullName -WindowStyle Hidden -PassThru `
        -RedirectStandardError $err -RedirectStandardOutput $outFile `
        -ArgumentList @("--shims", "`"$shims`"", "--log", "`"$log`"", "--timeout", "$Timeout", "`"$($exe.FullName)`"")
    if (-not $p.WaitForExit(($Timeout + 30) * 1000)) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        $code = "killed"
    } else {
        $code = "0x{0:x}" -f $p.ExitCode
    }
    $seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
    # Keep only the launcher's and shims' own lines (names and numbers), never sample output.
    if (Test-Path $err) {
        Get-Content $err | Where-Object { $_.StartsWith("[x2w] ") -and -not $_.StartsWith("[x2w] import ") } |
            Set-Content (Join-Path $target "stderr.txt")
        Remove-Item $err -Force
    }
    if (Test-Path $outFile) { Remove-Item $outFile -Force }
    Set-Content (Join-Path $target "exit.txt") "$code $seconds s"
    $tail = if (Test-Path $log) { (Get-Content $log | Select-Object -Last 2) -join " | " } else { "no log" }
    $summary += "$($dir.Name)`t$code`t$seconds`t$tail"
}
$summary | Set-Content (Join-Path $Out "summary.tsv")
$summary | ForEach-Object { Write-Output $_ }
exit 0
