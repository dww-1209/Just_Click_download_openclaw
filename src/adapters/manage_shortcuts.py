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
