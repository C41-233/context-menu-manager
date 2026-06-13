# -*- coding: utf-8 -*-
"""菜单扫描：根据调用类型扫描注册表中的右键菜单项"""

import os
import winreg
from dataclasses import dataclass
from registry_ops import read_shell_entries, _try_open_key
from com_display_name import get_context_menu_display_names
from log_utils import write_log

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
    except (FileNotFoundError, OSError):
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


def scan_ext_menus(ext_lower: str,
                    com_names: dict[str, str] | None = None) -> list[MenuEntry]:
    """扫描指定扩展名的所有专属菜单项。

    来源包括:
      - ProgID shell（含 CurVer 重定向）
      - SystemFileAssociations 按扩展名
      - SystemFileAssociations 按感知类型
    """
    ext_menus: list[MenuEntry] = []

    progid = resolve_progid(ext_lower)
    if progid:
        ext_menus.extend(scan_entries(f"{progid}\\shell", ext_lower, com_names))

    sfa_ext_path = f"SystemFileAssociations\\{ext_lower}\\shell"
    if _has_key(sfa_ext_path):
        ext_menus.extend(scan_entries(sfa_ext_path, ext_lower, com_names))

    perceived = read_perceived_type(ext_lower)
    if perceived and perceived != ext_lower:
        sfa_type_path = f"SystemFileAssociations\\{perceived}\\shell"
        if _has_key(sfa_type_path):
            ext_menus.extend(scan_entries(sfa_type_path, ext_lower, com_names))

    return ext_menus


def _get_clsid_dll(clsid_str: str) -> str:
    """查询 CLSID 对应的 DLL 路径。"""
    for server_key in ("InprocServer32", "LocalServer32"):
        dll = _read_value(f"CLSID\\{clsid_str}\\{server_key}")
        if dll:
            return dll
    return ""


def _get_file_description(dll_path: str) -> str:
    """读取 DLL 版本资源中的 FileDescription。"""
    dll_path = os.path.expandvars(dll_path)
    if not os.path.exists(dll_path):
        return ""

    import ctypes as _ct
    from ctypes import wintypes as _w

    size = _ct.windll.version.GetFileVersionInfoSizeW(dll_path, None)
    if size == 0:
        return ""

    buf = _ct.create_string_buffer(size)
    if not _ct.windll.version.GetFileVersionInfoW(dll_path, 0, size, buf):
        return ""

    trans_ptr = _ct.c_void_p()
    trans_len = _w.UINT()
    if not _ct.windll.version.VerQueryValueW(
        buf, r"\VarFileInfo\Translation",
        _ct.byref(trans_ptr), _ct.byref(trans_len),
    ):
        return ""

    code = _ct.cast(trans_ptr, _ct.POINTER(_w.DWORD))[0]
    lang, cp = code & 0xFFFF, (code >> 16) & 0xFFFF
    query = f"\\StringFileInfo\\{lang:04X}{cp:04X}\\FileDescription"

    desc_ptr = _ct.c_void_p()
    desc_len = _w.UINT()
    if _ct.windll.version.VerQueryValueW(
        buf, query, _ct.byref(desc_ptr), _ct.byref(desc_len),
    ):
        return _ct.cast(desc_ptr, _ct.c_wchar_p).value

    return ""


def _build_handler_verb_map(subpath: str, filepath: str) -> dict[str, str]:
    """遍历 shellex handlers，对可实例化的构建 {verb: handler_display_name} 映射。"""
    from com_display_name import get_handler_menu_items

    handlers_path = f"{subpath}\\shellex\\ContextMenuHandlers"
    k = _try_open_key(handlers_path, winreg.KEY_READ)
    if k is None:
        return {}

    verb_map: dict[str, str] = {}
    i = 0
    while True:
        try:
            key_name = winreg.EnumKey(k, i)
            i += 1
        except OSError:
            break

        default_val = _read_value(f"{handlers_path}\\{key_name}")
        if default_val and default_val.startswith("{"):
            handler_name = key_name
            actual_clsid = default_val
        else:
            handler_name = default_val or key_name
            actual_clsid = key_name if key_name.startswith("{") else ""

        if actual_clsid:
            items = get_handler_menu_items(filepath, actual_clsid)
            for verb in items:
                verb_map[verb] = handler_name
    k.Close()
    return verb_map


