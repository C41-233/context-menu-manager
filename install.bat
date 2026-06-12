@echo off

echo ========================================
echo   右键菜单管理器 —— 安装
echo ========================================
echo.

:: 1. 检测 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3
    pause
    exit /b 1
)
echo [OK] Python 已检测到

:: 2. 检测 textual 库
python -c "import textual" >nul 2>&1
if %errorlevel% neq 0 (
    echo [安装] 正在安装 textual 库...
    pip install textual
    if %errorlevel% neq 0 (
        echo [错误] textual 安装失败，请手动执行: pip install textual
        pause
        exit /b 1
    )
)
echo [OK] textual 库已就绪

:: 3. 获取管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提权] 需要管理员权限，正在重新启动...
    powershell -Command "Start-Process '%~f0' -Verb RunAs -Wait"
    exit /b %errorlevel%
)
echo [OK] 管理员权限已确认

:: 4. 获取脚本所在目录
set "TOOL_DIR=%~dp0"
set "TOOL_DIR=%TOOL_DIR:~0,-1%"

:: 5. 注册右键菜单（Python 直写注册表，避免 reg add 的引号转义问题）
echo 正在注册右键菜单...
python "%TOOL_DIR%\fix_install.py"
echo.

echo ========================================
echo   安装完成！
echo   现在可在文件/目录/目录背景上右键
echo   找到"右键菜单管理"选项
echo ========================================
pause
