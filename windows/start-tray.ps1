[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputPath = Join-Path $projectRoot 'artifacts\geekmagic-current.jpg'
$logPath = Join-Path $projectRoot 'artifacts\logs\monitor.log'
$lockPath = Join-Path $projectRoot 'artifacts\geekmagic-monitor.lock'

# Explorer may still have the PATH from before a CLI was installed. Refresh the
# registered user PATH so desktop shortcuts can use newly installed commands
# without requiring a Windows sign-out.
$registeredUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($registeredUserPath) {
    $env:Path = "$registeredUserPath;$env:Path"
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        'uv를 PATH에서 찾을 수 없습니다. uv를 설치한 뒤 다시 실행하세요.',
        'GeekMagic AI Monitor',
        'OK',
        'Error'
    ) | Out-Null
    exit 1
}

$argumentLine = @(
    'run'
    '--project'
    "`"$projectRoot`""
    'geekmagic-ai-monitor-tray'
    '--settings-dir'
    "`"$projectRoot`""
    '--output'
    "`"$outputPath`""
    '--log-file'
    "`"$logPath`""
    '--lock-file'
    "`"$lockPath`""
) -join ' '

Start-Process `
    -FilePath $uvCommand.Source `
    -ArgumentList $argumentLine `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden

exit 0
