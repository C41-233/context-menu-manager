# -*- coding: utf-8 -*-
"""菜单扫描：根据调用类型扫描注册表中的右键菜单项"""

import os
import winreg
from dataclasses import dataclass
from registry_ops import read_shell_entries, _try_open_key
from com_display_name import get_context_menu_display_names

HKCR = winreg.HKEY_CLASSES_ROOT


@dataclass
class MenuEntry:
    name: str           # 注册表键名
    display_name: str   # 显示文本
    command: str        # 命令
    enabled: bool       # True=已启用
    reg_path: str       # 完整注册表路径（HKCR 相对路径）
    source: str         # 来源标识，如 "*" / ".txt" / "Directory"
    hidden_reason: str | None = None  # 隐藏原因，如 "按住 Shift 显示"


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


# 标准动词本地化回退表（COM 和注册表都无法提供显示名时使用）
_STANDARD_VERBS_ZH = {
    "open": "打开(&O)",
    "edit": "编辑(&E)",
    "print": "打印(&P)",
    "printto": "打印到...",
    "find": "查找(&F)",
    "explore": "资源管理器(&X)",
    "play": "播放(&P)",
    "preview": "预览(&V)",
    "properties": "属性(&R)",
    "runas": "以管理员身份运行(&A)",
    "runasuser": "以其他用户身份运行(&U)",
    "cut": "剪切(&T)",
    "copy": "复制(&C)",
}


def _resolve_final_display(verb: str, registry_display: str,
                           com_overrides: dict[str, str] | None) -> str:
    """组合注册表、COM、硬编码映射的显示名解析。

    优先级:
      1. 注册表已解析（MUIVerb/默认值）— 直接使用
      2. COM 覆盖（跨语言，仅当注册表只返回键名时）
      3. 硬编码标准动词映射（中文回退）
      4. 键名本身
    """
    # 注册表已给出有效显示名
    if registry_display != verb:
        return registry_display

    verb_lower = verb.lower()

    # 注册表只返回了键名，尝试 COM
    if com_overrides:
        for com_verb, com_display in com_overrides.items():
            if com_verb.lower() == verb_lower:
                return com_display

    # COM 也没有，尝试硬编码标准动词
    if verb_lower in _STANDARD_VERBS_ZH:
        return _STANDARD_VERBS_ZH[verb_lower]

    return verb


def scan_entries(subpath: str, source_label: str,
                 display_overrides: dict[str, str] | None = None) -> list[MenuEntry]:
    """扫描一个注册表路径下的所有菜单项，返回 MenuEntry 列表。"""
    raw = read_shell_entries(subpath)
    return [
        MenuEntry(
            name=r["name"],
            display_name=_resolve_final_display(
                r["name"], r["display_name"], display_overrides,
            ),
            command=r["command"],
            enabled=r["enabled"],
            reg_path=r["reg_path"],
            source=source_label,
            hidden_reason=r.get("hidden_reason"),
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

    对文件/目录场景尝试用 COM 获取跨语言一致的显示名，失败则回退到注册表。
    """
    # 先尝试 COM 获取所有动词的显示名
    com_names = get_context_menu_display_names(filepath)

    result: dict[str, list[MenuEntry]] = {}

    # 1. 通用文件菜单
    result["*"] = scan_entries("*\\shell", "*", com_names)

    # 2-4. 文件类型专属菜单
    _, ext = os.path.splitext(filepath)
    if ext:
        ext_lower = ext.lower()
        ext_menus: list[MenuEntry] = []

        # 2. ProgID shell
        progid = resolve_progid(ext_lower)
        if progid:
            ext_menus.extend(scan_entries(f"{progid}\\shell", ext_lower, com_names))

        # 3. SystemFileAssociations 按扩展名
        sfa_ext_path = f"SystemFileAssociations\\{ext_lower}\\shell"
        if _has_key(sfa_ext_path):
            ext_menus.extend(scan_entries(sfa_ext_path, ext_lower, com_names))

        # 4. SystemFileAssociations 按感知类型
        perceived = read_perceived_type(ext_lower)
        if perceived and perceived != ext_lower:
            sfa_type_path = f"SystemFileAssociations\\{perceived}\\shell"
            if _has_key(sfa_type_path):
                ext_menus.extend(scan_entries(sfa_type_path, ext_lower, com_names))

        if ext_menus:
            result[ext_lower] = ext_menus

    return result


def scan_directory_menus(dirpath: str = "") -> dict[str, list[MenuEntry]]:
    """扫描目录右键菜单。

    dirpath: 目录路径，用于 COM 显示名解析。为空时跳过 COM。
    """
    com_names = get_context_menu_display_names(dirpath) if dirpath else {}
    entries = scan_entries("Directory\\shell", "Directory", com_names)
    return {"Directory": entries}


def scan_background_menus() -> dict[str, list[MenuEntry]]:
    """扫描目录背景右键菜单。"""
    entries = scan_entries("Directory\\Background\\shell", "Directory\\Background")
    return {"Directory\\Background": entries}
