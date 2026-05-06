"""Worker 回调类型别名定义

职责：统一各 Worker 与 UI 之间的回调签名，消除不一致的传参方式。
"""

from __future__ import annotations

from typing import Callable

from src.models.install import InstallProgress
from src.models.config import ConfigProgress

# 安装阶段进度回调：携带 InstallProgress 数据对象
ProgressCallback = Callable[[InstallProgress], None]

# 通用日志回调：携带单条日志字符串
LogCallback = Callable[[str], None]

# 配置/启动阶段进度回调：携带 ConfigProgress 数据对象
ConfigProgressCallback = Callable[[ConfigProgress], None]
