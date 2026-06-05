"""安装器主窗口(纯展示层 + 信号编排器)

职责:
- 管理 QStackedWidget 的 5 页新安装流程:欢迎 → 环境检测 → 安装 → 配置 → 完成
- 已安装场景提供重装入口;日常启动和模型配置交给独立 Launcher
- 把 UI 事件桥接到 Service 层(通过 Signal/Slot)
- 通过工厂函数与系统启动器从外部注入具体实现,UI 层不直接接触 adapter / core

设计要点:
- 严格遵守分层依赖方向(UI 只允许导入 src.services / src.contracts / src.models),
  不直接 import src.adapters / src.core 中的具体类。
- 所有跨层装配(具体 adapter / core 实现)由 launch_*.py(Composition Root)负责。
- 所有耗时操作均在 QThread 中执行,主线程零阻塞。
"""

import sys
from pathlib import Path
from typing import Callable

# 确保 src/ 在模块搜索路径中(无论从哪里启动)
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget, QLabel, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from src.ui._theme import GLOBAL_QSS
from src.models.utils import find_app_icon_path
from src.ui.show_welcome import WelcomePage
from src.ui.show_envcheck import EnvCheckPage
from src.ui.show_install_progress import InstallingPage
from src.ui.show_default_config import US05ConfigPage, InstallDonePage
from src.services.check_environment import EnvCheckService
from src.services.perform_install import InstallService, ReinstallWorker
from src.contracts import IEnvChecker, IInstaller, IOpenClawManager, ISystemLauncher


# 类型别名:由 launch_*.py 提供的工厂函数,UI 层只通过工厂创建对象
EnvCheckerFactory = Callable[[], IEnvChecker]
InstallerFactory = Callable[[], IInstaller]
OpenClawManagerFactory = Callable[[], IOpenClawManager]


class StepIndicator(QWidget):
    """全局步骤指示器 — 显示在窗口顶部,所有页面共享

    用 QLabel 展示 5 个步骤名称,通过 set_current_step() 高亮当前步骤,
    已完成步骤显示绿色勾,未完成步骤置灰。
    """

    def __init__(self, steps, parent=None) -> None:
        super().__init__(parent)
        self.steps = steps
        self.labels = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(40, 14, 40, 14)
        layout.setSpacing(0)

        for i, name in enumerate(self.steps):
            label = QLabel(name)
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName("stepIndicatorItem")
            label.setProperty("state", "pending")
            self.labels.append(label)
            layout.addWidget(label)
            layout.addStretch(1)

    def set_current_step(self, index) -> None:
        for i, label in enumerate(self.labels):
            if i < index:
                label.setProperty("state", "done")
                label.setText(self.steps[i])
            elif i == index:
                label.setProperty("state", "active")
                label.setText(self.steps[i])
            else:
                label.setProperty("state", "pending")
                label.setText(self.steps[i])
            label.style().unpolish(label)
            label.style().polish(label)


