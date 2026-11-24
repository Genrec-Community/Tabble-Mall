@echo off
rem Normally you stop MallT by closing its window. Use this if MallT was closed abruptly
rem and will not start again:  stop.bat
rem To delete all local data and start fresh with the demo mall:  stop.bat reset
cd /d "%~dp0"
set UV_CACHE_DIR=%~dp0local\tools\uv-cache
set UV_PYTHON_INSTALL_DIR=%~dp0local\tools\python
set UV=%~dp0local\tools\uv\uv.exe
if not exist "%UV%" (echo Nothing to stop: MallT has not been started on this computer yet. & pause & exit /b 0)
if /i "%~1"=="reset" (
  "%UV%" run --no-dev --project backend python local\run_local.py --reset
) else (
  "%UV%" run --no-dev --project backend python local\run_local.py --stop
)
pause
