@echo off
chcp 65001 >nul
title LLM Wiki - Stop Services

echo.
echo ============================================
echo  Stopping LLM Wiki Services
echo ============================================
echo.

nssm stop LlmWikiAgent
nssm stop LlmWikiApi

echo.
echo [OK] 两个服务已停止
echo.
pause
exit /b 0
