<#
.SYNOPSIS
    Convert (if needed) and open a song in GoatTracker.

.DESCRIPTION
    Accepts a .sid or a .sng. A .sid is converted first via the h2g CLI, then
    the resulting .sng is opened in GoatTracker.

    Defaults to --format gts5. GoatTracker's *legacy* GTS2 importer has a
    buffer overrun (src/gsong.c:306: `length` is rows*4 bytes but the
    command-conversion loop indexes it as rows, so it walks ~3 patterns past
    the end and writes wherever it finds command $1/$2/$3/$4/$0E -- exactly the
    portamento commands this converter emits). The GTS3/4/5 loader has no such
    loop, so gts5 is the right format for anything you actually open here.
    Pass -Format gts2 if you specifically want the original tool's output.

    Converted files go to build\ -- never next to the input, because
    Commando.sng at the repo root is the byte-exact regression fixture and
    must not be overwritten.

    GoatTracker is located via -GoatTracker, else $env:H2G_GOATTRACKER, else a
    default install path.

.PARAMETER Song
    Path to a .sid or .sng file.

.PARAMETER Format
    Output format when converting a .sid. Default gts5. Ignored for a .sng input.

.PARAMETER GoatTracker
    Path to goattrk2.exe, or the directory containing it.

.PARAMETER NoLaunch
    Convert and stage only; do not start GoatTracker.

.EXAMPLE
    .\play.ps1 Commando.sid

.EXAMPLE
    .\play.ps1 arkiv\Crazy_Comets.sid -MaxRows 128 -TerminatePatterns

.EXAMPLE
    .\play.ps1 build\Commando.sng          # already converted

.NOTES
    Once the window is up: F1 plays from the beginning, F2 from the current
    position. The song is loaded at startup but does NOT auto-play.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Song,

    [ValidateSet('gts2', 'gts5')]
    [string]$Format = 'gts5',

    [ValidateRange(1, 128)]
    [int]$MaxRows,

    [switch]$TerminatePatterns,

    [switch]$DedupPatterns,

    [switch]$PrunePatterns,

    [switch]$PackRepeats,

    # Startup tempo, calls per pattern row, or 'auto' (default).
    # 'none' omits it and leaves Goattracker's 6 calls/row.
    [string]$Tempo = 'auto',

    [string]$GoatTracker,

    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$repoRoot  = $PSScriptRoot
$buildDir  = Join-Path $repoRoot "build"

if (-not (Test-Path -LiteralPath $Song)) {
    Write-Error "Song not found: $Song"
    exit 1
}
$songPath = (Resolve-Path -LiteralPath $Song).Path
$ext      = [System.IO.Path]::GetExtension($songPath).ToLowerInvariant()

# ---- convert a .sid -------------------------------------------------------
if ($ext -eq ".sid") {
    if (-not (Test-Path $buildDir)) {
        New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    }
    $stem   = [System.IO.Path]::GetFileNameWithoutExtension($songPath)
    $sngOut = Join-Path $buildDir "$stem.sng"

    $convert = Join-Path $repoRoot "convert.ps1"
    $cArgs = @{ SidFile = $songPath; OutputFile = $sngOut; Format = $Format; Quiet = $true }
    if ($PSBoundParameters.ContainsKey("MaxRows")) { $cArgs.MaxRows = $MaxRows }
    if ($TerminatePatterns)                        { $cArgs.TerminatePatterns = $true }
    if ($DedupPatterns)                            { $cArgs.DedupPatterns = $true }
    if ($PrunePatterns)                            { $cArgs.PrunePatterns = $true }
    if ($PackRepeats)                              { $cArgs.PackRepeats = $true }
    if ($Tempo -and $Tempo -ne 'none')             { $cArgs.Tempo = $Tempo }

    & $convert @cArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Conversion failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
    $songPath = (Resolve-Path -LiteralPath $sngOut).Path
}
elseif ($ext -ne ".sng") {
    Write-Error "Expected a .sid or .sng file, got '$ext'"
    exit 1
}

# goattrk2 does `strcpy(songfilename, argv[c])` into a char[60] (MAX_FILENAME)
# *before* reducing it to the basename, so a long path smashes that buffer. We
# pass the bare filename with the working directory set instead, which is also
# what goattrk2 would end up doing itself after its own chdir().
$songDir  = Split-Path -Parent $songPath
$songLeaf = Split-Path -Leaf   $songPath
if ($songLeaf.Length -ge 60) {
    Write-Error "Filename '$songLeaf' is $($songLeaf.Length) chars; GoatTracker's MAX_FILENAME is 60"
    exit 1
}

Write-Host "song: $songPath"

if ($NoLaunch) {
    Write-Host "staged only (-NoLaunch)"
    exit 0
}

# ---- locate GoatTracker ---------------------------------------------------
# Accepts either the exe itself or the directory holding it.
function Resolve-GoatTracker([string]$candidate) {
    if (-not $candidate) { return $null }
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        $try = Join-Path $candidate "goattrk2.exe"
        if (Test-Path -LiteralPath $try) { return (Resolve-Path -LiteralPath $try).Path }
        return $null
    }
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    return $null
}

$defaultExe = "C:\Users\mit\Downloads\GoatTracker_2.77\win32\goattrk2.exe"

# An explicit override must never silently fall back to the default -- that
# would launch a different binary than the one asked for.
if ($GoatTracker) {
    $exe = Resolve-GoatTracker $GoatTracker
    if (-not $exe) { Write-Error "-GoatTracker '$GoatTracker' does not contain goattrk2.exe"; exit 1 }
}
elseif ($env:H2G_GOATTRACKER) {
    $exe = Resolve-GoatTracker $env:H2G_GOATTRACKER
    if (-not $exe) { Write-Error "`$env:H2G_GOATTRACKER '$env:H2G_GOATTRACKER' does not contain goattrk2.exe"; exit 1 }
}
else {
    $exe = Resolve-GoatTracker $defaultExe
    if (-not $exe) {
        Write-Error ("goattrk2.exe not found at $defaultExe`n" +
                     "Set -GoatTracker or `$env:H2G_GOATTRACKER.")
        exit 1
    }
}

# sdl.dll must sit beside the exe; Windows resolves an exe's own imports from
# its directory regardless of the working directory we set below.
$sdl = Join-Path (Split-Path -Parent $exe) "sdl.dll"
if (-not (Test-Path -LiteralPath $sdl)) {
    Write-Warning "sdl.dll not found next to $exe -- GoatTracker will fail to start."
}

Write-Host "launching: $exe"
$proc = Start-Process -FilePath $exe -ArgumentList $songLeaf `
                      -WorkingDirectory $songDir -PassThru
Start-Sleep -Milliseconds 1500

if ($proc.HasExited) {
    Write-Error "GoatTracker exited immediately (code $($proc.ExitCode))."
    exit 1
}

Write-Host "running (PID $($proc.Id)) -- F1 plays from the beginning, F2 from current position."
if ($Tempo -and $Tempo -ne 'none') {
    Write-Host "tempo written: press SHIFT+F6 once to set speed multiplier 2 for correct timing."
}
exit 0
