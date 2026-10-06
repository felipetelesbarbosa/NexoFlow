@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0NexoFlow Analytics.exe" (
    echo [ERRO] NexoFlow Analytics.exe nao foi encontrado.
    pause
    exit /b 1
)
if not exist "%~dp0NexoFlow Weni.exe" (
    echo [ERRO] NexoFlow Weni.exe nao foi encontrado.
    pause
    exit /b 1
)
if not exist "%~dp0NexoFlow Terminal.exe" (
    echo [ERRO] NexoFlow Terminal.exe nao foi encontrado.
    pause
    exit /b 1
)

rem -Command nao executa arquivo .ps1 e portanto nao precisa de ExecutionPolicy Bypass.
powershell.exe -NoLogo -NoProfile -Command ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$shortcut=Join-Path $desktop 'NexoFlow Analytics.lnk';" ^
  "$s=$ws.CreateShortcut($shortcut);" ^
  "$s.TargetPath='%~dp0NexoFlow Analytics.exe';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.Description='Valida o ambiente e executa uma sincronizacao incremental do NexoFlow';" ^
  "$s.IconLocation='%~dp0assets\NexoFlow.ico,0';" ^
  "$s.Save();" ^
  "$updateShortcut=Join-Path $desktop 'NexoFlow Weni.lnk';" ^
  "$u=$ws.CreateShortcut($updateShortcut);" ^
  "$u.TargetPath='%~dp0NexoFlow Weni.exe';" ^
  "$u.WorkingDirectory='%~dp0';" ^
  "$u.Description='Audita e atualiza contatos e campos da Weni';" ^
  "$u.IconLocation='%~dp0assets\NexoFlow_Weni.ico,0';" ^
  "$u.Save();" ^
  "$terminalShortcut=Join-Path $desktop 'NexoFlow Terminal.lnk';" ^
  "$c=$ws.CreateShortcut($terminalShortcut);" ^
  "$c.TargetPath='%~dp0NexoFlow Terminal.exe';" ^
  "$c.WorkingDirectory='%~dp0';" ^
  "$c.Description='Terminal NexoFlow com ambiente e proxy preparados para a sessao';" ^
  "$c.IconLocation='%~dp0assets\NexoFlow_Terminal.ico,0';" ^
  "$c.Save();" ^
  "Write-Host ('[OK] Atalhos criados: ' + $shortcut + ' | ' + $updateShortcut + ' | ' + $terminalShortcut)"

if errorlevel 1 (
    echo [ERRO] Nao foi possivel criar os atalhos.
    pause
    exit /b 1
)
echo.
pause
exit /b 0
