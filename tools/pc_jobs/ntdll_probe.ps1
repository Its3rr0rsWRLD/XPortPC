# Copies this PC's ntdll.dll (a Windows system file) and prints its version, so faults reported as
# ntdll.dll+0xRVA can be resolved against Microsoft's public symbols off the PC.
param(
    [Parameter(Mandatory = $true)][string]$Build,
    [Parameter(Mandatory = $true)][string]$Out
)
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$path = Join-Path $env:WINDIR "System32\ntdll.dll"
Copy-Item $path (Join-Path $Out "ntdll.bin") -Force
(Get-Item $path).VersionInfo.FileVersionRaw.ToString() | Out-File (Join-Path $Out "ntdll-version.txt")
[System.Environment]::OSVersion.Version.ToString() | Out-File -Append (Join-Path $Out "ntdll-version.txt")
