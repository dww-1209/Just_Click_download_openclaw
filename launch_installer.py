"""
OpenClaw 在线安装器主入口(Composition Root)

提供 6 步安装流程:欢迎 → 环境检测 → 安装 → 配置 → 模型 → 启动
通过 QStackedWidget 管理页面切换,所有耗时操作均在 QThread 中执行。

设计要点:
- 本文件为唯一允许跨层导入的装配器层(Composition Root)。
- 在此处把具体 adapter / core 实现注入到 InstallerWindow,UI 层不接触任何具体类。
- 上层依赖的是 src.contracts 中的 Protocol 接口,实现可替换。
"""

import sys
from pathlib import Path

# 确保 src/ 在模块搜索路径中(无论从哪里启动)
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# UI 层入口(只接受 Protocol 抽象,具体实现由本文件注入)
from src.ui.installer_window import InstallerWindow

# 具体实现 — 仅在 Composition Root 中导入
from src.adapters.check_system import SystemChecker
from src.adapters.install_openclaw import OpenClawInstaller
from src.adapters.launch_system import SystemLauncher
from src.core.manage_openclaw import OpenClawManager


def main() -> None:
    """程序入口:在装配器层组装依赖并启动事件循环。

    注入策略:
    - env_checker_factory / installer_factory / manager_factory:每次调用都新建实例,
      允许 UI 重复触发检测/安装/重启流程而不互相影响。
    - system_launcher:无状态服务,直接持有单例即可。
    """
    installer = InstallerWindow(
        env_checker_factory=SystemChecker,
        installer_factory=OpenClawInstaller,
        manager_factory=OpenClawManager,
        system_launcher=SystemLauncher(),
    )
    installer.show()
    try:
        sys.exit(installer.run())
    finally:
        installer.cleanup()


if __name__ == "__main__":
    main()
