@echo off
rem Stops MallT. Your data is kept; start.bat brings it back.
rem To wipe everything and start fresh, run:  stop.bat reset
cd /d "%~dp0"
set COMPOSE=docker compose -p mallt -f docker-compose.yml -f local\docker-compose.local.yml
if /i "%~1"=="reset" (
  %COMPOSE% down -v
  if exist demo-logins.txt del demo-logins.txt
  echo MallT stopped and all its data deleted.
) else (
  %COMPOSE% down
  echo MallT stopped. Data kept.
)
pause
