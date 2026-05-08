"""安装器主窗口(纯展示层 + 信号编排器)

职责:
- 管理 QStackedWidget 的 6 步页面切换
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

from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget, QLabel
from PySide6.QtCore import Qt

from src.ui.show_welcome import WelcomePage
from src.ui.show_envcheck import EnvCheckPage
from src.ui.show_install_progress import InstallingPage
from src.ui.show_default_config import US05ConfigPage
from src.ui.show_provider_config import ProviderConfigPage
from src.ui.show_startup import US06StartupPage
from src.services.check_environment import EnvCheckService
from src.services.perform_install import InstallService, ReinstallWorker
from src.contracts import IEnvChecker, IInstaller, IOpenClawManager, ISystemLauncher


# 类型别名:由 launch_*.py 提供的工厂函数,UI 层只通过工厂创建对象
EnvCheckerFactory = Callable[[], IEnvChecker]
InstallerFactory = Callable[[], IInstaller]
OpenClawManagerFactory = Callable[[], IOpenClawManager]


class StepIndicator(QWidget):
    """全局步骤指示器 — 显示在窗口顶部,所有页面共享

    用 QLabel 展示 6 个步骤名称,通过 set_current_step() 高亮当前步骤,
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
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(4)

        for i, name in enumerate(self.steps):
            label = QLabel(name)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("padding: 5px 14px; border-radius: 16px; font-size: 12px;")
            self.labels.append(label)
            layout.addWidget(label)

            if i < len(self.steps) - 1:
                arrow = QLabel("›")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet("color: #CBD5E1; font-size: 18px; font-weight: bold;")
                arrow.setFixedWidth(16)
                layout.addWidget(arrow)

        layout.addStretch(1)

    def set_current_step(self, index) -> None:
        for i, label in enumerate(self.labels):
            if i < index:
                label.setStyleSheet(
                    "background-color: #E8F5E9; color: #2E7D32; padding: 5px 14px; "
                    "border-radius: 16px; font-size: 12px; font-weight: bold;"
                )
                label.setText("✓ " + self.steps[i])
            elif i == index:
                label.setStyleSheet(
                    "background-color: #4CAF50; color: white; padding: 5px 14px; "
                    "border-radius: 16px; font-size: 12px; font-weight: bold;"
                )
                label.setText(self.steps[i])
            else:
                label.setStyleSheet(
                    "background-color: #F1F5F9; color: #94A3B8; padding: 5px 14px; "
                    "border-radius: 16px; font-size: 12px;"
                )
                label.setText(self.steps[i])


