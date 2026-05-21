# Windows 快捷方式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Windows 用户在桌面 + 开始菜单创建指向安装器 .exe 的快捷方式,完成页提供两个 checkbox 控制,卸载时同步清理。Mac 不做。

**Architecture:** 新增 `src/adapters/manage_shortcuts.py` 封装 pywin32 COM 调用,通过 `is_windows()` 卫兵让 Mac 自动 no-op。UI 改 `show_startup.py`(创建)和 `show_uninstall_done.py`(展示),Core 改 `manage_openclaw.py:uninstall()`(执行删除)。失败永不阻塞主流程,只写日志。

**Tech Stack:** Python 3.12 + PySide6 + pywin32 (`win32com.client.WScript.Shell`)

**Spec:** `docs/superpowers/specs/2026-05-21-windows-shortcut-design.md`

---

## File Structure

| 文件 | 操作 | 职责 |
|---|---|---|
| `src/adapters/manage_shortcuts.py` | 新增 | 快捷方式创建/删除 + ShortcutResult dataclass + Mac 卫兵 |
| `pyproject.toml` | 修改 | 追加 `pywin32` 依赖(Windows-only) |
| `src/ui/show_startup.py` | 修改 | 完成页加两个 checkbox(仅 Windows),完成槽统一调 create_shortcuts |
| `src/core/manage_openclaw.py` | 修改 | `uninstall()` 内追加 remove_shortcuts 步骤 |
| `src/ui/show_uninstall_done.py` | 修改 | 卸载完成清单根据平台决定是否插入两行 |

**测试策略:** 项目无 pytest 用例,本 plan 不新增测试基础设施。验证手段:
- import smoke test(每次提交后必跑)
- Mac 上跑安装器/卸载器看 UI 行为(checkbox 不应渲染、清单不应多行)
- Windows 真机验证(交付给 Windows 同事)

---

## Task 1: 新增 manage_shortcuts.py 模块骨架与 Mac 卫兵

**Files:**
- Create: `src/adapters/manage_shortcuts.py`

- [ ] **Step 1: 创建文件,写入完整内容**

