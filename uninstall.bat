@echo off

echo ========================================
echo   右键菜单管理器 —— 卸载
echo ========================================
echo.

:: 1. 获取管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提权] 需要管理员权限，正在重新启动...
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
echo   backups 文件夹中保留着已删除菜单
echo   的 .reg 备份文件，如需恢复请双击导入
echo ========================================
pause