def scan_shellex_handlers(subpath: str, filepath: str = "") -> list[MenuEntry]:
    """扫描 shellex\\ContextMenuHandlers 下的所有 Shell 扩展。

    若有 filepath，对每个 CLSID 调用 COM 实例化获取真实子菜单项；
    实例化失败则回退到仅显示注册表静态信息。

    每个扩展的父级条目 reg_path 指向其 CLSID 键，可被整体删除；
    command 字段填入 DLL 路径以标识来源程序。
    """
    handlers_path = f"{subpath}\\shellex\\ContextMenuHandlers"
    k = _try_open_key(handlers_path, winreg.KEY_READ)
    if k is None:
        return []

    entries: list[MenuEntry] = []
    i = 0
    while True:
        try:
            clsid = winreg.EnumKey(k, i)
            i += 1
        except OSError:
            break

        full_path = f"{handlers_path}\\{clsid}"
        default_val = _read_value(full_path)

        # 显示名：优先用可读名称；若默认值是 CLSID 则键名才是可读名
        if default_val and default_val.startswith("{"):
            handler_name = clsid
        else:
            handler_name = default_val or clsid

        # 确定实际 CLSID：按优先级 键名 → 默认值 → 遍历所有值
        actual_clsid = clsid if clsid.startswith("{") else ""
        if not actual_clsid and default_val and default_val.startswith("{"):
            actual_clsid = default_val
        if not actual_clsid:
            hk = _try_open_key(full_path, winreg.KEY_READ)
            if hk is not None:
                j = 0
                while True:
                    try:
                        vname, vdata, _ = winreg.EnumValue(hk, j)
                        j += 1
                        if isinstance(vdata, str) and vdata.startswith("{"):
                            actual_clsid = vdata
                            break
                    except OSError:
                        break
                hk.Close()

        # 查询 DLL 路径及文件描述
        dll_path = _get_clsid_dll(actual_clsid) if actual_clsid else ""
        desc = _get_file_description(dll_path) if dll_path else ""
        if desc and dll_path:
            dll_info = f"{desc} — {dll_path}"
        elif dll_path:
            dll_info = f"DLL: {dll_path}"
        else:
            dll_info = "由 Shell 扩展实现"

        if filepath and actual_clsid:
            from com_display_name import get_handler_menu_items
            items = get_handler_menu_items(filepath, actual_clsid)
            if items:
                entries.append(MenuEntry(
                    name=handler_name,
                    display_name=handler_name,
                    command=dll_info,
                    enabled=True,
                    reg_path=full_path,
                    source="Shell 扩展",
                    hidden_reason="删除将移除整个扩展",
                ))
                for verb, display in items.items():
                    if display.lstrip("&").startswith(handler_name):
                        child_display = display
                    else:
                        child_display = f"{handler_name} ▸ {display}"
                    entries.append(MenuEntry(
                        name=verb,
                        display_name=child_display,
                        command="",
                        enabled=True,
                        reg_path="",
                        source="Shell 扩展",
                        hidden_reason="由 Shell 扩展提供",
                    ))
            else:
                entries.append(MenuEntry(
                    name=handler_name,
                    display_name=handler_name,
                    command=dll_info,
                    enabled=True,
                    reg_path=full_path,
                    source="Shell 扩展",
                    hidden_reason="无法获取子菜单（COM 实例化失败）",
                ))
        else:
            entries.append(MenuEntry(
                name=handler_name,
                display_name=handler_name,
                command=dll_info,
                enabled=True,
                reg_path=full_path,
                source="Shell 扩展",
                hidden_reason="包含动态子菜单，删除将移除整个扩展",
            ))

    k.Close()
    return entries


