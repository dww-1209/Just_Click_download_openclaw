"""OpenClawManager 共享基类

职责：为所有生命周期管理器实现类提供共享工具和横切关注钩子，
消除 _log()、is_cancelled、stop() 等逻辑在多个类中的重复实现。

设计原则：
- 本基类是可选的：实现类可以选择继承本基类（获得默认实现），
  或仅实现 IOpenClawManager Protocol（保持灵活）。
- 因为继承本基类不是契约约束,这里没有用 ABC/@abstractmethod;
  真正的契约由 src/contracts/define_manager.py 的 IOpenClawManager Protocol 定义。
"""

from __future__ import annotations

import time
from typing import Callable, Optional


class BaseOpenClawManager:
    """OpenClaw 生命周期管理器共享基类。

    提供以下默认实现：
    - 统一日志记录（_log）：自动追加时间戳并回调 UI。
    - 取消状态管理（is_cancelled、stop、_check_cancelled）。
    - 日志行缓存（_log_lines）。

    子类只需调用 self._log("...") 和 self._check_cancelled() 即可，
    无需重复实现日志格式化和取消检查逻辑。
    """

    def __init__(self) -> None:
        self.process: Optional[object] = None
        self.is_cancelled: bool = False
        self._log_lines: list[str] = []
        self._on_log: Optional[Callable[[str], None]] = None

    def _log(self, message: str) -> None:
        """统一日志记录：自动追加时间戳并回调 UI。

        Args:
            message: 日志内容，会自动追加时间戳前缀。
        """
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        self._log_lines.append(log_line)
        print(log_line)
        if self._on_log:
            self._on_log(log_line)

    def _check_cancelled(self) -> bool:
        """检查是否已请求取消。

        Returns:
            bool: True 表示已取消，子类应在耗时操作前调用并提前返回。
        """
        return self.is_cancelled

    def stop(self) -> None:
        """标记取消状态。子类可覆盖以添加进程终止逻辑。"""
        self.is_cancelled = True
