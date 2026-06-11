# -*- coding: utf-8 -*-
"""Textual TUI — 右键菜单管理交互界面

架构说明:
- ContextMenuApp 只管理一个主 Screen
- 主 Screen 内 compose MenuListContainer (单来源) 或 TabbedContent (多来源)
- MenuListContainer 是带 BINDINGS 的 Container，可独立获取焦点
- BINDINGS 只在 active 的 Container 上生效（Tab 切换时自动处理）
"""

import os
from datetime import datetime
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Header, Footer, ListView, ListItem, Label,
    TabbedContent, TabPane,
)

from menu_scanner import MenuEntry
from registry_ops import (
    set_disabled, read_key_tree, delete_key_tree, export_as_reg,
)


class ConfirmDeleteScreen(ModalScreen[bool]):
    """删除确认弹窗。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("enter", "confirm", "确认删除"),
    ]

    def __init__(self, entry: MenuEntry, backup_filename: str):
        super().__init__()
        self.entry = entry
        self.backup_filename = backup_filename

    def compose(self) -> ComposeResult:
        yield Container(
            Label("[bold red]⚠ 确认删除[/bold red]"),
            Label(""),
            Label("即将从注册表删除以下菜单项："),
            Label(f"[bold]{self.entry.reg_path}[/bold]"),
            Label(f"  └── command: {self.entry.command}"),
            Label(""),
            Label("此操作[bold]不可撤销[/bold]！"),
            Label(f"恢复文件将保存至: backups\\{self.backup_filename}"),
            Label(""),
            Label("[bold]Enter[/bold] 确认删除    [bold]Esc[/bold] 取消"),
            id="confirm-dialog",
        )

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class MenuListContainer(Container, can_focus=True):
    """菜单项列表容器 — 带键盘快捷键绑定。

    作为 Container 子类可被直接 compose 到 Screen 或 TabPane 中。
    can_focus=True 使其可获得焦点以接收按键。
    """

    BINDINGS = [
        Binding("space", "toggle", "启用/禁用"),
        Binding("delete", "delete_item", "删除"),
        Binding("r", "refresh", "刷新"),
        Binding("q", "quit", "退出"),
        Binding("escape", "quit", "退出"),
    ]

    def __init__(self, entries: list[MenuEntry], source_name: str,
                 title_extra: str, backup_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.entries = entries
        self.source_name = source_name
        self.title_extra = title_extra
        self.backup_dir = backup_dir
        self._list_view = None

    def on_mount(self):
        self._build_list()

    def _build_list(self):
        """重建列表。"""
        # 移除旧的 ListView
        for child in self.query(ListView):
            child.remove()

        items = []
        for e in self.entries:
            status_icon = "●" if e.enabled else "○"
            status_text = "已启用" if e.enabled else "已禁用"
            cmd_short = e.command[:50] + "..." if len(e.command) > 50 else e.command
            items.append(ListItem(
                Label(f"{status_icon} {e.display_name}    {status_text}    {cmd_short}")
            ))
        lv = ListView(*items, id="menu-list")
        self.mount(lv)
        lv.focus()

    def _get_selected_entry(self) -> MenuEntry | None:
        """获取当前选中的菜单项。"""
        lv = self.query_one("#menu-list", ListView)
        if lv.index is None:
            return None
        idx = lv.index
        if 0 <= idx < len(self.entries):
            return self.entries[idx]
        return None

    def _refresh_entries(self):
        """重新扫描并刷新列表。"""
        from menu_scanner import scan_entries, resolve_progid
        if self.source_name == "*":
            self.entries = scan_entries("*\\shell", "*")
        elif self.source_name == "Directory":
            self.entries = scan_entries("Directory\\shell", "Directory")
        elif self.source_name == "Directory\\Background":
            self.entries = scan_entries("Directory\\Background\\shell", "Directory\\Background")
        else:
            progid = resolve_progid(self.source_name)
            if progid:
                self.entries = scan_entries(f"{progid}\\shell", self.source_name)
            else:
                self.entries = []
        self._build_list()

    def action_toggle(self):
        """切换启用/禁用状态。"""
        entry = self._get_selected_entry()
        if entry is None:
            return
        new_state = not entry.enabled
        set_disabled(entry.reg_path, disabled=not new_state)
        entry.enabled = new_state
        self._build_list()

    async def action_delete_item(self):
        """删除菜单项（先备份后删除）。"""
        entry = self._get_selected_entry()
        if entry is None:
            return

        # 生成备份文件名
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_source = self.source_name.replace("\\", "_").replace("*", "Star")
        safe_name = entry.name.replace("\\", "_").replace("/", "_")
        filename = f"{timestamp}_{safe_source}_{safe_name}.reg"
        backup_path = os.path.join(self.backup_dir, filename)

        # 弹出确认对话框
        screen = ConfirmDeleteScreen(entry, filename)
        confirmed = await self.app.push_screen_wait(screen)

        if not confirmed:
            return

        # 1. 读取键树并生成备份
        try:
            key_tree = read_key_tree(entry.reg_path)
            reg_content = export_as_reg(key_tree, entry.reg_path)
            with open(backup_path, "w", encoding="utf-16-le") as f:
                f.write(reg_content)
        except Exception as exc:
            self.app.notify(
                f"备份写入失败，删除已取消: {exc}",
                severity="error",
            )
            return

        # 2. 执行删除
        try:
            delete_key_tree(entry.reg_path)
        except Exception as exc:
            self.app.notify(
                f"删除失败（备份文件已保留: {filename}）: {exc}",
                severity="error",
            )
            self._refresh_entries()
            return

        # 3. 成功
        self.app.notify(f"已删除，恢复文件: backups\\{filename}")
        self._refresh_entries()

    def action_refresh(self):
        self._refresh_entries()

    def action_quit(self):
        self.app.exit()


class MainScreen(Screen):
    """主屏幕 — 组合 Header/Footer 和菜单列表。"""

    def __init__(self, sources: dict[str, list[MenuEntry]],
                 title_extra: str, backup_dir: str):
        super().__init__()
        self.sources = sources
        self.title_extra = title_extra
        self.backup_dir = backup_dir
        self._containers: list[MenuListContainer] = []

    def compose(self) -> ComposeResult:
        yield Header()

        if len(self.sources) > 1:
            with TabbedContent():
                for source_name, entries in self.sources.items():
                    display_name = (
                        f"通用文件 {source_name}" if source_name == "*"
                        else f"{source_name} 专属"
                    )
                    with TabPane(display_name):
                        container = MenuListContainer(
                            entries, source_name,
                            self.title_extra, self.backup_dir,
                        )
                        self._containers.append(container)
                        yield container
        else:
            source_name, entries = next(iter(self.sources.items()))
            container = MenuListContainer(
                entries, source_name,
                self.title_extra, self.backup_dir,
            )
            self._containers.append(container)
            yield Label(
                f"右键菜单管理 — {source_name}"
                f" [dim]({self.title_extra})[/dim]    [共 {len(entries)} 项]"
            )
            yield container

        yield Footer()


class ContextMenuApp(App):
    """右键菜单管理 — Textual 主应用。"""

    CSS = """
    #confirm-dialog {
        padding: 2 4;
        border: solid red;
        background: $surface;
        width: 60;
        height: auto;
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("escape", "quit", "退出"),
    ]

    def __init__(self, sources: dict[str, list[MenuEntry]],
                 title_extra: str, backup_dir: str):
        super().__init__()
        self.sources = sources
        self.title_extra = title_extra
        self.backup_dir = backup_dir

    def on_mount(self):
        self.push_screen(MainScreen(self.sources, self.title_extra, self.backup_dir))

    def action_quit(self):
        self.exit()


def launch_tui(sources: dict[str, list[MenuEntry]],
               title_extra: str, backup_dir: str):
    """启动 TUI 应用。"""
    app = ContextMenuApp(sources, title_extra, backup_dir)
    app.run()