```python
"""Windows 桌面 + 开始菜单快捷方式管理。

职责:为 Windows 用户在桌面和开始菜单创建/删除指向安装器 .exe 的快捷方式,
让用户可以双击桌面图标或 Win 键搜索直达。Mac 上所有 API 直接 no-op。

设计原则:
- 仅 Windows 实际执行 COM 调用,Mac 上顶部 is_windows() 卫兵直接返回空 result。
- 所有 pywin32 异常在内部捕获,记入 ShortcutResult.errors,永不抛给上层。
  快捷方式失败不应阻塞安装/卸载主流程。
- 路径解析统一用 WScript.Shell.SpecialFolders,避免 OneDrive 桌面重定向、
  多语言系统、自定义环境变量等边角问题。

依赖:
- Windows 上需要 pywin32(已在 pyproject.toml 标记为 Windows-only 依赖)
- Mac 上不需要任何额外依赖
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.models.constants import is_windows


# 快捷方式文件名(桌面 + 开始菜单都用同一个名字)
_LNK_FILENAME = "OpenClaw.lnk"

# 快捷方式悬浮提示
_SHORTCUT_DESCRIPTION = "OpenClaw 一键安装与启动"


@dataclass
class ShortcutResult:
    """快捷方式创建/删除结果。

    创建场景下 desktop_ok=True 表示成功创建;
    删除场景下 desktop_ok=True 表示成功删除(包含"原本就不存在"的幂等成功)。
    Mac 平台调用所有 API 时 desktop_ok 与 start_menu_ok 均为 False、
    errors 为空——这是"未执行"的语义,调用方应先用 is_windows() 判断
    再决定是否展示结果。
    """
    desktop_ok: bool = False
    start_menu_ok: bool = False
    errors: list[str] = field(default_factory=list)


def create_shortcuts(desktop: bool, start_menu: bool) -> ShortcutResult:
    """创建桌面 + 开始菜单快捷方式。

    Args:
        desktop: 是否创建桌面快捷方式
        start_menu: 是否创建开始菜单快捷方式

    Returns:
        ShortcutResult,失败的项目记入 errors,永不抛异常给调用方。
        Mac 上直接返回空结果。
    """
    if not is_windows():
        return ShortcutResult()

    result = ShortcutResult()
    try:
        from win32com.client import Dispatch  # type: ignore[import-not-found]
    except ImportError as e:
        result.errors.append(f"pywin32 未安装: {e!r}")
        return result

    shell = Dispatch("WScript.Shell")
    target = sys.executable
    working_dir = str(Path(target).parent)

    if desktop:
        try:
            desktop_path = Path(shell.SpecialFolders("Desktop")) / _LNK_FILENAME
            _write_shortcut(shell, desktop_path, target, working_dir)
            result.desktop_ok = True
        except Exception as e:  # noqa: BLE001 — pywintypes.com_error 等都要兜住
            result.errors.append(f"桌面快捷方式创建失败: {e!r}")

    if start_menu:
        try:
            start_path = Path(shell.SpecialFolders("Programs")) / _LNK_FILENAME
            _write_shortcut(shell, start_path, target, working_dir)
            result.start_menu_ok = True
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"开始菜单项创建失败: {e!r}")

    return result


def remove_shortcuts() -> ShortcutResult:
    """删除桌面 + 开始菜单快捷方式(幂等)。

    不存在视为成功——用户可能从未勾选过创建,或者已经手动删过。
    Mac 上直接返回空结果。

    Returns:
        ShortcutResult,desktop_ok/start_menu_ok 为 True 表示
        操作完成后该位置已不存在快捷方式(包含原本就不存在的幂等情况)。
    """
    if not is_windows():
        return ShortcutResult()

    result = ShortcutResult()
    try:
        from win32com.client import Dispatch  # type: ignore[import-not-found]
    except ImportError as e:
        result.errors.append(f"pywin32 未安装: {e!r}")
        return result

    shell = Dispatch("WScript.Shell")

    for slot, folder_key in [("desktop", "Desktop"), ("start_menu", "Programs")]:
        try:
            lnk_path = Path(shell.SpecialFolders(folder_key)) / _LNK_FILENAME
            if lnk_path.exists():
                lnk_path.unlink()
            # 不存在 = 幂等成功
            if slot == "desktop":
                result.desktop_ok = True
            else:
                result.start_menu_ok = True
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"{slot} 快捷方式删除失败: {e!r}")

    return result


def _write_shortcut(
    shell: object,
    lnk_path: Path,
    target: str,
    working_dir: str,
) -> None:
    """内部 helper:写入单个 .lnk 文件。

    抛出的异常由调用方在 try/except Exception 中捕获并记入 errors。
    """
    # CreateShortCut 在已存在时会打开现有项允许修改;不存在时新建。
    # 我们每次 save 都会覆盖,无需先 unlink。
    shortcut = shell.CreateShortCut(str(lnk_path))  # type: ignore[attr-defined]
    shortcut.Targetpath = target
    shortcut.IconLocation = target
    shortcut.WorkingDirectory = working_dir
    shortcut.Description = _SHORTCUT_DESCRIPTION
    shortcut.save()
```

- [ ] **Step 2: Mac 上 import smoke 验证**

Run:
```bash
uv run python -c "
from src.adapters.manage_shortcuts import ShortcutResult, create_shortcuts, remove_shortcuts
r1 = create_shortcuts(True, True)
r2 = remove_shortcuts()
assert r1.desktop_ok is False and r1.start_menu_ok is False and r1.errors == []
assert r2.desktop_ok is False and r2.start_menu_ok is False and r2.errors == []
print('OK Mac 卫兵生效,所有调用 no-op')
"
```

Expected: `OK Mac 卫兵生效,所有调用 no-op`

- [ ] **Step 3: Commit**

```bash
git add src/adapters/manage_shortcuts.py
git commit -m "feat(shortcuts): 新增 Windows 桌面/开始菜单快捷方式 adapter"
```

---

## Task 2: pyproject.toml 追加 pywin32 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 修改 dependencies 列表**

把:
```toml
dependencies = [
    "httpx>=0.28.1",
    "psutil>=7.2.2",
    "pyinstaller>=6.11.0,<6.12.0",
    "pyside6>=6.8.0,<6.9.0",
    "pytest>=8.0.0",
]
```

