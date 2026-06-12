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
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Footer, ListView, ListItem, Label,
    TabbedContent, TabPane,
)

from menu_scanner import MenuEntry
from registry_ops import (
    set_disabled, read_key_tree, delete_key_tree, export_as_reg,
)
from log_utils import write_log


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

    ListView 保持不变；左/右方向键控制子菜单项的展开与收回。
    """

    BINDINGS = [
        Binding("space", "toggle", "启用/禁用"),
        Binding("delete", "delete_item", "删除"),
        Binding("r", "refresh", "刷新"),
        Binding("right", "expand", "展开子菜单", show=False),
        Binding("left", "collapse", "收回子菜单", show=False),
        Binding("escape", "quit", "退出"),
    ]

    def __init__(self, entries: list[MenuEntry], source_name: str,
                 title_extra: str, backup_dir: str,
                 argv: list[str] | None = None, **kwargs):
        self._target_path: str | None = kwargs.pop("target_path", None)
        super().__init__(**kwargs)
        self.entries = entries
        self.source_name = source_name
        self.title_extra = title_extra
        self.backup_dir = backup_dir
        self._argv = argv
        self._list_view: ListView | None = None
        self._expanded: set[str] = set()

    def on_mount(self):
        self._build_list()

    def on_show(self):
        if self._list_view is not None:
            self._list_view.focus()

    def _visible_entries(self) -> list[MenuEntry]:
        """当前可见条目：顶层 + 已展开父级的直属子级。"""
        result: list[MenuEntry] = []
        for e in self.entries:
            parts = e.display_name.split(" ▸ ")
            if len(parts) == 1:
                result.append(e)
                continue
            # 所有直属祖先的 display_name 前缀都在 _expanded 中才可见
            visible = True
            for d in range(1, len(parts)):
                prefix = " ▸ ".join(parts[:d])
                if prefix not in self._expanded:
                    visible = False
                    break
            if visible:
                result.append(e)
        return result

    def _has_children(self, entry: MenuEntry) -> bool:
        prefix = entry.display_name + " ▸ "
        return any(e.display_name.startswith(prefix) for e in self.entries)

    def _build_list(self):
        if self._list_view is not None:
            try:
                self._list_view.remove()
            except Exception:
                pass
            self._list_view = None

        visible = self._visible_entries()
        items = []
        for e in visible:
            depth = e.display_name.count(" ▸ ")
            indent = "    " * depth
            expand_hint = "▸ " if self._has_children(e) and e.display_name not in self._expanded else ""
            status_icon = "●" if e.enabled else "○"
            status_text = "已启用" if e.enabled else "已禁用"
            line2 = f"    {expand_hint}{status_text}"
            if e.hidden_reason:
                line2 += f"    [dim][{e.hidden_reason}][/dim]"
            cmd = e.command if e.command else "（由 Shell 扩展实现）"
            reg_info = f"    注册表: HKCR\\{e.reg_path}" if e.reg_path else "    （由 Shell 扩展动态提供）"
            # 取最后一段作为简短显示名
            short_name = e.display_name.split(" ▸ ")[-1]
            items.append(ListItem(
                Label(
                    f"{indent}{status_icon} [bold]{short_name}[/bold]\n"
                    f"{line2}\n"
                    f"{reg_info}\n"
                    f"    命令: {cmd}"
                )
            ))
        self._list_view = ListView(*items)
        self.mount(self._list_view)
        self._list_view.focus()

    def _get_selected_entry(self) -> MenuEntry | None:
        if self._list_view is None or self._list_view.index is None:
            return None
        visible = self._visible_entries()
        idx = self._list_view.index
        if 0 <= idx < len(visible):
            return visible[idx]
        return None

    def action_expand(self):
        """右键：展开当前选中项的直属子菜单。"""
        entry = self._get_selected_entry()
        if entry is None:
            return
        if self._has_children(entry):
            self._expanded.add(entry.display_name)
            self._build_list()

    def action_collapse(self):
        """左键：收起当前选中项的子菜单；若已是叶子则跳回父级。"""
        entry = self._get_selected_entry()
        if entry is None:
            return

        if entry.display_name in self._expanded:
            self._expanded.discard(entry.display_name)
            self._build_list()
            return

        if " ▸ " in entry.display_name:
            # 返回父级
            parent = entry.display_name.rsplit(" ▸ ", 1)[0]
            visible = self._visible_entries()
            for i, e in enumerate(visible):
                if e.display_name == parent:
                    self._list_view.index = i
                    break

    def _refresh_entries(self):
        """重新扫描并刷新列表，有 target_path 时走完整 COM 扫描。"""
        if self._target_path and self.source_name != "Directory\\Background":
            from menu_scanner import scan_file_menus, scan_directory_menus
            if self.source_name == "Directory":
                sources = scan_directory_menus(self._target_path)
            else:
                sources = scan_file_menus(self._target_path)
            self.entries = sources.get(self.source_name, [])
        else:
            from menu_scanner import scan_entries, scan_ext_menus, scan_shellex_handlers
            if self.source_name == "*":
                self.entries = scan_entries("*\\shell", "*")
            elif self.source_name == "Directory":
                self.entries = scan_entries("Directory\\shell", "Directory")
            elif self.source_name == "Directory\\Background":
                self.entries = scan_entries("Directory\\Background\\shell", "Directory\\Background")
            elif self.source_name == "Shell 扩展":
                # 静态回退时重建 shellex 条目；有 target_path 则走上方完整扫描
                pass
            else:
                self.entries = scan_ext_menus(self.source_name)
        self._build_list()

    def action_toggle(self):
        """切换启用/禁用状态。"""
        entry = self._get_selected_entry()
        if entry is None:
            return
        if not entry.reg_path:
            self.app.notify(
                "此菜单项由 Shell 扩展动态生成，无法通过注册表启用/禁用",
                severity="warning",
            )
            return
        new_state = not entry.enabled
        set_disabled(entry.reg_path, disabled=not new_state)
        entry.enabled = new_state
        write_log(f"{'启用' if new_state else '禁用'}: HKCR\\{entry.reg_path}")
        self._build_list()

    def action_delete_item(self):
        """删除菜单项 — 入口，将实际逻辑交给 Worker 执行。"""
        entry = self._get_selected_entry()
        if entry is None:
            return
        if not entry.reg_path:
            self.app.notify(
                "此菜单项由 Shell 扩展动态生成，没有对应的注册表路径，无法删除",
                severity="warning",
            )
            return
        self._do_delete(entry)

    @work
    async def _do_delete(self, entry: MenuEntry):
        """Worker: 删除菜单项（先备份后删除）。"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            safe_source = self.source_name.replace("\\", "_").replace("*", "Star")
            safe_name = entry.name.replace("\\", "_").replace("/", "_")
            filename = f"{timestamp}_{safe_source}_{safe_name}.reg"
            backup_path = os.path.join(self.backup_dir, filename)

            screen = ConfirmDeleteScreen(entry, filename)
            confirmed = await self.app.push_screen_wait(screen)

            if not confirmed:
                return

            # 1. 读取键树并生成备份
            try:
                key_tree = read_key_tree(entry.reg_path)
                reg_content = export_as_reg(key_tree, entry.reg_path)
                with open(backup_path, "w", encoding="utf-16", newline="") as f:
                    f.write(reg_content)
            except OSError as exc:
                write_log(f"备份失败: HKCR\\{entry.reg_path}, 错误: {exc}")
                self.app.notify(
                    f"备份写入失败，删除已取消: {exc}",
                    severity="error",
                )
                return

            # 2. 执行删除（启动时已提权，此处无需再提权）
            try:
                delete_key_tree(entry.reg_path)
            except OSError as exc:
                write_log(f"删除失败: HKCR\\{entry.reg_path}, 错误: {exc}")
                self.app.notify(
                    f"删除失败（备份文件已保留: {filename}）: {exc}",
                    severity="error",
                )
                self._refresh_entries()
                return

            # 3. 成功
            write_log(f"删除: HKCR\\{entry.reg_path}, 备份: {filename}")
            self.app.notify(f"已删除，恢复文件: backups\\{filename}")
            self._refresh_entries()
        except Exception:
            import traceback
            write_log("删除操作崩溃，详见 crash_delete.log")
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "crash_delete.log"), "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            raise

    def action_refresh(self):
        write_log(f"刷新菜单: {self.source_name}")
        self._refresh_entries()

    def action_quit(self):
        self.app.exit()


