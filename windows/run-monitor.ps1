[CmdletBinding()]
param(
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputPath = Join-Path $projectRoot 'artifacts\geekmagic-current.jpg'
$logPath = Join-Path $projectRoot 'artifacts\logs\monitor.log'
$lockPath = Join-Path $projectRoot 'artifacts\geekmagic-monitor.lock'
$commandName = if ($Once) { 'run-once' } else { 'run' }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found on PATH. Install uv before starting the monitor.'
}

& uv run --project $projectRoot geekmagic-ai-monitor `
    --settings-dir $projectRoot `
    $commandName `
    --output $outputPath `
    --log-file $logPath `
    --lock-file $lockPath

exit $LASTEXITCODE
