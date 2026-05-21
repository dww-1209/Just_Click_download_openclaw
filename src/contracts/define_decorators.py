"""横切关注装饰器

职责:为 core/adapters 层的方法提供统一的横切功能,目前仅保留:
- 日志包装(@log_method):在方法调用前后自动记录日志。

设计原则:
- 装饰器只依赖 self._log(),因此要求被装饰的类继承 BaseOpenClawManager 或 BaseInstaller。
- 装饰器使用 functools.wraps 保留原函数的元信息。
- 本文件位于 contracts 层,可供 core 和 adapters 共同依赖,避免反向导入。

历史备忘:
- 早期还提供过 @check_cancelled 装饰器和 CancellationError 异常,但全项目零使用,
  2026-05 已清理。取消检查直接通过 self._check_cancelled() 显式调用,见
  BaseInstaller / BaseOpenClawManager。
"""

from __future__ import annotations

import functools
from typing import Callable, Any, TypeVar


F = TypeVar("F", bound=Callable[..., Any])


def log_method(func: F) -> F:
    """方法调用日志装饰器。

    在方法调用前后自动记录日志,格式为:
    - 开始: {方法名}
    - 完成: {方法名}
    - 异常: {方法名} - {异常类型}: {异常信息}

    要求被装饰的类具有 self._log(message: str) 方法。
    """

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        self._log(f"开始: {func.__name__}")
        try:
            result = func(self, *args, **kwargs)
            self._log(f"完成: {func.__name__}")
            return result
        except Exception as e:
            self._log(f"异常: {func.__name__} - {type(e).__name__}: {e}")
            raise

    return wrapper  # type: ignore[return-value]
