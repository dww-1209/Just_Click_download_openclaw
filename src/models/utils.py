"""模型层公共工具函数

职责：提供纯数据/工具辅助函数，供 models、core、infra 等各层共享使用。

设计原则：
- 本层只包含不依赖任何业务逻辑和系统调用的纯工具函数。
- 若函数涉及文件系统操作但属于通用辅助（如 remove_readonly），也可放在此处。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from typing import Callable, Any, Optional

from src.models.constants import is_windows, TIMEOUT_SHORT_CMD


def remove_readonly(func: Callable[[str], None], path: str, _: Any) -> None:
    """shutil.rmtree 的 onerror 回调：移除只读属性后重试删除。

    用途：删除可能包含只读文件（如 Git 仓库中的文件）的目录时，
    先修改文件权限再重试删除操作。

    Args:
        func: 原始删除函数（如 os.unlink 或 os.rmdir）。
        path: 要删除的文件或目录路径。
        _: excinfo 占位参数（未使用）。
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def resolve_openclaw_cmd(env: Optional[dict] = None) -> str:
    """检测系统中可用的 openclaw 命令。

    优先检测 openclaw-cn，fallback 到 openclaw。
    Windows 使用 where 命令（能正确处理 %APPDATA% 等环境变量展开），
    Linux/macOS 使用 shutil.which。

    Args:
        env: 可选的环境变量字典，用于 Linux/macOS 的自定义 PATH 检测。

    Returns:
        str: 检测到的命令名（如 "openclaw-cn"），若都未找到则返回 "openclaw"。
    """
    if is_windows():
        for cmd in ["openclaw-cn", "openclaw"]:
            result = subprocess.run(
                ["where", cmd],
                shell=False,
                capture_output=True,
                timeout=TIMEOUT_SHORT_CMD,
            )
            if result.returncode == 0:
                return cmd
    else:
        path_env = env.get("PATH", os.environ.get("PATH", "")) if env else os.environ.get("PATH", "")
        for cmd in ["openclaw-cn", "openclaw"]:
            if shutil.which(cmd, path=path_env) is not None:
                return cmd
    return "openclaw"
