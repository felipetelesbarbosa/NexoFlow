@echo off
chcp 65001 >nul
call "%~dp0carga_planilhas.bat" weni
exit /b %ERRORLEVEL%
