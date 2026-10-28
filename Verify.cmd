@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -m pytest -q
if errorlevel 1 exit /b 1
call npm.cmd run build
