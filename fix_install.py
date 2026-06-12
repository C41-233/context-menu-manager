# -*- coding: utf-8 -*-
"""修复右键菜单注册表命令（给 %1 加引号）。需要管理员权限运行。"""
import winreg
import os
import sys
import ctypes

HKCR = winreg.HKEY_CLASSES_ROOT
tool_dir = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable

# 直接用 Python 路径代替 cmd /c python，避免 cmd 的引号解析问题
cmd_file = f'"{python_exe}" "{tool_dir}\\menu_manager.py" -file "%1"'
cmd_dir = f'"{python_exe}" "{tool_dir}\\menu_manager.py" -dir "%1"'
cmd_bg = f'"{python_exe}" "{tool_dir}\\menu_manager.py" -bg "%V"'

entries = [
    (r"*\shell\MenuManager", "右键菜单管理", cmd_file),
    (r"Directory\shell\MenuManager", "右键菜单管理", cmd_dir),
    (r"Directory\Background\shell\MenuManager", "右键菜单管理", cmd_bg),
]

for path, display, cmd in entries:
    # 写入显示名
    k = winreg.CreateKey(HKCR, path)
    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, display)
    k.Close()
    # 写入命令
    k = winreg.CreateKey(HKCR, path + r"\command")
    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    k.Close()
    print(f"OK: {path}")

print("\nDone. You can now right-click files with spaces/special chars in path.")
