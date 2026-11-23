<#
.SYNOPSIS
  Builds a few small, Microsoft-authored GDK samples for PC so XPortPC's launcher,
  report tool and shims can be exercised against real Microsoft-built callers.

.DESCRIPTION
  Public sources only:
    - https://github.com/microsoft/Xbox-GDK-Samples  (MIT)
    - the public PC GDK NuGet packages Microsoft.GDK.Core + Microsoft.GDK.Windows
      (api.nuget.org), extracted user-level into the work folder. Nothing is
      installed system-wide and no admin rights or reboot are needed.

  Samples are built with the stock x64 platform against the new (simplified) GDK
  layout, which is Microsoft's replacement for the Gaming.Desktop.x64 platform.
  Only source, the extracted GDK and build outputs land under -Work. Nothing is
  committed; -Work lives under out\ which git ignores.

  Outputs: <Work>\bin\<Sample>\ (exe, pdb, MicrosoftGame.config, redist DLLs, Media).

.EXAMPLE
  .\tools\build_standin_samples.ps1 -Work "$PWD\out\standin"
#>
[CmdletBinding()]
param(
    [string]$Work = (Join-Path (Get-Location) 'out\standin'),
    [string]$GdkVersion = '2610.0.9661',
    [string]$SamplesRef = 'b1e77b6',
    [string]$Configuration = 'Release',
    [string]$Toolset = 'v145',
    [string[]]$Only = @()
)
$ErrorActionPreference = 'Stop'

# name -> folder under Samples\ (solution has the same base name)
$samples = [ordered]@{
    SimpleTriangleDesktop = 'IntroGraphics\SimpleTriangleDesktop'  # D3D12 + XGameRuntimeInitialize
    SystemInfo            = 'System\SystemInfo'                    # XSystem*
    AsynchronousProgramming = 'System\AsynchronousProgramming'     # XTaskQueue / XAsync
    GameSaveCombo         = 'System\GameSaveCombo'                 # XUser + XGameSave
    GameInputSequential   = 'System\GameInputSequential'           # GameInput
}
if ($Only.Count) { foreach ($k in @($samples.Keys)) { if ($Only -notcontains $k) { $samples.Remove($k) } } }

New-Item -ItemType Directory -Force $Work | Out-Null
$Work = (Resolve-Path $Work).Path

# --- 1. public PC GDK from NuGet, extracted user-level -----------------------------
$nupkgDir = Join-Path $Work 'nupkg'; New-Item -ItemType Directory -Force $nupkgDir | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($id in 'core', 'windows') {
    $pkg = "microsoft.gdk.$id"
    $nupkg = Join-Path $nupkgDir "$pkg.$GdkVersion.nupkg"
    $dest = Join-Path $Work "gdk\$id"
    if (Test-Path $dest) { continue }
    if (-not (Test-Path $nupkg)) {
        & curl.exe -sSL --fail -o $nupkg "https://api.nuget.org/v3-flatcontainer/$pkg/$GdkVersion/$pkg.$GdkVersion.nupkg"
        if ($LASTEXITCODE) { throw "download of $pkg failed" }
    }
    [IO.Compression.ZipFile]::ExtractToDirectory($nupkg, $dest)   # also validates CRCs
}
$gdkRoot = (Get-ChildItem (Join-Path $Work 'gdk\windows\native') -Directory | Select-Object -First 1).FullName + '\'
$gameDk = Join-Path $Work 'gdk\core\native\'
if (-not (Test-Path (Join-Path $gdkRoot 'windows\include\XGameRuntime.h'))) { throw "GDK headers not found under $gdkRoot" }
$env:GameDKCoreLatest = $gdkRoot
$env:GameDKLatest = $gdkRoot
Write-Host "GDK: $gdkRoot"

# --- 2. samples source (public, pinned) --------------------------------------------
$src = Join-Path $Work 'samples'
if (-not (Test-Path $src)) {
    # blobless clone + sparse checkout: the repo's Media folder is multiple GB, the samples
    # here only need the UI fonts and textures
    git clone --quiet --no-checkout --filter=blob:none https://github.com/microsoft/Xbox-GDK-Samples.git $src
    if ($LASTEXITCODE) { throw 'clone failed' }
    git -C $src sparse-checkout init --no-cone
    Set-Content (Join-Path $src '.git\info\sparse-checkout') "/*`n!/Media/*`n/Media/Fonts/`n/Media/Textures/UI/`n/Media/Textures/ATGSampleBackground.DDS"
    git -C $src checkout --quiet $SamplesRef
    if ($LASTEXITCODE) { throw 'checkout failed' }
}
Write-Host ("Samples: " + (git -C $src rev-parse --short HEAD))

# --- 3. build ----------------------------------------------------------------------
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
if (-not (Test-Path $msbuild)) {
    $vsw = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $msbuild = & $vsw -latest -products * -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
}
$binRoot = Join-Path $Work 'bin'; $logRoot = Join-Path $Work 'logs'
New-Item -ItemType Directory -Force $binRoot, $logRoot | Out-Null
$gdkBin = Join-Path $gdkRoot 'windows\bin\x64'
$results = @()
foreach ($name in $samples.Keys) {
    $dir = Join-Path $src "Samples\$($samples[$name])"
    $log = Join-Path $logRoot "$name-build.log"
    Write-Host "== $name"
    & $msbuild (Join-Path $dir "$name.sln") -restore -p:RestorePackagesConfig=true `
        "-p:Configuration=$Configuration" -p:Platform=x64 "-p:PlatformToolset=$Toolset" `
        "-p:GameDK=$gameDk" -v:m -nologo "-fl" "-flp:logfile=$log;verbosity=normal" 2>&1 | Out-Null
    $ok = $LASTEXITCODE -eq 0
    $out = Join-Path $dir "x64\$Configuration"
    if ($ok -and (Test-Path (Join-Path $out "$name.exe"))) {
        $dst = Join-Path $binRoot $name
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse $out $dst
        # redist DLLs the sample links against but the build did not copy
        foreach ($dll in 'libHttpClient.dll', 'XCurl.dll') {
            if (-not (Test-Path (Join-Path $dst $dll)) -and (Test-Path (Join-Path $gdkBin $dll))) {
                Copy-Item (Join-Path $gdkBin $dll) $dst
            }
        }
        # samples load Media\ relative to the exe
        $media = Join-Path $src 'Media'
        if ((Test-Path $media) -and -not (Test-Path (Join-Path $dst 'Media'))) { Copy-Item -Recurse $media (Join-Path $dst 'Media') }
        $results += "$name`tOK`t$dst"
    } else {
        $results += "$name`tFAILED`t$log"
    }
}
$results | ForEach-Object { Write-Host $_ }
$results | Set-Content (Join-Path $Work 'build-summary.tsv')
