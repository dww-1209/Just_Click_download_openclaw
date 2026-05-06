"""横切关注装饰器

职责：为 core/adapters 层的方法提供统一的横切功能，包括：
- 日志包装（@log_method）：在方法调用前后自动记录日志。
- 取消检查（@check_cancelled）：若已取消则提前返回 None 或抛出异常。
- 异常转换（@catch_errors）：捕获指定异常并转为日志记录。

设计原则：
- 装饰器只依赖 self._log() 和 self.is_cancelled / self._check_cancelled()，
  因此要求被装饰的类继承 BaseOpenClawManager 或 BaseInstaller。
- 装饰器使用 functools.wraps 保留原函数的元信息。
"""

from __future__ import annotations

import functools
from typing import Callable, Any, TypeVar


F = TypeVar("F", bound=Callable[..., Any])


class CancellationError(Exception):
    """操作被取消时抛出的异常。"""

    pass


def log_method(func: F) -> F:
    """方法调用日志装饰器。

    在方法调用前后自动记录日志，格式为：
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
        except CancellationError:
            # 取消异常不需要记为错误，重新抛出即可
            self._log(f"取消: {func.__name__}")
            raise
        except Exception as e:
            self._log(f"异常: {func.__name__} - {type(e).__name__}: {e}")
            raise

    return wrapper  # type: ignore[return-value]


def check_cancelled(raise_on_cancel: bool = True) -> Callable[[F], F]:
    """取消检查装饰器工厂。

    在方法执行前检查 self.is_cancelled 或 self._check_cancelled()，
    若已取消则提前终止。

    Args:
        raise_on_cancel: True 时抛出 CancellationError；False 时返回 None。

    Returns:
        装饰器函数。
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            cancelled = getattr(self, "is_cancelled", False)
            if callable(getattr(self, "_check_cancelled", None)):
                cancelled = cancelled or self._check_cancelled()

            if cancelled:
                if getattr(self, "_log", None):
                    self._log(f"跳过（已取消）: {func.__name__}")
                if raise_on_cancel:
                    raise CancellationError(f"{func.__name__} 已取消")
                return None
            return func(self, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
