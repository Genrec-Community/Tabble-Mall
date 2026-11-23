@echo off
setlocal
rem ---------------------------------------------------------------------------------------------
rem  MallT: run the whole app on this computer.
rem  Needs Docker Desktop (https://www.docker.com/products/docker-desktop/) installed and running.
rem  First start builds everything and takes 5-15 minutes; later starts take under a minute.
rem ---------------------------------------------------------------------------------------------
cd /d "%~dp0"
set COMPOSE=docker compose -p mallt -f docker-compose.yml -f local\docker-compose.local.yml

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker is not installed. Install Docker Desktop, start it, then run start.bat again:
  echo   https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is installed but not running. Start Docker Desktop, wait until it says
  echo "Engine running", then run start.bat again.
  pause
  exit /b 1
)

echo.
echo [1/3] Building and starting MallT (database, API, website, nginx)...
%COMPOSE% up -d --build --wait
if errorlevel 1 (
  echo.
  echo Something failed to start. The last API log lines:
  %COMPOSE% logs --tail 40 api
  pause
  exit /b 1
)

echo.
echo [2/3] Adding the demo mall, stores and menus (first run only)...
%COMPOSE% exec -T api python local/seed_demo.py > "%TEMP%\mallt-seed.txt"
if errorlevel 1 (
  type "%TEMP%\mallt-seed.txt"
  echo Seeding the demo failed. See the message above.
  pause
  exit /b 1
)
findstr /c:"MallT demo logins" "%TEMP%\mallt-seed.txt" >nul && copy /y "%TEMP%\mallt-seed.txt" "demo-logins.txt" >nul

echo.
echo [3/3] Ready.
echo.
if exist demo-logins.txt (type demo-logins.txt) else (type "%TEMP%\mallt-seed.txt")
echo.
echo   Customer page : http://localhost:8080/m/demo-mall
echo   Staff sign-in : http://localhost:8080/login
echo   Login codes   : run show-otp.bat
echo   Stop          : run stop.bat
echo.
start "" "http://localhost:8080/m/demo-mall"
pause
