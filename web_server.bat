@echo off
TITLE ia_profesor Web Server LAN
SETLOCAL

set IA_PROFESOR_HOST=0.0.0.0
set IA_PROFESOR_PORT=5000

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%IA_PROFESOR_PORT%" ^| findstr "LISTENING"') do (
    if not "%%P"=="0" (
        echo [INFO] Cerrando instancia previa en el puerto %IA_PROFESOR_PORT% - PID %%P
        taskkill /F /PID %%P >nul 2>&1
    )
)

timeout /t 1 /nobreak >nul
powershell -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
ENDLOCAL
