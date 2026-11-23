# Runs the title memory layer's tests verbosely on the PC worker (cards: pc-gpu-queue, "Script jobs") and keeps
# their full output, which the plain ctest job does not: -Build is out\build\dev of the job's worktree, -Out the
# job's results folder. The ctest regex is the first line of tools\pc_jobs\xmem_regex.txt; an optional second line
# is a repeat count (ctest --repeat until-fail:N).
# Writes <Out>\ctest-v.txt (ctest -V output) and <Out>\exit.txt (ctest's exit code).
param(
    [Parameter(Mandatory = $true)][string]$Build,
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$lines = @(Get-Content (Join-Path $PSScriptRoot "xmem_regex.txt"))
$regex = $lines[0].Trim()
$repeat = @()
if ($lines.Count -gt 1 -and $lines[1].Trim()) { $repeat = @("--repeat", "until-fail:$($lines[1].Trim())") }
$ctest = (Get-Command ctest -ErrorAction SilentlyContinue).Source
if (-not $ctest) {
    $ctest = Get-ChildItem "C:\Program Files\Microsoft Visual Studio\*\*\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\ctest.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ctest) { "ctest not found" | Out-File (Join-Path $Out "ctest-v.txt"); exit 3 }
$log = Join-Path $Out "ctest-v.txt"
& $ctest --test-dir $Build --no-tests=error -R $regex -V --timeout 300 @repeat *>&1 | Out-File -Encoding utf8 $log
$code = $LASTEXITCODE
"$code" | Out-File -Encoding ascii (Join-Path $Out "exit.txt")
exit $code
