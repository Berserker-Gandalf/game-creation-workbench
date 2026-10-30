@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Setup.ps1" -InstallMissing -Repair %*
pause
