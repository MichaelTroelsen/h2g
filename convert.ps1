<#
.SYNOPSIS
    Convert a Rob Hubbard .SID file to Goattracker (.sng) format via the h2g Python CLI.

.PARAMETER SidFile
    Path to the input .sid file.

.PARAMETER OutputFile
    Path to the output .sng file. Defaults to <SidFile> with a .sng extension.

.PARAMETER Quiet
    Suppress the progress log.

.EXAMPLE
    .\convert.ps1 Commando.sid

.EXAMPLE
    .\convert.ps1 -SidFile arkiv\Bump_Set_Spike.sid -OutputFile out\Bump_Set_Spike.sng
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$SidFile,

    [Parameter(Position = 1)]
    [string]$OutputFile,

    [switch]$Quiet,

    # Pattern-slicing length, 1..128. Default 94 matches the original VB6 tool;
    # 128 is Goattracker's real MAX_PATTROWS since v2.32 and fits some tunes
    # that otherwise exceed its capacity.
    [ValidateRange(1, 128)]
    [int]$MaxRows,

    # Append an explicit ENDPATT row to every pattern slice, as Goattracker's
    # own saver does. Off by default because it changes the output bytes.
    [switch]$TerminatePatterns,

    # Share one pattern between byte-identical slices. Removes 10-20% of
    # patterns on typical Hubbard tunes; does not shorten orderlists.
    [switch]$DedupPatterns,

    # Drop patterns no track's orderlist references. Cannot change playback --
    # an unreferenced pattern is unreachable -- but it renumbers the rest.
    [switch]$PrunePatterns,

    # Collapse runs of one repeated pattern into Goattracker REPEAT commands.
    # The only option that shortens an orderlist, so the only one that can
    # rescue a tune from the 254-byte orderlist limit.
    [switch]$PackRepeats,

    # Rewrite the out-of-range restart position that stands in for Hubbard's
    # "tune ended" marker. Required for -Sid: greloc.c:244 refuses to export a
    # song that carries one. The tune loops from the top instead of ending.
    # Implied by a preset file whose `always.legal_restart` is true.
    [switch]$LegalRestart,

    # JSON file of per-song options (see python/presets.py). The entry matching
    # this .sid supplies the options that suit it; anything passed explicitly
    # still wins.
    [string]$Presets,

    # Pack the converted .sng back to a .sid with gt2reloc, Goattracker's F9
    # packer. Implied by a preset file whose `always.gt2reloc` is true.
    [switch]$Sid,

    # Path to gt2reloc.exe. Falls back to $env:H2G_GT2RELOC, then a default.
    [string]$Gt2reloc,

    # Output .sng format. gts5 is the modern 4-table format and avoids a
    # buffer overrun in Goattracker's legacy gts2 importer.
    [ValidateSet('gts2','gts5')]
    [string]$Format,

    # Startup tempo in play-routine calls per pattern row, or 'auto'.
    # Without one, Goattracker uses 6 calls/row -- 6x too slow, since
    # the converter emits one row per player tick.
    [string]$Tempo
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$pythonDir = Join-Path $repoRoot "python"

if (-not (Test-Path $SidFile)) {
    Write-Error "SID file not found: $SidFile"
    exit 1
}

$resolvedSid = (Resolve-Path $SidFile).Path

$resolvedOutput = $null
if ($OutputFile) {
    $outDir = Split-Path -Parent $OutputFile
    if ($outDir -and -not (Test-Path $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }
    # Join-Path against the CWD would duplicate the root for an already-absolute
    # path ("C:\repo" + "C:\out\x.sng" -> "C:\repo\C:\out\x.sng"), so only
    # resolve relative paths against it.
    $resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputFile)) {
        [System.IO.Path]::GetFullPath($OutputFile)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputFile))
    }
}

$pyArgs = @($resolvedSid)
if ($resolvedOutput) { $pyArgs += @("-o", $resolvedOutput) }
if ($Quiet) { $pyArgs += "-q" }
if ($PSBoundParameters.ContainsKey("MaxRows")) { $pyArgs += @("--max-rows", $MaxRows) }
if ($TerminatePatterns) { $pyArgs += "--terminate-patterns" }
if ($DedupPatterns)     { $pyArgs += "--dedup-patterns" }
if ($PrunePatterns)     { $pyArgs += "--prune-patterns" }
if ($PackRepeats)       { $pyArgs += "--pack-repeats" }
if ($LegalRestart)      { $pyArgs += "--legal-restart" }
if ($Presets)           { $pyArgs += @("--presets", (Resolve-Path -LiteralPath $Presets).Path) }
if ($Format) { $pyArgs += @("--format", $Format) }
if ($Tempo)  { $pyArgs += @("--tempo", $Tempo) }

Push-Location $pythonDir
try {
    python -m h2g @pyArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) { exit $exitCode }

# ---- pack to .sid ---------------------------------------------------------
# gt2reloc is the standalone form of GoatTracker's F9 packer and writes .sid
# straight from the output extension, so this turns a conversion into
# something a SID player can play.
$wantSid = $Sid
if ($Presets -and -not $Sid) {
    $doc = Get-Content -LiteralPath $Presets -Raw | ConvertFrom-Json
    if ($doc.always.gt2reloc) { $wantSid = $true }
}

if ($wantSid) {
    $exe = $Gt2reloc
    if (-not $exe) { $exe = $env:H2G_GT2RELOC }
    if (-not $exe) { $exe = "C:\Users\mit\Downloads\GoatTracker_2.77\win32\gt2reloc.exe" }
    if (-not (Test-Path -LiteralPath $exe)) {
        Write-Error "gt2reloc.exe not found at '$exe'. Set -Gt2reloc or `$env:H2G_GT2RELOC."
        exit 1
    }

    $sngPath = if ($resolvedOutput) { $resolvedOutput } else {
        [System.IO.Path]::ChangeExtension($resolvedSid, ".sng") }
    $sidOut  = [System.IO.Path]::ChangeExtension($sngPath, ".sid")
    if (Test-Path -LiteralPath $sidOut) { Remove-Item -LiteralPath $sidOut -Force }

    # Bare filenames with the working directory set: gt2reloc strcpy()s argv
    # into a 60-byte buffer before reducing it to a basename.
    $dir = Split-Path -Parent $sngPath
    Start-Process -FilePath $exe -WorkingDirectory $dir -Wait -NoNewWindow `
                  -ArgumentList @((Split-Path -Leaf $sngPath), (Split-Path -Leaf $sidOut)) | Out-Null

    # Never trust the exit code: gt2reloc reports fatal errors through
    # fopen("CON") and SDL routines that do nothing headless, so a refusal is
    # exit 0 with no output and no file. The written file is the only signal.
    if (Test-Path -LiteralPath $sidOut) {
        Write-Host "Packed $sidOut ($((Get-Item -LiteralPath $sidOut).Length) bytes)"
    } else {
        Write-Error ("gt2reloc wrote no .sid. The usual cause is the restart position " +
                     "this converter emits for a $FE track byte, which greloc.c:244 " +
                     "rejects -- pass -LegalRestart (or use -Presets, whose `always` " +
                     "block sets it). See SNG2SID-FIDELITY.md.")
        exit 1
    }
}

exit $exitCode
