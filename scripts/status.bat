@echo off
chcp 65001 >nul
title LLM Wiki - Service Status

echo.
echo ============================================
echo  LLM Wiki Service Status
echo ============================================
echo.

echo [FastAPI - LlmWikiApi]
sc query LlmWikiApi | findstr "STATE"
nssm status LlmWikiApi
echo.

echo [Agent  - LlmWikiAgent]
sc query LlmWikiAgent | findstr "STATE"
nssm status LlmWikiAgent
echo.

echo ─── 健康检查 ───
curl -s -o nul -w "API http://localhost:8021/        : %%{http_code}^n" http://localhost:8021/
curl -s -o nul -w "API http://localhost:8021/v1/agent/status : %%{http_code}^n" http://localhost:8021/v1/agent/status
echo.

pause
exit /b 0
