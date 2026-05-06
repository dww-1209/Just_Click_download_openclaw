"""安装器抽象基类

职责：为所有安装器实现类提供共享工具和横切关注钩子，
消除 _log()、is_cancelled、cancel() 等逻辑在多个类中的重复实现。

设计原则：
- 本基类是可选的：实现类可以选择继承本基类（获得默认实现），
  或仅实现 IInstaller Protocol（保持灵活）。
- 基类提供的是"能力"而非"契约"，真正的契约仍由 Protocol 定义。
"""

from __future__ import annotations

import re
import time
from abc import ABC
from typing import Callable, Optional


class BaseInstaller(ABC):
    """安装器抽象基类。

    提供以下默认实现：
    - 统一日志记录（_log）：自动过滤 ANSI 颜色码、追加时间戳并回调 UI。
    - 取消状态管理（is_cancelled、cancel）。
    - 日志行缓存（log_lines）。

    子类只需调用 self._log("...") 和检查 self.is_cancelled 即可，
    无需重复实现日志格式化和取消检查逻辑。
    """

    def __init__(self) -> None:
        self.process: Optional[object] = None
        self.log_lines: list[str] = []
        self.is_cancelled: bool = False
        self._on_log: Optional[Callable[[str], None]] = None

    def _log(self, message: str) -> None:
        """统一日志记录：过滤 ANSI 颜色码、追加时间戳并回调 UI。

        Args:
            message: 日志内容，会自动过滤 ANSI 控制序列并追加时间戳。
        """
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", message)
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {cleaned}"
        self.log_lines.append(log_line)
        if self._on_log:
            self._on_log(log_line)

    def cancel(self) -> None:
        """请求取消安装。设置取消标志，子类可覆盖以添加进程终止逻辑。"""
        self.is_cancelled = True
