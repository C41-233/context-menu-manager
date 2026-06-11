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
    buf = ctypes.create_unicode_buffer(512)
    shlwapi = ctypes.windll.shlwapi
    hr = shlwapi.SHLoadIndirectString(raw, buf, 511, None)
    if hr == 0:  # S_OK
        return buf.value
    return raw


# Windows 标准 Shell 动词的本地化名称
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


def resolve_display_name(key_handle, key_name: str = "") -> str:
    """从注册表键读取并解析显示名称。

    优先: MUIVerb → 默认值 → 标准动词本地化 → 键名
    对间接字符串执行 resolve_indirect_string 解析。
    """
    raw = read_value(key_handle, "MUIVerb") or read_default_value(key_handle)
    if raw:
        return resolve_indirect_string(raw)
    # 标准动词回退到本地化名称
    if key_name.lower() in _STANDARD_VERBS_ZH:
        return _STANDARD_VERBS_ZH[key_name.lower()]
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
    except FileNotFoundError:
        return None


def read_value(key_handle, name: str) -> Optional[str]:
    """读取指定名称的值。"""
    try:
        value, _ = winreg.QueryValueEx(key_handle, name)
        return value
    except FileNotFoundError:
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


def read_shell_entries(subpath: str) -> list[dict]:
    """枚举 subpath 下所有子键，返回原始信息列表。

    每个 dict 包含: name, display_name, command, enabled, reg_path
    """
    entries = []
    shell_key = _try_open_key(subpath, winreg.KEY_READ)
    if shell_key is None:
        return entries

    for name in list_subkeys(shell_key):
        full_path = f"{subpath}\\{name}"
        item_key = _try_open_key(full_path, winreg.KEY_READ)
        if item_key is None:
            continue

        # 读取显示名：间接字符串解析 + 标准动词本地化 + 多重回退
        display_name = resolve_display_name(item_key, name)

        # 读取命令
        command = ""
        cmd_key = _try_open_key(f"{full_path}\\command", winreg.KEY_READ)
        if cmd_key is not None:
            command = read_default_value(cmd_key) or ""
            cmd_key.Close()

        # 检查是否禁用
        legacy_disable = read_value(item_key, "LegacyDisable")
        enabled = legacy_disable is None

        item_key.Close()

        entries.append({
            "name": name,
            "display_name": display_name,
            "command": command,
            "enabled": enabled,
            "reg_path": full_path,
        })

    shell_key.Close()
    return entries


def set_disabled(reg_path: str, disabled: bool):
    """设置菜单项的 LegacyDisable 状态。

    reg_path: HKCR 下的相对路径，如 r"*\\shell\\VSCode"
    disabled: True=写入 LegacyDisable(禁用), False=删除 LegacyDisable(启用)
    """
    key = _open_key(reg_path, winreg.KEY_SET_VALUE | winreg.KEY_READ)

    if disabled:
        winreg.SetValueEx(key, "LegacyDisable", 0, winreg.REG_SZ, "")
    else:
        try:
            winreg.DeleteValue(key, "LegacyDisable")
        except FileNotFoundError:
            pass  # 本来就没有，忽略

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


def delete_key_tree(reg_path: str):
    """递归删除一个注册表键树。

    winreg.DeleteKey 不支持删除有子键的键，需先递归删除子键。
    """
    # 先获取父路径和键名
    parts = reg_path.rsplit("\\", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的注册表路径: {reg_path}")
    parent_path, key_name = parts

    # 递归删除子键
    _delete_key_recursive(parent_path, key_name)


def _delete_key_recursive(parent_path: str, key_name: str):
    """递归删除指定子键。打开子键 → 递归删其子键 → 关闭 → 从父键删除自身。"""
    full_path = f"{parent_path}\\{key_name}"
    key = _open_key(full_path, winreg.KEY_ALL_ACCESS)

    for sub_name in list_subkeys(key):
        _delete_key_recursive(full_path, sub_name)

    key.Close()
    parent = _open_key(parent_path, winreg.KEY_ALL_ACCESS)
    winreg.DeleteKey(parent, key_name)
    parent.Close()


def export_as_reg(key_tree: dict, reg_path: str) -> str:
    """将 read_key_tree 的结果转换为 .reg 文件内容字符串。

    reg_path: 完整注册表路径，如 HKCR\\\\*\\\\shell\\\\EditPlus
    """
    lines = ["Windows Registry Editor Version 5.00", ""]
    _export_section(lines, f"HKEY_CLASSES_ROOT\\{reg_path}", key_tree)
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
