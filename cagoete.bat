@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_FULL_PATH=%~f0"
for %%I in ("%SCRIPT_FULL_PATH%") do set "APP_ROOT=%%~dpI"
if "%APP_ROOT:~-1%"=="\" set "APP_ROOT=%APP_ROOT:~0,-1%"

set "APP_HOST=127.0.0.1"
set "APP_PORT=3600"
set "APP_URL=http://%APP_HOST%:%APP_PORT%/health"
set "DEFAULT_PYTHON_EXE=C:\Program Files\Python312\python.exe"
set "DEFAULT_PYTHONW_EXE=C:\Program Files\Python312\pythonw.exe"
set "PYTHON_EXE="
set "PYTHONW_EXE="
set "PID_FILE=%APP_ROOT%\Cagoete.pid"
set "RUNTIME_LOG=%APP_ROOT%\Cagoete.runtime.log"
set "RUNTIME_ERR_LOG=%APP_ROOT%\Cagoete.runtime.err.log"
set "LOG_FILE=%APP_ROOT%\Cagoete.log"
set "START_WAIT_SECONDS=45"
set "STOP_WAIT_SECONDS=20"

call :resolve_python_exe || exit /b 1

if /I "%~1"=="iniciar" goto cli_start
if /I "%~1"=="start" goto cli_start
if /I "%~1"=="encerrar" goto cli_stop
if /I "%~1"=="stop" goto cli_stop
if /I "%~1"=="reiniciar" goto cli_restart
if /I "%~1"=="restart" goto cli_restart
if /I "%~1"=="status" goto cli_status

goto menu

:menu
cls
echo ============================================================
echo cagoete - Controle da Aplicacao
echo ============================================================
echo.
echo Python: %PYTHON_EXE%
if not "%PYTHONW_EXE%"=="" echo PythonW: %PYTHONW_EXE%
echo Porta : %APP_PORT%
echo URL   : %APP_URL%
echo.
call :show_status
echo.
echo [1] Ver status
echo [2] Iniciar aplicacao
echo [3] Encerrar aplicacao
echo [4] Reiniciar aplicacao
echo [0] Sair
echo.
set "choice="
set /p "choice=Selecione uma opcao: "

if "%choice%"=="1" goto option_status
if "%choice%"=="2" goto option_start
if "%choice%"=="3" goto option_stop
if "%choice%"=="4" goto option_restart
if "%choice%"=="0" goto option_exit

echo.
echo Opcao invalida.
pause
goto menu

:option_status
call :show_status
echo.
pause
goto menu

:option_start
call :start_application || (
  echo.
  echo Falha ao iniciar a aplicacao.
  echo Consulte "%RUNTIME_ERR_LOG%" e "%LOG_FILE%".
  pause
  goto menu
)
exit /b 0

:option_stop
call :stop_application || (
  echo.
  echo Falha ao encerrar completamente a aplicacao.
  echo Consulte "%LOG_FILE%".
  pause
  goto menu
)
exit /b 0

:option_restart
call :restart_application || (
  echo.
  echo Falha ao reiniciar a aplicacao.
  echo Consulte "%LOG_FILE%".
  pause
  goto menu
)
exit /b 0

:option_exit
echo Menu fechado.
exit /b 0

:cli_status
call :show_status
exit /b 0

:cli_start
call :start_application || exit /b 1
exit /b 0

:cli_stop
call :stop_application || exit /b 1
exit /b 0

:cli_restart
call :restart_application || exit /b 1
exit /b 0

:show_status
call :cleanup_stale_pid
set "PID="
set "PORT_PID="
if exist "%PID_FILE%" set /p PID=<"%PID_FILE%"
call :get_pid_from_port %APP_PORT% PORT_PID
if not "%PORT_PID%"=="" (
  if "%PID%"=="" (
    echo Status: Porta %APP_PORT% em uso por processo nao monitorado ^(PID %PORT_PID%^)
    exit /b 0
  )
  if "%PORT_PID%"=="%PID%" (
    echo Status: Em execucao na porta %APP_PORT% ^(PID monitorado: %PID%^)
    exit /b 0
  )
  echo Status: Porta %APP_PORT% em uso por PID %PORT_PID%, diferente do PID monitorado %PID%.
  exit /b 0
)
if not "%PID%"=="" (
  call :is_pid_running %PID%
  if not errorlevel 1 (
    echo Status: PID monitorado em execucao, mas sem escutar a porta %APP_PORT% ^(PID: %PID%^)
    exit /b 0
  )
)
echo Status: Parado
exit /b 0

