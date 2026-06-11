# -*- coding: utf-8 -*-
"""右键菜单管理器 — 主入口。
被右键菜单调用，解析参数并启动 TUI。
"""

import sys
import os
import argparse
from menu_scanner import scan_file_menus, scan_directory_menus, scan_background_menus
from tui_app import launch_tui


def main():
    # 设置 stdout 为 UTF-8，防止启动前打印乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="右键菜单管理器")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-file", metavar="PATH", help="文件路径（右键点击文件时传入）")
    group.add_argument("-dir", metavar="PATH", help="目录路径（右键点击目录时传入）")
    group.add_argument("-bg", metavar="PATH", help="目录路径（右键点击目录背景时传入）")

    args = parser.parse_args()

    # 确定工具所在目录（用于 backups 路径）
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(tool_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    # 根据触发类型扫描菜单
    if args.file:
        sources = scan_file_menus(args.file)
        title_extra = os.path.basename(args.file)
    elif args.dir:
        sources = scan_directory_menus()
        title_extra = os.path.basename(args.dir)
    elif args.bg:
        sources = scan_background_menus()
        title_extra = os.path.basename(args.bg)

    # 启动 TUI
    launch_tui(sources, title_extra, backup_dir)


if __name__ == "__main__":
    main()
