# -*- coding: utf-8 -*-
"""注册表原子操作：读、写 LegacyDisable、读取键树、删除键树、导出 .reg"""

import ctypes
import winreg
from typing import Optional

HKCR = winreg.HKEY_CLASSES_ROOT


def resolve_indirect_string(raw: str) -> str:
    """解析 Windows 间接字符串引用。

    @shell32.dll,-8506 → 实际资源字符串
    @C:\\path\\to\\file.dll,-123 → 实际资源字符串
    非 @ 开头的字符串原样返回。
    """
    if not raw or not raw.startswith("@"):
        return raw

    # SHLoadIndirectString 接受完整的 @path,-resid 格式
    buf = ctypes.create_unicode_buffer(1024)
    shlwapi = ctypes.windll.shlwapi
    hr = shlwapi.SHLoadIndirectString(raw, buf, 1023, None)
    if hr == 0:  # S_OK
        return buf.value
    return raw


def resolve_display_name(key_handle, key_name: str = "") -> str:
    """从注册表键读取并解析显示名称。

    优先级: MUIVerb → 默认值 → 键名
    对间接字符串执行 resolve_indirect_string 解析。
    更上层的回退（COM、标准动词映射）在 menu_scanner 中处理。
    """
    raw = read_value(key_handle, "MUIVerb") or read_default_value(key_handle)
    if raw:
        return resolve_indirect_string(raw)
    return key_name


def _open_key(path: str, access: int = winreg.KEY_READ):
    """打开注册表键，返回句柄。path 为 HKCR 下的相对路径。"""
    return winreg.OpenKey(HKCR, path, 0, access)


def _try_open_key(path: str, access: int = winreg.KEY_READ) -> Optional[winreg.HKEYType]:
    """尝试打开键，不存在则返回 None。"""
    try:
        return _open_key(path, access)
    except FileNotFoundError:
        return None


def read_default_value(key_handle) -> Optional[str]:
    """读取键的默认值。"""
    try:
        value, _ = winreg.QueryValueEx(key_handle, "")
        return value
    except (FileNotFoundError, OSError):
        return None


def read_value(key_handle, name: str) -> Optional[str]:
    """读取指定名称的值。"""
    try:
        value, _ = winreg.QueryValueEx(key_handle, name)
        return value
    except (FileNotFoundError, OSError):
        return None


def list_subkeys(key_handle) -> list[str]:
    """列出键下的所有子键名。"""
    keys = []
    i = 0
    while True:
        try:
            keys.append(winreg.EnumKey(key_handle, i))
            i += 1
        except OSError:
            break
    return keys


def _read_shell_recursive(subpath: str, parent_display: str,
                          parent_hidden: str,
                          entries: list[dict]):
    """递归扫描 shell 子键，展开级联子菜单。"""
    shell_key = _try_open_key(subpath, winreg.KEY_READ)
    if shell_key is None:
        return

    for name in list_subkeys(shell_key):
        full_path = f"{subpath}\\{name}"
        item_key = _try_open_key(full_path, winreg.KEY_READ)
        if item_key is None:
            continue

        display_name = resolve_display_name(item_key, name)
        if parent_display:
            display_name = f"{parent_display} ▸ {display_name}"

        command = ""
        delegate_execute = ""
        cmd_key = _try_open_key(f"{full_path}\\command", winreg.KEY_READ)
        if cmd_key is not None:
            command = read_default_value(cmd_key) or ""
            delegate_execute = read_value(cmd_key, "DelegateExecute") or ""
            cmd_key.Close()

        legacy_disable = read_value(item_key, "LegacyDisable")
        enabled = legacy_disable is None

        # 检测隐藏原因
        hidden_reasons = []
        has_ext_val = read_value(item_key, "Extended")
        has_ext_key = _try_open_key(f"{full_path}\\Extended", winreg.KEY_READ)
        if has_ext_val is not None or has_ext_key is not None:
            hidden_reasons.append("按住 Shift 显示")
        if has_ext_key is not None:
            has_ext_key.Close()

        # COM 委托：可见性由 shell 扩展动态控制，Win11 简化菜单通常不显示
        if delegate_execute and not command:
            hidden_reasons.append("COM 委托，可见性由 shell 扩展控制")

        # ProgrammaticAccessOnly：仅允许程序调用，不显示在菜单中
        if read_value(item_key, "ProgrammaticAccessOnly") is not None:
            hidden_reasons.append("仅限程序调用")

        subcommands = read_value(item_key, "Subcommands")
        nested = f"{full_path}\\shell"
        has_nested = _try_open_key(nested, winreg.KEY_READ) is not None
        invalid_sub = (subcommands == "" and has_nested)
        if invalid_sub:
            hidden_reasons.append("Subcommands 异常，未显示")

        item_key.Close()

        # 拼接标记字符串
        tag = ", ".join(hidden_reasons)
        if parent_hidden:
            tag = f"{parent_hidden}, {tag}" if tag else parent_hidden

        if command or not has_nested:
            entries.append({
                "name": name,
                "display_name": display_name,
                "command": command,
                "enabled": enabled,
                "reg_path": full_path,
                "hidden_reason": tag or None,
            })

        if has_nested:
            child_hidden = parent_hidden
            if invalid_sub and not command:
                child_hidden = f"{child_hidden}, Subcommands 异常，未显示" if child_hidden else "Subcommands 异常，未显示"
            _read_shell_recursive(nested, display_name, child_hidden, entries)

    shell_key.Close()


