"""卸载任务接口定义

职责：抽象卸载流程的各个步骤，支持通过接口组合不同的卸载策略。
"""

from __future__ import annotations

from typing import Protocol, Callable


class IUninstallTask(Protocol):
    """卸载任务接口。

    封装完整的卸载流程，由 UninstallWorker 在后台线程中调用。
    """

    def execute(self, on_log: Callable[[str], None]) -> bool:
        """执行卸载。

        Args:
            on_log: 日志回调，用于在 UI 中展示卸载进度。

        Returns:
            bool: 是否全部成功。
        """
        ...
