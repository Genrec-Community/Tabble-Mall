@echo off
rem Follows the logs of every MallT service. Press Ctrl+C to stop following.
cd /d "%~dp0"
docker compose -p mallt -f docker-compose.yml -f local\docker-compose.local.yml logs -f --tail 100
