import sys
from PySide6.QtWidgets import QApplication, QStackedWidget
from PySide6.QtCore import Qt

from ui.welcome_page import WelcomePage
from ui.env_check_page import EnvCheckPage
from ui.installing_page import InstallingPage
from ui.us05_config_page import US05ConfigPage
from ui.us06_startup_page import US06StartupPage
from services.env_check_service import EnvCheckService
from services.install_service import InstallService
from core.openclaw_manager import OpenClawManager


class InstallerWindow:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("OpenClaw Installer")
        self.current_stage = "welcome"
        self.env_check_service = EnvCheckService()
        self.install_service = InstallService()
        self.openclaw_manager = OpenClawManager()
        self._setup_window()

    def _setup_window(self):
        from PySide6.QtCore import QSize

        self.stacked_widget = QStackedWidget()

        self.welcome_page = WelcomePage()
        self.env_check_page = EnvCheckPage()
        self.installing_page = InstallingPage()
        self.config_page = US05ConfigPage()
        self.startup_page = US06StartupPage()

        self.stacked_widget.addWidget(self.welcome_page)
        self.stacked_widget.addWidget(self.env_check_page)
        self.stacked_widget.addWidget(self.installing_page)
        self.stacked_widget.addWidget(self.config_page)
        self.stacked_widget.addWidget(self.startup_page)

        self.stacked_widget.setWindowTitle("OpenClaw One-Click Installer")

        screen = QApplication.primaryScreen().geometry()
        window_width = 800
        window_height = min(700, int(screen.height() * 0.85))
        self.stacked_widget.resize(window_width, window_height)
        self.stacked_widget.setMinimumSize(QSize(700, 600))

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
        self.stacked_widget.setCurrentIndex(4)
        self._start_startup(quick_start=True)

    def _on_openclaw_config_and_start(self):
        # Config and start - go to US-05 config page
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)
        self._start_config()

    def _on_openclaw_manual_config(self):
        self._open_manual_config_terminal()
        self.env_check_page.status_label.setText("请完成手动配置后，点击'重新配置并启动'")

    def _on_openclaw_reinstall(self):
        try:
            import subprocess
            subprocess.run("openclaw gateway stop", shell=True, capture_output=True)
            subprocess.run("npm uninstall -g openclaw", shell=True, capture_output=True)
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
        # Config done, go to startup
        self.current_stage = "startup"
        self.stacked_widget.setCurrentIndex(4)
        self._start_startup(quick_start=False)

    def _on_config_back(self):
        self.current_stage = "installing"
        self.stacked_widget.setCurrentIndex(2)

    def _on_config_manual(self):
        self._open_manual_config_terminal()

    def _open_manual_config_terminal(self):
        """跨平台打开终端并执行 openclaw config"""
        import subprocess
        import platform
        import shutil

        os_type = platform.system().lower()
        try:
            if os_type == "windows" or sys.platform == "win32":
                subprocess.Popen("start cmd /k openclaw config", shell=True)
            elif os_type == "darwin":
                # macOS: use AppleScript to open Terminal
                script = 'tell application "Terminal" to do script "openclaw config"'
                subprocess.Popen(["osascript", "-e", script])
            else:
                # Linux: try common terminals
                opened = False
                terminals = [
                    ["gnome-terminal", "--", "bash", "-c", "openclaw config; exec bash"],
                    ["xterm", "-e", "bash -c 'openclaw config; exec bash'"],
                    ["konsole", "-e", "bash", "-c", "openclaw config; exec bash"],
                ]
                for cmd in terminals:
                    if shutil.which(cmd[0]):
                        subprocess.Popen(cmd)
                        opened = True
                        break
                if not opened:
                    print("未找到可用的终端模拟器，请手动运行: openclaw config")
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
        self.current_stage = "configuring"
        self.stacked_widget.setCurrentIndex(3)

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
        self.stacked_widget.close()

    def show(self):
        self.stacked_widget.show()

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
