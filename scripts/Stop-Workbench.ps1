param([ValidateRange(1,65535)][int]$Port=8765, [string]$DataDirectory='', [string]$PythonExecutable='', [switch]$LegacyConfirmed)
$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspaceRoot
$pythonExe = if ($PythonExecutable) { (Resolve-Path -LiteralPath $PythonExecutable).Path } else { Join-Path $workspaceRoot '.venv\Scripts\python.exe' }
if (-not $PythonExecutable -and (Test-Path -LiteralPath (Join-Path $workspaceRoot '.runtime\python\python.exe'))) { $pythonExe = Join-Path $workspaceRoot '.runtime\python\python.exe' }
$launchArgs = @('-X','utf8','-m','backend.launcher','stop','--port',"$Port")
if ($DataDirectory) { $launchArgs += @('--data-directory',$DataDirectory) }
if ($LegacyConfirmed) { $launchArgs += '--legacy-confirmed' }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
& $pythonExe @launchArgs
exit $LASTEXITCODE
