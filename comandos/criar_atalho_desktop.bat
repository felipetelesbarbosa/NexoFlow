@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
cd /d "%NEXOFLOW_HOME%\"

if not exist "%NEXOFLOW_HOME%\NexoFlow Analytics.exe" (
    echo [ERRO] NexoFlow Analytics.exe não foi encontrado.
    pause
    exit /b 1
)
if not exist "%NEXOFLOW_HOME%\NexoFlow Weni.exe" (
    echo [ERRO] NexoFlow Weni.exe não foi encontrado.
    pause
    exit /b 1
)
if not exist "%NEXOFLOW_HOME%\NexoFlow Terminal.exe" (
    echo [ERRO] NexoFlow Terminal.exe não foi encontrado.
    pause
    exit /b 1
)

rem -Command não executa arquivo .ps1 e portanto não precisa de ExecutionPolicy Bypass.
powershell.exe -NoLogo -NoProfile -Command ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$shortcut=Join-Path $desktop 'NexoFlow Analytics.lnk';" ^
  "$s=$ws.CreateShortcut($shortcut);" ^
  "$s.TargetPath='%NEXOFLOW_HOME%\NexoFlow Analytics.exe';" ^
  "$s.WorkingDirectory='%NEXOFLOW_HOME%\';" ^
  "$s.Description='Valida o ambiente e executa uma sincronizacao incremental do NexoFlow';" ^
  "$s.IconLocation='%NEXOFLOW_HOME%\assets\NexoFlow.ico,0';" ^
  "$s.Save();" ^
  "$updateShortcut=Join-Path $desktop 'NexoFlow Weni.lnk';" ^
  "$u=$ws.CreateShortcut($updateShortcut);" ^
  "$u.TargetPath='%NEXOFLOW_HOME%\NexoFlow Weni.exe';" ^
  "$u.WorkingDirectory='%NEXOFLOW_HOME%\';" ^
  "$u.Description='Audita e atualiza contatos e campos da Weni';" ^
  "$u.IconLocation='%NEXOFLOW_HOME%\assets\NexoFlow_Weni.ico,0';" ^
  "$u.Save();" ^
  "$terminalShortcut=Join-Path $desktop 'NexoFlow Terminal.lnk';" ^
  "$c=$ws.CreateShortcut($terminalShortcut);" ^
  "$c.TargetPath='%NEXOFLOW_HOME%\NexoFlow Terminal.exe';" ^
  "$c.WorkingDirectory='%NEXOFLOW_HOME%\';" ^
  "$c.Description='Terminal NexoFlow com ambiente e proxy preparados para a sessao';" ^
  "$c.IconLocation='%NEXOFLOW_HOME%\assets\NexoFlow_Terminal.ico,0';" ^
  "$c.Save();" ^
  "Write-Host ('[OK] Atalhos criados: ' + $shortcut + ' | ' + $updateShortcut + ' | ' + $terminalShortcut)"

if errorlevel 1 (
    echo [ERRO] Não foi possível criar os atalhos.
    pause
    exit /b 1
)
echo.
pause
exit /b 0
