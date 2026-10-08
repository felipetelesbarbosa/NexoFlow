@echo off
chcp 65001 >nul
setlocal
set "NEXO_HOME=%~dp0"
if exist "%NEXO_HOME%.venv\Scripts\python.exe" (
  "%NEXO_HOME%.venv\Scripts\python.exe" "%NEXO_HOME%nexo_cli.py" %*
) else (
  python "%NEXO_HOME%nexo_cli.py" %*
)
exit /b %errorlevel%