class InstallerWindow:
    """安装器主窗口控制器(UI 层)

    管理 5 个页面的生命周期、信号连接和状态流转。
    所有耗时操作都委托给 Service/Worker,自身不阻塞主线程。

    新安装流程:欢迎 → 环境检测 → 安装 → 配置(onboard) → 完成
    已安装场景:提供"重装"入口,其他操作(启动/配置模型)引导用户使用 Launcher。

    依赖注入说明:
    - env_checker_factory:每次需要新建 IEnvChecker 时调用(允许重复检测)
    - installer_factory:每次需要新建 IInstaller 时调用(允许重试安装)
    - manager_factory:首次访问 openclaw_manager 时调用一次,后续复用
    - system_launcher:无状态服务,直接持有单例即可
    """

    def __init__(
        self,
        env_checker_factory: EnvCheckerFactory,
        installer_factory: InstallerFactory,
        manager_factory: OpenClawManagerFactory,
        system_launcher: ISystemLauncher,
    ) -> None:
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("OpenClaw Installer")
        self.app.setStyleSheet(GLOBAL_QSS)

        icon_path = find_app_icon_path()
        if icon_path:
            self.app.setWindowIcon(QIcon(icon_path))
        self.current_stage = "welcome"

        # 注入的工厂函数与服务实例
        self._env_checker_factory = env_checker_factory
        self._installer_factory = installer_factory
        self._manager_factory = manager_factory
        self.system_launcher = system_launcher

        # 服务层桥接器(纯转发,不持有 adapter/core 实现)
        self.env_check_service = EnvCheckService()
        self.install_service = InstallService()

        # OpenClawManager 延迟创建:仅在配置阶段才需要
        self._openclaw_manager: IOpenClawManager | None = None

        self._setup_window()

    @property
    def openclaw_manager(self) -> IOpenClawManager:
        if self._openclaw_manager is None:
            self._openclaw_manager = self._manager_factory()
        return self._openclaw_manager

    def _setup_window(self) -> None:
        """初始化主窗口 UI

        布局从上到下:步骤指示器 → 分割线 → QStackedWidget(5 个页面)
        窗口默认 800x700,最小 700x600,高度自适应不超过屏幕 85%。
        """
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QVBoxLayout, QFrame

        self.main_window = QWidget()
        self.main_window.setWindowTitle("OpenClaw One-Click Installer")
        main_layout = QVBoxLayout(self.main_window)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 全局步骤指示器 — 5 步(去掉了 Provider 配置和启动,由 Launcher 承担)
        self.step_indicator = StepIndicator(
            ["欢迎", "环境检测", "安装", "配置", "完成"]
        )
        main_layout.addWidget(self.step_indicator)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #E2E8F0;")
        separator.setFixedHeight(1)
        main_layout.addWidget(separator)

        self.stacked_widget = QStackedWidget()

        self.welcome_page = WelcomePage()          # 0
        self.env_check_page = EnvCheckPage()       # 1
        self.installing_page = InstallingPage()    # 2
        self.config_page = US05ConfigPage()        # 3
        self.done_page = InstallDonePage()         # 4

        self.stacked_widget.addWidget(self.welcome_page)      # 0
        self.stacked_widget.addWidget(self.env_check_page)    # 1
        self.stacked_widget.addWidget(self.installing_page)   # 2
        self.stacked_widget.addWidget(self.config_page)       # 3
        self.stacked_widget.addWidget(self.done_page)         # 4

        self.stacked_widget.currentChanged.connect(self._on_page_changed)
        main_layout.addWidget(self.stacked_widget, 1)

        screen = QApplication.primaryScreen().geometry()
        window_width = 800
        window_height = min(700, int(screen.height() * 0.85))
        self.main_window.resize(window_width, window_height)
        self.main_window.setMinimumSize(QSize(700, 600))

        self._connect_signals()

    def _connect_signals(self) -> None:
        """连接所有页面和服务的信号与槽"""

        # US-01 Welcome page
        self.welcome_page.next_clicked.connect(self._on_welcome_next)
        self.welcome_page.exit_clicked.connect(self._on_exit)

        # US-02 Environment check page
        self.env_check_page.retry_clicked.connect(self._on_env_check_retry)
        self.env_check_page.next_clicked.connect(self._on_env_check_next)
        self.env_check_page.back_clicked.connect(self._on_env_check_back)
        # 已安装分支:快速启动/配置模型 → 引导到 Launcher;重新下载保留
        self.env_check_page.openclaw_quick_start.connect(self._on_use_launcher_prompt)
        self.env_check_page.openclaw_provider_config.connect(self._on_use_launcher_prompt)
        self.env_check_page.openclaw_reinstall.connect(self._on_openclaw_reinstall)

        # 环境检测服务信号
        self.env_check_service.check_complete.connect(self._on_env_check_complete)
        self.env_check_service.check_failed.connect(self._on_env_check_failed)

        # US-04 Install page
        self.installing_page.back_clicked.connect(self._on_install_back)
        self.installing_page.retry_clicked.connect(self._on_install_retry)
        self.installing_page.cancel_clicked.connect(self._on_install_cancel)
        self.installing_page.next_clicked.connect(self._on_install_next)

        self.install_service.progress_updated.connect(self._on_install_progress)
        self.install_service.log_updated.connect(self._on_install_log)
        self.install_service.install_complete.connect(self._on_install_complete)

        # US-05 Config page
        self.config_page.retry_clicked.connect(self._on_config_retry)
        self.config_page.next_clicked.connect(self._on_config_next)
        self.config_page.back_clicked.connect(self._on_config_back)
        self.config_page.manual_config_clicked.connect(self._on_config_manual)

        # 安装完成页
        self.done_page.finish_clicked.connect(self._on_exit)

    # ========== US-01 Welcome Page ==========
    def _on_welcome_next(self) -> None:
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)
        self._start_env_check()

    # ========== US-02 Environment Check ==========
    def _start_env_check(self) -> None:
        self.env_check_page.start_checking()
        self.env_check_service.start_check(self._env_checker_factory())

    def _on_env_check_complete(self, result) -> None:
        self.env_check_page.update_os_result(result.os_type)
        self.env_check_page.update_disk_result(
            result.disk_space.status,
            result.disk_space.message,
            result.disk_space.path
        )
        self.env_check_page.update_permission_result(
            result.permission.status, result.permission.message
        )
        self.env_check_page.update_browser_result(result.browser)
        self.env_check_page.update_openclaw_result(
            result.openclaw_install.status, result.openclaw_install.message
        )
        self.env_check_page.check_complete(result.is_ready, result.message)

    def _on_env_check_failed(self, error) -> None:
        self.env_check_page.status_label.setText(f"Check failed: {error}")
        self.env_check_page.retry_button.show()

    def _on_env_check_retry(self) -> None:
        self._start_env_check()

    def _on_env_check_back(self) -> None:
        self.current_stage = "welcome"
        self.stacked_widget.setCurrentIndex(0)

    def _on_env_check_next(self) -> None:
        self.current_stage = "installing"
        self.stacked_widget.setCurrentIndex(2)
        self._start_install()

    # ========== OpenClaw Already Installed ==========
    def _on_use_launcher_prompt(self) -> None:
        """已安装场景：引导用户使用 Launcher 进行日常操作

        安装器定位是"一次性安装工具",日常启动和模型配置应由
        独立的 Launcher(约 40MB)处理。用户拿到的是两个 .app:
        - 安装器:装完可删
        - 启动器:日常使用,保留
        """
        QMessageBox.information(
            self.main_window,
            "请使用启动器",
            "检测到 OpenClaw 已安装。\n\n"
            "日常启动和模型配置请使用「OpenClaw 启动器」——"
            "它是独立的轻量程序(约 40MB),专为日常使用设计。\n\n"
            "本安装器为一次性工具,安装完成后可安全删除以释放磁盘空间。\n\n"
            "如需重新安装,请点击下方「重新下载」按钮。"
        )

    def _on_openclaw_reinstall(self) -> None:
        """已安装分支 — 重新下载:在后台线程清理旧安装后重新执行完整安装流程"""
        self.current_stage = "installing"
        self.installing_page.reset()
        self.installing_page.start_installing()
        self.installing_page.add_log_line("正在清理旧安装,请稍候...")
        self.stacked_widget.setCurrentIndex(2)

        self.reinstall_worker = ReinstallWorker()
        self.reinstall_worker.complete.connect(self._on_reinstall_complete)
        self.reinstall_worker.log_line.connect(self.installing_page.add_log_line)
        self.reinstall_worker.start()

    def _on_reinstall_complete(self, ok: bool) -> None:
        self._on_env_check_next()

    # ========== US-04 Install ==========
    def _start_install(self) -> None:
        self.installing_page.reset()
        self.installing_page.start_installing()
        installer = self._installer_factory()
        self.install_service.start_install(installer)

    def _on_install_progress(self, progress) -> None:
        self.installing_page.update_progress(progress)

    def _on_install_log(self, log_line) -> None:
        self.installing_page.add_log_line(log_line)

    def _on_install_complete(self, result) -> None:
        from src.models.install import InstallStatus
        if result.status == InstallStatus.SUCCESS:
            self.installing_page.install_success(result)
        else:
            self.installing_page.install_failed(result)

    def _on_install_back(self) -> None:
        self.install_service.cancel_install()
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_install_retry(self) -> None:
        self._start_install()

    def _on_install_cancel(self) -> None:
        self.install_service.cancel_install()
        self.installing_page.install_cancelled()

    def _on_install_next(self) -> None:
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)
        self._start_config()

    # ========== US-05 Config ==========
    def _start_config(self) -> None:
        from src.services.configure_providers import ConfigWorker

        self.config_page.reset()
        self.config_page.start_configuring()

        self.config_worker = ConfigWorker(self.openclaw_manager)
        self.config_worker.progress_updated.connect(self._on_config_progress)
        self.config_worker.log_line.connect(self.config_page.add_log_line)
        self.config_worker.complete.connect(self._on_config_complete)
        self.config_worker.start()

    def _on_config_progress(self, progress) -> None:
        self.config_page.update_progress(progress)

    def _on_config_complete(self, result) -> None:
        from src.models.config import ConfigStatus
        if result.status == ConfigStatus.COMPLETED:
            self.config_page.config_success(result)
        else:
            self.config_page.config_failed(result)

    def _on_config_retry(self) -> None:
        self._start_config()

    def _on_config_next(self) -> None:
        """配置完成 → 安装完成页(第 4 页)

        安装完成后不再进入 Provider 配置和启动流程——
        用户日常使用交给独立的 Launcher,安装器可安全删除。
        """
        self.current_stage = "done"
        self.stacked_widget.setCurrentIndex(4)

    def _on_config_back(self) -> None:
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_config_manual(self) -> None:
        """配置页点击'手动配置':打开系统终端"""
        ok = self.system_launcher.open_terminal_command(
            ("openclaw-cn", "openclaw"),
            ("config",),
        )
        if not ok:
            self.env_check_page.status_label.setText(
                "未能自动打开终端,请手动运行: openclaw config"
            )

    # ========== 退出 & 清理 ==========

    def _on_exit(self) -> None:
        """统一退出处理"""
        if self.current_stage == "env_check":
            self.env_check_service.stop()
        elif self.current_stage == "installing":
            self.install_service.cancel_install()
        elif self.current_stage == "configuring":
            if self._openclaw_manager is not None:
                self._openclaw_manager.stop()
        self.main_window.close()

    def _on_page_changed(self, index) -> None:
        """页面切换时同步更新步骤指示器

        index 4(完成页)不在步骤条范围内,完成页显示时把所有步骤标为完成。
        """
        if hasattr(self, 'step_indicator'):
            if index == 4:
                # 完成页:所有步骤标记为 done
                self.step_indicator.set_current_step(5)
            else:
                self.step_indicator.set_current_step(index)

    def show(self) -> None:
        self.main_window.show()

    def run(self) -> None:
        return self.app.exec()

    def cleanup(self) -> None:
        self.env_check_service.stop()
        self.install_service.stop()
        if self._openclaw_manager is not None:
            self._openclaw_manager.stop()
