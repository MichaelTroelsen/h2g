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
    [switch]$TerminatePatterns
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
    $resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputFile))
}

$pyArgs = @($resolvedSid)
if ($resolvedOutput) { $pyArgs += @("-o", $resolvedOutput) }
if ($Quiet) { $pyArgs += "-q" }
if ($PSBoundParameters.ContainsKey("MaxRows")) { $pyArgs += @("--max-rows", $MaxRows) }
if ($TerminatePatterns) { $pyArgs += "--terminate-patterns" }

Push-Location $pythonDir
try {
    python -m h2g @pyArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
