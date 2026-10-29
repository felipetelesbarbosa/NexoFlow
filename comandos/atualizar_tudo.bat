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
set "NEXOFLOW_LAUNCHER=1"
set "NEXOFLOW_FULL_WORKFLOW=1"
set "FORCE_FULL_SYNC="
set "FULL_SYNC_QUARTER="
cd /d "%NEXOFLOW_HOME%\"
title NexoFlow 1.5.3 - Atualização completa

echo ==========================================================
echo NexoFlow 1.5.3 - Atualização completa em ordem
echo ==========================================================
echo As cargas integrais serão executadas com 100%% da base.
echo Cada aplicação Weni, Planilhas e Recompra exige sua revisão.
echo Falha, cancelamento ou carga parcial interrompe o fluxo.
echo.
set "ETAPA=Preparação"
set "RC=1"
if not exist ".venv\Scripts\python.exe" goto :ambiente_ausente
for %%F in (comandos\atualizar_weni_carga_completa.bat comandos\atualizar_weni_planilhas.bat comandos\executar_analytics_planilhas.bat comandos\executar_carga_completa.bat comandos\atualizar_recompra.bat comandos\executar_manual.bat) do if not exist "%%F" goto :componente_ausente
if not exist "%IMPORT_DIR%\Conversas_Delivery.xlsx" goto :planilhas_ausentes
if not exist "%IMPORT_DIR%\Contatos_Delivery.xlsx" goto :planilhas_ausentes

set "ETAPA=1/5 - Weni: carga completa 100%%"
echo [ETAPA %ETAPA%]
call "%NEXOFLOW_HOME%\comandos\atualizar_weni_carga_completa.bat" --fluxo-completo
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :interrompido

set "ETAPA=2/5 - Planilhas: Weni"
echo [ETAPA %ETAPA%]
call "%NEXOFLOW_HOME%\comandos\atualizar_weni_planilhas.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :interrompido
set "ETAPA=2/5 - Planilhas: Analytics e Google Sheets"
echo [ETAPA %ETAPA%]
call "%NEXOFLOW_HOME%\comandos\executar_analytics_planilhas.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :interrompido

set "ETAPA=3/5 - Analytics: carga completa 100%%"
echo [ETAPA %ETAPA%]
call "%NEXOFLOW_HOME%\comandos\executar_carga_completa.bat" --fluxo-completo
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :interrompido

set "ETAPA=4/5 - Recompra: revisão e aplicação"
echo [ETAPA %ETAPA%]
call "%NEXOFLOW_HOME%\comandos\atualizar_recompra.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :interrompido

set "ETAPA=5/5 - Analytics: sincronização incremental"
echo [ETAPA %ETAPA%]
set "FORCE_FULL_SYNC="
set "FULL_SYNC_QUARTER="
call "%NEXOFLOW_HOME%\comandos\executar_manual.bat"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :interrompido
echo.
echo [OK] As cinco etapas foram concluídas.
echo No Data Studio, atualize os dados e os campos das fontes alteradas.
echo Essa atualização no Data Studio precisa ser feita na interface do painel.
goto :fim

:ambiente_ausente
echo [ERRO] Ambiente virtual ausente. Execute instalar.bat primeiro.
goto :interrompido
:componente_ausente
echo [ERRO] Componente ausente. Reinstale o Setup atualizado do NexoFlow.
goto :interrompido
:planilhas_ausentes
echo [ERRO] Coloque Conversas_Delivery.xlsx e Contatos_Delivery.xlsx em %IMPORT_DIR%.
goto :interrompido
:interrompido
echo.
echo [INTERROMPIDO] %ETAPA% - código de saída: %RC%.
echo As próximas etapas não foram executadas.
echo Confira os logs e o snapshot revisado antes de retomar uma aplicação parcial.
:fim
echo.
pause
exit /b %RC%
