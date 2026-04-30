from PySide6.QtCore import QThread, Signal

from src.core.openclaw_manager import OpenClawManager


class ConfigWorker(QThread):
    """OpenClaw 配置后台工作线程。

    职责：在独立线程中执行 OpenClaw 的初始化配置（onboard），
    通过 Signal 向 UI 层回传进度、日志和配置结果。
    """

    # Signal 方向：Worker -> UI 页面（config_page）
    progress_updated = Signal(object)  # 配置进度更新（携带 ConfigProgress 对象）
    log_line = Signal(str)             # 单行日志输出
    complete = Signal(object)          # 配置完成（携带 ConfigResult 对象）

    def __init__(self, manager: OpenClawManager):
        """初始化配置工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例，负责实际配置逻辑。
        """
        super().__init__()
        self.manager = manager

    def run(self):
        """线程入口。调用 OpenClawManager.configure_only 执行配置，并发射结果。"""
        result = self.manager.configure_only(
            on_progress=self.progress_updated.emit,
            on_log=self.log_line.emit,
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

    def __init__(self, manager: OpenClawManager, quick_start: bool = False):
        """初始化启动工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例。
            quick_start: 是否使用快速启动模式（跳过部分初始化步骤）。
        """
        super().__init__()
        self.manager = manager
        self.quick_start = quick_start

    def run(self):
        """线程入口。调用 OpenClawManager.startup_only 执行启动，并发射结果。"""
        result = self.manager.startup_only(
            on_progress=self.progress_updated.emit,
            on_log=self.log_line.emit,
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
        manager: OpenClawManager,
        providers_config: dict,
        global_default_model: str,
        fallback_models: list,
    ):
        """初始化 Provider 配置工作线程。

        Args:
            manager: OpenClaw 生命周期管理器实例。
            providers_config: 各供应商的配置字典，格式为 {vendor_id: {key_type: {env_var: value, ...}, ...}}。
            global_default_model: 用户选择的全局默认模型 ref（如 "moonshot/kimi-k2.5"）。
            fallback_models: 全局 fallback 模型列表，按优先级排序。
        """
        super().__init__()
        self.manager = manager
        self.providers_config = providers_config
        self.global_default_model = global_default_model
        self.fallback_models = fallback_models

    def run(self):
        """线程入口。调用 OpenClawManager.configure_providers 写入配置，并发射布尔结果。"""
        ok = self.manager.configure_providers(
            self.providers_config,
            self.global_default_model,
            self.fallback_models,
            on_progress=self.progress_updated.emit,
            on_log=self.log_line.emit,
        )
        self.complete.emit(ok)
