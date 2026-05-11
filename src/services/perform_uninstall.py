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
        """线程入口。直接调用 manager.uninstall() 同步执行卸载流程。

        重要历史教训:
        之前这里包了一个 threading.Thread + Event.wait(timeout=120) 试图加超时,
        但 wait() 是阻塞调用,会让 QThread 无法处理 Qt 事件 120 秒,Windows
        会判定整个 GUI 进程"无响应"并弹出"是否关闭程序"。daemon 子线程也不能
        被强杀,即便 wait 超时返回,子线程仍在跑,造成更深的死锁。

        正确做法: 直接同步调 manager.uninstall(),内部所有 subprocess.run 都
        有自己的 timeout(taskkill 2s, attrib 30s, rmdir 60s),不会真正"无限
        hang"。force_rmtree 的逐文件删除是 Python 原生 os.unlink,几千个文件
        也就几秒,不需要外层超时。
        """
        failed_items: list[str] = []

        self.progress.emit(10, "正在停止 Gateway 服务...")

        def on_log(message: str) -> None:
            """日志回调：将 manager 的日志转发为 Signal,并推断进度。"""
            self.log_line.emit(message)
            if "停止" in message or "Gateway" in message:
                self.progress.emit(20, message)
            elif "正在删除旧文件" in message:
                self.progress.emit(35, message)
            elif "删除" in message and "openclaw-cn" in message:
                self.progress.emit(40, message)
            elif "删除" in message and ".openclaw" in message:
                self.progress.emit(60, message)
            elif "旧文件已处理" in message:
                self.progress.emit(65, message)
            elif "正在清理 npm" in message or "npm 包已清理" in message:
                self.progress.emit(80, message)
            elif "命令" in message:
                self.progress.emit(90, message)
            elif "清理完成" in message:
                self.progress.emit(95, message)

        try:
            ok = self.manager.uninstall(
                on_log=on_log,
                cancel_event=self._cancel_event.is_set,
            )
            if not ok:
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
        """强制停止卸载线程。请求取消,但不在主线程同步等待。

        Windows 关键问题: worker.wait() 是阻塞调用,会让 Qt 主线程在用户点
        "取消"或关窗口时同步等几十秒(force_rmtree 删 100k 个文件),5 秒内
        不响应 DWM 探测就触发"程序无响应"弹窗。
        改成只设置 cancel 标志,Worker 会在下一次 cancel_event 检查点自行退出。
        若调用方需要阻塞等待(如 closeEvent),应自己用带 timeout 的 wait。
        """
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
