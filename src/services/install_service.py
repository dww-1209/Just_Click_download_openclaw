from PySide6.QtCore import QThread, Signal, QObject
from typing import Callable

from src.models.install import (
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
)
from src.infra.openclaw_installer import OpenClawInstaller


class InstallWorker(QThread):
    """安装后台工作线程。

    职责：在独立线程中执行 OpenClaw 的完整安装流程，通过 Signal 向 UI 层回传进度、日志和结果。
    """

    # Signal 方向：Worker -> Service -> UI 页面（installing_page）
    progress_updated = Signal(InstallProgress)   # 安装进度更新
    log_updated = Signal(str)                    # 单行日志输出
    install_complete = Signal(InstallResult)     # 安装完成（成功）
    install_failed = Signal(str)                 # 安装失败（异常信息）

    def __init__(self, os_type: str | None = None, parent: QObject | None = None) -> None:
        """初始化安装工作线程。

        Args:
            os_type: 目标操作系统类型（windows / linux / macos），用于选择平台特定的安装逻辑。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.os_type = os_type
        self.installer = OpenClawInstaller(os_type)

    def run(self) -> None:
        """线程入口。调用 OpenClawInstaller 执行安装，并转发结果或异常。"""
        try:
            result = self.installer.install(
                on_progress=self._on_progress,
                on_log=self._on_log,
            )
            self.install_complete.emit(result)
        except Exception as e:
            self.install_failed.emit(str(e))

    def _on_progress(self, progress: InstallProgress) -> None:
        """内部回调：将安装进度通过 Signal 发射出去。

        Args:
            progress: 当前安装进度对象。
        """
        self.progress_updated.emit(progress)

    def _on_log(self, log_line: str) -> None:
        """内部回调：将日志行通过 Signal 发射出去。

        Args:
            log_line: 单条日志文本。
        """
        self.log_updated.emit(log_line)

    def cancel(self) -> None:
        """请求取消安装。会转发给 OpenClawInstaller 的取消标志。"""
        self.installer.cancel()


class InstallService(QObject):
    """安装服务（UI 层与 Worker 之间的桥接层）。

    职责：管理 InstallWorker 的生命周期，将 Worker 的 Signal 统一暴露给 UI 页面，
    使 UI 无需直接操作 QThread。
    """

    # Signal 方向：Service -> UI 页面（installing_page）
    progress_updated = Signal(InstallProgress)   # 安装进度更新
    log_updated = Signal(str)                    # 单行日志输出
    install_complete = Signal(InstallResult)     # 安装完成
    install_failed = Signal(str)                 # 安装失败

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化安装服务。

        Args:
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.worker: InstallWorker | None = None
        self.result: InstallResult | None = None

    def start_install(self, os_type: str | None = None) -> None:
        """启动安装流程。

        创建 InstallWorker 并连接所有 Signal，然后启动线程。

        Args:
            os_type: 目标操作系统类型。
        """
        self.worker = InstallWorker(os_type)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.log_updated.connect(self._on_log)
        self.worker.install_complete.connect(self._on_complete)
        self.worker.install_failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, progress: InstallProgress) -> None:
        """内部槽：转发进度 Signal。

        Args:
            progress: 当前安装进度对象。
        """
        self.progress_updated.emit(progress)

    def _on_log(self, log_line: str) -> None:
        """内部槽：转发日志 Signal。

        Args:
            log_line: 单条日志文本。
        """
        self.log_updated.emit(log_line)

    def _on_complete(self, result: InstallResult) -> None:
        """内部槽：保存结果并转发完成 Signal。

        Args:
            result: 安装结果对象。
        """
        self.result = result
        self.install_complete.emit(result)

    def _on_failed(self, error: str) -> None:
        """内部槽：转发失败 Signal。

        Args:
            error: 异常描述字符串。
        """
        self.install_failed.emit(error)

    def cancel_install(self) -> None:
        """取消当前安装。仅设置取消标志，不强制终止线程。"""
        if self.worker:
            self.worker.cancel()

    def stop(self) -> None:
        """强制停止安装线程。先请求取消，再退出并等待线程结束。"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.quit()
            self.worker.wait()
