@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PROFILE_LOG=logs"
set "IMPORT_DIR=importacoes"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "IMPORT_DIR=importacoes\PET"
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow Planilha

:menu
cls
echo ==========================================================
echo NexoFlow Planilha - NexoFlow 1.5.9
echo ==========================================================
echo Coloque os arquivos na pasta %IMPORT_DIR%:
echo   Conversas_Delivery.xlsx
echo   Contatos_Delivery.xlsx
echo.
echo [1] Atualizar contatos e pedidos na Weni
echo [2] Atualizar Analytics e Google Sheets
echo [3] Abrir pasta de importações
echo [4] Sair
echo.
choice /C 1234 /N /M "Escolha uma opção: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto :importacoes
if errorlevel 2 goto :analytics
if errorlevel 1 goto :weni
exit /b 1

:importacoes
if not exist "%IMPORT_DIR%" mkdir "%IMPORT_DIR%"
start "" explorer.exe "%CD%\%IMPORT_DIR%"
goto :menu

:weni
call "%NEXOFLOW_HOME%\comandos\atualizar_weni_planilhas.bat"
goto :menu

:analytics
call "%NEXOFLOW_HOME%\comandos\executar_analytics_planilhas.bat"
goto :menu
