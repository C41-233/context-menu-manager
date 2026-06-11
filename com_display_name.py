# -*- coding: utf-8 -*-
"""通过 IContextMenu COM 接口获取菜单项的真实显示名。

用系统 COM 接口获取右键菜单动词的实际显示文本，避免硬编码语言映射。
结果与 Windows 资源管理器右键菜单 100% 一致。
"""

import os
import ctypes
from ctypes import wintypes, byref, sizeof, cast, POINTER, c_char, c_void_p, c_ulong, c_wchar


# === GUID 定义 ===

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

IID_IShellFolder = GUID(
    0x000214E6, 0x0000, 0x0000,
    (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
)

IID_IContextMenu = GUID(
    0x000214E4, 0x0000, 0x0000,
    (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46)
)


# === MENUITEMINFOW 结构 ===

# ULONG_PTR / UINT_PTR 在旧版 ctypes.wintypes 中可能不存在
_PTR_SIZE = ctypes.sizeof(ctypes.c_void_p)
_UINT_PTR = ctypes.c_uint64 if _PTR_SIZE == 8 else ctypes.c_uint32
_ULONG_PTR = _UINT_PTR


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("fMask", wintypes.UINT),
        ("fType", wintypes.UINT),
        ("fState", wintypes.UINT),
        ("wID", wintypes.UINT),
        ("hSubMenu", wintypes.HMENU),
        ("hbmpChecked", wintypes.HBITMAP),
        ("hbmpUnchecked", wintypes.HBITMAP),
        ("dwItemData", _ULONG_PTR),
        ("dwTypeData", wintypes.LPWSTR),
        ("cch", wintypes.UINT),
        ("hbmpItem", wintypes.HBITMAP),
    ]


# === Win32 DLL ===

shell32 = ctypes.windll.shell32
ole32 = ctypes.windll.ole32
user32 = ctypes.windll.user32

# 设置常用函数签名
HRESULT = ctypes.c_long


# === COM vtable 辅助 ===

def _com_method(ptr, idx, restype):
    """从 COM 接口 vtable 获取指定索引的方法，返回函数地址。"""
    vtbl = cast(ptr, POINTER(c_void_p)).contents  # vtable 地址
    vtbl_array = cast(vtbl, POINTER(c_void_p))    # 作为指针数组
    return vtbl_array[idx]                         # 第 idx 个函数指针


def _com_call(ptr, idx, restype, *argtypes):
    """调用 COM 接口 vtable 中指定索引的方法。"""
    func_addr = _com_method(ptr, idx, restype)
    prototype = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    func = prototype(func_addr)
    return lambda *args: func(ptr, *args)


def _com_release(ptr):
    """释放 COM 接口引用。"""
    if ptr:
        _com_call(ptr, 2, ctypes.c_ulong)()


# === 核心功能 ===

def get_context_menu_display_names(filepath: str) -> dict[str, str]:
    """使用 IContextMenu COM 获取指定文件/目录的所有右键菜单动词→显示名映射。

    流程:
      1. SHParseDisplayName → PIDL
      2. SHBindToParent → IShellFolder (父目录) + 子 PIDL
      3. IShellFolder::GetUIObjectOf → IContextMenu
      4. CreatePopupMenu → 临时菜单句柄
      5. IContextMenu::QueryContextMenu → 填充菜单项
      6. 遍历菜单项, 用 GetCommandString(GCS_VERBW) 取动词,
         GetMenuItemInfoW 取显示文本
      7. 清理并返回 {verb: display_name}

    Args:
        filepath: 文件或目录的绝对路径。

    Returns:
        verb_name → display_text 映射字典。COM 解析失败时返回空字典。
    """
    result: dict[str, str] = {}
    filepath = os.path.abspath(filepath)

    if not os.path.exists(filepath):
        return result

    # COM 初始化
    co_init = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    need_uninit = (co_init == 0)  # S_OK 表示我们负责反初始化

    pidl = None
    psf = None
    pcm = None
    hmenu = None

    try:
        # 1. 解析路径为 PIDL
        pidl = c_void_p()
        hr = shell32.SHParseDisplayName(filepath, None, byref(pidl), 0, None)
        if hr != 0:
            return result

        # 2. 绑定到父文件夹, 获取 IShellFolder 和子 PIDL
        ppv = c_void_p()
        child_pidl = c_void_p()
        hr = shell32.SHBindToParent(
            pidl, byref(IID_IShellFolder), byref(ppv), byref(child_pidl)
        )
        if hr != 0:
            return result
        psf = ppv

        # 3. IShellFolder::GetUIObjectOf → IContextMenu
        pcm_out = c_void_p()
        call_GetUIObjectOf = _com_call(
            psf, 10, HRESULT,
            wintypes.HWND, wintypes.UINT,
            c_void_p, c_void_p, c_void_p,
            POINTER(c_void_p),
        )
        hr = call_GetUIObjectOf(
            None, 1,
            cast(byref(child_pidl), c_void_p),
            cast(byref(IID_IContextMenu), c_void_p),
            None,
            byref(pcm_out),
        )
        if hr != 0:
            return result
        pcm = pcm_out

        # 4. 创建临时菜单
        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return result

        # 5. IContextMenu::QueryContextMenu
        call_QueryContextMenu = _com_call(
            pcm, 3, HRESULT,
            wintypes.HMENU, wintypes.UINT, wintypes.UINT,
            wintypes.UINT, wintypes.UINT,
        )
        hr = call_QueryContextMenu(hmenu, 0, 1, 0x7FFF, 0)  # CMF_NORMAL
        if hr < 0:
            return result

        # 6. 遍历菜单项, 匹配动词
        count = user32.GetMenuItemCount(hmenu)
        call_GetCommandString = _com_call(
            pcm, 5, HRESULT,
            _UINT_PTR, wintypes.UINT,
            c_void_p, c_void_p, wintypes.UINT,
        )

        for i in range(count):
            # 先获取菜单项信息（含实际 command ID 和显示文本）
            display_buf = (c_wchar * 512)()
            mii = MENUITEMINFOW()
            mii.cbSize = sizeof(MENUITEMINFOW)
            # MIIM_STRING | MIIM_FTYPE | MIIM_ID
            mii.fMask = 0x00000040 | 0x00000002 | 0x00000001
            mii.dwTypeData = cast(display_buf, wintypes.LPWSTR)
            mii.cch = 512

            if not user32.GetMenuItemInfoW(hmenu, i, True, byref(mii)):
                continue
            if mii.fType & 0x800:  # MFT_SEPARATOR
                continue

            cmd_id = mii.wID
            if cmd_id == 0:
                continue

            # 用实际 command ID 获取动词 (GCS_VERBW = 0x4)
            verb_buf = (c_wchar * 256)()
            try:
                hr = call_GetCommandString(
                    cmd_id, 0x4, None, cast(verb_buf, c_void_p), 256
                )
            except OSError:
                continue
            if hr != 0:
                continue

            verb = verb_buf.value
            text = display_buf.value
            if verb and text:
                result[verb] = text

    finally:
        # 清理资源
        if hmenu:
            user32.DestroyMenu(hmenu)
        _com_release(pcm)
        _com_release(psf)
        if pidl:
            ole32.CoTaskMemFree(pidl)
        if need_uninit:
            ole32.CoUninitialize()

    return result
