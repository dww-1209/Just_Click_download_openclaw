# Windows 桌面快捷方式 + 开始菜单项 — 设计文档

**日期**：2026-05-21
**作者**：邓伟文 + Claude
**状态**：Approved（待用户最终签字）

## 1. 背景与目标

OpenClaw 一键安装器目前装完后，用户需要从 Applications / 开始菜单进入找 `OpenClaw 安装器.exe` → 等加载 → 点快速启动 → 等 Gateway 起来 → 浏览器打开。Windows 用户的常用心智路径是桌面图标 + 开始菜单搜索，缺这两个入口让"再次使用"流程比同类应用（VSCode / Chrome）多一步。

**目标**：为 Windows 用户在桌面 + 开始菜单创建指向安装器 .exe 的快捷方式，让用户可以双击桌面图标 / Win 键搜索直达。Mac 不做（Mac 用户的心智路径是 Spotlight / Launchpad / 程序坞，桌面快捷方式反而显得 Windows 味重）。

**非目标**：
- 不做 Mac 的 Finder alias 或 .command 脚本
- 不做"固定到任务栏"或开机自启
- 不做独立的 launcher 进程（快捷方式直接指向现有 .exe）
- 不做托盘 / 状态栏图标（已在前期讨论中砍掉）
- 不为快捷方式失效场景做兜底（用户挪 .exe 自负，沿用 Chrome / VSCode 的处理方式）

## 2. 设计决策汇总

| 决策点 | 选择 | 理由 |
|---|---|---|
| 平台范围 | 仅 Windows | Mac 用户不需要桌面图标 |
| 创建位置 | 桌面 + 开始菜单（双勾）| 业界主流做法，兼顾两类用户习惯 |
| 用户选择权 | 完成页两个独立 checkbox，默认都勾选 | 用户对桌面图标有母语级认知，给知情权不算"做选择题" |
| 创建时机 | 用户点"完成"按钮时统一执行 | 避免勾选反复带来的"创建-删除-创建"噪声 |
| 失败处理 | 不阻塞退出，仅写日志 | 快捷方式失败不应卡住用户主流程 |
| 快捷方式 target | `sys.executable`（当前运行的 .exe）| 在线版/离线版自动适配 |
| 死链兜底 | 不做 | 挪 .exe 是非常规操作，沿用 Windows 主流应用做法 |
| 图标 | 显式 `IconLocation = sys.executable` | 避免某些 Windows 版本对未指定 IconLocation 的渲染兜底问题 |
| 实现技术 | `pywin32` 的 `WScript.Shell` COM 接口 | 微软官方、几十年标准、零兼容性风险 |
| 卸载清理 | 同步删除并在卸载报告中明确列出 | 对称原则——装的时候告诉用户，卸的时候也告诉用户 |
| 测试策略 | 手工验证 + import smoke | 项目当前无 pytest 用例，不为单一功能新增测试基础设施 |

## 3. 模块与文件变更

### 3.1 新增文件

#### `src/adapters/manage_shortcuts.py`

放在 Adapters 层，符合"系统交互、平台差异"的层定义。

**对外暴露 API**：

```python
@dataclass
class ShortcutResult:
    """快捷方式创建/删除结果。

    创建场景下 desktop_ok=True 表示成功创建；
    删除场景下 desktop_ok=True 表示成功删除（包含"原本就不存在"的幂等成功）。
    Mac 平台所有字段均为 False，errors 为空。
    """
    desktop_ok: bool
    start_menu_ok: bool
    errors: list[str]


def windows_shortcut_paths() -> tuple[Path, Path]:
    """返回 (desktop_lnk_path, start_menu_lnk_path)。

    Mac 上调用返回任意值不应被使用（调用方应先判 is_windows）；
    建议实现内部直接 raise 或返回占位，避免误用。
    """


def create_shortcuts(desktop: bool, start_menu: bool) -> ShortcutResult:
    """创建桌面 + 开始菜单快捷方式。

    Mac 上直接返回空结果不抛异常。
    Windows 上失败的项目记入 errors，永不抛异常给调用方。
    """


def remove_shortcuts() -> ShortcutResult:
    """删除桌面 + 开始菜单快捷方式（幂等）。

    不存在视为成功（用户可能从未勾选过创建）。
    Mac 上直接返回空结果。
    """
```

