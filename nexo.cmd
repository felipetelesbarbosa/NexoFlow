@echo off
setlocal
set "NEXO_HOME=%~dp0"
if exist "%NEXO_HOME%.venv\Scripts\python.exe" (
  "%NEXO_HOME%.venv\Scripts\python.exe" "%NEXO_HOME%nexo_cli.py" %*
) else (
  python "%NEXO_HOME%nexo_cli.py" %*
)
exit /b %errorlevel%
