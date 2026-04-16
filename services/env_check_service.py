from PySide6.QtCore import QThread, Signal, QObject

from models.env_check import EnvCheckResult, OpenClawStatus
from infra.system_checker import check_environment


class EnvCheckWorker(QThread):
    """环境检测后台工作线程"""

    started_check = Signal()
    check_complete = Signal(EnvCheckResult)
    check_failed = Signal(str)

    def __init__(self, install_path: str = None, parent=None):
        super().__init__(parent)
        self.install_path = install_path

    def run(self):
        try:
            self.started_check.emit()
            result = check_environment(self.install_path)
            self.check_complete.emit(result)
        except Exception as e:
            self.check_failed.emit(str(e))


class EnvCheckService(QObject):
    """环境检测服务"""

    check_complete = Signal(EnvCheckResult)
    check_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: EnvCheckWorker = None
        self.result: EnvCheckResult = None

    def start_check(self, install_path: str = None):
        self.worker = EnvCheckWorker(install_path)
        self.worker.started_check.connect(self._on_started)
        self.worker.check_complete.connect(self._on_service_complete)
        self.worker.check_failed.connect(self._on_service_failed)
        self.worker.start()

    def _on_service_complete(self, result: EnvCheckResult):
        self.result = result
        self.check_complete.emit(result)

    def _on_service_failed(self, error: str):
        self.check_failed.emit(error)

    def _on_started(self):
        pass

    def is_openclaw_installed(self) -> bool:
        if self.result:
            return self.result.openclaw_install.status == OpenClawStatus.INSTALLED
        return False

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