:start_application
call :log Inicio solicitado.
call :cleanup_stale_pid
call :ensure_python_dependencies || exit /b 1

set "PID="
set "PORT_PID="
if exist "%PID_FILE%" set /p PID=<"%PID_FILE%"
call :get_pid_from_port %APP_PORT% PORT_PID

if not "%PORT_PID%"=="" if not "%PID%"=="" if "%PORT_PID%"=="%PID%" (
  echo Aplicacao ja esta em execucao na porta %APP_PORT% ^(PID %PID%^).
  call :log Aplicacao ja estava em execucao com PID %PID%.
  exit /b 0
)
if not "%PORT_PID%"=="" if not "%PID%"=="" if not "%PORT_PID%"=="%PID%" (
  echo Porta %APP_PORT% ocupada por PID %PORT_PID%, diferente do PID monitorado %PID%.
  echo Libere a porta antes de iniciar a aplicacao.
  call :log Porta %APP_PORT% ocupada por PID %PORT_PID%, diferente do PID monitorado %PID%.
  exit /b 1
)
if not "%PORT_PID%"=="" goto start_port_conflict

if not "%PID%"=="" (
  call :is_pid_running %PID%
  if not errorlevel 1 (
    echo Encerrando PID orfao monitorado %PID% antes de iniciar...
    call :log Encerrando PID orfao monitorado %PID% antes da inicializacao.
    call :terminate_pid_tree %PID%
    call :wait_for_pid_down %PID% >nul 2>&1 || (
      echo Falha ao encerrar o PID orfao monitorado %PID%.
      call :log Falha ao encerrar o PID orfao monitorado %PID%.
      exit /b 1
    )
  ) else (
    if exist "%PID_FILE%" del /f /q "%PID_FILE%" >nul 2>&1
  )
)

echo Iniciando cagoete...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$process = Start-Process -FilePath '%PYTHON_EXE%' -WorkingDirectory '%APP_ROOT%' -ArgumentList '-m','uvicorn','app.main:app','--host','%APP_HOST%','--port','%APP_PORT%' -WindowStyle Hidden -RedirectStandardOutput '%RUNTIME_LOG%' -RedirectStandardError '%RUNTIME_ERR_LOG%' -PassThru; $process.Id | Set-Content '%PID_FILE%'" >nul 2>&1
if errorlevel 1 (
  echo Falha ao iniciar a aplicacao em %APP_URL%.
  echo Verifique "%RUNTIME_ERR_LOG%".
  call :log Falha ao iniciar aplicacao.
  exit /b 1
)

call :wait_for_http || (
  echo Falha ao iniciar a aplicacao em %APP_URL%.
  echo Verifique "%RUNTIME_ERR_LOG%".
  call :log Falha ao iniciar aplicacao.
  if exist "%PID_FILE%" (
    for /f "usebackq delims=" %%P in ("%PID_FILE%") do call :terminate_pid_tree %%P >nul 2>&1
    del /f /q "%PID_FILE%" >nul 2>&1
  )
  exit /b 1
)

set "APP_PID="
if exist "%PID_FILE%" set /p APP_PID=<"%PID_FILE%"
if "%APP_PID%"=="" call :get_pid_from_port %APP_PORT% APP_PID
if "%APP_PID%"=="" (
  timeout /t 1 /nobreak >nul
  call :get_pid_from_port %APP_PORT% APP_PID
)
if "%APP_PID%"=="" (
  echo Aplicacao ativa, mas o PID nao foi identificado.
  call :log Aplicacao ativa sem PID identificado.
  exit /b 1
)

>"%PID_FILE%" echo %APP_PID%
echo Aplicacao iniciada com sucesso na porta %APP_PORT% ^(PID %APP_PID%^).
call :log Aplicacao iniciada com PID %APP_PID%.
exit /b 0

:start_port_conflict
call :get_process_name %PORT_PID% PORT_PROCESS_NAME
if "%PORT_PROCESS_NAME%"=="" set "PORT_PROCESS_NAME=desconhecido"
echo Porta %APP_PORT% ja esta em uso por %PORT_PROCESS_NAME% ^(PID %PORT_PID%^).
echo Libere a porta antes de iniciar a aplicacao.
call :log Porta %APP_PORT% ocupada por %PORT_PROCESS_NAME% ^(PID %PORT_PID%^).
exit /b 1

:restart_application
call :log Reinicio solicitado.
call :stop_application >nul 2>&1
call :start_application || exit /b 1
exit /b 0