def read_shell_entries(subpath: str) -> list[dict]:
    """枚举 subpath 下所有子键（含级联展开），返回原始信息列表。

    每个 dict 包含: name, display_name, command, enabled, reg_path
    """
    entries: list[dict] = []
    _read_shell_recursive(subpath, "", "", entries)
    return entries


def set_disabled(reg_path: str, disabled: bool):
    """设置菜单项的 LegacyDisable 状态。

    reg_path: HKCR 下的相对路径，如 r"*\\shell\\VSCode"
    disabled: True=写入 LegacyDisable(禁用), False=删除 LegacyDisable(启用)
    """
    key = _try_open_key(reg_path, winreg.KEY_SET_VALUE | winreg.KEY_READ)
    if key is None:
        return

    if disabled:
        winreg.SetValueEx(key, "LegacyDisable", 0, winreg.REG_SZ, "")
    else:
        try:
            winreg.DeleteValue(key, "LegacyDisable")
        except FileNotFoundError:
            pass

    key.Close()


def read_key_tree(reg_path: str) -> dict:
    """递归读取一个键的完整树，返回嵌套字典。

    格式:
    {
        "values": {"(默认)": "xxx", "Icon": "..."},
        "subkeys": {
            "command": {"values": {"(默认)": "..."}, "subkeys": {}},
            ...
        }
    }
    """
    key = _open_key(reg_path, winreg.KEY_READ)
    tree = {"values": {}, "subkeys": {}}

    # 读取所有值
    i = 0
    while True:
        try:
            name, data, _ = winreg.EnumValue(key, i)
            display_name = name if name else "(默认)"
            if isinstance(data, str):
                tree["values"][display_name] = data
            i += 1
        except OSError:
            break

    # 递归读取子键
    for sub_name in list_subkeys(key):
        tree["subkeys"][sub_name] = read_key_tree(f"{reg_path}\\{sub_name}")

    key.Close()
    return tree


def _resolve_delete_hive(reg_path: str) -> tuple[int, str, str]:
    """解析 HKCR 相对路径到实际的 hive、父路径、键名。

    Returns (hive, parent_relpath, key_name)。HKCU 优先于 HKLM。
    """
    parts = reg_path.rsplit("\\", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的注册表路径: {reg_path}")
    parent_relpath, key_name = parts

    # 探测实际 hive（HKCU 优先）
    for hive, prefix_relpath in [
        (winreg.HKEY_CURRENT_USER, "Software\\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Classes"),
    ]:
        try:
            full = f"{prefix_relpath}\\{parent_relpath}\\{key_name}"
            k = winreg.OpenKey(hive, full, 0, winreg.KEY_READ)
            k.Close()
            return hive, f"{prefix_relpath}\\{parent_relpath}", key_name
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"注册表键不存在: {reg_path}")


