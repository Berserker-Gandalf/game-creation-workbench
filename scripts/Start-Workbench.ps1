param([switch]$NoBrowser, [ValidateRange(1,65535)][int]$Port=8765, [string]$DataDirectory='', [string]$PythonExecutable='')
$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspaceRoot
$pythonExe = if ($PythonExecutable) { (Resolve-Path -LiteralPath $PythonExecutable).Path } else { Join-Path $workspaceRoot '.venv\Scripts\python.exe' }
if (-not $PythonExecutable -and (Test-Path -LiteralPath (Join-Path $workspaceRoot '.runtime\python\python.exe'))) { $pythonExe = Join-Path $workspaceRoot '.runtime\python\python.exe' }
if (-not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Path -LiteralPath 'dist\index.html')) {
    & (Join-Path $PSScriptRoot 'Setup.ps1') -InstallMissing
}
$launchArgs = @('-X','utf8','-m','backend.launcher','start','--port',"$Port")
if ($DataDirectory) { $launchArgs += @('--data-directory',$DataDirectory) }
if ($NoBrowser) { $launchArgs += '--no-browser' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
& $pythonExe @launchArgs
exit $LASTEXITCODE
