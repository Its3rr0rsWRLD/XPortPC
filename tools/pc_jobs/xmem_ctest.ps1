# Runs the title memory layer's tests verbosely on the PC worker (cards: pc-gpu-queue, "Script jobs") and keeps
# their full output, which the plain ctest job does not: -Build is out\build\dev of the job's worktree, -Out the
# job's results folder. The ctest regex is the first line of tools\pc_jobs\xmem_regex.txt; an optional second line
# is a repeat count (ctest --repeat until-fail:N). Prefer a plain ctest regex job; use this only for -V output.
# Writes <Out>\ctest-v.txt (ctest -V output), <Out>\exit.txt (ctest's exit code) and <Out>\leftovers.txt.
#
# Bounded: ctest runs with a per-test --timeout and the whole run with a wall-clock limit ($WallSeconds), after
# which its process tree is killed. Afterwards every process still descending from ctest is listed and killed: a
# crashed test can leave WerFault.exe (Windows Error Reporting) waiting in the tree, and a caller that waits for the
# whole tree would otherwise wait forever (job xmem2-bebc93ae: ctest finished in 570 s, the job hung for 6 h).
param(
    [Parameter(Mandatory = $true)][string]$Build,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$WallSeconds = 1200,
    [int]$TestSeconds = 300
)
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$lines = @(Get-Content (Join-Path $PSScriptRoot "xmem_regex.txt"))
$regex = $lines[0].Trim()
$arguments = @("--test-dir", "`"$Build`"", "--no-tests=error", "-R", "`"$regex`"", "-V", "--timeout", "$TestSeconds")
if ($lines.Count -gt 1 -and $lines[1].Trim()) { $arguments += @("--repeat", "until-fail:$($lines[1].Trim())") }
$ctest = (Get-Command ctest -ErrorAction SilentlyContinue).Source
if (-not $ctest) {
    $ctest = Get-ChildItem "C:\Program Files\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\ctest.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
$log = Join-Path $Out "ctest-v.txt"
if (-not $ctest) { "ctest not found" | Out-File $log; "3" | Out-File -Encoding ascii (Join-Path $Out "exit.txt"); exit 3 }

# Every live process descending from $root (by parent id), deepest first.
function Get-Descendants([int]$root) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $found = @()
    $frontier = @($root)
    while ($frontier.Count) {
        $next = @()
        foreach ($p in $all) {
            if ($frontier -contains [int]$p.ParentProcessId -and $p.ProcessId -ne $root -and
                -not ($found | Where-Object { $_.ProcessId -eq $p.ProcessId })) {
                $found += $p
                $next += [int]$p.ProcessId
            }
        }
        $frontier = $next
    }
    [array]::Reverse($found)
    return $found
}

# Files, not pipes: nothing the tests start can hold this script's output open.
$process = Start-Process -FilePath $ctest -ArgumentList $arguments -NoNewWindow -PassThru `
    -RedirectStandardOutput $log -RedirectStandardError (Join-Path $Out "ctest-err.txt")
$null = $process.Handle  # keeps the exit code readable after the process ends
$finished = $process.WaitForExit($WallSeconds * 1000)
$descendants = @(Get-Descendants $process.Id)
if ($finished) {
    $code = $process.ExitCode
} else {
    $code = 124
    "ctest still running after $WallSeconds s; killing its process tree" | Out-File -Append -Encoding utf8 $log
    & taskkill.exe /T /F /PID $process.Id 2>&1 | Out-Null
}
$report = Join-Path $Out "leftovers.txt"
"" | Out-File -Encoding utf8 $report
foreach ($p in $descendants) {
    "leftover pid=$($p.ProcessId) parent=$($p.ParentProcessId) name=$($p.Name) command=$($p.CommandLine)" |
        Out-File -Append -Encoding utf8 $report
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
"$code" | Out-File -Encoding ascii (Join-Path $Out "exit.txt")
exit $code
