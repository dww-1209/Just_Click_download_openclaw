from typing import Any

from PySide6.QtCore import QThread, Signal

from src.contracts.define_manager import IOpenClawManager
from src.models.config import ConfigResult, ConfigStatus, ServiceStatus


class ConfigWorker(QThread):
    """OpenClaw 配置后台工作线程。

    职责：在独立线程中执行 OpenClaw 的初始化配置（onboard），
    通过 Signal 向 UI 层回传进度、日志和配置结果。
    """

    # Signal 方向：Worker -> UI 页面（config_page）
    progress_updated = Signal(object)  # 配置进度更新（携带 ConfigProgress 对象）
    log_line = Signal(str)             # 单行日志输出
    complete = Signal(object)          # 配置完成（携带 ConfigResult 对象）

    def __init__(self, manager: IOpenClawManager) -> None:
        """初始化配置工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例（通过接口引用）。
        """
        super().__init__()
        self.manager = manager

    def run(self) -> None:
        """线程入口。调用 OpenClawManager.configure_only 执行配置，并发射结果。

        manager.configure_only 内部已捕获绝大多数异常并返回 ConfigResult,
        但若它本身抛出(如 import 错误、类型错误),也要保证 UI 收到 complete
        信号,否则进度页会卡死等待。
        """
        try:
            result = self.manager.configure_only(
                on_progress=self.progress_updated.emit,
                on_log=self.log_line.emit,
            )
        except Exception as e:
            self.log_line.emit(f"配置异常: {type(e).__name__}: {e}")
            result = ConfigResult(
                status=ConfigStatus.FAILED,
                service_status=ServiceStatus.FAILED,
                message="配置异常",
                error_message=str(e),
            )
        self.complete.emit(result)


class StartupWorker(QThread):
    """OpenClaw 启动后台工作线程。

    职责：在独立线程中执行网关启动、健康检查和浏览器打开流程，
    通过 Signal 向 UI 层回传进度、日志和启动结果。
    """

    # Signal 方向：Worker -> UI 页面（config_page / startup_page）
    progress_updated = Signal(object)  # 启动进度更新（携带 ConfigProgress 对象）
    log_line = Signal(str)             # 单行日志输出
    complete = Signal(object)          # 启动完成（携带 ConfigResult 对象）

    def __init__(self, manager: IOpenClawManager, quick_start: bool = False) -> None:
        """初始化启动工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例（通过接口引用）。
            quick_start: 是否使用快速启动模式（跳过部分初始化步骤）。
        """
        super().__init__()
        self.manager = manager
        self.quick_start = quick_start

    def run(self) -> None:
        """线程入口。调用 manager 启动并发射结果。

        quick_start=True 时调用 manager.quick_start()(语义上"已配置过的快速启动"),
        否则调 startup_only。当前两者实现等价,保留这层接驳是为了:
        1. 让"快速启动"路径在 UI 日志中可被识别;
        2. 未来 manager.quick_start 若需特化(如跳过更多检查),改一处即可。

        manager 内部已捕获大部分异常,这里再加一层兜底,保证 complete 信号一定 emit。
        """
        try:
            if self.quick_start:
                result = self.manager.quick_start(
                    on_progress=self.progress_updated.emit,
                    on_log=self.log_line.emit,
                )
            else:
                result = self.manager.startup_only(
                    on_progress=self.progress_updated.emit,
                    on_log=self.log_line.emit,
                )
        except Exception as e:
            self.log_line.emit(f"启动异常: {type(e).__name__}: {e}")
            result = ConfigResult(
                status=ConfigStatus.FAILED,
                service_status=ServiceStatus.FAILED,
                message="启动异常",
                error_message=str(e),
            )
        self.complete.emit(result)


class ProviderConfigWorker(QThread):
    """AI Provider 配置后台工作线程。

    职责：在独立线程中执行多供应商 API Key 和模型配置写入，
    通过 Signal 向 UI 层回传进度、日志和配置是否成功。
    """

    # Signal 方向：Worker -> UI 页面（provider_config_page）
    progress_updated = Signal(object)  # 配置进度更新（携带 ConfigProgress 对象）
    log_line = Signal(str)             # 单行日志输出
    complete = Signal(bool)            # 配置完成（True 表示成功，False 表示失败）

    def __init__(
        self,
        manager: IOpenClawManager,
        providers_config: dict[str, Any],
        global_default_model: str,
        fallback_models: list[str],
    ) -> None:
        """初始化 Provider 配置工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例（通过接口引用）。
            providers_config: 各供应商的配置字典，格式为 {vendor_id: {key_type: {env_var: value, ...}, ...}}。
            global_default_model: 用户选择的全局默认模型 ref（如 "moonshot/kimi-k2.5"）。
            fallback_models: 全局 fallback 模型列表，按优先级排序。
        """
        super().__init__()
        self.manager = manager
        self.providers_config = providers_config
        self.global_default_model = global_default_model
        self.fallback_models = fallback_models

    def run(self) -> None:
        """线程入口。调用 OpenClawManager.configure_providers 写入配置，并发射布尔结果。

        manager 异常时(如配置文件被外部进程占用、磁盘只读),保证 complete(False)
        一定 emit,否则 UI 配置页会一直转圈。
        """
        try:
            ok = self.manager.configure_providers(
                self.providers_config,
                self.global_default_model,
                self.fallback_models,
                on_progress=self.progress_updated.emit,
                on_log=self.log_line.emit,
            )
        except Exception as e:
            self.log_line.emit(f"Provider 配置异常: {type(e).__name__}: {e}")
            ok = False
        self.complete.emit(ok)
