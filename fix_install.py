# -*- coding: utf-8 -*-
"""安装/修复右键菜单注册表项。需要管理员权限运行。"""
import winreg
import os
import sys


def install_menus():
    HKCR = winreg.HKEY_CLASSES_ROOT
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable

    cmd_file = f'"{python_exe}" "{tool_dir}\\menu_manager.py" -file "%1"'
    cmd_dir = f'"{python_exe}" "{tool_dir}\\menu_manager.py" -dir "%1"'
    cmd_bg = f'"{python_exe}" "{tool_dir}\\menu_manager.py" -bg "%V"'

    entries = [
        (r"*\shell\MenuManager", "右键菜单管理", cmd_file),
        (r"Directory\shell\MenuManager", "右键菜单管理", cmd_dir),
        (r"Directory\Background\shell\MenuManager", "右键菜单管理", cmd_bg),
    ]

    ok_count = 0
    for path, display, cmd in entries:
        try:
            k = winreg.CreateKey(HKCR, path)
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, display)
            k.Close()
            k = winreg.CreateKey(HKCR, path + r"\command")
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
            k.Close()
            print(f"  [OK] {path}")
            ok_count += 1
        except PermissionError:
            print(f"  [错误] 权限不足，请以管理员身份运行此脚本")
            return False
        except OSError as e:
            print(f"  [错误] 写入失败 {path}: {e}")
            return False

    print(f"\n安装/修复完成，共 {ok_count} 项。")
    return True


def uninstall_menus():
    HKCR = winreg.HKEY_CLASSES_ROOT
    paths = [
        r"*\shell\MenuManager",
        r"Directory\shell\MenuManager",
        r"Directory\Background\shell\MenuManager",
    ]

    for path in paths:
        try:
            key = winreg.OpenKey(HKCR, path, 0, winreg.KEY_ALL_ACCESS)
            winreg.DeleteKey(key, r"command")
            key.Close()
            parent_path, key_name = path.rsplit("\\", 1)
            parent = winreg.OpenKey(HKCR, parent_path, 0, winreg.KEY_ALL_ACCESS)
            winreg.DeleteKey(parent, key_name)
            parent.Close()
            print(f"  [已移除] {path}")
        except FileNotFoundError:
            print(f"  [信息] {path} 未注册，跳过")
        except PermissionError:
            print(f"  [错误] 权限不足，请以管理员身份运行")
            return False

    print("\n卸载完成。")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="右键菜单管理器 — 安装/卸载")
    parser.add_argument("--uninstall", action="store_true", help="卸载右键菜单项")
    args = parser.parse_args()

    if args.uninstall:
        success = uninstall_menus()
    else:
        success = install_menus()

    sys.exit(0 if success else 1)
