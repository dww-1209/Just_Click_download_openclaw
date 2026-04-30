"""OpenClaw 卸载工具 — 独立程序入口"""

import sys
from pathlib import Path

# 确保 src/ 在模块搜索路径中
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QStackedWidget, QMessageBox
from PySide6.QtCore import Qt, QThread, Signal

from src.ui.uninstall_welcome_page import UninstallWelcomePage
from src.ui.uninstall_progress_page import UninstallProgressPage
from src.ui.uninstall_done_page import UninstallDonePage
from src.core.openclaw_manager import OpenClawManager


class UninstallerWindow:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("OpenClaw Uninstaller")
        # 全局样式重置：避免 macOS 原生风格给 QLabel 添加边框
        self.app.setStyleSheet("QLabel { background: transparent; border: none; }")
        self._setup_window()

    def _setup_window(self):
        from PySide6.QtCore import QSize

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setWindowTitle("OpenClaw Uninstaller")

        screen = QApplication.primaryScreen().geometry()
        window_width = 600
        window_height = min(520, int(screen.height() * 0.7))
        self.stacked_widget.resize(window_width, window_height)
        self.stacked_widget.setMinimumSize(QSize(500, 420))

        self.welcome_page = UninstallWelcomePage()
        self.progress_page = UninstallProgressPage()
        self.done_page = UninstallDonePage()

        self.stacked_widget.addWidget(self.welcome_page)   # 0
        self.stacked_widget.addWidget(self.progress_page)  # 1
        self.stacked_widget.addWidget(self.done_page)      # 2

        self._connect_signals()

    def _connect_signals(self):
        self.welcome_page.confirm_clicked.connect(self._on_confirm)
        self.welcome_page.cancel_clicked.connect(self._on_exit)

        self.progress_page.cancel_clicked.connect(self._on_cancel_uninstall)

        self.done_page.recheck_clicked.connect(self._on_recheck)
        self.done_page.exit_clicked.connect(self._on_exit)

    def _on_confirm(self):
        self.progress_page.reset()
        self.stacked_widget.setCurrentIndex(1)
        self._start_uninstall()

    def _start_uninstall(self):
        class UninstallWorker(QThread):
            progress = Signal(int, str)
            log_line = Signal(str)
            complete = Signal(bool, list)

            def __init__(self, manager):
                super().__init__()
                self.manager = manager
                self._cancelled = False

            def run(self):
                failed_items = []
                # 手动逐步卸载以便反馈进度
                import os
                import shutil
                import platform
                import subprocess

                os_type = platform.system().lower()
                home = os.path.expanduser("~")

                # 1. 停止 Gateway
                self.progress.emit(10, "正在停止 Gateway 服务...")
                try:
                    self.manager._stop_gateway()
                    self.log_line.emit("✓ 已停止 OpenClaw Gateway")
                except Exception as e:
                    self.log_line.emit(f"⚠ 停止 Gateway 失败（可能未运行）: {e}")

                if self._cancelled:
                    return

                # 2. 删除源码目录
                self.progress.emit(25, "正在删除程序文件...")
                src_dir = os.path.join(home, "openclaw-cn")
                if os.path.exists(src_dir):
                    try:
                        shutil.rmtree(src_dir, onerror=self._remove_readonly)
                        self.log_line.emit(f"✓ 已删除: {src_dir}")
                    except Exception as e:
                        self.log_line.emit(f"✗ 删除 {src_dir} 失败: {e}")
                        failed_items.append("程序文件")
                else:
                    self.log_line.emit("ℹ 程序目录不存在，跳过")

                if self._cancelled:
                    return

                # 3. 删除配置目录
                self.progress.emit(45, "正在删除配置文件...")
                cfg_dir = os.path.join(home, ".openclaw")
                if os.path.exists(cfg_dir):
                    try:
                        shutil.rmtree(cfg_dir, onerror=self._remove_readonly)
                        self.log_line.emit(f"✓ 已删除: {cfg_dir}")
                    except Exception as e:
                        self.log_line.emit(f"✗ 删除 {cfg_dir} 失败: {e}")
                        failed_items.append("配置文件")
                else:
                    self.log_line.emit("ℹ 配置目录不存在，跳过")

                if self._cancelled:
                    return

                # 4. 卸载 npm 全局包
                self.progress.emit(65, "正在清理 npm 包...")
                for pkg in ["openclaw-cn", "openclaw"]:
                    try:
                        result = subprocess.run(
                            f'npm uninstall -g {pkg}',
                            shell=True, capture_output=True, text=True
                        )
                        if result.returncode == 0:
                            self.log_line.emit(f"✓ 已卸载 npm 包: {pkg}")
                        else:
                            self.log_line.emit(f"ℹ npm 包 {pkg} 未安装或已卸载")
                    except Exception as e:
                        self.log_line.emit(f"⚠ 卸载 {pkg} 出错: {e}")

                if self._cancelled:
                    return

                # 5. 删除命令包装器
                self.progress.emit(85, "正在清理命令行工具...")
                if os_type == "win32":
                    wrapper_dir = os.path.join(home, r"AppData\Roaming\npm")
                    wrappers = ["openclaw.cmd", "openclaw-cn.cmd"]
                else:
                    wrapper_dir = os.path.join(home, ".local", "bin")
                    wrappers = ["openclaw", "openclaw-cn"]

                for w in wrappers:
                    wpath = os.path.join(wrapper_dir, w)
                    if os.path.exists(wpath):
                        try:
                            os.remove(wpath)
                            self.log_line.emit(f"✓ 已删除命令: {wpath}")
                        except Exception as e:
                            self.log_line.emit(f"✗ 删除 {wpath} 失败: {e}")
                            failed_items.append("命令行工具")

                self.progress.emit(100, "卸载完成")
                self.log_line.emit("卸载流程结束")
                self.complete.emit(len(failed_items) == 0, failed_items)

            def cancel(self):
                self._cancelled = True

            @staticmethod
            def _remove_readonly(func, path, _):
                import stat
                os.chmod(path, stat.S_IWRITE)
                func(path)

        self._worker = UninstallWorker(self.openclaw_manager)
        self._worker.progress.connect(self.progress_page.set_progress)
        self._worker.log_line.connect(self.progress_page.add_log)
        self._worker.complete.connect(self._on_uninstall_complete)
        self._worker.start()

    def _on_cancel_uninstall(self):
        if hasattr(self, '_worker') and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self.stacked_widget.setCurrentIndex(0)

    def _on_uninstall_complete(self, ok: bool, failed_items: list):
        self.progress_page.set_done()
        if ok:
            self.done_page.set_success()
        else:
            self.done_page.set_partial(failed_items)
        self.stacked_widget.setCurrentIndex(2)

    def _on_recheck(self):
        self.stacked_widget.setCurrentIndex(0)
        self.welcome_page._check_installation()

    def _on_exit(self):
        self.stacked_widget.close()

    def show(self):
        self.stacked_widget.show()

    def run(self):
        return self.app.exec()


def main():
    # 创建轻量级的 manager（只用于卸载，不启动服务）
    window = UninstallerWindow()
    window.openclaw_manager = OpenClawManager()
    window.show()
    sys.exit(window.run())


if __name__ == "__main__":
    main()
