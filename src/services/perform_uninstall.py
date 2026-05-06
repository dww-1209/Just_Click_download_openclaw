"""卸载服务模块

职责：提供卸载后台工作线程（QThread）和服务层桥接，
使 launch_uninstaller.py 入口无需直接操作 core/adapters 层。

设计要点：
- UninstallWorker 通过 IOpenClawManager 接口调用卸载逻辑，
  避免在 Worker 中重写与 openclaw_manager.uninstall() 重复的逻辑。
- UninstallService 管理 Worker 生命周期，将 Signal 统一暴露给 UI。
"""

import threading

from PySide6.QtCore import QThread, Signal, QObject

from src.contracts.define_manager import IOpenClawManager


class UninstallWorker(QThread):
    """卸载后台工作线程。

    职责：在独立线程中执行 OpenClaw 的完全卸载流程，
    通过 IOpenClawManager 接口调用卸载逻辑，避免重复实现。
    """

    # Signal 方向：Worker -> Service -> UI 页面（uninstall_progress_page）
    progress = Signal(int, str)       # 进度百分比, 状态文本
    log_line = Signal(str)            # 单条日志
    complete = Signal(bool, list)     # 是否全部成功, 失败项列表

    def __init__(self, manager: IOpenClawManager) -> None:
        """初始化卸载工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例（通过接口引用）。
        """
        super().__init__()
        self.manager = manager
        self._cancel_event = threading.Event()

    def run(self) -> None:
        """线程入口。调用 manager.uninstall() 执行卸载，并转发日志和结果。"""
        failed_items: list[str] = []

        self.progress.emit(10, "正在停止 Gateway 服务...")
        # manager.uninstall 内部会处理停止 Gateway、删除目录、清理 npm 包和包装器
        # 我们通过 on_log 回调收集进度信息

        def on_log(message: str) -> None:
            """日志回调：将 manager 的日志转发为 Signal。"""
            self.log_line.emit(message)
            # 根据日志内容推断进度
            if "停止" in message or "Gateway" in message:
                self.progress.emit(20, message)
            elif "删除" in message and "openclaw-cn" in message:
                self.progress.emit(40, message)
            elif "删除" in message and ".openclaw" in message:
                self.progress.emit(60, message)
            elif "npm" in message or "卸载" in message:
                self.progress.emit(80, message)
            elif "命令" in message:
                self.progress.emit(90, message)

        try:
            ok = self.manager.uninstall(
                on_log=on_log,
                cancel_event=self._cancel_event.is_set,
            )
            if not ok:
                # 如果 manager 返回 False，标记为部分失败
                failed_items.append("部分清理步骤")
        except Exception as e:
            self.log_line.emit(f"卸载异常: {e}")
            failed_items.append("卸载过程")

        if self._cancel_event.is_set():
            self.log_line.emit("卸载已取消")
            self.progress.emit(0, "已取消")
            self.complete.emit(False, ["用户取消"])
            return

        self.progress.emit(100, "卸载完成")
        self.complete.emit(len(failed_items) == 0, failed_items)

    def cancel(self) -> None:
        """请求取消卸载。设置取消标志，run() 中会检查并提前返回。"""
        self._cancel_event.set()
        # 同时通知 manager 停止（manager.stop 会停止 Gateway 并标记取消）
        self.manager.stop()


class UninstallService(QObject):
    """卸载服务（UI 层与 Worker 之间的桥接层）。

    职责：管理 UninstallWorker 的生命周期，将 Worker 的 Signal 统一暴露给 UI 页面。
    """

    # Signal 方向：Service -> UI 页面（uninstall_progress_page）
    progress = Signal(int, str)       # 进度百分比, 状态文本
    log_line = Signal(str)            # 单条日志
    complete = Signal(bool, list)     # 是否全部成功, 失败项列表

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化卸载服务。

        Args:
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.worker: UninstallWorker | None = None

    def start_uninstall(self, manager: IOpenClawManager) -> None:
        """启动卸载流程。

        创建 UninstallWorker 并连接所有 Signal，然后启动线程。

        Args:
            manager: OpenClaw 生命周期管理器实例（通过接口引用）。
        """
        self.worker = UninstallWorker(manager)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_line.connect(self._on_log)
        self.worker.complete.connect(self._on_complete)
        self.worker.start()

    def _on_progress(self, percent: int, message: str) -> None:
        """内部槽：转发进度 Signal。"""
        self.progress.emit(percent, message)

    def _on_log(self, log_line: str) -> None:
        """内部槽：转发日志 Signal。"""
        self.log_line.emit(log_line)

    def _on_complete(self, ok: bool, failed_items: list[str]) -> None:
        """内部槽：转发完成 Signal。"""
        self.complete.emit(ok, failed_items)

    def cancel_uninstall(self) -> None:
        """取消当前卸载。仅设置取消标志，不强制终止线程。"""
        if self.worker:
            self.worker.cancel()

    def stop(self) -> None:
        """强制停止卸载线程。请求取消并等待线程自然结束。"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
