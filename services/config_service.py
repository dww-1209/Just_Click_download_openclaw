from PySide6.QtCore import QThread, Signal, QObject

from models.config import (
    OpenClawConfig,
    ConfigStatus,
    ConfigProgress,
    ConfigResult,
)
from core.openclaw_manager import OpenClawManager


class ConfigWorker(QThread):
    """配置工作线程"""

    progress_updated = Signal(ConfigProgress)
    config_complete = Signal(ConfigResult)
    config_failed = Signal(str)

    def __init__(self, install_path: str, parent=None):
        super().__init__(parent)
        self.install_path = install_path
        self.manager = OpenClawManager(install_path)

    def run(self):
        try:
            result = self.manager.setup_and_start(
                on_progress=self._on_progress,
            )
            self.config_complete.emit(result)
        except Exception as e:
            self.config_failed.emit(str(e))

    def _on_progress(self, progress: ConfigProgress):
        self.progress_updated.emit(progress)

    def stop(self):
        self.manager.stop()


class ConfigService(QObject):
    """配置服务"""

    progress_updated = Signal(ConfigProgress)
    config_complete = Signal(ConfigResult)
    config_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ConfigWorker = None
        self.result: ConfigResult = None

    def start_config(self, install_path: str):
        """开始配置和启动"""
        self.worker = ConfigWorker(install_path)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.config_complete.connect(self._on_complete)
        self.worker.config_failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, progress: ConfigProgress):
        self.progress_updated.emit(progress)

    def _on_complete(self, result: ConfigResult):
        self.result = result
        self.config_complete.emit(result)

    def _on_failed(self, error: str):
        self.config_failed.emit(error)

    def stop(self):
        """停止服务"""
        if self.worker:
            self.worker.stop()
            if self.worker.isRunning():
                self.worker.quit()
                self.worker.wait()