:stop_application
call :log Encerramento solicitado.
call :cleanup_stale_pid
set "PID="
set "PORT_PID="
if exist "%PID_FILE%" set /p PID=<"%PID_FILE%"
call :get_pid_from_port %APP_PORT% PORT_PID

if "%PID%"=="" if "%PORT_PID%"=="" (
  echo Aplicacao ja esta parada.
  call :log Aplicacao ja estava parada.
  exit /b 0
)

if "%PID%"=="" if not "%PORT_PID%"=="" goto stop_unmonitored_port

if not "%PID%"=="" call :terminate_pid_tree %PID%
set "PORT_PID="
call :get_pid_from_port %APP_PORT% PORT_PID
if not "%PORT_PID%"=="" if not "%PORT_PID%"=="%PID%" (
  echo Porta %APP_PORT% permaneceu associada ao PID %PORT_PID%, diferente do PID monitorado %PID%.
  echo O script nao encerrara automaticamente um processo nao monitorado.
  call :log Porta %APP_PORT% associada a PID %PORT_PID% diferente do PID monitorado %PID% durante encerramento.
  exit /b 1
)
if exist "%PID_FILE%" del /f /q "%PID_FILE%" >nul 2>&1

call :wait_for_port_down || (
  echo Aplicacao ainda responde na porta %APP_PORT%.
  call :log Aplicacao ainda ativa na porta %APP_PORT%.
  exit /b 1
)

echo Aplicacao encerrada com sucesso.
call :log Aplicacao encerrada com sucesso.
exit /b 0

:stop_unmonitored_port
call :get_process_name %PORT_PID% PORT_PROCESS_NAME
if "%PORT_PROCESS_NAME%"=="" set "PORT_PROCESS_NAME=desconhecido"
echo Porta %APP_PORT% ocupada por processo nao monitorado ^(%PORT_PROCESS_NAME% / PID %PORT_PID%^) e nao sera encerrada automaticamente.
call :log Porta %APP_PORT% ocupada por processo nao monitorado ^(%PORT_PROCESS_NAME% / PID %PORT_PID%^) durante encerramento.
exit /b 1

:stop_existing
set "PID="
set "PORT_PID="
if exist "%PID_FILE%" set /p PID=<"%PID_FILE%"
call :get_pid_from_port %APP_PORT% PORT_PID
if not "%PID%"=="" call :terminate_pid_tree %PID%
if exist "%PID_FILE%" del /f /q "%PID_FILE%" >nul 2>&1
exit /b 0

:cleanup_stale_pid
set "PID="
set "PORT_PID="
if not exist "%PID_FILE%" exit /b 0
set /p PID=<"%PID_FILE%"
if "%PID%"=="" (
  del /f /q "%PID_FILE%" >nul 2>&1
  exit /b 0
)
call :is_pid_running %PID%
if errorlevel 1 (
  del /f /q "%PID_FILE%" >nul 2>&1
  exit /b 0
)
call :get_pid_from_port %APP_PORT% PORT_PID
if not "%PORT_PID%"=="" (
  if "%PORT_PID%"=="%PID%" (
    >"%PID_FILE%" echo %PORT_PID%
  )
  exit /b 0
)
exit /b 0

:ensure_python_dependencies
if not exist "%APP_ROOT%\requirements.txt" (
  echo Arquivo requirements.txt nao encontrado em "%APP_ROOT%".
  call :log Arquivo requirements.txt nao encontrado.
  exit /b 1
)
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0)" >nul 2>&1 || (
  echo Python encontrado, mas nao executa corretamente.
  echo Se necessario, reinstale o Python 3.12 no ambiente.
  call :log Python encontrado, mas nao executa corretamente.
  exit /b 1
)
"%PYTHON_EXE%" -m pip --version >nul 2>&1 || "%PYTHON_EXE%" -m ensurepip --upgrade >nul 2>&1
"%PYTHON_EXE%" -m pip --version >nul 2>&1 || (
  echo Pip nao esta disponivel para o Python configurado.
  echo Se necessario, instale ou repare o Python 3.12 no ambiente.
  call :log Pip nao esta disponivel para o Python configurado.
  exit /b 1
)
"%PYTHON_EXE%" -c "import fastapi,uvicorn,sqlalchemy,jinja2,itsdangerous,structlog,tenacity,httpx,passlib,bcrypt" >nul 2>&1 && exit /b 0
echo Instalando dependencias Python...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --no-input -r "%APP_ROOT%\requirements.txt" || (
  echo Falha ao instalar dependencias Python.
  echo Se o Python nao estiver instalado corretamente, instale o Python 3.12 no ambiente.
  call :log Falha ao instalar dependencias Python.
  exit /b 1
)
"%PYTHON_EXE%" -c "import fastapi,uvicorn,sqlalchemy,jinja2,itsdangerous,structlog,tenacity,httpx,passlib,bcrypt" >nul 2>&1 || (
  echo Dependencias Python continuam indisponiveis apos a instalacao.
  echo Se precisar, instale o Python 3.12 no ambiente.
  call :log Dependencias Python continuam indisponiveis.
  exit /b 1
)
exit /b 0

