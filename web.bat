@echo off
TITLE English Voice Coach Web
SETLOCAL

SET PYTHON_CMD=%~dp0.venv\Scripts\python.exe
IF NOT EXIST "%PYTHON_CMD%" (
    ECHO Local virtual environment not found at %PYTHON_CMD%
    PAUSE
    EXIT /B 1
)

ECHO Starting web voice coach on http://127.0.0.1:5000 ...
START "" http://127.0.0.1:5000
"%PYTHON_CMD%" "%~dp0web_app.py"
