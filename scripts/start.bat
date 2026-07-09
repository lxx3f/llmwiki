@echo off
chcp 65001 >nul
title LLM Wiki - Start Services

echo.
echo ============================================
echo  Starting LLM Wiki Services
echo ============================================
echo.

nssm start LlmWikiApi
if errorlevel 1 goto :err

nssm start LlmWikiAgent
if errorlevel 1 goto :err

echo.
echo [OK] 两个服务已启动
echo.
echo Web UI: http://localhost:8021
echo.
pause
exit /b 0

:err
echo.
echo [FAIL] 启动失败。请先运行 scripts\install_services.ps1 (需要管理员权限)
echo.
pause
exit /b 1
