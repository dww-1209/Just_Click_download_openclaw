import sys
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget, QLabel
from PySide6.QtCore import Qt

from ui.welcome_page import WelcomePage
from ui.env_check_page import EnvCheckPage
from ui.installing_page import InstallingPage
from ui.us05_config_page import US05ConfigPage
from ui.provider_config_page import ProviderConfigPage
from ui.us06_startup_page import US06StartupPage
from services.env_check_service import EnvCheckService
from services.install_service import InstallService
from core.openclaw_manager import OpenClawManager


class StepIndicator(QWidget):
    """全局步骤指示器 — 显示在窗口顶部，所有页面共享"""

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.labels = []
        self._setup_ui()

    def _setup_ui(self):
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

    def set_current_step(self, index):
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
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("OpenClaw Installer")
        self.app.setStyleSheet(self._global_qss())
        self.current_stage = "welcome"
        self.env_check_service = EnvCheckService()
        self.install_service = InstallService()
        self.openclaw_manager = OpenClawManager()
        self._setup_window()

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

        /* 危险按钮（卸载确认等） */
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

        /* 危险进度条（卸载） */
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

    def _setup_window(self):
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QVBoxLayout, QFrame

        # 主窗口容器（步骤指示器 + stacked_widget）
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

        # Stacked widget
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

        screen = QApplication.primaryScreen().geometry()
        window_width = 800
        window_height = min(700, int(screen.height() * 0.85))
        self.main_window.resize(window_width, window_height)
        self.main_window.setMinimumSize(QSize(700, 600))

        self._connect_signals()

    def _connect_signals(self):
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
        self.install_service.install_failed.connect(self._on_install_failed)

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
    def _on_welcome_next(self):
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)
        self._start_env_check()

    # ========== US-02 Environment Check ==========
    def _start_env_check(self):
        self.env_check_page.start_checking()
        self.env_check_service.start_check()

    def _on_env_check_complete(self, result):
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

    def _on_env_check_failed(self, error):
        self.env_check_page.status_label.setText(f"Check failed: {error}")
        self.env_check_page.retry_button.show()

    def _on_env_check_retry(self):
        self._start_env_check()

    def _on_env_check_back(self):
        self.current_stage = "welcome"
        self.stacked_widget.setCurrentIndex(0)

    def _on_env_check_next(self):
        self.current_stage = "installing"
        self.stacked_widget.setCurrentIndex(2)
        self._start_install()

    # ========== OpenClaw Already Installed ==========
    def _on_openclaw_quick_start(self):
        # Quick start - skip config, go directly to startup
        self.current_stage = "startup"
        self.stacked_widget.setCurrentIndex(5)
        self._start_startup(quick_start=True)

    def _on_openclaw_config_and_start(self):
        # Config and start - go to US-05 config page
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)
        self._start_config()

    def _on_openclaw_provider_config(self):
        # Directly go to provider config page
        self.current_stage = "provider_config"
        self.stacked_widget.setCurrentIndex(4)
        self.provider_config_page.reset()
        existing = self.openclaw_manager.read_existing_provider_config()
        self.provider_config_page.load_config(existing)

    def _on_openclaw_manual_config(self):
        self._open_manual_config_terminal()
        self.env_check_page.status_label.setText("请完成手动配置后，点击'重新配置并启动'")

    def _on_openclaw_reinstall(self):
        try:
            import subprocess
            import shutil
            import os
            cmd = "openclaw-cn" if shutil.which("openclaw-cn") else "openclaw"
            subprocess.run(f"{cmd} gateway stop", shell=True, capture_output=True)
            # 清理本地构建目录
            for d in [os.path.expanduser("~/openclaw-cn"), os.path.expanduser("~/.openclaw")]:
                if os.path.exists(d):
                    try:
                        import stat
                        def _remove_readonly(func, path, _):
                            os.chmod(path, stat.S_IWRITE)
                            func(path)
                        shutil.rmtree(d, onerror=_remove_readonly)
                    except Exception:
                        pass
            # 清理全局 npm 包（兼容旧版）
            for pkg in ["openclaw-cn", "openclaw"]:
                subprocess.run(f"npm uninstall -g {pkg}", shell=True, capture_output=True)
        except Exception:
            pass
        self._on_env_check_next()

    # ========== US-04 Install ==========
    def _start_install(self):
        self.installing_page.reset()
        self.installing_page.start_installing()

        import platform
        os_type = platform.system().lower()
        if os_type == "darwin":
            os_type = "macos"

        self.install_service.start_install(os_type)

    def _on_install_progress(self, progress):
        self.installing_page.update_progress(progress)

    def _on_install_log(self, log_line):
        self.installing_page.add_log_line(log_line)

    def _on_install_complete(self, result):
        from models.install import InstallStatus
        if result.status == InstallStatus.SUCCESS:
            self.installing_page.install_success(result)
        else:
            self.installing_page.install_failed(result)

    def _on_install_failed(self, error):
        from models.install import InstallResult, InstallStatus

        result = InstallResult(
            status=InstallStatus.FAILED, error_message=error, message="Install error"
        )
        self.installing_page.install_failed(result)

    def _on_install_back(self):
        self.install_service.cancel_install()
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_install_retry(self):
        self._start_install()

    def _on_install_cancel(self):
        self.install_service.cancel_install()
        self.installing_page.install_cancelled()

    def _on_install_next(self):
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)
        self._start_config()

    # ========== US-05 Config ==========
    def _start_config(self):
        """Start configuration only"""
        self.config_page.reset()
        self.config_page.start_configuring()

        from PySide6.QtCore import QThread, Signal

        class ConfigWorker(QThread):
            progress_updated = Signal(object)
            log_line = Signal(str)
            complete = Signal(object)

            def __init__(self, manager):
                super().__init__()
                self.manager = manager

            def run(self):
                result = self.manager.configure_only(
                    on_progress=self.progress_updated.emit,
                    on_log=self.log_line.emit
                )
                self.complete.emit(result)

        self.config_worker = ConfigWorker(self.openclaw_manager)
        self.config_worker.progress_updated.connect(self._on_config_progress)
        self.config_worker.log_line.connect(self.config_page.add_log_line)
        self.config_worker.complete.connect(self._on_config_complete)
        self.config_worker.start()

    def _on_config_progress(self, progress):
        self.config_page.update_progress(progress)

    def _on_config_complete(self, result):
        from models.config import ConfigStatus
        if result.status == ConfigStatus.COMPLETED:
            self.config_page.config_success(result)
        else:
            self.config_page.config_failed(result)

    def _on_config_retry(self):
        self._start_config()

    def _on_config_next(self):
        # Config done, go to provider config
        self.current_stage = "provider_config"
        self.stacked_widget.setCurrentIndex(4)
        self.provider_config_page.reset()
        existing = self.openclaw_manager.read_existing_provider_config()
        self.provider_config_page.load_config(existing)

    def _on_config_back(self):
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_config_manual(self):
        self._open_manual_config_terminal()

    def _open_manual_config_terminal(self):
        """跨平台打开终端并执行 openclaw config"""
        import subprocess
        import platform
        import shutil

        os_type = platform.system().lower()
        cmd = "openclaw-cn" if shutil.which("openclaw-cn") else "openclaw"
        try:
            if os_type == "windows" or sys.platform == "win32":
                subprocess.Popen(f"start cmd /k {cmd} config", shell=True)
            elif os_type == "darwin":
                # macOS: use AppleScript to open Terminal
                script = f'tell application "Terminal" to do script "{cmd} config"'
                subprocess.Popen(["osascript", "-e", script])
            else:
                # Linux: try common terminals
                opened = False
                terminals = [
                    ["gnome-terminal", "--", "bash", "-c", f"{cmd} config; exec bash"],
                    ["xterm", "-e", f"bash -c '{cmd} config; exec bash'"],
                    ["konsole", "-e", "bash", "-c", f"{cmd} config; exec bash"],
                ]
                for term_cmd in terminals:
                    if shutil.which(term_cmd[0]):
                        subprocess.Popen(term_cmd)
                        opened = True
                        break
                if not opened:
                    print(f"未找到可用的终端模拟器，请手动运行: {cmd} config")
        except Exception as e:
            print(f"打开终端失败: {e}")

    # ========== US-06 Startup ==========
    def _start_startup(self, quick_start=False):
        """Start gateway and open browser"""
        self.startup_page.reset()
        self.startup_page.start_startup()

        from PySide6.QtCore import QThread, Signal

        class StartupWorker(QThread):
            progress_updated = Signal(object)
            log_line = Signal(str)
            complete = Signal(object)

            def __init__(self, manager, quick_start=False):
                super().__init__()
                self.manager = manager
                self.quick_start = quick_start

            def run(self):
                if self.quick_start:
                    result = self.manager.startup_only(
                        on_progress=self.progress_updated.emit,
                        on_log=self.log_line.emit
                    )
                else:
                    # Full flow: config done, just startup
                    result = self.manager.startup_only(
                        on_progress=self.progress_updated.emit,
                        on_log=self.log_line.emit
                    )
                self.complete.emit(result)

        self.startup_worker = StartupWorker(self.openclaw_manager, quick_start=quick_start)
        self.startup_worker.progress_updated.connect(self._on_startup_progress)
        self.startup_worker.log_line.connect(self.startup_page.add_log_line)
        self.startup_worker.complete.connect(self._on_startup_complete)
        self.startup_worker.start()

    def _on_startup_progress(self, progress):
        self.startup_page.update_progress(progress)

    def _on_startup_complete(self, result):
        from models.config import ConfigStatus
        if result.status == ConfigStatus.COMPLETED:
            self.startup_page.startup_success(result)
        else:
            self.startup_page.startup_failed(result)

    def _on_startup_retry(self):
        self._start_startup(quick_start=True)

    def _on_startup_back(self):
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    # ========== Provider Config ==========
    def _on_provider_config_back(self):
        self.current_stage = "env_check"
        self.stacked_widget.setCurrentIndex(1)

    def _on_provider_config_skip(self):
        self.current_stage = "startup"
        self.stacked_widget.setCurrentIndex(5)
        self._start_startup(quick_start=False)

    def _on_provider_config_save(self, payload: dict):
        """保存 Provider 配置并启动"""
        from PySide6.QtCore import QThread, Signal

        class ProviderConfigWorker(QThread):
            progress_updated = Signal(object)
            log_line = Signal(str)
            complete = Signal(bool)

            def __init__(self, manager, providers_config, global_default_model, fallback_models):
                super().__init__()
                self.manager = manager
                self.providers_config = providers_config
                self.global_default_model = global_default_model
                self.fallback_models = fallback_models

            def run(self):
                ok = self.manager.configure_providers(
                    self.providers_config,
                    self.global_default_model,
                    self.fallback_models,
                    on_progress=self.progress_updated.emit,
                    on_log=self.log_line.emit,
                )
                self.complete.emit(ok)

        self.provider_config_page.show_saving()
        self._provider_config_worker = ProviderConfigWorker(
            self.openclaw_manager,
            payload["providers"],
            payload["global_default_model"],
            payload.get("fallback_models", []),
        )
        self._provider_config_worker.complete.connect(self._on_provider_config_complete)
        self._provider_config_worker.start()

    def _on_provider_config_complete(self, ok: bool):
        self.provider_config_page.hide_saving()
        if ok:
            self.current_stage = "startup"
            self.stacked_widget.setCurrentIndex(5)
            self._start_startup(quick_start=False)
        else:
            self.provider_config_page.show_error("配置保存失败，请检查 API Key 和网络连接后重试。")

    def _on_open_webchat(self):
        """User clicked 'Open WebChat' button"""
        import webbrowser
        import os
        import platform
        
        url = self.startup_page.url_input.text()
        if not url:
            self.startup_page.browser_hint.setText("地址为空，无法打开浏览器")
            return
        
        opened = False
        try:
            webbrowser.open(url, new=2)
            opened = True
        except Exception as e:
            print(f"打开浏览器失败: {e}")
        
        if not opened and platform.system().lower() == "windows":
            try:
                os.system(f'start "" "{url}"')
                opened = True
            except Exception as e:
                print(f"系统命令打开浏览器失败: {e}")
        
        if opened:
            self.startup_page.browser_hint.setText("浏览器已打开，如果未显示请检查是否被拦截")
        else:
            self.startup_page.browser_hint.setText("未能自动打开浏览器，请复制上方地址手动访问")

    def _on_startup_finish(self):
        self._on_exit()

    def _on_exit(self):
        if self.current_stage == "env_check":
            self.env_check_service.stop()
        elif self.current_stage == "installing":
            self.install_service.cancel_install()
        elif self.current_stage in ["configuring", "startup"]:
            self.openclaw_manager.stop()
        self.main_window.close()

    def _on_page_changed(self, index):
        if hasattr(self, 'step_indicator'):
            self.step_indicator.set_current_step(index)

    def show(self):
        self.main_window.show()

    def run(self):
        return self.app.exec()

    def cleanup(self):
        self.env_check_service.stop()
        self.install_service.stop()
        self.openclaw_manager.stop()


def main():
    installer = InstallerWindow()
    installer.show()
    try:
        sys.exit(installer.run())
    finally:
        installer.cleanup()


if __name__ == "__main__":
    main()
