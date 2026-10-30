@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Stop-Workbench.ps1" %*
if errorlevel 1 pause