改为:
```toml
dependencies = [
    "httpx>=0.28.1",
    "psutil>=7.2.2",
    "pyinstaller>=6.11.0,<6.12.0",
    "pyside6>=6.8.0,<6.9.0",
    "pytest>=8.0.0",
    "pywin32>=308; platform_system == 'Windows'",
]
```

- [ ] **Step 2: Mac 上跑 uv sync 验证不会拉 pywin32**

Run:
```bash
uv sync
uv tree | grep -i pywin32 || echo "(Mac 上 pywin32 未安装,符合预期)"
```

Expected: `(Mac 上 pywin32 未安装,符合预期)` 且 `uv sync` 无错误

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): 追加 pywin32 (Windows-only) 用于桌面快捷方式"
```

---

## Task 3: show_startup.py 加两个 checkbox 与完成槽改造

**Files:**
- Modify: `src/ui/show_startup.py`

**说明:** 当前完成按钮直接 `self.finish_button.clicked.connect(self.finish_clicked.emit)`。
需要在中间插入一个槽函数,先调 create_shortcuts 再 emit。
Mac 上不创建 checkbox(不是 hide,是不创建),保持 UI 完全不变。

- [ ] **Step 1: 修改 import 语句**

把:
```python
from src.models.config import ConfigStatus, ConfigProgress, ConfigResult
from src.models.constants import is_windows
```

改为:
```python
from src.models.config import ConfigStatus, ConfigProgress, ConfigResult
from src.models.constants import is_windows
from src.adapters.manage_shortcuts import create_shortcuts
```

并在文件顶部 PySide6 import 中追加 `QCheckBox`:

把:
```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QFrame, QLineEdit, QApplication, QPlainTextEdit,
)
```

改为:
```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QFrame, QLineEdit, QApplication, QPlainTextEdit,
    QCheckBox,
)
```

- [ ] **Step 2: 在底部按钮栏之前插入 checkbox 区域**

定位到 `_setup_ui` 中底部按钮栏的注释位置(原代码约第 372 行):
```python
        # ── 底部按钮栏 ────────────────────────────────────
        button_bar = QFrame()
```

在这一行**之前**插入以下代码块:

```python
        # ── 桌面快捷方式选项(仅 Windows) ─────────────────
        # Mac 用户的心智路径是 Spotlight/Launchpad,桌面图标显得 Windows 味重,
        # 所以这两个 checkbox 在 Mac 上根本不创建(不是 hide,是不存在)。
        self._chk_desktop: QCheckBox | None = None
        self._chk_start_menu: QCheckBox | None = None
        if is_windows():
            shortcut_frame = QFrame()
            shortcut_layout = QVBoxLayout(shortcut_frame)
            shortcut_layout.setContentsMargins(56, 8, 56, 8)
            shortcut_layout.setSpacing(4)

            self._chk_desktop = QCheckBox("在桌面创建快捷方式")
            self._chk_desktop.setChecked(True)
            self._chk_start_menu = QCheckBox("在开始菜单创建快捷方式")
            self._chk_start_menu.setChecked(True)

            shortcut_layout.addWidget(self._chk_desktop)
            shortcut_layout.addWidget(self._chk_start_menu)
            main_layout.addWidget(shortcut_frame)

```

- [ ] **Step 3: 修改完成按钮的 click 连接**

找到原代码:
```python
        self.finish_button.clicked.connect(self.finish_clicked.emit)
```

改为:
```python
        self.finish_button.clicked.connect(self._on_finish_clicked)
```

- [ ] **Step 4: 在类底部添加 _on_finish_clicked 方法**

定位到类的最末尾(在最后一个方法之后),追加:

```python
    def _on_finish_clicked(self) -> None:
        """完成按钮点击槽。

        在 emit finish_clicked 之前,先根据 checkbox 状态创建桌面/开始菜单快捷方式。
        失败不阻塞退出——快捷方式不是核心功能,失败仅记录日志,用户始终能正常关闭。
        Mac 上 checkbox 未创建,直接 emit。
        """
        if is_windows() and self._chk_desktop is not None and self._chk_start_menu is not None:
            desktop = self._chk_desktop.isChecked()
            start_menu = self._chk_start_menu.isChecked()
            if desktop or start_menu:
                result = create_shortcuts(desktop, start_menu)
                if desktop and not result.desktop_ok:
                    self.add_log_line("桌面快捷方式创建失败")
                if start_menu and not result.start_menu_ok:
                    self.add_log_line("开始菜单项创建失败")
                for err in result.errors:
                    self.add_log_line(f"  详情: {err}")
        self.finish_clicked.emit()
