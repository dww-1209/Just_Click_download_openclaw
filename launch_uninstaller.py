"""OpenClaw 卸载工具 — 独立程序入口

提供三页卸载流程：欢迎/检测 → 进度执行 → 完成清单。
卸载逻辑通过 UninstallService 在 QThread 中执行，避免阻塞 UI 主线程。

注意：本文件属于「装配器层」（Composition Root），负责组装对象图并连接信号。
在规范架构中，入口文件允许导入所有层来完成依赖注入。
"""

import sys
from pathlib import Path

# 确保 src/ 在模块搜索路径中（无论从哪里启动）
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QStackedWidget, QMessageBox
from PySide6.QtCore import Qt

from src.ui.show_uninstall_welcome import UninstallWelcomePage
from src.ui.show_uninstall_progress import UninstallProgressPage
from src.ui.show_uninstall_done import UninstallDonePage
from src.services.perform_uninstall import UninstallService
from src.core.manage_openclaw import OpenClawManager


class UninstallerWindow:
    """卸载器主窗口控制器

    管理三页流程：欢迎页 → 进度页 → 完成页。
    卸载操作通过 UninstallService 在后台线程中执行，通过 Signal 反馈进度。
    """

    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("OpenClaw Uninstaller")
        # 全局样式重置：避免 macOS 原生风格给 QLabel 添加边框
        self.app.setStyleSheet("QLabel { background: transparent; border: none; }")
        self.openclaw_manager = OpenClawManager()
        self._setup_window()

    def _setup_window(self) -> None:
        """初始化卸载器窗口和三页 UI"""
        from PySide6.QtCore import QSize

        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setWindowTitle("OpenClaw Uninstaller")

        # 窗口尺寸自适应屏幕高度，最大不超过屏幕 70%
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

    def _connect_signals(self) -> None:
        """连接各页面按钮信号到对应的槽函数"""
        self.welcome_page.confirm_clicked.connect(self._on_confirm)
        self.welcome_page.cancel_clicked.connect(self._on_exit)

        self.progress_page.cancel_clicked.connect(self._on_cancel_uninstall)

        self.done_page.recheck_clicked.connect(self._on_recheck)
        self.done_page.exit_clicked.connect(self._on_exit)

    def _on_confirm(self) -> None:
        """欢迎页点击'确认卸载'：重置进度页并开始卸载"""
        self.progress_page.reset()
        self.stacked_widget.setCurrentIndex(1)
        self._start_uninstall()

    def _start_uninstall(self) -> None:
        """创建卸载服务并启动卸载后台线程

        通过 UninstallService 桥接 UI 与 Worker，Worker 通过 IOpenClawManager
        接口调用 manager.uninstall() 执行实际卸载逻辑。
        """
        self._service = UninstallService()
        self._service.progress.connect(self.progress_page.set_progress)
        self._service.log_line.connect(self.progress_page.add_log)
        self._service.complete.connect(self._on_uninstall_complete)
        self._service.start_uninstall(self.openclaw_manager)

    def _on_cancel_uninstall(self) -> None:
        """进度页点击'取消'：请求取消并等待线程退出，回到欢迎页"""
        if hasattr(self, '_service'):
            self._service.stop()
        self.stacked_widget.setCurrentIndex(0)

    def _on_uninstall_complete(self, ok: bool, failed_items: list) -> None:
        """卸载完成回调：切换完成页，显示成功或部分失败结果"""
        self.progress_page.set_done()
        if ok:
            self.done_page.set_success()
        else:
            self.done_page.set_partial(failed_items)
        self.stacked_widget.setCurrentIndex(2)

    def _on_recheck(self) -> None:
        """完成页点击'重新检测'：回到欢迎页并重新检测安装状态"""
        self.stacked_widget.setCurrentIndex(0)
        self.welcome_page.check_installation()

    def _on_exit(self) -> None:
        """退出程序"""
        self.stacked_widget.close()

    def show(self) -> None:
        """显示卸载器窗口"""
        self.stacked_widget.show()

    def run(self) -> int:
        """进入 Qt 事件循环"""
        return self.app.exec()


def main() -> None:
    """程序入口：创建卸载器实例并启动事件循环

    使用轻量级 OpenClawManager（仅用于停止 Gateway，不启动服务）。
    """
    window = UninstallerWindow()
    window.show()
    sys.exit(window.run())


if __name__ == "__main__":
    main()