def _merge_com_entries(result: dict[str, list[MenuEntry]],
                       com_names: dict[str, str],
                       fallback_source: str,
                       handler_verb_map: dict[str, str] | None = None):
    """将 COM 发现但静态注册表扫描未覆盖的菜单项补充到结果中。

    handler_verb_map: {verb: handler_name} — 已实例化 handler，标注具体来源。
    """
    static_verbs: set[str] = set()
    for entries in result.values():
        for e in entries:
            static_verbs.add(e.name.lower())

    com_entries: list[MenuEntry] = []
    for verb, display in com_names.items():
        if verb.lower() not in static_verbs:
            if handler_verb_map:
                source_name = handler_verb_map.get(verb, "")
                source_hint = f"来自 {source_name}" if source_name else "由 Shell 扩展提供"
            else:
                source_hint = "由 Shell 扩展提供"
            com_entries.append(MenuEntry(
                name=verb,
                display_name=display,
                command="",
                enabled=True,
                reg_path="",
                source=fallback_source,
                hidden_reason=source_hint,
            ))

    if com_entries:
        if fallback_source in result:
            result[fallback_source].extend(com_entries)
        else:
            result[fallback_source] = com_entries


def scan_file_menus(filepath: str) -> dict[str, list[MenuEntry]]:
    """扫描文件右键菜单。

    扫描来源：
    1. HKCR\\*\\shell\\ — 通用文件菜单
    2. HKCR\\{ProgID}\\shell\\ — 文件类型专属（含 CurVer 重定向）
    3. HKCR\\SystemFileAssociations\\{ext}\\shell\\ — 系统文件关联（按扩展名）
    4. HKCR\\SystemFileAssociations\\{PerceivedType}\\shell\\ — 系统文件关联（按感知类型）
    5. COM IContextMenu — 捕获 shellex 扩展提供的动态菜单项

    对文件/目录场景尝试用 COM 获取跨语言一致的显示名，失败则回退到注册表。
    """
    com_names = get_context_menu_display_names(filepath)

    result: dict[str, list[MenuEntry]] = {}

    # 1. 通用文件菜单
    result["*"] = scan_entries("*\\shell", "*", com_names)

    # 2-4. 文件类型专属菜单
    _, ext = os.path.splitext(filepath)
    ext_lower = ext.lower() if ext else ""
    if ext_lower:
        ext_menus = scan_ext_menus(ext_lower, com_names)
        if ext_menus:
            result[ext_lower] = ext_menus

    # 5. 构建 handler→verb 映射（标注 COM 合并条目来源）
    handler_verb_map = _build_handler_verb_map("*", filepath)
    if ext_lower:
        handler_verb_map.update(_build_handler_verb_map(ext_lower, filepath))

    # 6. 补充 COM 独有的菜单项（shellex 扩展），标注已知 handler
    _merge_com_entries(result, com_names, ext_lower or "*", handler_verb_map)

    # 7. Shell 扩展（shellex\ContextMenuHandlers）— 实例化获取真实子菜单
    shellex_entries = scan_shellex_handlers("*", filepath)
    if ext_lower:
        shellex_entries.extend(scan_shellex_handlers(ext_lower, filepath))
    if shellex_entries:
        result["Shell 扩展"] = shellex_entries

    return result


def scan_directory_menus(dirpath: str = "") -> dict[str, list[MenuEntry]]:
    """扫描目录右键菜单。

    dirpath: 目录路径，用于 COM 显示名解析。为空时跳过 COM。
    """
    com_names = get_context_menu_display_names(dirpath) if dirpath else {}
    result = {"Directory": scan_entries("Directory\\shell", "Directory", com_names)}
    if com_names:
        handler_verb_map = _build_handler_verb_map("Directory", dirpath)
        _merge_com_entries(result, com_names, "Directory", handler_verb_map)
    shellex_entries = scan_shellex_handlers("Directory", dirpath)
    if shellex_entries:
        result["Shell 扩展"] = shellex_entries
    return result


def scan_background_menus() -> dict[str, list[MenuEntry]]:
    """扫描目录背景右键菜单。

    COM 显示名解析不适用于背景菜单（没有可传入 IContextMenu 的文件/目录对象），
    因此仅使用注册表显示名和标准动词回退表。
    """
    entries = scan_entries("Directory\\Background\\shell", "Directory\\Background")
    return {"Directory\\Background": entries}