class MainScreen(Screen):
    """主屏幕 — 组合 Header/Footer 和菜单列表。"""

    BINDINGS = [
        Binding("tab", "switch_tab", "切换标签", show=False),
    ]

    def __init__(self, sources: dict[str, list[MenuEntry]],
                 title_extra: str, backup_dir: str,
                 argv: list[str] | None = None,
                 target_path: str | None = None):
        super().__init__()
        self.sources = sources
        self.title_extra = title_extra
        self.backup_dir = backup_dir
        self._argv = argv
        self._target_path = target_path
        self._containers: list[MenuListContainer] = []

    def compose(self) -> ComposeResult:
        yield Label("[bold reverse] 右键菜单管理 — ContextMenuApp [/bold reverse]")

        if len(self.sources) > 1:
            with TabbedContent():
                for source_name, entries in self.sources.items():
                    display_name = (
                        "Shell 扩展" if source_name == "Shell 扩展"
                        else f"通用文件 {source_name}" if source_name == "*"
                        else f"{source_name} 专属"
                    )
                    with TabPane(display_name):
                        container = MenuListContainer(
                            entries, source_name,
                            self.title_extra, self.backup_dir,
                            argv=self._argv,
                            target_path=self._target_path,
                        )
                        self._containers.append(container)
                        yield container
        else:
            source_name, entries = next(iter(self.sources.items()))
            container = MenuListContainer(
                entries, source_name,
                self.title_extra, self.backup_dir,
                argv=self._argv,
                target_path=self._target_path,
            )
            self._containers.append(container)
            yield Label(
                f"右键菜单管理 — {source_name}"
                f" [dim]({self.title_extra})[/dim]    [共 {len(entries)} 项]"
            )
            yield container

        yield Footer()

    def action_switch_tab(self):
        """Tab 键直接切换到下一个标签页。"""
        try:
            tabs = self.query_one(TabbedContent)
        except Exception:
            return
        panes = list(self.query(TabPane))
        if len(panes) <= 1:
            return
        active = tabs.active
        for i, pane in enumerate(panes):
            if pane.id == active:
                next_pane = panes[(i + 1) % len(panes)]
                tabs.active = next_pane.id
                return


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

    ListView {
        padding: 0 1;
    }
    ListView > ListItem {
        padding: 0 1;
    }
    ListView > ListItem > Label {
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "退出"),
    ]

    def __init__(self, sources: dict[str, list[MenuEntry]],
                 title_extra: str, backup_dir: str,
                 argv: list[str] | None = None,
                 target_path: str | None = None):
        super().__init__()
        self.sources = sources
        self.title_extra = title_extra
        self.backup_dir = backup_dir
        self._argv = argv
        self._target_path = target_path

    def on_mount(self):
        self.push_screen(MainScreen(self.sources, self.title_extra,
                                    self.backup_dir, self._argv,
                                    target_path=self._target_path))

    def action_quit(self):
        self.exit()


def launch_tui(sources: dict[str, list[MenuEntry]],
               title_extra: str, backup_dir: str,
               argv: list[str] | None = None,
               target_path: str | None = None):
    """启动 TUI 应用。"""
    import sys as _sys, traceback as _tb

    tool_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(tool_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    _orig_hook = _sys.excepthook

    def _crash_hook(exc_type, exc_value, exc_tb):
        log_path = os.path.join(log_dir, "crash.log")
        with open(log_path, "w", encoding="utf-8") as f:
            _tb.print_exception(exc_type, exc_value, exc_tb, file=f)
        _tb.print_exception(exc_type, exc_value, exc_tb)
        _orig_hook(exc_type, exc_value, exc_tb)

    _sys.excepthook = _crash_hook

    app = ContextMenuApp(sources, title_extra, backup_dir, argv,
                         target_path=target_path)
    app.run()