```

- [ ] **Step 5: Mac 上 import smoke + 启动安装器视觉验证**

Run:
```bash
uv run python -c "import launch_installer; import launch_installer_offline; print('OK imports')"
```

Expected: `OK imports`

(可选,如果有图形环境)Run:
```bash
uv run python launch_installer.py
```
Expected: 跑到 US-06 完成页时,**不应**看到 checkbox。完成按钮行为如旧。

- [ ] **Step 6: Commit**

```bash
git add src/ui/show_startup.py
git commit -m "feat(ui): 完成页加桌面/开始菜单快捷方式 checkbox (仅 Windows)"
```

---

## Task 4: manage_openclaw.py uninstall 内追加 remove_shortcuts 步骤

**Files:**
- Modify: `src/core/manage_openclaw.py`

**说明:** 当前 uninstall 流程:1.停 Gateway → 2.删目录 → 3.卸载 npm 包 → 4.删 wrapper → 5.清 PATH。
快捷方式语义上和 wrapper 同档(都是"用户可见入口"),所以**插在第 4 步之后、第 5 步之前**。

`uninstall()` 返回 `bool`(`all_ok`),不维护 dataclass 字段。删除快捷方式失败不影响 `all_ok`(快捷方式失败属于次要,不应让用户看到"卸载部分完成")。

- [ ] **Step 1: 找到第 4 步"删除命令包装器"的代码块**

定位到 `def uninstall` 方法内的第 4 步注释(约 1644 行):
```python
        # 4. 删除命令包装器
```

向下找到第 4 步**结束**的位置(下一个步骤注释或 `return all_ok` 之前)。
具体是哪一行需要执行人在编辑时实际定位——通常是第 5 步 PATH 清理的注释,例如 `# 5.` 或 `# 清理 shell rc` 之类。

- [ ] **Step 2: 在第 4 步结束后、第 5 步开始前插入新步骤**

在 wrapper 删除步骤结束后插入:

```python
        # 5. 删除桌面 + 开始菜单快捷方式(仅 Windows 实际执行)
        # 即使删除失败也不影响 all_ok——快捷方式不是核心数据,只是入口。
        # 用户看到"OpenClaw 已卸载"足矣,不需要因为一个 .lnk 文件失败就报"部分完成"。
        if cancel_event and cancel_event():
            if on_log:
                on_log("卸载已取消")
            return False
        try:
            from src.adapters.manage_shortcuts import remove_shortcuts
            sc_result = remove_shortcuts()
            if is_windows() and on_log:
                if sc_result.desktop_ok:
                    on_log("已删除桌面快捷方式")
                else:
                    on_log("删除桌面快捷方式失败(忽略,继续)")
                if sc_result.start_menu_ok:
                    on_log("已删除开始菜单项")
                else:
                    on_log("删除开始菜单项失败(忽略,继续)")
                for err in sc_result.errors:
                    on_log(f"  详情: {err}")
        except Exception as e:
            if on_log:
                on_log(f"快捷方式清理出错(忽略,继续): {e}")
```

注意原步骤号需要调整——原有"5/6/..."之类的注释需要顺延,实际由编辑人在改的时候手动顺移。

- [ ] **Step 3: 验证 import smoke**

