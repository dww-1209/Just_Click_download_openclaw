"""环境检测器接口定义

职责：抽象系统环境检测操作，使 Service 层可以通过接口调用不同的检测实现。
"""

from __future__ import annotations

from typing import Protocol, Optional

from src.models.env_check import EnvCheckResult


class IEnvChecker(Protocol):
    """环境检测器接口。

    负责检测操作系统、磁盘空间、权限、浏览器、OpenClaw 安装状态等环境信息。
    """

    def check(self, install_path: Optional[str] = None) -> EnvCheckResult:
        """执行环境检测。

        Args:
            install_path: 可选的预期安装路径，用于检测该路径下的磁盘空间。

        Returns:
            EnvCheckResult: 完整的环境检测结果。
        """
        ...
