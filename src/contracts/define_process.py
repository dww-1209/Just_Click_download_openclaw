"""子进程执行器接口定义

职责：抽象 run_shell 等基础设施的子进程调用能力，
使上层业务逻辑可以不依赖具体的 subprocess 实现。
"""

from __future__ import annotations

import subprocess
from typing import Protocol


class IProcessRunner(Protocol):
    """子进程执行器接口。

    封装 `subprocess.run` 的能力，支持同步执行命令并返回结果。
    """

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """同步执行命令。

        Args:
            cmd: 命令参数列表（如 ["pnpm", "install"]）。
            **kwargs: 传递给 subprocess.run 的额外参数。

        Returns:
            subprocess.CompletedProcess: 包含 returncode、stdout、stderr 的结果对象。
        """
        ...


class IPopenRunner(Protocol):
    """Popen 执行器接口。

    封装 `subprocess.Popen` 的能力，支持启动后台进程并返回进程对象。
    """

    def popen(self, cmd: list[str], **kwargs) -> subprocess.Popen:
        """启动后台进程。

        Args:
            cmd: 命令参数列表。
            **kwargs: 传递给 subprocess.Popen 的额外参数。

        Returns:
            subprocess.Popen: 进程对象，可用于后续状态检查和终止。
        """
        ...
