@echo off
TITLE ia_profesor Web
SETLOCAL

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    if not "%%P"=="0" (
        echo [INFO] Cerrando instancia previa en el puerto 5000 - PID %%P
        taskkill /F /PID %%P >nul 2>&1
    )
)

timeout /t 1 /nobreak >nul
CALL "%~dp0Iniciar ia_profesor.bat"
ENDLOCAL
