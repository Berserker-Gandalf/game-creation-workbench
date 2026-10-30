@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Setup.ps1" -InstallMissing %*
if errorlevel 1 (pause) else (call "%~dp0Start-Workbench.cmd")
