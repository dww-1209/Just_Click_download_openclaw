"""安装器接口定义

职责：抽象 OpenClaw 安装流程，使 Service 层可以通过接口调度不同的安装实现
（如 Gitee + pnpm 本地构建、预编译二进制下载等）。
"""

from __future__ import annotations

from typing import Protocol

from src.models.install import InstallResult
from src.contracts.define_worker import ProgressCallback, LogCallback


class IInstaller(Protocol):
    """安装器接口。

    负责执行 OpenClaw 的完整安装流程，并通过回调向 UI 反馈进度与日志。
    """

    def install(
        self,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
    ) -> InstallResult:
        """执行完整安装流程。

        Args:
            on_progress: 进度回调，用于驱动 UI 进度条与阶段文本。
            on_log: 日志回调，用于在 UI 中实时展示安装日志。

        Returns:
            InstallResult: 包含最终状态、消息、日志与耗时。
        """
        ...

    def cancel(self) -> None:
        """请求取消安装。设置取消标志，不强制终止线程。"""
        ...

    def is_running(self) -> bool:
        """检查安装是否正在进行中。

        Returns:
            bool: True 表示安装仍在运行。
        """
        ...
