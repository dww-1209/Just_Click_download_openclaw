from PySide6.QtCore import QThread, Signal, QObject
from typing import Callable

from models.install import (
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
)
from infra.openclaw_installer import OpenClawInstaller


class InstallWorker(QThread):
    """安装工作线程"""

    progress_updated = Signal(InstallProgress)
    log_updated = Signal(str)
    install_complete = Signal(InstallResult)
    install_failed = Signal(str)

    def __init__(self, os_type: str = None, parent=None):
        super().__init__(parent)
        self.os_type = os_type
        self.installer = OpenClawInstaller(os_type)

    def run(self):
        try:
            result = self.installer.install(
                on_progress=self._on_progress,
                on_log=self._on_log,
            )
            self.install_complete.emit(result)
        except Exception as e:
            self.install_failed.emit(str(e))

    def _on_progress(self, progress: InstallProgress):
        self.progress_updated.emit(progress)

    def _on_log(self, log_line: str):
        self.log_updated.emit(log_line)

    def cancel(self):
        self.installer.cancel()


class InstallService(QObject):
    """安装服务"""

    progress_updated = Signal(InstallProgress)
    log_updated = Signal(str)
    install_complete = Signal(InstallResult)
    install_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: InstallWorker = None
        self.result: InstallResult = None

    def start_install(self, os_type: str = None):
        """开始安装"""
        self.worker = InstallWorker(os_type)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.log_updated.connect(self._on_log)
        self.worker.install_complete.connect(self._on_complete)
        self.worker.install_failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, progress: InstallProgress):
        self.progress_updated.emit(progress)

    def _on_log(self, log_line: str):
        self.log_updated.emit(log_line)

    def _on_complete(self, result: InstallResult):
        self.result = result
        self.install_complete.emit(result)

    def _on_failed(self, error: str):
        self.install_failed.emit(error)

    def cancel_install(self):
        """取消安装"""
        if self.worker:
            self.worker.cancel()

    def stop(self):
        """停止服务"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.quit()
            self.worker.wait()
