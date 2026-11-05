@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PROFILE_LOG=logs"
set "IMPORT_DIR=importacoes"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "PROFILE_LOG=logs\PET"
if /i "%NEXOFLOW_PERFIL%"=="PET" set "IMPORT_DIR=importacoes\PET"
cd /d "%NEXOFLOW_HOME%\"

echo ==============================================
echo Check-up do projeto - NexoFlow
echo ==============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente .venv não encontrado.
    echo Execute instalar.bat primeiro.
    if not defined NEXOFLOW_LAUNCHER pause
    exit /b 1
)

echo [1/2] Verificando componentes e dependências locais...
".venv\Scripts\python.exe" app\run_checkup_tests.py
if errorlevel 1 goto :erro

echo.
echo [2/2] Auditando consistência entre arquivos...
".venv\Scripts\python.exe" app\auditar_consistencia.py
if errorlevel 1 goto :erro

echo.
echo [OK] Componentes locais e auditoria passaram.
echo [INFO] Testes completos de desenvolvimento são executados separadamente no CI.
if not defined NEXOFLOW_LAUNCHER pause
exit /b 0

:erro
echo.
echo [ERRO] A verificação encontrou um problema.
if not defined NEXOFLOW_LAUNCHER pause
exit /b 1