class InstallerWindow:
    """安装器主窗口控制器(UI 层)

    管理 6 个页面的生命周期、信号连接和状态流转。
    所有耗时操作都委托给 Service/Worker,自身不阻塞主线程。

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
        self.app.setStyleSheet(self._global_qss())
        self.current_stage = "welcome"

        # 注入的工厂函数与服务实例
        self._env_checker_factory = env_checker_factory
        self._installer_factory = installer_factory
        self._manager_factory = manager_factory
        self.system_launcher = system_launcher

        # 服务层桥接器(纯转发,不持有 adapter/core 实现)
        self.env_check_service = EnvCheckService()
        self.install_service = InstallService()

        # OpenClawManager 延迟创建:仅在配置/启动阶段才需要
        self._openclaw_manager: IOpenClawManager | None = None

        self._setup_window()

    @property
    def openclaw_manager(self) -> IOpenClawManager:
        """延迟创建 OpenClawManager 实例,首次访问时通过注入的工厂构造。"""
        if self._openclaw_manager is None:
            self._openclaw_manager = self._manager_factory()
        return self._openclaw_manager

    @staticmethod
    def _global_qss() -> str:
        return """
        /* 全局背景和字体 */
        QWidget {
            background-color: #F8F9FC;
            font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
        }

        /* macOS 原生边框修复 */
        QLabel {
            background: transparent;
            border: none;
        }

        /* 主按钮 */
        QPushButton#primaryButton {
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: bold;
            font-size: 14px;
            min-width: 100px;
        }
        QPushButton#primaryButton:hover {
            background-color: #45a049;
        }
        QPushButton#primaryButton:pressed {
            background-color: #388E3C;
        }
        QPushButton#primaryButton:disabled {
            background-color: #cccccc;
            color: #888888;
        }

        /* 次要按钮 */
        QPushButton {
            background-color: transparent;
            color: #1E293B;
            border: 1px solid #CBD5E1;
            border-radius: 8px;
            padding: 8px 20px;
            font-size: 13px;
            min-width: 80px;
        }
        QPushButton:hover {
            background-color: #F1F5F9;
            border-color: #94A3B8;
        }
        QPushButton:pressed {
            background-color: #E2E8F0;
        }
        QPushButton:disabled {
            color: #94A3B8;
            border-color: #E2E8F0;
        }

        /* 危险按钮(卸载确认等) */
        QPushButton#dangerButton {
            background-color: #DC3545;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 24px;
            font-weight: bold;
            font-size: 14px;
            min-width: 100px;
        }
        QPushButton#dangerButton:hover {
            background-color: #C82333;
        }
        QPushButton#dangerButton:pressed {
            background-color: #BD2130;
        }
        QPushButton#dangerButton:disabled {
            background-color: #cccccc;
            color: #888888;
        }

        /* 日志区 */
        QPlainTextEdit#logArea, QTextEdit#logArea {
            background-color: #1E293B;
            color: #E2E8F0;
            font-family: "SF Mono", "Fira Code", "Cascadia Code", Consolas, monospace;
            font-size: 12px;
            border-radius: 12px;
            padding: 12px;
            border: none;
        }
        QPlainTextEdit#logArea:focus, QTextEdit#logArea:focus {
            border: none;
            outline: none;
        }

        /* 进度条 */
        QProgressBar {
            border: none;
            background-color: #E2E8F0;
            border-radius: 10px;
            height: 8px;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: #4CAF50;
            border-radius: 10px;
        }

        /* 危险进度条(卸载) */
        QProgressBar#dangerProgressBar {
            border: none;
            background-color: #E2E8F0;
            border-radius: 10px;
            height: 8px;
            text-align: center;
        }
        QProgressBar#dangerProgressBar::chunk {
            background-color: #DC3545;
            border-radius: 10px;
        }

        /* 输入框 */
        QLineEdit {
            background-color: white;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 13px;
            color: #1E293B;
        }
        QLineEdit:focus {
            border: 1px solid #4CAF50;
        }

        /* 下拉框 */
        QComboBox {
            background-color: white;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 13px;
            color: #1E293B;
        }
        QComboBox:focus {
            border: 1px solid #4CAF50;
        }
        QComboBox::drop-down {
            border: none;
            width: 24px;
        }
        QComboBox QAbstractItemView {
            background-color: white;
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            selection-background-color: #E8F5E9;
        }
        """

    def _setup_window(self) -> None:
        """初始化主窗口 UI

        布局从上到下:步骤指示器 → 分割线 → QStackedWidget(6 个页面)
        窗口默认 800x700,最小 700x600,高度自适应不超过屏幕 85%。
        """
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QVBoxLayout, QFrame

        self.main_window = QWidget()
        self.main_window.setWindowTitle("OpenClaw One-Click Installer")
        main_layout = QVBoxLayout(self.main_window)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 全局步骤指示器
        self.step_indicator = StepIndicator(
            ["欢迎", "环境检测", "安装", "配置", "模型", "启动"]
        )
        main_layout.addWidget(self.step_indicator)

        # 分割线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #E2E8F0;")
        separator.setFixedHeight(1)
        main_layout.addWidget(separator)

        # Stacked widget 管理 6 个页面,通过 setCurrentIndex 切换
        self.stacked_widget = QStackedWidget()

        self.welcome_page = WelcomePage()
        self.env_check_page = EnvCheckPage()
        self.installing_page = InstallingPage()
        self.config_page = US05ConfigPage()
        self.provider_config_page = ProviderConfigPage()
        self.startup_page = US06StartupPage()

        self.stacked_widget.addWidget(self.welcome_page)      # 0
        self.stacked_widget.addWidget(self.env_check_page)    # 1
        self.stacked_widget.addWidget(self.installing_page)   # 2
        self.stacked_widget.addWidget(self.config_page)       # 3
        self.stacked_widget.addWidget(self.provider_config_page)  # 4
        self.stacked_widget.addWidget(self.startup_page)      # 5

        self.stacked_widget.currentChanged.connect(self._on_page_changed)
        main_layout.addWidget(self.stacked_widget, 1)

        # 根据主屏幕高度自适应窗口尺寸
        screen = QApplication.primaryScreen().geometry()
        window_width = 800
        window_height = min(700, int(screen.height() * 0.85))
        self.main_window.resize(window_width, window_height)
        self.main_window.setMinimumSize(QSize(700, 600))

        self._connect_signals()

    def _connect_signals(self) -> None:
        """连接所有页面和服务的信号与槽

        按用户故事分组:US-01 欢迎页、US-02 环境检测、US-04 安装、
        US-05 配置、Provider 配置、US-06 启动。保持信号连接集中管理,
        便于排查页面跳转问题。
        """
        # US-01 Welcome page
        self.welcome_page.next_clicked.connect(self._on_welcome_next)
        self.welcome_page.exit_clicked.connect(self._on_exit)

        # US-02 Environment check page
        self.env_check_page.retry_clicked.connect(self._on_env_check_retry)
        self.env_check_page.next_clicked.connect(self._on_env_check_next)
        self.env_check_page.back_clicked.connect(self._on_env_check_back)
        self.env_check_page.openclaw_quick_start.connect(self._on_openclaw_quick_start)
        self.env_check_page.openclaw_config_and_start.connect(self._on_openclaw_config_and_start)
        self.env_check_page.openclaw_provider_config.connect(self._on_openclaw_provider_config)
        self.env_check_page.openclaw_manual_config.connect(self._on_openclaw_manual_config)
        self.env_check_page.openclaw_reinstall.connect(self._on_openclaw_reinstall)

        # 环境检测服务信号:结果反馈到 env_check_page
        self.env_check_service.check_complete.connect(self._on_env_check_complete)
        self.env_check_service.check_failed.connect(self._on_env_check_failed)

        # US-04 Install page
        self.installing_page.back_clicked.connect(self._on_install_back)
        self.installing_page.retry_clicked.connect(self._on_install_retry)
        self.installing_page.cancel_clicked.connect(self._on_install_cancel)
        self.installing_page.next_clicked.connect(self._on_install_next)

        # 安装服务信号:进度、日志、完成(含成功/失败/取消)
        self.install_service.progress_updated.connect(self._on_install_progress)
        self.install_service.log_updated.connect(self._on_install_log)
        self.install_service.install_complete.connect(self._on_install_complete)

        # US-05 Config page
        self.config_page.retry_clicked.connect(self._on_config_retry)
        self.config_page.next_clicked.connect(self._on_config_next)
        self.config_page.back_clicked.connect(self._on_config_back)
        self.config_page.manual_config_clicked.connect(self._on_config_manual)

        # Provider Config page
        self.provider_config_page.back_clicked.connect(self._on_provider_config_back)
        self.provider_config_page.skip_clicked.connect(self._on_provider_config_skip)
        self.provider_config_page.save_and_start_clicked.connect(self._on_provider_config_save)

        # US-06 Startup page
        self.startup_page.retry_clicked.connect(self._on_startup_retry)
        self.startup_page.finish_clicked.connect(self._on_startup_finish)
        self.startup_page.back_clicked.connect(self._on_startup_back)
        self.startup_page.open_webchat_clicked.connect(self._on_open_webchat)

    # ========== US-01 Welcome Page ==========
    def _on_welcome_next(self) -> None:
        """欢迎页点击'下一步':进入环境检测阶段"""
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)
        self._start_env_check()

    # ========== US-02 Environment Check ==========
    def _start_env_check(self) -> None:
        """启动环境检测后台线程,通过工厂创建 checker 实例"""
        self.env_check_page.start_checking()
        self.env_check_service.start_check(self._env_checker_factory())

    def _on_env_check_complete(self, result) -> None:
        """环境检测完成回调:将检测结果分发到各检测项 UI

        Args:
            result: EnvCheckResult,包含 OS、磁盘、权限、浏览器、OpenClaw 状态
        """
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
        """环境检测异常回调:显示错误并提供重试"""
        self.env_check_page.status_label.setText(f"Check failed: {error}")
        self.env_check_page.retry_button.show()

    def _on_env_check_retry(self) -> None:
        """环境检测页点击'重试':重新执行检测"""
        self._start_env_check()

    def _on_env_check_back(self) -> None:
        """环境检测页点击'返回':回到欢迎页"""
        self.current_stage = "welcome"
        self.stacked_widget.setCurrentIndex(0)

    def _on_env_check_next(self) -> None:
        """环境检测页点击'下一步':进入安装阶段"""
        self.current_stage = "installing"
        self.stacked_widget.setCurrentIndex(2)
        self._start_install()

    # ========== OpenClaw Already Installed ==========
    def _on_openclaw_quick_start(self) -> None:
        """已安装分支 — 快速启动:跳过配置,直接进入启动页"""
        self.current_stage = "startup"
        self.stacked_widget.setCurrentIndex(5)
        self._start_startup(quick_start=True)

    def _on_openclaw_config_and_start(self) -> None:
        """已安装分支 — 重新配置并启动:进入默认配置页"""
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)
        self._start_config()

    def _on_openclaw_provider_config(self) -> None:
        """已安装分支 — 配置模型:直接进入 Provider 配置页并加载已有配置"""
        self.current_stage = "provider_config"
        self.stacked_widget.setCurrentIndex(4)
        self.provider_config_page.reset()
        existing = self.openclaw_manager.read_existing_provider_config()
        self.provider_config_page.load_config(existing)

    def _on_openclaw_manual_config(self) -> None:
        """已安装分支 — 手动配置:打开系统终端执行 openclaw config"""
        self._open_manual_config_terminal()
        self.env_check_page.status_label.setText("请完成手动配置后,点击'重新配置并启动'")

    def _on_openclaw_reinstall(self) -> None:
        """已安装分支 — 重新下载:在后台线程清理旧安装后重新执行完整安装流程

        清理内容包括:停止 Gateway、删除源码和配置目录、卸载全局 npm 包。
        所有阻塞操作委托给 ReinstallWorker 执行,避免 UI 冻结。
        完成后自动跳转到 US-04 安装阶段。
        """
        self.env_check_page.status_label.setText("正在清理旧安装,请稍候...")
        self.reinstall_worker = ReinstallWorker()
        self.reinstall_worker.complete.connect(self._on_reinstall_complete)
        self.reinstall_worker.log_line.connect(self.env_check_page.status_label.setText)
        self.reinstall_worker.start()

    def _on_reinstall_complete(self, ok: bool) -> None:
        """重装清理完成后回调:进入安装阶段"""
        self._on_env_check_next()

    # ========== US-04 Install ==========
    def _start_install(self) -> None:
        """启动安装后台线程,通过工厂创建 installer 实例

        平台判断、构造参数等细节都由 installer_factory 内部处理,UI 层不关心。
        """
        self.installing_page.reset()
        self.installing_page.start_installing()
        installer = self._installer_factory()
        self.install_service.start_install(installer)

    def _on_install_progress(self, progress) -> None:
        """安装进度回调:更新进度条和状态文本"""
        self.installing_page.update_progress(progress)

    def _on_install_log(self, log_line) -> None:
        """安装日志回调:追加到日志区域并自动滚动到底部"""
        self.installing_page.add_log_line(log_line)

    def _on_install_complete(self, result) -> None:
        """安装完成回调:成功则显示下一步按钮,失败则显示重试按钮"""
        from src.models.install import InstallStatus
        if result.status == InstallStatus.SUCCESS:
            self.installing_page.install_success(result)
        else:
            self.installing_page.install_failed(result)

    def _on_install_back(self) -> None:
        """安装页点击'返回':取消当前安装,回到环境检测页"""
        self.install_service.cancel_install()
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_install_retry(self) -> None:
        """安装页点击'重试':重新启动安装流程"""
        self._start_install()

    def _on_install_cancel(self) -> None:
        """安装页点击'取消':取消安装并更新 UI 为已取消状态"""
        self.install_service.cancel_install()
        self.installing_page.install_cancelled()

    def _on_install_next(self) -> None:
        """安装页点击'完成'(安装成功后):进入默认配置阶段"""
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)
        self._start_config()

    # ========== US-05 Config ==========
    def _start_config(self) -> None:
        """启动默认配置后台线程(ConfigWorker)

        执行内容:验证安装 → 设置 Gateway 默认参数 → onboard 初始化。
        """
        from src.services.configure_providers import ConfigWorker

        self.config_page.reset()
        self.config_page.start_configuring()

        self.config_worker = ConfigWorker(self.openclaw_manager)
        self.config_worker.progress_updated.connect(self._on_config_progress)
        self.config_worker.log_line.connect(self.config_page.add_log_line)
        self.config_worker.complete.connect(self._on_config_complete)
        self.config_worker.start()

    def _on_config_progress(self, progress) -> None:
        """配置进度回调:更新配置页进度条"""
        self.config_page.update_progress(progress)

    def _on_config_complete(self, result) -> None:
        """配置完成回调:成功则进入 Provider 配置,失败则显示重试"""
        from src.models.config import ConfigStatus
        if result.status == ConfigStatus.COMPLETED:
            self.config_page.config_success(result)
        else:
            self.config_page.config_failed(result)

    def _on_config_retry(self) -> None:
        """配置页点击'重试':重新执行配置"""
        self._start_config()

    def _on_config_next(self) -> None:
        """配置页点击'下一步':进入 Provider 模型配置页并加载已有配置"""
        self.current_stage = "provider_config"
        self.stacked_widget.setCurrentIndex(4)
        self.provider_config_page.reset()
        existing = self.openclaw_manager.read_existing_provider_config()
        self.provider_config_page.load_config(existing)

    def _on_config_back(self) -> None:
        """配置页点击'返回':回到环境检测页"""
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_config_manual(self) -> None:
        """配置页点击'手动配置':打开系统终端"""
        self._open_manual_config_terminal()

    def _open_manual_config_terminal(self) -> None:
        """通过 system_launcher 唤起终端执行 openclaw config

        UI 不关心终端怎么打开、命令名怎么解析:候选命令列表交给 adapter 选择第一个可用项。
        """
        ok = self.system_launcher.open_terminal_command(
            ("openclaw-cn", "openclaw"),
            ("config",),
        )
        if not ok:
            self.env_check_page.status_label.setText(
                "未能自动打开终端,请手动运行: openclaw config"
            )

    # ========== US-06 Startup ==========
    def _start_startup(self, quick_start=False) -> None:
        """启动 Gateway 后台线程(StartupWorker)

        Args:
            quick_start: 若为 True,表示从已安装分支快速启动,跳过配置检查。
        """
        from src.services.configure_providers import StartupWorker

        self.startup_page.reset()
        self.startup_page.start_startup()

        self.startup_worker = StartupWorker(self.openclaw_manager, quick_start=quick_start)
        self.startup_worker.progress_updated.connect(self._on_startup_progress)
        self.startup_worker.log_line.connect(self.startup_page.add_log_line)
        self.startup_worker.complete.connect(self._on_startup_complete)
        self.startup_worker.start()

    def _on_startup_progress(self, progress) -> None:
        """启动进度回调:更新启动页进度条"""
        self.startup_page.update_progress(progress)

    def _on_startup_complete(self, result) -> None:
        """启动完成回调:成功则显示 WebChat 地址和打开浏览器按钮,失败则显示重试"""
        from src.models.config import ConfigStatus
        if result.status == ConfigStatus.COMPLETED:
            self.startup_page.startup_success(result)
        else:
            self.startup_page.startup_failed(result)

    def _on_startup_retry(self) -> None:
        """启动页点击'重试':以 quick_start 模式重新启动 Gateway"""
        self._start_startup(quick_start=True)

    def _on_startup_back(self) -> None:
        """启动页点击'返回':回到环境检测页"""
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    # ========== Provider Config ==========
    def _on_provider_config_back(self) -> None:
        """Provider 配置页点击'返回':回到环境检测页"""
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_provider_config_skip(self) -> None:
        """Provider 配置页点击'跳过':跳过模型配置,直接启动(使用 onboard 默认)"""
        self.current_stage = "startup"
        self.stacked_widget.setCurrentIndex(5)
        self._start_startup(quick_start=False)

    def _on_provider_config_save(self, payload: dict) -> None:
        """Provider 配置页点击'保存并启动':保存配置后启动 Gateway

        Args:
            payload: 包含 providers、global_default_model、fallback_models
        """
        from src.services.configure_providers import ProviderConfigWorker

        self.provider_config_page.show_saving()
        self._provider_config_worker = ProviderConfigWorker(
            self.openclaw_manager,
            payload["providers"],
            payload["global_default_model"],
            payload.get("fallback_models", []),
        )
        self._provider_config_worker.complete.connect(self._on_provider_config_complete)
        self._provider_config_worker.start()

    def _on_provider_config_complete(self, ok: bool) -> None:
        """Provider 配置保存完成回调

        Args:
            ok: True 表示全部配置写入成功,进入启动页;False 则提示用户重试。
        """
        self.provider_config_page.hide_saving()
        if ok:
            self.current_stage = "startup"
            self.stacked_widget.setCurrentIndex(5)
            self._start_startup(quick_start=False)
        else:
            self.provider_config_page.show_error("配置保存失败,请检查 API Key 和网络连接后重试。")

    def _on_open_webchat(self) -> None:
        """启动页点击'打开 WebChat':通过 system_launcher 唤起浏览器

        URL 校验与系统调用都委托给 adapter,UI 只负责输入校验和提示文案。
        """
        url = self.startup_page.url_input.text()
        if not url:
            self.startup_page.browser_hint.setText("地址为空,无法打开浏览器")
            return
        if not url.startswith(("http://", "https://")):
            self.startup_page.browser_hint.setText("地址格式不正确,无法打开浏览器")
            return

        if self.system_launcher.open_url(url):
            self.startup_page.browser_hint.setText("浏览器已打开,如果未显示请检查是否被拦截")
        else:
            self.startup_page.browser_hint.setText("未能自动打开浏览器,请复制上方地址手动访问")

    def _on_startup_finish(self) -> None:
        """启动页点击'完成':退出程序"""
        self._on_exit()

    def _on_exit(self) -> None:
        """统一退出处理:根据当前阶段释放对应资源

        环境检测阶段停止检测服务;安装阶段取消安装;
        配置/启动阶段停止 Gateway 服务。
        """
        if self.current_stage == "env_check":
            self.env_check_service.stop()
        elif self.current_stage == "installing":
            self.install_service.cancel_install()
        elif self.current_stage in ["configuring", "startup"]:
            self.openclaw_manager.stop()
        self.main_window.close()

    def _on_page_changed(self, index) -> None:
        """StackedWidget 页面切换回调:同步更新步骤指示器高亮"""
        if hasattr(self, 'step_indicator'):
            self.step_indicator.set_current_step(index)

    def show(self) -> None:
        """显示主窗口"""
        self.main_window.show()

    def run(self) -> None:
        """进入 Qt 事件循环"""
        return self.app.exec()

    def cleanup(self) -> None:
        """程序退出前清理:停止所有后台服务和进程"""
        self.env_check_service.stop()
        self.install_service.stop()
        if self._openclaw_manager is not None:
            self._openclaw_manager.stop()