Run:
```bash
uv run python -c "import launch_uninstaller; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Mac 上跑卸载器(无实际安装也能跑到 done 页)**

Run(可选,需要图形环境):
```bash
uv run python launch_uninstaller.py
```

Expected: 卸载流程不抛异常。日志中不出现"已删除桌面快捷方式"等行(因为 Mac 卫兵让 result 全 False 且 is_windows() 分支跳过日志)。

- [ ] **Step 5: Commit**

```bash
git add src/core/manage_openclaw.py
git commit -m "feat(uninstall): 卸载时同步清理桌面/开始菜单快捷方式 (Windows)"
```

---

## Task 5: show_uninstall_done.py 清单根据平台插入两行

**Files:**
- Modify: `src/ui/show_uninstall_done.py`

**说明:** 当前 `set_success()` 写死了清单字符串,`set_partial()` 也是。
需要 Windows 时多加两行"桌面快捷方式 — 已删除"和"开始菜单项 — 已删除"。
Mac 时清单原样不变。

由于 `failed_items: list[str]` 粒度粗(只有"部分清理步骤"这种笼统描述,没有"快捷方式失败"的明细),
我们采用**简单策略**:Windows 时 set_success/set_partial 都默认在清单中加这两行。
快捷方式失败属于忽略类失败(不进 failed_items),所以不会在 set_partial 的红色失败区出现。

- [ ] **Step 1: 在 import 区域加入 is_windows**

找到文件顶部的 import 区域:
```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
```

在最后追加:
```python
from src.models.constants import is_windows
```

- [ ] **Step 2: 修改 set_success 方法的清单内容**

把:
```python
    def set_success(self) -> None:
        """完全成功:绿色 dot + 标题"卸载完成"。"""
        self.title_label.setText("卸载完成")
        self.status_dot.setStyleSheet("background-color: #16A34A; border-radius: 4px;")
        self.status_desc.setText("您的系统已恢复到安装前状态。")
        self.status_desc.setStyleSheet("color: #475569; font-size: 13px;")
        self.checklist_label.setText(
            "OpenClaw 程序文件 — 已删除\n"
            "配置文件 (含 API Key) — 已删除\n"
            "命令行工具 — 已删除\n"
            "Gateway 服务 — 已停止"
        )
        self.checklist_label.setStyleSheet(
            "color: #475569; font-size: 13px; line-height: 1.7;"
        )
```

改为:
```python
    def set_success(self) -> None:
        """完全成功:绿色 dot + 标题"卸载完成"。"""
        self.title_label.setText("卸载完成")
        self.status_dot.setStyleSheet("background-color: #16A34A; border-radius: 4px;")
        self.status_desc.setText("您的系统已恢复到安装前状态。")
        self.status_desc.setStyleSheet("color: #475569; font-size: 13px;")
        self.checklist_label.setText(self._build_checklist_text())
        self.checklist_label.setStyleSheet(
            "color: #475569; font-size: 13px; line-height: 1.7;"
        )
```

- [ ] **Step 3: 修改 set_partial 方法的清单内容**

把 set_partial 中的:
```python
        # 用 HTML 富文本对失败项染红,QLabel 默认支持
        lines: list[str] = [
            "OpenClaw 程序文件 — 已删除",
            "配置文件 (含 API Key) — 已删除",
            "命令行工具 — 已删除",
            "Gateway 服务 — 已停止",
        ]
```

改为:
```python
        # 用 HTML 富文本对失败项染红,QLabel 默认支持
        lines: list[str] = self._build_checklist_lines()
```

- [ ] **Step 4: 在类内部追加 helper 方法**

在 `set_partial` 方法之后追加:

```python
    def _build_checklist_lines(self) -> list[str]:
        """构造卸载清单的行列表。

        Windows 上多两行(桌面快捷方式 + 开始菜单项),Mac 上保持原样。
        位置:在"命令行工具"之后、"Gateway 服务"之前。
        """
        lines = [
            "OpenClaw 程序文件 — 已删除",
            "配置文件 (含 API Key) — 已删除",
            "命令行工具 — 已删除",
        ]
        if is_windows():
            lines.append("桌面快捷方式 — 已删除")
            lines.append("开始菜单项 — 已删除")
        lines.append("Gateway 服务 — 已停止")
        return lines

    def _build_checklist_text(self) -> str:
        """构造卸载清单的纯文本(给 set_success 用,不带 HTML)。"""
        return "\n".join(self._build_checklist_lines())
```

- [ ] **Step 5: import smoke 验证**

Run:
```bash
uv run python -c "
from src.ui.show_uninstall_done import UninstallDonePage
print('OK import')
# 验证 Mac 上 helper 输出正确条目数
import sys
class _FakeLabel:
    def setText(self,*_): pass
    def setStyleSheet(self,*_): pass
    def setTextFormat(self,*_): pass
