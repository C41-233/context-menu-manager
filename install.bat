@echo off

echo ========================================
echo   右键菜单管理器 — 安装
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
        echo [错误] textual 安装失败，请手动运行: pip install textual
        pause
        exit /b 1
    )
)
echo [OK] textual 库已就绪

:: 3. 检测管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [提权] 需要管理员权限，正在请求提升...
    powershell -Command "Start-Process '%~f0' -Verb RunAs -Wait"
    exit /b %errorlevel%
)
echo [OK] 管理员权限已确认

:: 4. 获取脚本所在目录
set "TOOL_DIR=%~dp0"
set "TOOL_DIR=%TOOL_DIR:~0,-1%"

:: 5. 注册右键菜单项（使用 cmd /c 前缀确保能找到 python）

:: 5a. 通用文件菜单
reg add "HKCR\*\shell\MenuManager" /ve /t REG_SZ /d "右键菜单管理" /f >nul
reg add "HKCR\*\shell\MenuManager\command" /ve /t REG_SZ /d "cmd /c python "%TOOL_DIR%\menu_manager.py" -file "%%1"" /f >nul
echo [OK] 已注册: 文件右键菜单

:: 5b. 目录菜单
reg add "HKCR\Directory\shell\MenuManager" /ve /t REG_SZ /d "右键菜单管理" /f >nul
reg add "HKCR\Directory\shell\MenuManager\command" /ve /t REG_SZ /d "cmd /c python "%TOOL_DIR%\menu_manager.py" -dir "%%1"" /f >nul
echo [OK] 已注册: 目录右键菜单

:: 5c. 目录背景菜单
reg add "HKCR\Directory\Background\shell\MenuManager" /ve /t REG_SZ /d "右键菜单管理" /f >nul
reg add "HKCR\Directory\Background\shell\MenuManager\command" /ve /t REG_SZ /d "cmd /c python "%TOOL_DIR%\menu_manager.py" -bg "%%V"" /f >nul
echo [OK] 已注册: 目录背景右键菜单

echo.
echo ========================================
echo   安装完成！
echo   现在可以在文件/目录/目录背景上右键
echo   找到「右键菜单管理」选项
echo ========================================
pause
