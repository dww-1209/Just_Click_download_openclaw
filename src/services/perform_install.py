from PySide6.QtCore import QThread, Signal, QObject
from typing import Callable

import time

from src.models.install import (
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
    InstallErrorDetail,
    ErrorCategory,
)
from src.contracts.define_installer import IInstaller


class ReinstallWorker(QThread):
    """重装前清理后台工作线程。

    职责：在独立线程中触发旧安装清理（停止 Gateway、删除目录、卸载 npm 包），
    完成后通过 Signal 通知 UI 进入安装阶段。
    所有阻塞操作（子进程调用、文件删除）由 adapters 层 cleanup_for_reinstall 完成,
    services 层只做线程编排,不直接调用 subprocess。
    """

    complete = Signal(bool)  # 清理完成信号（True 表示已执行，继续后续流程）
    log_line = Signal(str)   # 清理日志输出

    def run(self) -> None:
        """线程入口：调用 adapter 执行清理,完成后发射信号。

        重要历史教训(同 UninstallWorker):
        不要在 QThread.run 内再开一个 threading.Thread + Event.wait(timeout)
        来加超时,wait 是阻塞调用,会卡住 QThread 事件循环,Windows 会把整个
        GUI 进程判为"无响应"。adapter 内部 subprocess 都有自己的 timeout,
        force_rmtree 是 Python 原生 os.unlink 不会真正 hang,直接同步调即可。
        """
        try:
            from src.adapters.cleanup_reinstall import cleanup_for_reinstall
            cleanup_for_reinstall(on_log=self.log_line.emit)
        except Exception as e:
            self.log_line.emit(f"清理过程出错: {e}")
        # 不管成功失败都发 True,继续安装流程(adapter 是尽力而为语义)
        self.complete.emit(True)


class InstallWorker(QThread):
    """安装后台工作线程。

    职责：在独立线程中执行 OpenClaw 的完整安装流程，通过 Signal 向 UI 层回传进度、日志和结果。
    """

    # Signal 方向：Worker -> Service -> UI 页面（installing_page）
    progress_updated = Signal(InstallProgress)   # 安装进度更新
    log_updated = Signal(str)                    # 单行日志输出
    install_complete = Signal(InstallResult)     # 安装完成（含成功/失败/取消）

    def __init__(self, installer: IInstaller, parent: QObject | None = None) -> None:
        """初始化安装工作线程。

        Args:
            installer: 安装器实例（通过接口注入，避免硬编码具体类）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.installer = installer
        self._worker_start_time = time.time()

    def run(self) -> None:
        """线程入口。调用安装器接口执行安装，并转发结果或异常。

        异常时不再仅发射 install_failed 字符串，而是构造包含日志和耗时的
        完整 InstallResult 并通过 install_complete 发射，使 UI 层能统一处理
        成功与失败路径。
        """
        try:
            result = self.installer.install(
                on_progress=self._on_progress,
                on_log=self._on_log,
            )
            self.install_complete.emit(result)
        except Exception as e:
            self._on_log(f"安装异常: {e}")
            start_time = getattr(self.installer, "start_time", self._worker_start_time)
            result = InstallResult(
                status=InstallStatus.FAILED,
                message="安装异常",
                error_message=str(e),
                log_lines=getattr(self.installer, "log_lines", []),
                duration_seconds=time.time() - start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.UNKNOWN,
                    stage="INSTALLING",
                    context="InstallWorker 异常捕获",
                    raw_error=str(e),
                    user_message="安装过程中发生异常",
                    suggestion="请查看日志获取详细信息，或尝试重新安装",
                ),
            )
            self.install_complete.emit(result)

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
        """请求取消安装。会转发给安装器接口的 cancel 方法。"""
        self.installer.cancel()


class InstallService(QObject):
    """安装服务（UI 层与 Worker 之间的桥接层）。

    职责：管理 InstallWorker 的生命周期，将 Worker 的 Signal 统一暴露给 UI 页面，
    使 UI 无需直接操作 QThread。
    """

    # Signal 方向：Service -> UI 页面（installing_page）
    progress_updated = Signal(InstallProgress)   # 安装进度更新
    log_updated = Signal(str)                    # 单行日志输出
    install_complete = Signal(InstallResult)     # 安装完成（含成功/失败/取消）

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化安装服务。

        Args:
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.worker: InstallWorker | None = None
        self.result: InstallResult | None = None

    def start_install(self, installer: IInstaller) -> None:
        """启动安装流程。

        创建 InstallWorker 并连接所有 Signal，然后启动线程。

        Args:
            installer: 安装器实例（通过接口注入，由装配器层创建）。
        """
        self.worker = InstallWorker(installer)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.log_updated.connect(self._on_log)
        self.worker.install_complete.connect(self._on_complete)
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
