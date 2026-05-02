@echo off
TITLE Instalador de ia_profesor
SETLOCAL
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
IF ERRORLEVEL 1 (
    ECHO.
    ECHO Si hubo un bloqueo de PowerShell, probá clic derecho ^> Ejecutar con PowerShell
)
ENDLOCAL
