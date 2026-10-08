@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

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

echo [1/3] Verificando sintaxe...
".venv\Scripts\python.exe" -m compileall -q -x "(\.venv|webhook_eventos|webhook_pedidos)" .
if errorlevel 1 goto :erro

echo [OK] Sintaxe.
echo.
echo [2/3] Executando testes...
".venv\Scripts\python.exe" run_checkup_tests.py
if errorlevel 1 goto :erro

echo.
echo [OK] Testes.
echo.
echo [3/3] Auditando consistencia entre arquivos...
".venv\Scripts\python.exe" auditar_consistencia.py
if errorlevel 1 goto :erro

echo.
echo [OK] Código, testes e auditoria passaram.
if not defined NEXOFLOW_LAUNCHER pause
exit /b 0

:erro
echo.
echo [ERRO] A verificação encontrou um problema.
if not defined NEXOFLOW_LAUNCHER pause
exit /b 1
