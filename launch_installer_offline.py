"""
OpenClaw 离线安装器主入口(Composition Root)

提供 6 步离线安装流程:欢迎 → 环境检测 → 安装 → 配置 → 模型 → 启动
无需网络,从预构建产物解压安装。

设计要点:
- 仅在 installer_factory 处替换为 OfflineOpenClawInstaller,
  其余装配与在线版本保持一致(展示/服务/核心层完全复用)。
- 不需要继承 InstallerWindow:UI 层只通过工厂签名解耦,具体实现可自由替换。
"""

import sys
from pathlib import Path

# 确保 src/ 在模块搜索路径中(无论从哪里启动)
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 平台守卫:仅支持 Windows / macOS。Linux 上的代码路径未经测试,直接拒绝启动。
if sys.platform not in ("win32", "darwin"):
    sys.stderr.write(
        f"[OpenClaw 离线安装器] 不支持的平台: {sys.platform}\n"
        f"本程序仅支持 Windows 与 macOS。\n"
    )
    sys.exit(1)

# UI 层入口(与在线版本共用同一个窗口实现)
from src.ui.installer_window import InstallerWindow

# 具体实现 — 仅在 Composition Root 中导入
from src.adapters.check_system import SystemChecker
from src.adapters.install_openclaw_offline import OfflineOpenClawInstaller
from src.adapters.launch_system import SystemLauncher
from src.core.manage_openclaw import OpenClawManager


def main() -> None:
    """程序入口:装配离线版依赖并启动事件循环。

    与在线版本的唯一差异:installer_factory 注入 OfflineOpenClawInstaller。
    应用名称与窗口标题在此处统一覆盖,保持离线版可识别。
    """
    installer = InstallerWindow(
        env_checker_factory=SystemChecker,
        installer_factory=OfflineOpenClawInstaller,
        manager_factory=OpenClawManager,
        system_launcher=SystemLauncher(),
    )
    # 离线版本的应用标识与窗口标题
    installer.app.setApplicationName("OpenClaw Offline Installer")
    installer.main_window.setWindowTitle("OpenClaw 离线安装器")

    installer.show()
    try:
        sys.exit(installer.run())
    finally:
        installer.cleanup()


if __name__ == "__main__":
    main()