def delete_key_tree(reg_path: str):
    """递归删除一个注册表键树。直接操作底层 hive（HKCU 优先，HKLM 回退）。"""
    # 先读取 CLSID（删除 handler 后就读取不到了）
    clsid = _read_clsid_from_shellex(reg_path)

    hive, parent_path, key_name = _resolve_delete_hive(reg_path)
    _delete_key_recursive(hive, parent_path, key_name)

    # 删除关联的 CLSID 键
    if clsid:
        _delete_clsid_key(clsid)


def _read_clsid_from_shellex(reg_path: str) -> str:
    """从 shellex 注册项读取其关联的 CLSID。"""
    for hive, prefix in [
        (winreg.HKEY_CURRENT_USER, "Software\\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Classes"),
    ]:
        try:
            full = f"{prefix}\\{reg_path}"
            k = winreg.OpenKey(hive, full, 0, winreg.KEY_READ)
            clsid, _ = winreg.QueryValueEx(k, "")
            k.Close()
            return clsid if clsid.startswith("{") else ""
        except FileNotFoundError:
            continue
    return ""


def _delete_clsid_key(clsid: str):
    """删除 CLSID 注册项（尝试两个 hive）。"""
    for hive, prefix in [
        (winreg.HKEY_CURRENT_USER, "Software\\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Classes"),
    ]:
        try:
            _delete_key_recursive(hive, f"{prefix}\\CLSID", clsid)
            return
        except OSError:
            continue


def _delete_key_recursive(hive: int, parent_path: str, key_name: str):
    """递归删除指定子键。"""
    full_path = f"{parent_path}\\{key_name}"
    key = winreg.OpenKey(hive, full_path, 0, winreg.KEY_ALL_ACCESS)

    for sub_name in list_subkeys(key):
        _delete_key_recursive(hive, full_path, sub_name)

    key.Close()
    parent = winreg.OpenKey(hive, parent_path, 0, winreg.KEY_ALL_ACCESS)
    winreg.DeleteKey(parent, key_name)
    parent.Close()


def resolve_hkcr_root(reg_path: str) -> str:
    """探测 HKCR 键的实际物理位置。

    尝试在 HKCU\\Software\\Classes 和 HKLM\\Software\\Classes 下打开该键，
    返回 \"HKEY_CURRENT_USER\\Software\\Classes\" 或 \"HKEY_LOCAL_MACHINE\\Software\\Classes\"。
    均失败则回退到 \"HKEY_CLASSES_ROOT\"。
    """
    for hive, prefix in [
        (winreg.HKEY_CURRENT_USER, r"HKEY_CURRENT_USER\Software\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, r"HKEY_LOCAL_MACHINE\Software\Classes"),
    ]:
        try:
            k = winreg.OpenKey(hive, f"Software\\Classes\\{reg_path}", 0, winreg.KEY_READ)
            k.Close()
            return prefix
        except FileNotFoundError:
            continue
    return "HKEY_CLASSES_ROOT"


def export_as_reg(key_tree: dict, reg_path: str) -> str:
    """将 read_key_tree 的结果转换为 .reg 文件内容字符串。

    reg_path: HKCR 下的相对路径，如 *\\shell\\EditPlus
    """
    root = resolve_hkcr_root(reg_path)
    lines = ["Windows Registry Editor Version 5.00", ""]
    _export_section(lines, f"{root}\\{reg_path}", key_tree)
    return "\r\n".join(lines)


def _export_section(lines: list, full_path: str, tree: dict):
    """递归写入注册表段。"""
    lines.append(f"[{full_path}]")
    for name, value in tree["values"].items():
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        if name == "(默认)":
            lines.append(f'@="{escaped_value}"')
        else:
            escaped_name = name.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{escaped_name}"="{escaped_value}"')
    lines.append("")

    for sub_name, sub_tree in tree["subkeys"].items():
        _export_section(lines, f"{full_path}\\{sub_name}", sub_tree)
