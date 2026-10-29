@echo off
chcp 65001 >nul
rem Preparar o ambiente Python e instalar as dependências.
setlocal EnableExtensions
for %%I in ("%~dp0") do set "NEXOFLOW_HOME=%%~fI"
set "PYTHONPATH=%NEXOFLOW_HOME%;%NEXOFLOW_HOME%\app;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
cd /d "%NEXOFLOW_HOME%\"

echo ==============================================
echo NexoFlow - Preparação do ambiente
echo ==============================================
echo.

set "PYTHON_EXE="
set "PYTHON_PREFIX="

rem O instalador PowerShell já resolveu o caminho real do Python. Use-o primeiro.
if defined NEXOFLOW_PYTHON_EXE (
    if exist "%NEXOFLOW_PYTHON_EXE%" set "PYTHON_EXE=%NEXOFLOW_PYTHON_EXE%"
)

rem Python Install Manager (Python 3.14+): runtime real em %%LOCALAPPDATA%%\Python\pythoncore-*-64.
rem Também procura instalações por usuário em todos os perfis, útil quando o BAT é elevado.
if not defined PYTHON_EXE (
    for /f "delims=" %%F in ('dir /b /s /a-d "C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe" 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%F"
    )
)
if not defined PYTHON_EXE (
    for /f "delims=" %%F in ('dir /b /s /a-d "C:\Users\*\AppData\Local\Python\pythoncore-*\python.exe" 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%F"
    )
)

if not defined PYTHON_EXE if defined LOCALAPPDATA (
    for /f "delims=" %%F in ('dir /b /s /a-d "%LOCALAPPDATA%\Python\pythoncore-*-64\python.exe" 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%F"
    )
)

if not defined PYTHON_EXE (
    where python.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python.exe"
)
if not defined PYTHON_EXE (
    where python3.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python3.exe"
)
if not defined PYTHON_EXE (
    where python3.14.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python3.14.exe"
)
if not defined PYTHON_EXE (
    where python3.13.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python3.13.exe"
)
if not defined PYTHON_EXE (
    where python3.12.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python3.12.exe"
)
if not defined PYTHON_EXE (
    where python3.11.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python3.11.exe"
)
if not defined PYTHON_EXE (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py.exe"
        set "PYTHON_PREFIX=-3"
    )
)

if not defined PYTHON_EXE (
    echo [ERRO] Python 3.11 ou superior, 64 bits, não foi encontrado.
    echo Instale um Python compatível ou execute o NexoFlow Setup.
    if not defined NEXOFLOW_INSTALLER pause
    exit /b 1
)

"%PYTHON_EXE%" %PYTHON_PREFIX% --version
if errorlevel 1 goto :erro
"%PYTHON_EXE%" %PYTHON_PREFIX% -c "import struct,sys; raise SystemExit(0 if sys.version_info >= (3,11) and struct.calcsize('P')*8 == 64 else 1)"
if errorlevel 1 (
    echo [ERRO] O Python encontrado não atende ao requisito: Python 3.11 ou superior, 64 bits.
    if not defined NEXOFLOW_INSTALLER pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    "%PYTHON_EXE%" %PYTHON_PREFIX% -m venv .venv
    if errorlevel 1 goto :erro
)

echo.
echo Verificando configuração do proxy...
if exist "secrets_config.py" (
    echo secrets_config.py encontrado.
) else if defined NEXOFLOW_SETUP_NETWORK_CONFIG (
    echo Usando a configuração de rede temporária do Setup.
) else (
    echo [AVISO] secrets_config.py não foi encontrado.
    echo O pip tentará usar conexão direta.
    echo Se estiver na rede da empresa e o proxy exigir autenticação,
    echo configure secrets_config.py e execute novamente.
    echo.
)

echo Atualizando pip...
".venv\Scripts\python.exe" app\run_pip.py install --upgrade pip
if errorlevel 1 goto :erro_proxy

echo.
echo Instalando dependências...
".venv\Scripts\python.exe" app\run_pip.py install -r requirements.txt
if errorlevel 1 goto :erro_proxy

echo.
echo ==============================================
echo Ambiente preparado com sucesso.
echo ==============================================
echo.
if not defined NEXOFLOW_INSTALLER (
    echo Próximos passos:
    echo 1. Verifique secrets_config.py
    echo 2. Verifique credentials\google_credentials.json
    echo 3. Execute comandos\check-up.bat
    echo 4. Execute comandos\testar_conexoes.bat
    echo.
    pause
)
exit /b 0

:erro_proxy
echo.
echo ==============================================
echo [ERRO] Falha ao instalar dependências.
echo ==============================================
echo.
echo Se apareceu "407 Proxy Authentication Required", verifique
echo secrets_config.py e as configurações PROXY_MODE/PROXY_USER/PROXY_PASSWORD.
echo.
if not defined NEXOFLOW_INSTALLER pause
exit /b 1

:erro
echo.
echo [ERRO] Falha durante a preparação do ambiente.
if not defined NEXOFLOW_INSTALLER pause
exit /b 1