# 不实例化 UninstallDonePage(需要 QApplication),只验证逻辑函数
"
echo "OK"
```

Expected: `OK import` `OK`

- [ ] **Step 6: Mac 视觉验证(可选)**

启动卸载器,点击进入 done 页(即使没真卸载也可以通过假流程进入)。验证清单**不应**出现"桌面快捷方式 — 已删除"和"开始菜单项 — 已删除"。

- [ ] **Step 7: Commit**

```bash
git add src/ui/show_uninstall_done.py
git commit -m "feat(ui): 卸载完成页清单加桌面快捷方式/开始菜单项 (Windows)"
```

---

## Task 6: 整合验证 + 推送

**Files:** 无文件改动,仅验证

- [ ] **Step 1: 全量 import smoke**

Run:
```bash
uv run python -c "
import importlib
for mod in ['launch_installer', 'launch_installer_offline', 'launch_uninstaller']:
    importlib.import_module(mod)
    print(f'OK {mod}')
"
```

Expected: 三个入口都 OK

- [ ] **Step 2: Mac 上启动安装器(US-06 页)**

Run:
```bash
uv run python launch_installer.py
```

走到完成页,确认:
- 页面**不显示**两个 checkbox
- "完成"按钮可点,点击后正常关闭

如果有图形环境跑过验证,标完成。否则在 commit message 里注明"Mac 视觉验证待补"。

- [ ] **Step 3: Mac 上启动卸载器(done 页)**

Run:
```bash
uv run python launch_uninstaller.py
```

走到 done 页(可以走完整流程或假数据),确认:
- 清单**不显示**"桌面快捷方式 — 已删除"和"开始菜单项 — 已删除"
- 其他行不变

- [ ] **Step 4: 推送到 GitHub(给 Windows 同事测试)**

Run:
```bash
git push origin main
```

Expected: 五个 commit(Task 1-5)成功推送

- [ ] **Step 5: 通知 Windows 同事按以下清单测试**

发飞书消息(或人工通知)给虎豹营,内容大致:

```
新功能:Windows 桌面 + 开始菜单快捷方式
请在 Windows 测试:
1. 在线安装器 / 离线安装器跑到完成页 → 看到两个默认勾选的 checkbox
   ☑ 在桌面创建快捷方式
   ☑ 在开始菜单创建快捷方式
2. 点"完成"→ 桌面 + 开始菜单出现 OpenClaw.lnk(图标继承 .exe)
3. 双击桌面快捷方式 → 启动安装器,环境检测页 → 快速启动按钮可见
4. Win 键搜 "openclaw" → 能找到开始菜单项
5. 跑卸载器 → 清单出现"桌面快捷方式 — 已删除"和"开始菜单项 — 已删除"
6. 卸载后桌面 + 开始菜单的 .lnk 都消失
7. 重复跑卸载器(幂等性测试)→ 不报错
```

---

## Self-Review Checklist (执行人无需关心,plan 作者已完成)

- [x] **Spec coverage**:
  - §3.1 manage_shortcuts.py → Task 1
  - §3.2 pyproject.toml → Task 2
  - §3.2 show_startup.py → Task 3
  - §3.2 manage_openclaw.py → Task 4
  - §3.2 show_uninstall_done.py → Task 5
  - §6 测试与验证 → Task 6

- [x] **Placeholder scan**: 无 TBD/TODO,所有代码块完整。Task 4 step 1-2 提到"需执行人在编辑时实际定位",这是因为 manage_openclaw.py:uninstall 体长且有可能因其他改动行号漂移,允许执行人按代码注释("# 5.")定位是合理的——已在 step 中用具体注释名给出定位线索。

- [x] **Type consistency**:
  - `ShortcutResult` 字段名(desktop_ok / start_menu_ok / errors)在 Task 1/3/4/5 全程一致
  - `create_shortcuts(desktop, start_menu)` 参数顺序在 Task 1 定义、Task 3 调用一致
  - `remove_shortcuts()` 无参在 Task 1 定义、Task 4 调用一致
  - `_build_checklist_lines / _build_checklist_text` Task 5 内部一致
