"""
OpenClaw Launcher 主入口（Composition Root）

提供 3 页启动流程：首页 → Provider 配置 → 启动 Gateway。
与安装器不同，Launcher 不包含安装逻辑，仅负责配置和启动已安装的 OpenClaw。

设计要点:
- 本文件为唯一允许跨层导入的装配器层（Composition Root）。
- 复用安装器的所有 UI 页面和 adapter/core 实现。
- Launcher 包体积约 40MB，远小于离线安装器的 400MB+。
  用户安装完成后可删除安装器，仅保留启动器。
"""

import sys
from pathlib import Path

# 确保 src/ 在模块搜索路径中（无论从哪里启动）
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 平台守卫：仅支持 Windows / macOS
if sys.platform not in ("win32", "darwin"):
    sys.stderr.write(
        f"[OpenClaw Launcher] 不支持的平台: {sys.platform}\n"
        f"本程序仅支持 Windows 与 macOS。\n"
    )
    sys.exit(1)

# UI 层入口（只接受 Protocol 抽象，具体实现由本文件注入）
from src.ui.launcher_window import LauncherWindow

# 具体实现 — 仅在 Composition Root 中导入
from src.adapters.launch_system import SystemLauncher
from src.core.manage_openclaw import OpenClawManager


def main() -> None:
    """程序入口：组装 Launcher 依赖并启动事件循环。

    注入策略：
    - manager_factory：每次调用新建实例，
      允许 UI 重复触发启动流程而不互相影响。
    - system_launcher：无状态服务，直接持有单例。
    """
    launcher = LauncherWindow(
        manager_factory=OpenClawManager,
        system_launcher=SystemLauncher(),
    )
    launcher.show()
    try:
        sys.exit(launcher.run())
    finally:
        launcher.cleanup()


if __name__ == "__main__":
    main()
