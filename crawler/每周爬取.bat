@echo off
setlocal
REM ============================================================
REM  GitHub Trending weekly crawler + Dify KB sync
REM  Run every Monday by Windows Task Scheduler; double-click
REM  to run manually. Log appended to Desktop\agent\run.log
REM  Step 1: launcher finds the Chinese-named crawler (ASCII-safe)
REM  Step 2: dify_kb_sync.py reconciles knowledge base docs
REM ============================================================
set "PYTHONIOENCODING=utf-8"
set "LOG=%USERPROFILE%\Desktop\agent\run.log"

echo ============ %date% %time% START ============ >> "%LOG%"

python "%~dp0weekly_crawler_launcher.py" >> "%LOG%" 2>&1
echo ============ CRAWLER done exit=%errorlevel% ============ >> "%LOG%"

python "%~dp0dify_kb_sync.py" >> "%LOG%" 2>&1
echo ============ KB-SYNC done exit=%errorlevel% ============ >> "%LOG%"
