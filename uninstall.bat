@echo off

echo ========================================
echo   右键菜单管理器 — 卸载
echo ========================================
echo.

:: 1. 获取管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提权] 需要管理员权限，正在请求提升...
    powershell -Command "Start-Process '%~f0' -Verb RunAs -Wait"
    exit /b %errorlevel%
)
echo [OK] 管理员权限已确认

:: 2. 调用 Python 脚本卸载注册表项
set "TOOL_DIR=%~dp0"
set "TOOL_DIR=%TOOL_DIR:~0,-1%"
python "%TOOL_DIR%\fix_install.py" --uninstall
echo.

echo ========================================
echo   卸载完成！
echo   backups 文件夹中保留了已删除菜单
echo   的 .reg 恢复文件，双击即可恢复
echo ========================================
pause
