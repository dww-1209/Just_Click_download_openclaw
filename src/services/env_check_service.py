from PySide6.QtCore import QThread, Signal, QObject

from src.models.env_check import EnvCheckResult, OpenClawStatus
from src.infra.system_checker import check_environment


class EnvCheckWorker(QThread):
    """环境检测后台工作线程。

    职责：在独立线程中执行系统环境检测（磁盘、网络、权限、OpenClaw 安装状态、浏览器），
    并通过 Signal 向 UI 层回传检测进度和结果。
    """

    # Signal 方向：Worker -> Service -> UI 页面（env_check_page）
    started_check = Signal()                # 检测开始通知
    check_complete = Signal(EnvCheckResult) # 检测完成（携带完整结果）
    check_failed = Signal(str)              # 检测过程抛出异常

    def __init__(self, install_path: str | None = None, parent: QObject | None = None) -> None:
        """初始化环境检测工作线程。

        Args:
            install_path: 预期的安装路径，用于检测该路径下的磁盘空间和已有安装。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.install_path = install_path

    def run(self):
        """线程入口。执行环境检测并发射结果或异常。"""
        try:
            self.started_check.emit()
            result = check_environment(self.install_path)
            self.check_complete.emit(result)
        except Exception as e:
            self.check_failed.emit(str(e))


class EnvCheckService(QObject):
    """环境检测服务（UI 层与 Worker 之间的桥接层）。

    职责：管理 EnvCheckWorker 的生命周期，将 Worker 的 Signal 统一暴露给 UI 页面，
    并提供查询 OpenClaw 是否已安装的便捷方法。
    """

    # Signal 方向：Service -> UI 页面（env_check_page）
    check_complete = Signal(EnvCheckResult)  # 检测完成
    check_failed = Signal(str)               # 检测失败

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化环境检测服务。

        Args:
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.worker: EnvCheckWorker | None = None
        self.result: EnvCheckResult | None = None

    def start_check(self, install_path: str | None = None) -> None:
        """启动环境检测流程。

        创建 EnvCheckWorker 并连接所有 Signal，然后启动线程。

        Args:
            install_path: 预期的安装路径。
        """
        self.worker = EnvCheckWorker(install_path)
        self.worker.started_check.connect(self._on_started)
        self.worker.check_complete.connect(self._on_service_complete)
        self.worker.check_failed.connect(self._on_service_failed)
        self.worker.start()

    def _on_service_complete(self, result: EnvCheckResult) -> None:
        """内部槽：保存检测结果并转发完成 Signal。

        Args:
            result: 环境检测总结果对象。
        """
        self.result = result
        self.check_complete.emit(result)

    def _on_service_failed(self, error: str) -> None:
        """内部槽：转发失败 Signal。

        Args:
            error: 异常描述字符串。
        """
        self.check_failed.emit(error)

    def _on_started(self) -> None:
        """内部槽：检测开始时的占位回调（当前无额外逻辑）。"""
        pass

    def is_openclaw_installed(self) -> bool:
        """查询 OpenClaw 是否已安装。

        Returns:
            True 表示已检测到 OpenClaw 安装，False 表示未安装或尚未完成检测。
        """
        if self.result:
            return self.result.openclaw_install.status == OpenClawStatus.INSTALLED
        return False

    def stop(self) -> None:
        """停止环境检测线程。请求退出并等待线程结束。"""
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
