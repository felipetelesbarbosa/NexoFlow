@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "DESTINO=%~1"
if /I "%DESTINO%"=="weni" goto :destino_ok
if /I "%DESTINO%"=="analytics" goto :destino_ok
echo [ERRO] Destino inválido. Use os comandos nexo weni planilhas ou nexo analytics planilhas.
exit /b 1

:destino_ok
title NexoFlow 1.0 - Carga por planilhas
set "REVIEW_JSON=logs\delivery_%DESTINO%_review.json"
set "REVIEW_TXT=logs\delivery_%DESTINO%_review.txt"
if not exist "importacoes" mkdir "importacoes"
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual ausente. Execute instalar.bat primeiro.
    set "RC=1"
    goto :fim
)
echo ==========================================================
echo NexoFlow 1.0 - Carga por planilhas - %DESTINO%
echo ==========================================================
echo Coloque os exports originais na pasta importacoes:
echo   Conversas_Delivery.xlsx
echo   Contatos_Delivery.xlsx
echo.
echo [1/3] Validando vínculos e consultando pedidos na FarmaLíder...
".venv\Scripts\python.exe" run_delivery_tickets.py --dry-run --planilhas --target "%DESTINO%" --review-out "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :erro_consulta
echo.
echo [2/3] Revise o relatório no Bloco de Notas.
echo Confira identidade, pedidos, datas, exclusões e destino da carga.
start "" notepad.exe "%CD%\%REVIEW_TXT%"
echo O CMD permanecerá aguardando sua confirmação.
set "CONFIRMA="
set /p "CONFIRMA=Após revisar, digite PLANILHAS REVISADAS para aplicar: "
if /I not "%CONFIRMA%"=="PLANILHAS REVISADAS" (
    echo [INFO] Operação cancelada. Nenhuma alteração foi aplicada.
    set "RC=2"
    goto :fim
)
echo.
echo [3/3] Revalidando os contatos e aplicando o snapshot revisado...
".venv\Scripts\python.exe" run_delivery_tickets.py --apply --target "%DESTINO%" --require-review "%REVIEW_JSON%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [ERRO] Aplicação interrompida ou com conflitos. Consulte o relatório e logs\nexoflow_delivery.log.
    echo Uma aplicação parcial deve ser retomada com o mesmo snapshot revisado.
    goto :fim
)
echo [OK] Carga por planilhas concluída.
goto :fim

:erro_consulta
echo [ERRO] Consulta ou auditoria falhou. Nenhuma gravação foi iniciada.

:fim
if not defined NEXOFLOW_LAUNCHER pause
exit /b %RC%
