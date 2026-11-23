@echo off
rem Shows the latest customer sign-in codes. Locally no SMS is sent: the API prints the code instead.
cd /d "%~dp0"
docker compose -p mallt -f docker-compose.yml -f local\docker-compose.local.yml logs --no-log-prefix api 2>nul | findstr /c:"DEV OTP"
echo.
echo The last line is the newest code. Run this again after asking for a new code.
pause
