@echo off
TITLE ia_profesor
SETLOCAL
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
ENDLOCAL
