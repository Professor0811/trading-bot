@echo off
echo Starting Autonomous Crypto Trading Bot & Dashboard...
start cmd /k python multi_token_bot.py
start cmd /k python dashboard_server.py
pause