**内部实现要点**：

- 顶部 `if not is_windows(): return ShortcutResult(False, False, [])` 卫兵
- 使用 `from win32com.client import Dispatch` 调 `WScript.Shell`
- 写 `.lnk` 时设置以下属性：
  - `Targetpath = sys.executable`
  - `IconLocation = sys.executable`
  - `WorkingDirectory = str(Path(sys.executable).parent)`
  - `Description = "OpenClaw 一键安装与启动"`
- 路径解析：**统一使用 `WScript.Shell.SpecialFolders` 让 Windows 自己解析**，避免 OneDrive 桌面重定向 / 多语言系统 / 自定义环境变量等边角问题：
  - 桌面：`Path(shell.SpecialFolders("Desktop")) / "OpenClaw.lnk"`
  - 开始菜单：`Path(shell.SpecialFolders("Programs")) / "OpenClaw.lnk"`
  - 不使用 `USERPROFILE` / `APPDATA` 环境变量直接拼路径
- 异常捕获：catch `OSError`、`Exception`（pywin32 抛的是 `pywintypes.com_error`，但为了不引入 import，统一用 `Exception` 兜底，把 `repr(e)` 写进 errors）

### 3.2 修改文件

#### `pyproject.toml`

在 `dependencies` 列表追加：

```toml
"pywin32>=308; platform_system == 'Windows'",
```

`platform_system == 'Windows'` 标记保证 Mac 的 `uv sync` 不会去拉这个包（Mac 没有 pywin32）。

#### `src/ui/show_startup.py`

`US06StartupPage` 类内部修改：

1. 在 `__init__` 里通过 `is_windows()` 卫兵决定是否创建两个 `QCheckBox`，Mac 上不创建（不是 hide，是不创建）。
2. UI 位置：日志区下方、底部按钮栏（"完成"按钮）上方。两个 checkbox 默认 `setChecked(True)`。
3. "完成"按钮 click 槽 `_on_finish_clicked`：
   ```python
   def _on_finish_clicked(self):
       if is_windows() and hasattr(self, "_chk_desktop"):
           desktop = self._chk_desktop.isChecked()
           start_menu = self._chk_start_menu.isChecked()
           if desktop or start_menu:
               result = create_shortcuts(desktop, start_menu)
               if not result.desktop_ok and desktop:
                   self._append_log("快捷方式创建失败（桌面）")
               if not result.start_menu_ok and start_menu:
                   self._append_log("快捷方式创建失败（开始菜单）")
               for err in result.errors:
                   self._append_log(f"  详情: {err}")
       self.finish_clicked.emit()
   ```
   失败不阻塞 `emit finish_clicked`，用户始终能正常退出。

#### `src/core/manage_openclaw.py`

`OpenClawManager.uninstall()` 方法内部追加一步（位置：删 wrapper 之后、清 PATH 之前）：

```python
# 步骤 N: 删除桌面 + 开始菜单快捷方式
self._log("正在删除快捷方式...")
result = remove_shortcuts()
if is_windows():
    self._log(
        "桌面快捷方式 — 已删除" if result.desktop_ok else "桌面快捷方式 — 跳过/失败"
    )
    self._log(
        "开始菜单项 — 已删除" if result.start_menu_ok else "开始菜单项 — 跳过/失败"
    )
# Mac 平台 result 全 False，无需输出
```

返回的 `UninstallReport` 数据结构需要追加两个字段（若已有 dataclass）：

```python
@dataclass
class UninstallReport:
    # ...既有字段...
    desktop_shortcut_removed: bool   # 仅 Windows 有意义
    start_menu_removed: bool          # 仅 Windows 有意义
```

#### `src/ui/show_uninstall_done.py`

`UninstallDonePage.set_success()` 与 `set_partial()` 的清单字符串：

- 仅 Windows 时插入两行（位置：在"命令行工具 — 已删除"之后、"Gateway 服务 — 已停止"之前）
- 通过传入 `desktop_shortcut_removed` 和 `start_menu_removed` 两个 bool 控制

