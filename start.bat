@echo off
setlocal
rem ---------------------------------------------------------------------------------------------
rem  MallT: double-click to run the whole app on this computer. No Docker, nothing to install.
rem  The first run downloads Python, Node.js and PostgreSQL into local\tools (about 150 MB, a few
rem  minutes). Later starts take about half a minute. Keep the window open while you use MallT;
rem  close it (or press Ctrl+C) to stop.
rem ---------------------------------------------------------------------------------------------
cd /d "%~dp0"
title MallT
set TOOLS=%~dp0local\tools
set UV_VERSION=0.11.32
set NODE_VERSION=22.23.5
if not exist "%TOOLS%" mkdir "%TOOLS%"

if not exist "%TOOLS%\uv\uv.exe" (
  echo Downloading uv ^(runs Python for MallT^)...
  call :fetch "https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-x86_64-pc-windows-msvc.zip" "%TOOLS%\uv" || goto :failed
)
if not exist "%TOOLS%\node-v%NODE_VERSION%-win-x64\node.exe" (
  echo Downloading Node.js ^(runs the website^)...
  call :fetch "https://nodejs.org/dist/v%NODE_VERSION%/node-v%NODE_VERSION%-win-x64.zip" "%TOOLS%" || goto :failed
)

set UV=%TOOLS%\uv\uv.exe
set MALLT_NODE=%TOOLS%\node-v%NODE_VERSION%-win-x64\node.exe
set UV_CACHE_DIR=%TOOLS%\uv-cache
set UV_PYTHON_INSTALL_DIR=%TOOLS%\python

echo Preparing Python and the API (first run downloads about 100 MB)...
"%UV%" run --no-dev --project backend python local\run_local.py
if errorlevel 1 goto :failed
exit /b 0

:fetch
rem %1 = URL, %2 = folder to unpack into
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $z=Join-Path $env:TEMP ('mallt-'+[guid]::NewGuid()+'.zip'); Invoke-WebRequest -UseBasicParsing -Uri '%~1' -OutFile $z; Expand-Archive -Force -Path $z -DestinationPath '%~2'; Remove-Item $z"
exit /b %errorlevel%

:failed
echo.
echo MallT could not start. The message above says why; the logs are in local\logs.
pause
exit /b 1
