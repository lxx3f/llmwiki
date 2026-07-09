@echo off
chcp 65001 >nul
title LLM Wiki - Restart Services

echo.
echo ============================================
echo  Restarting LLM Wiki Services
echo ============================================
echo.

nssm restart LlmWikiApi
nssm restart LlmWikiAgent

echo.
echo [OK] 已重启
echo.
pause
exit /b 0