```
OpenClaw 程序文件 — 已删除
配置文件 (含 API Key) — 已删除
命令行工具 — 已删除
桌面快捷方式 — 已删除         ← 仅 Windows
开始菜单项 — 已删除            ← 仅 Windows
Gateway 服务 — 已停止
```

set_partial 同样根据传入的 bool 决定是否在失败行里加这两条。

## 4. 数据流

### 4.1 创建流程（仅 Windows）

```
US06StartupPage._on_finish_clicked
  ├── 读 self._chk_desktop.isChecked() / self._chk_start_menu.isChecked()
  └── if any: create_shortcuts(desktop, start_menu)
       ├── 卫兵: not is_windows() → return ShortcutResult(False, False, [])
       ├── from win32com.client import Dispatch
       ├── shell = Dispatch("WScript.Shell")
       ├── for each lnk in [desktop, start_menu]:
       │     try: 创建 .lnk + 设 4 个属性 + save()
       │     except Exception as e: errors.append(repr(e))
       └── return ShortcutResult(...)
       
失败仅日志记录，不阻塞 finish_clicked.emit()
```

### 4.2 删除流程（仅 Windows 实际删，Mac no-op）

```
OpenClawManager.uninstall()
  └── remove_shortcuts()
       ├── 卫兵: not is_windows() → return 空 result
       ├── for each lnk in [desktop, start_menu]:
       │     if lnk.exists(): try unlink, except → errors.append
       │     else: 视为成功（幂等）
       └── return ShortcutResult(...)
       
结果传给 UI，set_success / set_partial 根据 ok 字段渲染清单
```

## 5. 边界与陷阱

| 场景 | 处理方式 |
|---|---|
| 用户挪走 .exe 后双击死链 | 不兜底，同 Chrome / VSCode 行为 |
| 杀软拦截 COM 创建 .lnk | catch Exception，写日志，主流程不阻塞 |
| 用户已有同名 OpenClaw.lnk（来自旧版安装器或同名应用）| 直接覆盖（`shortcut.save()` 行为）。后续若多版本共存需重新讨论 |
| OneDrive 桌面重定向 | 用 `WScript.Shell.SpecialFolders("Desktop")` 让 Windows 自己解析路径，避免硬拼 `USERPROFILE\Desktop` |
| 卸载时 .lnk 已被用户手动删除 | 视为成功（幂等）|
| 安装时未勾选 → 后悔想要 | 不提供事后补救入口，用户重跑安装器即可（小白友好） |
| Mac 误调用 create_shortcuts | 卫兵直接返回空结果，零副作用 |

## 6. 测试与验证

**Mac 验证**（开发机）：
1. `uv run python launch_installer.py` → 完成页**不显示** checkbox
2. `uv run python launch_uninstaller.py` → 卸载清单**不出现**两行新增
3. `uv run python -c "import launch_installer; import launch_installer_offline; import launch_uninstaller"` → 全部 OK

**Windows 验证**（依赖 Windows 同事）：
1. 跑在线安装器到完成页，看到两个默认勾选的 checkbox
2. 点"完成"→ 桌面出现 `OpenClaw.lnk`，开始菜单 `OpenClaw.lnk` 也出现
3. 双击桌面快捷方式 → 启动安装器（环境检测页 → 快速启动按钮可见）
4. 跑卸载器 → 卸载报告清单出现"桌面快捷方式 — 已删除"和"开始菜单项 — 已删除"
5. 桌面 + 开始菜单的 .lnk 都消失
6. 重复跑卸载器（幂等性）→ 不报错，清单同样显示已删除

**回归检查**（Windows + Mac）：
- 现有完成页其他元素（日志区、警告文字、完成按钮）位置不偏
- 现有卸载清单其他行的格式不变

## 7. 工作量估计

- `manage_shortcuts.py` 新增：约 80 行（含卫兵、错误处理、SpecialFolders 解析、注释）
- `show_startup.py` checkbox + 完成槽改造：约 30 行
- `manage_openclaw.py` uninstall 新增步骤：约 15 行
- `show_uninstall_done.py` 清单渲染：约 15 行
- `pyproject.toml`：1 行
- 总计：约 140 行新增代码

预估 0.5-1 天（含 Mac 自测 + 写文档 + commit）。Windows 真机验证另算。
