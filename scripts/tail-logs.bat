@echo off
chcp 65001 >nul
title LLM Wiki - Tail Logs

REM 默认每个文件显示最后 50 行
set LINES=50

echo.
echo ============================================
echo  LLM Wiki Logs (last %LINES% lines)
echo ============================================
echo.

echo ── api.out.log ──
powershell -NoProfile -Command "Get-Content '%~dp0..\logs\api.out.log' -Tail %LINES% -Encoding UTF8 -ErrorAction SilentlyContinue"
echo.
echo ── api.err.log ──
powershell -NoProfile -Command "Get-Content '%~dp0..\logs\api.err.log' -Tail %LINES% -Encoding UTF8 -ErrorAction SilentlyContinue"
echo.
echo ── agent.out.log ──
powershell -NoProfile -Command "Get-Content '%~dp0..\logs\agent.out.log' -Tail %LINES% -Encoding UTF8 -ErrorAction SilentlyContinue"
echo.
echo ── agent.err.log ──
powershell -NoProfile -Command "Get-Content '%~dp0..\logs\agent.err.log' -Tail %LINES% -Encoding UTF8 -ErrorAction SilentlyContinue"
echo.

pause
exit /b 0
