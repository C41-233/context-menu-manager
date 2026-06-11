@echo off

echo ========================================
echo   右键菜单管理器 — 卸载
echo ========================================
echo.

:: 1. 检测管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提权] 需要管理员权限，正在请求提升...
    powershell -Command "Start-Process '%~f0' -Verb RunAs -Wait"
    exit /b %errorlevel%
)
echo [OK] 管理员权限已确认

:: 2. 删除注册表项
reg delete "HKCR\*\shell\MenuManager" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 已移除: 文件右键菜单
) else (
    echo [信息] 文件右键菜单未注册或已移除
)

reg delete "HKCR\Directory\shell\MenuManager" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 已移除: 目录右键菜单
) else (
    echo [信息] 目录右键菜单未注册或已移除
)

reg delete "HKCR\Directory\Background\shell\MenuManager" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 已移除: 目录背景右键菜单
) else (
    echo [信息] 目录背景右键菜单未注册或已移除
)

echo.
echo ========================================
echo   卸载完成！
echo   backups 文件夹保留在工具目录中，
echo   如需恢复已删除的菜单项，请双击其中
echo   的 .reg 文件。
echo ========================================
pause
