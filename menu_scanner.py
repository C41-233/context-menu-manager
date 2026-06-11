# -*- coding: utf-8 -*-
"""菜单扫描：根据调用类型扫描注册表中的右键菜单项"""

import winreg
from dataclasses import dataclass
from registry_ops import read_shell_entries, _try_open_key

HKCR = winreg.HKEY_CLASSES_ROOT


@dataclass
class MenuEntry:
    name: str           # 注册表键名
    display_name: str   # 显示文本
    command: str        # 命令
    enabled: bool       # True=已启用
    reg_path: str       # 完整注册表路径（HKCR 相对路径）
    source: str         # 来源标识，如 "*" / ".txt" / "Directory"


def _read_value(path: str, name: str = "") -> str | None:
    """读取注册表值，失败返回 None。"""
    k = _try_open_key(path, winreg.KEY_READ)
    if k is None:
        return None
    try:
        value, _ = winreg.QueryValueEx(k, name)
        k.Close()
        return value
    except FileNotFoundError:
        k.Close()
        return None


def _has_key(path: str) -> bool:
    """检查注册表键是否存在。"""
    k = _try_open_key(path, winreg.KEY_READ)
    if k is not None:
        k.Close()
        return True
    return False


def resolve_progid(ext: str) -> str | None:
    """通过扩展名解析 ProgID，跟随 CurVer 重定向。

    例如 .txt → txtfilelegacy → (CurVer) → txtfile
    """
    progid = _read_value(ext)
    if not progid:
        return None

    # 跟随 CurVer 重定向（最多 3 层防止循环）
    for _ in range(3):
        cur_ver = _read_value(progid, "CurVer")
        if cur_ver:
            progid = cur_ver
        else:
            break

    if _has_key(f"{progid}\\shell"):
        return progid
    return None


def read_perceived_type(ext: str) -> str | None:
    """读取扩展名的感知类型，如 .txt → text"""
    return _read_value(ext, "PerceivedType")


def scan_entries(subpath: str, source_label: str) -> list[MenuEntry]:
    """扫描一个注册表路径下的所有菜单项，返回 MenuEntry 列表。"""
    raw = read_shell_entries(subpath)
    return [
        MenuEntry(
            name=r["name"],
            display_name=r["display_name"],
            command=r["command"],
            enabled=r["enabled"],
            reg_path=r["reg_path"],
            source=source_label,
        )
        for r in raw
    ]


def scan_file_menus(filepath: str) -> dict[str, list[MenuEntry]]:
    """扫描文件右键菜单。

    扫描来源：
    1. HKCR\\*\\shell\\ — 通用文件菜单
    2. HKCR\\{ProgID}\\shell\\ — 文件类型专属（含 CurVer 重定向）
    3. HKCR\\SystemFileAssociations\\{ext}\\shell\\ — 系统文件关联（按扩展名）
    4. HKCR\\SystemFileAssociations\\{PerceivedType}\\shell\\ — 系统文件关联（按感知类型）

    返回 {"*": [...通用菜单...], ".txt": [...类型专属菜单...]}
    """
    import os
    result = {}

    # 1. 通用文件菜单
    result["*"] = scan_entries("*\\shell", "*")

    # 2-4. 文件类型专属菜单
    _, ext = os.path.splitext(filepath)
    if ext:
        ext_lower = ext.lower()
        ext_menus: list[MenuEntry] = []

        # 2. ProgID shell
        progid = resolve_progid(ext_lower)
        if progid:
            ext_menus.extend(scan_entries(f"{progid}\\shell", ext_lower))

        # 3. SystemFileAssociations 按扩展名
        sfa_ext_path = f"SystemFileAssociations\\{ext_lower}\\shell"
        if _has_key(sfa_ext_path):
            ext_menus.extend(scan_entries(sfa_ext_path, ext_lower))

        # 4. SystemFileAssociations 按感知类型
        perceived = read_perceived_type(ext_lower)
        if perceived and perceived != ext_lower:
            sfa_type_path = f"SystemFileAssociations\\{perceived}\\shell"
            if _has_key(sfa_type_path):
                ext_menus.extend(scan_entries(sfa_type_path, ext_lower))

        if ext_menus:
            result[ext_lower] = ext_menus

    return result


def scan_directory_menus() -> dict[str, list[MenuEntry]]:
    """扫描目录右键菜单。"""
    entries = scan_entries("Directory\\shell", "Directory")
    return {"Directory": entries}


def scan_background_menus() -> dict[str, list[MenuEntry]]:
    """扫描目录背景右键菜单。"""
    entries = scan_entries("Directory\\Background\\shell", "Directory\\Background")
    return {"Directory\\Background": entries}
