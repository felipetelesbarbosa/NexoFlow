@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title NexoFlow - Divisão das planilhas

if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente não encontrado. Execute instalar.bat.
    pause
    exit /b 1
)

echo ==========================================================
echo NexoFlow - Operação, Histórico e Dashboard
echo ==========================================================
echo Crie dois arquivos vazios e compartilhe como Editor com
 echo a conta de serviço configurada no NexoFlow.
echo O dashboard permanecerá no arquivo Google atual.
echo.
set /p "OPERACAO=ID ou link da planilha de Operação: "
set /p "HISTORICO=ID ou link da planilha de Histórico: "
".venv\Scripts\python.exe" run_sheets_migration.py --operacao "%OPERACAO%" --historico "%HISTORICO%"
if errorlevel 1 goto :erro

echo.
echo Antes de continuar, encerre todas as rotinas de Weni,
echo Analytics, Planilhas e Recompra e use esta atualização.
echo As cópias serão conferidas antes da retirada dos originais.
set "CONFIRMACAO="
set /p "CONFIRMACAO=Digite MIGRAR para confirmar que as rotinas estão encerradas: "
if /i not "%CONFIRMACAO%"=="MIGRAR" (
    echo [INFO] Migração não aplicada.
    pause
    exit /b 0
)
".venv\Scripts\python.exe" run_sheets_migration.py --operacao "%OPERACAO%" --historico "%HISTORICO%" --aplicar --rotinas-paradas --retirar-originais
if errorlevel 1 goto :erro
echo.
echo [OK] Migração concluída. As fontes BI do Looker permanecem no arquivo atual.
pause
exit /b 0

:erro
echo.
echo [ERRO] A migração não concluiu. Consulte logs\nexoflow.log.
echo Não limpe as abas manualmente; a retomada usa o registro privado da migração.
pause
exit /b 1
