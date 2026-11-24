@echo off
rem Shows customer sign-in codes. Locally no SMS is sent: the API writes the code to its log.
cd /d "%~dp0"
if not exist local\logs\api.log (echo MallT has not been started yet. & pause & exit /b 0)
findstr /c:"DEV OTP" local\logs\api.log
echo.
echo The last line is the newest code. Run this again after asking for a new code.
pause
