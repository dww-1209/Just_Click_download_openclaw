"""OpenClaw 生命周期管理器接口定义

职责：抽象 OpenClaw 的配置、启动、Provider 配置和卸载等核心操作，
使 Worker 和 Service 层可以不依赖具体的 OpenClawManager 实现。
"""

from __future__ import annotations

from typing import Protocol, Callable, Optional, Any

from src.models.config import ConfigResult, ConfigProgress
from src.contracts.define_worker import LogCallback as ConfigLogCallback, ConfigProgressCallback


class IOpenClawManager(Protocol):
    """OpenClaw 生命周期管理器接口。

    管理 OpenClaw 的完整生命周期：配置初始化、网关启停、Provider 配置、卸载。
    所有耗时操作均通过回调函数向调用方汇报进度。
    """

    def configure_only(
        self,
        on_progress: ConfigProgressCallback | None = None,
        on_log: ConfigLogCallback | None = None,
    ) -> ConfigResult:
        """仅执行配置，不启动网关（US-05）。

        流程：检测安装 → 设置默认配置 → 执行 onboard → 注入浏览器配置。

        Args:
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            ConfigResult: 包含状态、服务状态、消息及完整日志。
        """
        ...

    def startup_only(
        self,
        on_progress: ConfigProgressCallback | None = None,
        on_log: ConfigLogCallback | None = None,
    ) -> ConfigResult:
        """仅启动网关并获取 WebUI 地址，不自动打开浏览器（US-06）。

        流程：启动网关 → 健康检查（端口 18789）→ 获取 dashboard URL。

        Args:
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            ConfigResult: 若成功则包含 webchat_url 和 RUNNING 状态。
        """
        ...

    def quick_start(
        self,
        on_progress: ConfigProgressCallback | None = None,
        on_log: ConfigLogCallback | None = None,
    ) -> ConfigResult:
        """快速启动：跳过配置，直接启动网关。

        本质上是 startup_only 的别名，用于已配置过的场景。

        Args:
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            ConfigResult: 启动结果。
        """
        ...

    def setup_and_start(
        self,
        on_progress: ConfigProgressCallback | None = None,
    ) -> ConfigResult:
        """先配置再启动（config + startup）。

        先调用 configure_only，若成功再调用 startup_only。

        Args:
            on_progress: 进度回调。

        Returns:
            ConfigResult: 最终结果。
        """
        ...

    def configure_providers(
        self,
        providers_config: dict[str, Any],
        global_default_model: str,
        fallback_models: Optional[list[str]] = None,
        on_progress: ConfigProgressCallback | None = None,
        on_log: ConfigLogCallback | None = None,
    ) -> bool:
        """配置 AI Provider：写入 env 变量和默认模型。

        Args:
            providers_config: 各供应商的配置字典。
            global_default_model: 全局默认 model ref。
            fallback_models: 备选模型列表。
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            bool: 是否全部成功。
        """
        ...

    def read_existing_provider_config(self) -> dict:
        """读取已有的 Provider 配置。

        从 ~/.openclaw/openclaw.json 和 auth-profiles.json 中读取。

        Returns:
            dict: 包含 env、auth_profiles、primary_model、providers 等字段。
        """
        ...

    def stop(self) -> None:
        """停止服务并标记取消状态。"""
        ...

    def is_running(self) -> bool:
        """检查前台网关进程是否仍在运行。

        Returns:
            bool: 进程是否存活。
        """
        ...

    def uninstall(
        self,
        on_log: Optional[ConfigLogCallback] = None,
        cancel_event: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """完全卸载 OpenClaw。

        流程：停止 Gateway → 删除目录 → 卸载 npm 包 → 删除命令包装器。

        Args:
            on_log: 日志回调，用于展示卸载进度。

        Returns:
            bool: 是否全部成功。
        """
        ...