:resolve_python_exe
if exist "%DEFAULT_PYTHON_EXE%" (
  set "PYTHON_EXE=%DEFAULT_PYTHON_EXE%"
  if exist "%DEFAULT_PYTHONW_EXE%" set "PYTHONW_EXE=%DEFAULT_PYTHONW_EXE%"
  exit /b 0
)
for /f "delims=" %%I in ('py -c "import sys; print(sys.executable)" 2^>nul') do (
  if exist "%%~fI" (
    set "PYTHON_EXE=%%~fI"
    if exist "%%~dpIpythonw.exe" set "PYTHONW_EXE=%%~dpIpythonw.exe"
    exit /b 0
  )
)
for /f "delims=" %%I in ('where.exe python.exe 2^>nul') do (
  if exist "%%~fI" (
    set "PYTHON_EXE=%%~fI"
    if exist "%%~dpIpythonw.exe" set "PYTHONW_EXE=%%~dpIpythonw.exe"
    exit /b 0
  )
)
echo Python nao encontrado.
echo Instale o Python 3.12 para continuar.
exit /b 1

:wait_for_http
set /a WAIT_RETRIES=%START_WAIT_SECONDS%
:wait_for_http_loop
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $response = Invoke-WebRequest '%APP_URL%' -UseBasicParsing; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1 && exit /b 0
if %WAIT_RETRIES% LEQ 0 exit /b 1
timeout /t 1 /nobreak >nul
set /a WAIT_RETRIES-=1
goto wait_for_http_loop

:wait_for_port_down
set /a WAIT_RETRIES=%STOP_WAIT_SECONDS%
:wait_for_port_down_loop
call :is_port_listening %APP_PORT%
if errorlevel 1 exit /b 0
if %WAIT_RETRIES% LEQ 0 exit /b 1
timeout /t 1 /nobreak >nul
set /a WAIT_RETRIES-=1
goto wait_for_port_down_loop

:is_port_listening
for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr /R /C:":%~1 .*LISTENING"') do exit /b 0
exit /b 1

:get_pid_from_port
set "%~2="
for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr /R /C:":%~1 .*LISTENING"') do (
  set "%~2=%%P"
  goto :eof
)
exit /b 0

:is_pid_running
if "%~1"=="" exit /b 1
for /f "tokens=1 delims=," %%A in ('tasklist /FI "PID eq %~1" /FO CSV /NH 2^>nul') do (
  if /I not "%%~A"=="INFO: No tasks are running which match the specified criteria." exit /b 0
)
exit /b 1

:get_process_name
set "%~2="
if "%~1"=="" exit /b 0
for /f "tokens=1 delims=," %%A in ('tasklist /FI "PID eq %~1" /FO CSV /NH 2^>nul') do (
  if /I not "%%~A"=="INFO: No tasks are running which match the specified criteria." (
    set "%~2=%%~A"
    goto :eof
  )
)
exit /b 0

:wait_for_pid_down
if "%~1"=="" exit /b 0
set /a WAIT_RETRIES=%STOP_WAIT_SECONDS%
:wait_for_pid_down_loop
call :is_pid_running %~1
if errorlevel 1 exit /b 0
if %WAIT_RETRIES% LEQ 0 exit /b 1
timeout /t 1 /nobreak >nul
set /a WAIT_RETRIES-=1
goto wait_for_pid_down_loop

:terminate_pid_tree
if "%~1"=="" exit /b 0
taskkill /PID %~1 /T >nul 2>&1
timeout /t 2 /nobreak >nul
taskkill /PID %~1 /T /F >nul 2>&1
exit /b 0

:log
if not exist "%LOG_FILE%" type nul > "%LOG_FILE%" >nul 2>&1
>>"%LOG_FILE%" echo [%date% %time:~0,8%] %*
exit /b 0
