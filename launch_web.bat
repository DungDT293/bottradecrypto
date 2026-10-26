@echo off
setlocal
cd /d "%~dp0"
title Telegram Binance Signal Executor (Web Dashboard)

echo ===================================================================
echo   KHOI DONG SIGNAL EXECUTOR & GEMINI QUANT AI (TRINH DUYET WEB)
echo ===================================================================
echo 1. Dang dong bo cau hinh Live...
echo 2. Dang bat server va tu dong mo trinh duyet...

python -m backend.launcher --config config.yaml --open-browser

pause

