param([switch]$InstallMissing, [switch]$RebuildUI, [switch]$Repair, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $workspaceRoot
function Refresh-ToolPath {
    $extraPaths = @((Join-Path $env:ProgramFiles 'nodejs'), (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'))
    $registered = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = $env:Path + ';' + $registered + ';' + ($extraPaths -join ';')
}
function Find-Python {
    $runtimeCandidates = @()
    foreach ($file in @((Join-Path $workspaceRoot '.venv\Scripts\python.exe'), (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), (Join-Path $env:ProgramFiles 'Python312\python.exe'))) {
        if (Test-Path -LiteralPath $file) { $runtimeCandidates += [pscustomobject]@{File=$file; Args=@()} }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { $runtimeCandidates += [pscustomobject]@{File=$launcher.Source; Args=@('-3.12')} }
    $standard = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($standard -and $standard.Source -notlike '*WindowsApps*') { $runtimeCandidates += [pscustomobject]@{File=$standard.Source; Args=@()} }
    foreach ($candidate in $runtimeCandidates) {
        $pythonArgs = @($candidate.Args) + @('-c','import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)')
        try { & $candidate.File @pythonArgs *> $null; if ($LASTEXITCODE -eq 0) { return $candidate } } catch {}
    }
    return $null
}
function Test-PrebuiltUI {
    $metadataPath = Join-Path $workspaceRoot 'dist\workbench-build.json'
    if (-not (Test-Path -LiteralPath $metadataPath)) { return $false }
    try {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $package = Get-Content -LiteralPath (Join-Path $workspaceRoot 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $entries = @($metadata.files.PSObject.Properties)
        if ($metadata.format -ne 1 -or $metadata.version -ne $package.version -or $entries.Count -lt 1 -or $entries.Count -gt 1000 -or -not $metadata.files.'index.html') { return $false }
        $distRoot = [IO.Path]::GetFullPath((Join-Path $workspaceRoot 'dist')) + [IO.Path]::DirectorySeparatorChar
        foreach ($entry in $entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $distRoot $entry.Name))
            if (-not $target.StartsWith($distRoot,[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $target -PathType Leaf)) { return $false }
            $sha = [Security.Cryptography.SHA256]::Create()
            $stream = [IO.File]::OpenRead($target)
            try { $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() } finally { $stream.Dispose(); $sha.Dispose() }
            if ($digest -ne $entry.Value) { return $false }
        }
        return $true
    } catch { return $false }
}
function Install-RequiredPackage($packageId, $label, $url) {
    if (-not $InstallMissing) { throw "需要 $label。请双击 Install-Workbench.cmd，或访问 $url" }
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $wingetCommand) { throw "本机缺少 WinGet。请从 $url 安装 $label，然后重新打开 Install-Workbench.cmd。" }
    Write-Host "将通过 Windows 程序管理器安装 $label（$packageId）。需要联网；系统权限、来源协议和软件许可请本人确认。"
    $answer = Read-Host '继续安装请输入 Y，其他输入取消 / Type Y to install'
    if ($answer -notmatch '^[Yy]$') { throw '已取消装配；已有项目数据保留。' }
    & $wingetCommand.Source install --id $packageId --exact --source winget --no-upgrade
    if ($LASTEXITCODE -ne 0) { throw "安装器未完成。请使用 $url 的官方安装包，完成后重新打开启动器。" }
    Refresh-ToolPath
}
function Test-CoreDependencies($executable, $lockFile) {
    if (-not (Test-Path -LiteralPath $executable)) { return $false }
    $verifyCode = "import sys,importlib.metadata as m; from pathlib import Path; rows=[s.strip().split('==',1) for s in Path(sys.argv[1]).read_text().splitlines() if '==' in s]; sys.exit(any(m.version(k)!=v for k,v in rows))"
    try { & $executable -X utf8 -c $verifyCode $lockFile *> $null; $dependenciesReady = $LASTEXITCODE -eq 0 } catch { $dependenciesReady = $false }
    if ($dependenciesReady) {
        try { & $executable -X utf8 -c 'import fastapi,uvicorn,httpx,PIL,python_multipart,tinytag' *> $null; $dependenciesReady = $LASTEXITCODE -eq 0 } catch { $dependenciesReady = $false }
    }
    return [bool]$dependenciesReady
}
$prebuiltReady = (Test-PrebuiltUI) -and -not $RebuildUI
$embeddedPython = Join-Path $workspaceRoot '.runtime\python\python.exe'
if (Test-Path -LiteralPath $embeddedPython) {
    $embeddedReady = Test-CoreDependencies $embeddedPython (Join-Path $workspaceRoot 'requirements.lock.txt')
    if ($CheckOnly) { [pscustomobject]@{python_found=$true; prebuilt_ready=[bool]$prebuiltReady; node_required=$false; repair=[bool]$Repair; core_dependencies_ready=[bool]$embeddedReady; private_python=$true} | ConvertTo-Json -Compress; return }
    if (-not $embeddedReady -or -not $prebuiltReady -or $RebuildUI) { throw '自带运行环境或界面校验未通过，请重新解压完整发行包到新目录；保留原用户数据。' }
    Write-Host '自带 Python 与界面校验通过，无需安装基础组件。'
    return
}
$runtime = Find-Python
if ($CheckOnly) {
    [pscustomobject]@{python_found=[bool]$runtime; prebuilt_ready=[bool]$prebuiltReady; node_required=(-not $prebuiltReady); repair=[bool]$Repair; core_dependencies_ready=(Test-CoreDependencies (Join-Path $workspaceRoot '.venv/Scripts/python.exe') (Join-Path $workspaceRoot 'requirements.lock.txt'))} | ConvertTo-Json -Compress
    return
}
if (-not $runtime) {
    Install-RequiredPackage 'Python.Python.3.12' 'Python 3.12' 'https://www.python.org/downloads/windows/'
    $runtime = Find-Python
    if (-not $runtime) { throw '尚未发现兼容 Python，请关闭本窗口后重新打开安装器。' }
}
$pythonExe = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonArgs = @($runtime.Args) + @('-m','venv',(Join-Path $workspaceRoot '.venv'))
    & $runtime.File @pythonArgs
    if ($LASTEXITCODE -ne 0) { throw '无法建立运行环境，请将源码解压到可写目录。已有项目数据无需删除。' }
}
$requirementsFile = if (Test-Path -LiteralPath 'requirements.lock.txt') { 'requirements.lock.txt' } else { 'requirements.txt' }
$dependenciesReady = Test-CoreDependencies $pythonExe $requirementsFile
if ($Repair -or -not $dependenciesReady) {
    Write-Host '正在装配工作台基础依赖 / Preparing core dependencies...'
    & $pythonExe -m pip install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) { throw '基础依赖安装失败。检查网络后重新运行 Repair-Workbench.cmd；保留原数据目录。' }
}
if (-not $prebuiltReady) {
    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        Install-RequiredPackage 'OpenJS.NodeJS.LTS' 'Node.js LTS' 'https://nodejs.org/en/download'
    }
    Write-Host '正在构建源码界面 / Building UI...'
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw '界面依赖安装失败，请检查网络或使用含预构建界面的发布包。' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '界面构建失败。请查看本窗口错误；已有项目数据保留。' }
} else { Write-Host '预构建界面校验通过，跳过 Node/npm 安装与构建。' }
Write-Host '准备完成。运行 Start-Workbench.cmd，在快速上手中选择创作功能。'
